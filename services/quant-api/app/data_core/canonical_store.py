from __future__ import annotations

import ctypes
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from types import MappingProxyType
from typing import Callable, Mapping
import uuid

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy.orm import Session

from app.data_core.bar_schema import CanonicalBar
from app.data_core.catalog import (
    ALLOWED_OVERLAP_REASONS,
    HistoricalCatalog,
    PartitionManifest,
)
from app.data_core.contracts import DataCoreError, DatasetKey
from app.data_core.quality import (
    ValidatedProviderBatch,
    require_safe_component,
    validate_provider_batch,
)
from app.data_core.rqdata_adapter import ProviderBarBatch


CANONICAL_PARQUET_PROFILE_ID = "canonical-parquet-v1"
CANONICAL_MANIFEST_FORMAT = "canonical-manifest-v1"
CANONICAL_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("provider", pa.string(), nullable=False),
        pa.field("dataset_kind", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("contract_or_series", pa.string(), nullable=False),
        pa.field("frequency", pa.string(), nullable=False),
        pa.field("bar_end", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("trading_day", pa.date32(), nullable=False),
        pa.field("open", pa.decimal128(38, 18), nullable=False),
        pa.field("high", pa.decimal128(38, 18), nullable=False),
        pa.field("low", pa.decimal128(38, 18), nullable=False),
        pa.field("close", pa.decimal128(38, 18), nullable=False),
        pa.field("volume", pa.decimal128(38, 18), nullable=False),
        pa.field("turnover", pa.decimal128(38, 18), nullable=True),
        pa.field("open_interest", pa.decimal128(38, 18), nullable=True),
        pa.field("adjustment", pa.string(), nullable=False),
        pa.field("schema_version", pa.string(), nullable=False),
    ]
)
CANONICAL_PARQUET_WRITER_PARAMETERS: Mapping[str, object] = MappingProxyType(
    {
        "version": "2.6",
        "data_page_version": "1.0",
        "compression": "zstd",
        "compression_level": 3,
        "use_dictionary": False,
        "row_group_size": 65536,
        "data_page_size": 1048576,
        "write_statistics": True,
        "coerce_timestamps": "us",
        "allow_truncated_timestamps": False,
        "use_deprecated_int96_timestamps": False,
        "write_page_index": False,
        "store_schema": True,
    }
)
_LOGICAL_SCHEMA = (
    {"name": "provider", "type": "string", "nullable": False},
    {"name": "dataset_kind", "type": "string", "nullable": False},
    {"name": "symbol", "type": "string", "nullable": False},
    {"name": "contract_or_series", "type": "string", "nullable": False},
    {"name": "frequency", "type": "string", "nullable": False},
    {
        "name": "bar_end",
        "type": "utc_datetime_microsecond",
        "nullable": False,
    },
    {"name": "trading_day", "type": "date", "nullable": False},
    {"name": "open", "type": "decimal", "nullable": False},
    {"name": "high", "type": "decimal", "nullable": False},
    {"name": "low", "type": "decimal", "nullable": False},
    {"name": "close", "type": "decimal", "nullable": False},
    {"name": "volume", "type": "decimal", "nullable": False},
    {"name": "turnover", "type": "optional_decimal", "nullable": True},
    {
        "name": "open_interest",
        "type": "optional_decimal",
        "nullable": True,
    },
    {"name": "adjustment", "type": "string", "nullable": False},
    {"name": "schema_version", "type": "string", "nullable": False},
)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
_FILE_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
_FILE_CREATE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
)
_JOURNAL_DIR = "canonical-publish-journal"
_CLEANUP_QUARANTINE_DIR = "canonical-cleanup-quarantine"
_MAX_JOURNAL_COUNT = 64
_MAX_JOURNAL_BYTES = 1024 * 1024
_MAX_WRITER_VERSION_LENGTH = 128


class CanonicalStoreError(DataCoreError):
    error_code = "CANONICAL_STORE_ERROR"

    def __init__(self, code: str, *, facts: dict[str, object] | None = None) -> None:
        self.error_code = code
        super().__init__(facts=facts)


class CanonicalPublishError(CanonicalStoreError):
    pass


@dataclass(frozen=True, slots=True)
class _Identity:
    device: int
    inode: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> _Identity:
        return cls(device=value.st_dev, inode=value.st_ino)


@dataclass(frozen=True, slots=True)
class _OwnedEntry:
    parent_parts: tuple[str, ...]
    name: str
    identity: _Identity


@dataclass(frozen=True, slots=True)
class _OwnedDirectory:
    parts: tuple[str, ...]
    identity: _Identity


@dataclass(frozen=True, slots=True)
class _RootAnchor:
    path: Path
    identity: _Identity
    kind: str


@dataclass(frozen=True, slots=True)
class _StagedOwnership:
    task_name: str
    task_identity: _Identity
    file_identity: _Identity


@dataclass(frozen=True, slots=True)
class _JournalRecord:
    transaction_id: str
    dataset: DatasetKey
    data_version: str
    canonical_logical_fingerprint: str
    manifest: PartitionManifest
    manifest_document: dict[str, object]
    parent_parts: tuple[str, ...]
    names: dict[str, str]
    preexisting_finals: dict[str, _Identity | None]
    created_dir_parts: tuple[tuple[str, ...], ...]
    preexisting_directories: tuple[_OwnedDirectory, ...]
    staged: _StagedOwnership


@dataclass(frozen=True, slots=True)
class StagedBatch:
    source: ValidatedProviderBatch
    task_root: Path
    file_path: Path
    file_checksum: str
    canonical_logical_fingerprint: str
    task_name: str
    task_identity: _Identity
    file_identity: _Identity


@dataclass(frozen=True, slots=True)
class ValidationResult:
    staged: StagedBatch
    dataset: DatasetKey
    bars: tuple[CanonicalBar, ...]
    coverage_start: datetime
    coverage_end: datetime
    row_count: int
    data_version: str
    file_checksum: str
    canonical_logical_fingerprint: str


@dataclass(frozen=True, slots=True)
class PublishExpectation:
    dataset: DatasetKey
    coverage_start: datetime
    coverage_end: datetime
    row_count: int
    data_version: str
    manifest_version: str
    file_checksum: str | None = None
    canonical_logical_fingerprint: str | None = None
    manifest_digest: str | None = None
    overlap_reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.dataset, DatasetKey)
            or not _is_aware_utc(self.coverage_start)
            or not _is_aware_utc(self.coverage_end)
            or self.coverage_start >= self.coverage_end
            or type(self.row_count) is not int
            or self.row_count <= 0
        ):
            raise CanonicalPublishError(
                "CANONICAL_PUBLISH_EXPECTATION_INVALID"
            )
        try:
            require_safe_component(self.data_version, field="data_version")
            require_safe_component(
                self.manifest_version,
                field="manifest_version",
            )
        except DataCoreError as exc:
            raise CanonicalPublishError(
                "CANONICAL_PUBLISH_EXPECTATION_INVALID"
            ) from exc
        for digest in (
            self.file_checksum,
            self.canonical_logical_fingerprint,
            self.manifest_digest,
        ):
            if digest is not None and not _is_sha256(digest):
                raise CanonicalPublishError(
                    "CANONICAL_PUBLISH_EXPECTATION_INVALID"
                )
        if (
            self.overlap_reason is not None
            and self.overlap_reason not in ALLOWED_OVERLAP_REASONS
        ):
            raise CanonicalPublishError(
                "CANONICAL_PUBLISH_EXPECTATION_INVALID"
            )

    @classmethod
    def from_validation(
        cls,
        validation: ValidationResult,
        *,
        manifest_version: str,
        overlap_reason: str | None = None,
    ) -> PublishExpectation:
        if not isinstance(validation, ValidationResult):
            raise CanonicalPublishError(
                "CANONICAL_PUBLISH_EXPECTATION_INVALID"
            )
        return cls(
            dataset=validation.dataset,
            coverage_start=validation.coverage_start,
            coverage_end=validation.coverage_end,
            row_count=validation.row_count,
            data_version=validation.data_version,
            manifest_version=manifest_version,
            file_checksum=validation.file_checksum,
            canonical_logical_fingerprint=(
                validation.canonical_logical_fingerprint
            ),
            overlap_reason=overlap_reason,
        )


@dataclass(frozen=True, slots=True)
class PublishedPartition:
    file_path: Path
    manifest_path: Path
    prepared_marker_path: Path
    partition_manifest: PartitionManifest
    file_checksum: str
    canonical_logical_fingerprint: str
    data_version: str


class CanonicalStore:
    def __init__(
        self,
        *,
        staging_root: Path,
        canonical_root: Path,
        metadata_session_factory: Callable[[], Session],
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not callable(metadata_session_factory):
            raise TypeError("metadata_session_factory must be callable")
        self._staging_anchor = _create_and_anchor_root(
            staging_root,
            kind="STAGING",
        )
        self._canonical_anchor = _create_and_anchor_root(
            canonical_root,
            kind="CANONICAL",
        )
        self._metadata_session_factory = metadata_session_factory
        self._fault_injector = fault_injector or (lambda _point: None)
        self._ensure_journal_directory()
        self._ensure_cleanup_quarantine(self._canonical_anchor)
        self._ensure_cleanup_quarantine(self._staging_anchor)
        self.recover_pending_publications()

    def _ensure_journal_directory(self) -> None:
        root_fd = self._open_root(self._canonical_anchor)
        journal_fd: int | None = None
        try:
            journal_fd = _open_directory_parts(
                root_fd,
                (_JOURNAL_DIR,),
                create=True,
                created=None,
            )
            os.fsync(root_fd)
            os.fsync(journal_fd)
        finally:
            if journal_fd is not None:
                os.close(journal_fd)
            os.close(root_fd)

    def _ensure_cleanup_quarantine(self, anchor: _RootAnchor) -> None:
        root_fd = self._open_root(anchor)
        quarantine_fd: int | None = None
        try:
            quarantine_fd = _open_cleanup_quarantine(root_fd)
            os.fsync(quarantine_fd)
        finally:
            if quarantine_fd is not None:
                os.close(quarantine_fd)
            os.close(root_fd)

    def stage(self, batch: ProviderBarBatch) -> StagedBatch:
        validated = validate_provider_batch(batch)
        fingerprint = _logical_fingerprint(validated)
        root_fd = self._open_root(self._staging_anchor)
        task_name = f"canonical-stage-{uuid.uuid4().hex}"
        task_identity: _Identity | None = None
        file_identity: _Identity | None = None
        try:
            os.mkdir(task_name, mode=0o700, dir_fd=root_fd)
            task_identity = _lstat_identity(root_fd, task_name, directory=True)
            task_fd = _open_child_directory(root_fd, task_name)
            try:
                file_fd = os.open(
                    "batch.parquet",
                    _FILE_CREATE_FLAGS,
                    0o600,
                    dir_fd=task_fd,
                )
                try:
                    file_identity = _Identity.from_stat(os.fstat(file_fd))
                    self._fault("staging_write")
                    with os.fdopen(os.dup(file_fd), "wb") as handle:
                        _write_table(_table_from_bars(validated.bars), handle)
                    os.fsync(file_fd)
                finally:
                    os.close(file_fd)
                os.fsync(task_fd)
                checksum = _sha256_at(
                    task_fd,
                    "batch.parquet",
                    file_identity,
                )
            finally:
                os.close(task_fd)
            return StagedBatch(
                source=validated,
                task_root=self._staging_anchor.path / task_name,
                file_path=(
                    self._staging_anchor.path
                    / task_name
                    / "batch.parquet"
                ),
                file_checksum=checksum,
                canonical_logical_fingerprint=fingerprint,
                task_name=task_name,
                task_identity=task_identity,
                file_identity=file_identity,
            )
        except BaseException:
            self._cleanup_stage_parts(
                root_fd,
                task_name,
                task_identity,
                file_identity,
            )
            raise
        finally:
            os.close(root_fd)

    def validate(self, staged: StagedBatch) -> ValidationResult:
        try:
            task_fd, file_fd = self._open_staged(staged)
            try:
                self._fault("validation")
                with os.fdopen(os.dup(file_fd), "rb") as handle:
                    table = pq.read_table(handle)
                if table.schema != CANONICAL_PARQUET_SCHEMA:
                    raise CanonicalStoreError(
                        "CANONICAL_STAGED_SCHEMA_MISMATCH"
                    )
                bars = _bars_from_table(table)
                if bars != staged.source.bars:
                    raise CanonicalStoreError(
                        "CANONICAL_STAGED_CONTENT_MISMATCH"
                    )
                checksum = _sha256_fd(file_fd)
                fingerprint = _logical_fingerprint(staged.source)
                if (
                    checksum != staged.file_checksum
                    or fingerprint
                    != staged.canonical_logical_fingerprint
                ):
                    raise CanonicalStoreError(
                        "CANONICAL_STAGED_INTEGRITY_MISMATCH"
                    )
            finally:
                os.close(file_fd)
                os.close(task_fd)
            return ValidationResult(
                staged=staged,
                dataset=staged.source.dataset,
                bars=bars,
                coverage_start=staged.source.coverage_start,
                coverage_end=staged.source.coverage_end,
                row_count=len(bars),
                data_version=staged.source.data_version,
                file_checksum=checksum,
                canonical_logical_fingerprint=fingerprint,
            )
        except BaseException:
            if isinstance(staged, StagedBatch):
                self._cleanup_staged(staged)
            raise

    def discard(self, staged: StagedBatch) -> None:
        """Remove one caller-owned staged batch without touching canonical data."""

        if not isinstance(staged, StagedBatch):
            raise CanonicalStoreError("CANONICAL_STAGED_HANDLE_INVALID")
        self._cleanup_staged(staged)

    def publish(
        self,
        staged: StagedBatch,
        expected: PublishExpectation,
    ) -> PublishedPartition:
        validation = self.validate(staged)
        try:
            return self._publish_validated(staged, expected, validation)
        finally:
            self._cleanup_staged(staged)

    def _publish_validated(
        self,
        staged: StagedBatch,
        expected: PublishExpectation,
        validation: ValidationResult,
    ) -> PublishedPartition:
        _validate_expectation(validation, expected)
        transaction_id = uuid.uuid4().hex
        parent_parts = self._partition_parts(validation)
        names = self._publication_names(expected, transaction_id)
        relative_file = Path(*parent_parts, names["file"])
        relative_manifest = Path(*parent_parts, names["manifest"])
        relative_marker = Path(*parent_parts, names["marker"])
        manifest_payload = _manifest_payload(
            validation=validation,
            expected=expected,
            file_path=relative_file,
            manifest_path=relative_manifest,
        )
        manifest_digest = canonical_json_digest(manifest_payload)
        if (
            expected.manifest_digest is not None
            and expected.manifest_digest != manifest_digest
        ):
            raise CanonicalPublishError(
                "CANONICAL_PUBLISH_EXPECTATION_MISMATCH"
            )
        manifest_document = {
            **manifest_payload,
            "manifest_digest": manifest_digest,
        }
        marker_document = {
            "state": "PREPARED",
            "transaction_id": transaction_id,
            "manifest_digest": manifest_digest,
            "file_checksum": validation.file_checksum,
        }
        partition_manifest = PartitionManifest(
            coverage_start=validation.coverage_start,
            coverage_end=validation.coverage_end,
            manifest_version=expected.manifest_version,
            manifest_uri=relative_manifest.as_posix(),
            manifest_digest=manifest_digest,
            file_uri=relative_file.as_posix(),
            checksum=validation.file_checksum,
            row_count=validation.row_count,
            overlap_reason=expected.overlap_reason,
        )
        journal_name = f"txn-{transaction_id}.json"
        journal_temp_name = f"journal-temp-{transaction_id}.partial"
        root_fd = self._open_root(self._canonical_anchor)
        created_dirs: list[_OwnedDirectory] = []
        owned_entries: dict[str, _OwnedEntry] = {}
        journal_entry: _OwnedEntry | None = None
        commit_attempted = False
        published: PublishedPartition | None = None
        session: Session | None = None
        parent_fd: int | None = None
        journal_fd: int | None = None
        journal_payload: dict[str, object] | None = None
        try:
            directory_plan = _directory_intent_plan(
                root_fd,
                parent_parts,
            )
            final_entries = _final_presence_plan(
                root_fd,
                parent_parts,
                names,
            )
            journal_payload = _journal_payload(
                transaction_id=transaction_id,
                validation=validation,
                staged=staged,
                partition_manifest=partition_manifest,
                manifest_document=manifest_document,
                parent_parts=parent_parts,
                names=names,
                directory_plan=directory_plan,
                final_entries=final_entries,
            )
            journal_fd = _open_directory_parts(
                root_fd,
                (_JOURNAL_DIR,),
                create=False,
                created=None,
            )
            journal_temp_identity = _write_journal_temp_create_only(
                journal_fd,
                journal_temp_name,
                _canonical_json_bytes(journal_payload),
                self._fault,
            )
            owned_entries["journal_temp"] = _OwnedEntry(
                (_JOURNAL_DIR,),
                journal_temp_name,
                journal_temp_identity,
            )
            self._fault("after_journal_temp_fsync")
            try:
                _atomic_rename_no_replace_at(
                    journal_fd,
                    journal_temp_name,
                    journal_fd,
                    journal_name,
                )
            except FileExistsError as exc:
                raise CanonicalPublishError(
                    "CANONICAL_PUBLISH_COLLISION"
                ) from exc
            except BaseException:
                if (
                    _optional_lstat_identity(journal_fd, journal_name)
                    == journal_temp_identity
                ):
                    journal_entry = _OwnedEntry(
                        (_JOURNAL_DIR,),
                        journal_name,
                        journal_temp_identity,
                    )
                raise
            journal_entry = _OwnedEntry(
                (_JOURNAL_DIR,),
                journal_name,
                journal_temp_identity,
            )
            if (
                _lstat_identity(journal_fd, journal_name)
                != journal_temp_identity
            ):
                raise CanonicalPublishError(
                    "CANONICAL_PUBLISHED_ENTRY_REPLACED"
                )
            self._fault("after_journal_publish")
            os.fsync(journal_fd)
            self._fault("after_intent_fsync")
            self._fault("after_journal_fsync")

            directory_index = 0

            def after_directory_created(
                _directory: _OwnedDirectory,
            ) -> None:
                nonlocal directory_index
                directory_index += 1
                self._fault(
                    f"after_publish_directory_fsync_{directory_index}"
                )

            parent_fd = _open_directory_parts(
                root_fd,
                parent_parts,
                create=True,
                created=created_dirs,
                on_created=after_directory_created,
            )
            _recheck_final_presence_before_link(
                parent_fd,
                names,
                final_entries,
            )

            source_task_fd, source_fd = self._open_staged(staged)
            try:
                partial_file = _copy_fd_create_only(
                    source_fd,
                    parent_fd,
                    names["partial_file"],
                )
            finally:
                os.close(source_fd)
                os.close(source_task_fd)
            owned_entries["partial_file"] = _OwnedEntry(
                parent_parts,
                names["partial_file"],
                partial_file,
            )
            os.fsync(parent_fd)
            self._fault("after_partial_file_fsync")
            checksum = _sha256_at(
                parent_fd,
                names["partial_file"],
                partial_file,
            )
            if checksum != validation.file_checksum:
                raise CanonicalPublishError(
                    "CANONICAL_PUBLISH_FILE_CHECKSUM_MISMATCH"
                )

            partial_manifest = _write_bytes_create_only(
                parent_fd,
                names["partial_manifest"],
                _canonical_json_bytes(manifest_document),
            )
            owned_entries["partial_manifest"] = _OwnedEntry(
                parent_parts,
                names["partial_manifest"],
                partial_manifest,
            )
            os.fsync(parent_fd)
            self._fault("after_partial_manifest_fsync")

            partial_marker = _write_bytes_create_only(
                parent_fd,
                names["partial_marker"],
                _canonical_json_bytes(marker_document),
            )
            owned_entries["partial_marker"] = _OwnedEntry(
                parent_parts,
                names["partial_marker"],
                partial_marker,
            )
            os.fsync(parent_fd)
            self._fault("after_partial_prepared_marker_fsync")

            session = self._new_owned_session()
            _begin_physical_write_transaction(session)
            self._fault("metadata_registration")
            HistoricalCatalog(session).register_partition(
                validation.dataset,
                partition_manifest,
            )
            self._fault("after_metadata_registration")

            self._fault("file_rename")
            _link_and_record_owned_final(
                owned_entries,
                role="file",
                parent_fd=parent_fd,
                parent_parts=parent_parts,
                source_name=names["partial_file"],
                target_name=names["file"],
                identity=partial_file,
            )
            self._fault("after_file_link")

            self._fault("manifest_rename")
            _link_and_record_owned_final(
                owned_entries,
                role="manifest",
                parent_fd=parent_fd,
                parent_parts=parent_parts,
                source_name=names["partial_manifest"],
                target_name=names["manifest"],
                identity=partial_manifest,
            )
            self._fault("after_manifest_link")
            os.fsync(parent_fd)

            _link_and_record_owned_final(
                owned_entries,
                role="marker",
                parent_fd=parent_fd,
                parent_parts=parent_parts,
                source_name=names["partial_marker"],
                target_name=names["marker"],
                identity=partial_marker,
            )
            os.fsync(parent_fd)
            self._fault("after_prepared_marker")
            self._fault("after_commit_marker")

            self._fault("metadata_commit")
            commit_attempted = True
            session.commit()
            self._fault("after_metadata_commit")
            published = PublishedPartition(
                file_path=self._canonical_anchor.path / relative_file,
                manifest_path=self._canonical_anchor.path / relative_manifest,
                prepared_marker_path=(
                    self._canonical_anchor.path / relative_marker
                ),
                partition_manifest=partition_manifest,
                file_checksum=checksum,
                canonical_logical_fingerprint=(
                    validation.canonical_logical_fingerprint
                ),
                data_version=validation.data_version,
            )
        except BaseException as exc:
            if session is not None:
                try:
                    session.rollback()
                except Exception:
                    commit_attempted = True
            if (
                commit_attempted
                and self._metadata_matches(
                    validation.dataset,
                    partition_manifest,
                )
            ):
                record = _parse_journal(
                    journal_payload,
                    journal_name=journal_name,
                )
                if not self._published_content_matches(
                    root_fd,
                    record,
                ):
                    raise CanonicalPublishError(
                        "CANONICAL_RECOVERY_UNCERTAIN"
                    ) from exc
                published = self._published_from_recovery(
                    validation,
                    partition_manifest,
                    parent_parts,
                    names,
                )
            else:
                try:
                    self._compensate(
                        root_fd,
                        owned_entries,
                        journal_entry,
                        created_dirs,
                    )
                except BaseException as compensation_error:
                    raise CanonicalPublishError(
                        "CANONICAL_RECOVERY_UNCERTAIN",
                        facts={
                            "cause": type(exc).__name__,
                            "compensation_error": type(
                                compensation_error
                            ).__name__,
                        },
                    ) from exc
                if isinstance(exc, CanonicalStoreError):
                    raise
                raise CanonicalPublishError(
                    "CANONICAL_PUBLISH_FAILED",
                    facts={"error_type": type(exc).__name__},
                ) from exc
        finally:
            if session is not None:
                session.close()
            if parent_fd is not None:
                os.close(parent_fd)
            if journal_fd is not None:
                os.close(journal_fd)
            if published is not None:
                self._cleanup_committed_transaction(
                    root_fd,
                    owned_entries,
                    journal_entry,
                    created_dirs,
                )
            os.close(root_fd)
        if published is None:
            raise CanonicalPublishError("CANONICAL_RECOVERY_UNCERTAIN")
        return published

    def recover_pending_publications(self) -> None:
        root_fd = self._open_root(self._canonical_anchor)
        try:
            journal_fd = _open_directory_parts(
                root_fd,
                (_JOURNAL_DIR,),
                create=False,
                created=None,
            )
            try:
                journal_names: list[str] = []
                with os.scandir(journal_fd) as journal_entries:
                    for journal_dir_entry in journal_entries:
                        journal_names.append(journal_dir_entry.name)
                        if len(journal_names) > _MAX_JOURNAL_COUNT:
                            raise CanonicalPublishError(
                                "CANONICAL_JOURNAL_COUNT_EXCEEDED"
                            )
                journal_names.sort()
                parsed: list[
                    tuple[_OwnedEntry, _JournalRecord]
                ] = []
                journal_temps: dict[str, list[_OwnedEntry]] = {}
                for name in journal_names:
                    temp_transaction_id = _journal_temp_transaction_id(name)
                    if temp_transaction_id is not None:
                        try:
                            temp_identity = _lstat_identity(journal_fd, name)
                        except CanonicalStoreError:
                            continue
                        journal_temps.setdefault(
                            temp_transaction_id,
                            [],
                        ).append(
                            _OwnedEntry(
                                (_JOURNAL_DIR,),
                                name,
                                temp_identity,
                            )
                        )
                        continue
                    if not (
                        name.startswith("txn-") and name.endswith(".json")
                    ):
                        raise CanonicalPublishError(
                            "CANONICAL_JOURNAL_INVALID"
                        )
                    try:
                        identity, payload = _read_json_at(journal_fd, name)
                        record = _parse_journal(
                            payload,
                            journal_name=name,
                        )
                    except CanonicalPublishError:
                        raise
                    except (
                        OSError,
                        ValueError,
                        json.JSONDecodeError,
                        RecursionError,
                    ) as exc:
                        raise CanonicalPublishError(
                            "CANONICAL_JOURNAL_INVALID"
                        ) from exc
                    parsed.append(
                        (
                            _OwnedEntry(
                                (_JOURNAL_DIR,),
                                name,
                                identity,
                            ),
                            record,
                        )
                    )
                self._validate_journal_set(root_fd, parsed)
                for _, record in parsed:
                    self._validate_recovery_candidate(root_fd, record)
                paired_temps = [
                    temp
                    for journal_entry, record in parsed
                    for temp in journal_temps.get(
                        record.transaction_id,
                        (),
                    )
                    if temp.identity == journal_entry.identity
                ]
                for journal_entry, record in parsed:
                    self._recover_one(root_fd, journal_entry, record)
                for temp in paired_temps:
                    _unlink_owned(root_fd, temp)
            finally:
                os.close(journal_fd)
        finally:
            os.close(root_fd)

    def _validate_journal_set(
        self,
        root_fd: int,
        parsed: list[tuple[_OwnedEntry, _JournalRecord]],
    ) -> None:
        grouped: dict[
            tuple[tuple[str, ...], str, str, str],
            list[_JournalRecord],
        ] = {}
        for _, record in parsed:
            key = (
                record.parent_parts,
                record.names["file"],
                record.names["manifest"],
                record.names["marker"],
            )
            grouped.setdefault(key, []).append(record)
        for records in grouped.values():
            if len(records) == 1:
                continue
            owners = [
                record
                for record in records
                if self._is_complete_owned_publication(root_fd, record)
            ]
            if (
                len(owners) != 1
                or any(
                    record is not owners[0]
                    and not self._is_preexisting_collision_loser(
                        root_fd,
                        record,
                    )
                    for record in records
                )
            ):
                raise CanonicalPublishError(
                    "CANONICAL_JOURNAL_CONFLICT"
                )

    def _validate_recovery_candidate(
        self,
        root_fd: int,
        record: _JournalRecord,
    ) -> None:
        if not all(
            _directory_matches(root_fd, directory)
            for directory in record.preexisting_directories
        ):
            raise CanonicalPublishError(
                "CANONICAL_RECOVERY_UNCERTAIN"
            )
        metadata_matches = self._metadata_matches(
            record.dataset,
            record.manifest,
        )
        self._discover_recovery_entries(
            root_fd,
            record,
            require_partial_for_final=not metadata_matches,
        )
        _discover_created_directories(
            root_fd,
            record.created_dir_parts,
        )
        if (
            not any(
                identity is not None
                for identity in record.preexisting_finals.values()
            )
            and metadata_matches
            and not self._published_content_matches(root_fd, record)
        ):
            raise CanonicalPublishError(
                "CANONICAL_RECOVERY_UNCERTAIN"
            )

    def _is_complete_owned_publication(
        self,
        root_fd: int,
        record: _JournalRecord,
    ) -> bool:
        if any(
            identity is not None
            for identity in record.preexisting_finals.values()
        ):
            return False
        try:
            return (
                self._metadata_matches(record.dataset, record.manifest)
                and self._published_content_matches(root_fd, record)
            )
        except CanonicalStoreError:
            return False

    def _is_preexisting_collision_loser(
        self,
        root_fd: int,
        record: _JournalRecord,
    ) -> bool:
        if any(
            identity is None
            for identity in record.preexisting_finals.values()
        ):
            return False
        try:
            parent_fd = _open_directory_parts(
                root_fd,
                record.parent_parts,
                create=False,
                created=None,
            )
        except (FileNotFoundError, CanonicalStoreError):
            return False
        try:
            return all(
                _optional_lstat_identity(parent_fd, record.names[role])
                == record.preexisting_finals[role]
                for role in ("file", "manifest", "marker")
            )
        finally:
            os.close(parent_fd)

    def _recover_one(
        self,
        root_fd: int,
        journal_entry: _OwnedEntry,
        record: _JournalRecord,
    ) -> None:
        if not all(
            _directory_matches(root_fd, directory)
            for directory in record.preexisting_directories
        ):
            raise CanonicalPublishError(
                "CANONICAL_RECOVERY_UNCERTAIN"
            )
        metadata_matches = self._metadata_matches(
            record.dataset,
            record.manifest,
        )
        entries = self._discover_recovery_entries(
            root_fd,
            record,
            require_partial_for_final=not metadata_matches,
        )
        created_dirs = _discover_created_directories(
            root_fd,
            record.created_dir_parts,
        )
        if any(
            identity is not None
            for identity in record.preexisting_finals.values()
        ):
            self._compensate(
                root_fd,
                entries,
                journal_entry,
                created_dirs,
            )
            self._cleanup_staged_ownership(record.staged)
            return
        if metadata_matches:
            if not self._published_content_matches(root_fd, record):
                raise CanonicalPublishError(
                    "CANONICAL_RECOVERY_UNCERTAIN"
                )
            self._cleanup_committed_transaction(
                root_fd,
                entries,
                journal_entry,
                created_dirs,
            )
            self._cleanup_staged_ownership(record.staged)
            return
        self._compensate(
            root_fd,
            entries,
            journal_entry,
            created_dirs,
        )
        self._cleanup_staged_ownership(record.staged)

    def _discover_recovery_entries(
        self,
        root_fd: int,
        record: _JournalRecord,
        *,
        require_partial_for_final: bool,
    ) -> dict[str, _OwnedEntry]:
        try:
            parent_fd = _open_directory_parts(
                root_fd,
                record.parent_parts,
                create=False,
                created=None,
            )
        except FileNotFoundError:
            return {}
        entries: dict[str, _OwnedEntry] = {}
        try:
            for role, name in record.names.items():
                try:
                    identity = _lstat_identity(parent_fd, name)
                except FileNotFoundError:
                    if (
                        role in {"file", "manifest", "marker"}
                        and record.preexisting_finals[role] is not None
                    ):
                        raise CanonicalPublishError(
                            "CANONICAL_RECOVERY_UNCERTAIN"
                        )
                    continue
                if role in {"file", "manifest", "marker"}:
                    preexisting = record.preexisting_finals[role]
                    if preexisting is not None:
                        if identity != preexisting:
                            raise CanonicalPublishError(
                                "CANONICAL_RECOVERY_UNCERTAIN"
                            )
                        continue
                    partial_role = {
                        "file": "partial_file",
                        "manifest": "partial_manifest",
                        "marker": "partial_marker",
                    }[role]
                    partial_identity = _optional_lstat_identity(
                        parent_fd,
                        record.names[partial_role],
                    )
                    if not _recovery_entry_content_matches(
                        parent_fd,
                        role,
                        name,
                        identity,
                        record,
                    ):
                        raise CanonicalPublishError(
                            "CANONICAL_RECOVERY_UNCERTAIN"
                        )
                    if partial_identity is None:
                        if require_partial_for_final:
                            raise CanonicalPublishError(
                                "CANONICAL_RECOVERY_UNCERTAIN"
                            )
                    elif partial_identity != identity:
                        raise CanonicalPublishError(
                            "CANONICAL_RECOVERY_UNCERTAIN"
                        )
                entries[role] = _OwnedEntry(
                    record.parent_parts,
                    name,
                    identity,
                )
            return entries
        finally:
            os.close(parent_fd)

    def _published_content_matches(
        self,
        root_fd: int,
        record: _JournalRecord,
    ) -> bool:
        try:
            parent_fd = _open_directory_parts(
                root_fd,
                record.parent_parts,
                create=False,
                created=None,
            )
        except (FileNotFoundError, CanonicalStoreError):
            return False
        try:
            for role in ("file", "manifest", "marker"):
                name = record.names[role]
                try:
                    identity = _lstat_identity(parent_fd, name)
                except (FileNotFoundError, CanonicalStoreError):
                    return False
                if not _recovery_entry_content_matches(
                    parent_fd,
                    role,
                    name,
                    identity,
                    record,
                ):
                    return False
            return True
        finally:
            os.close(parent_fd)

    def _new_owned_session(self) -> Session:
        session = self._metadata_session_factory()
        if (
            not isinstance(session, Session)
            or session.in_transaction()
            or session.new
            or session.dirty
            or session.deleted
        ):
            raise CanonicalPublishError(
                "CANONICAL_METADATA_SESSION_NOT_CLEAN"
            )
        return session

    def _metadata_matches(
        self,
        dataset: DatasetKey,
        manifest: PartitionManifest,
    ) -> bool:
        session = self._new_owned_session()
        try:
            rows = HistoricalCatalog(session).list_partitions(dataset)
            matches = [
                row
                for row in rows
                if (
                    _utc_naive(row.coverage_start)
                    == _utc_naive(manifest.coverage_start)
                    and _utc_naive(row.coverage_end)
                    == _utc_naive(manifest.coverage_end)
                    and row.manifest_version == manifest.manifest_version
                )
            ]
            if not matches:
                return False
            if len(matches) != 1 or not _row_matches_manifest(
                matches[0],
                manifest,
            ):
                raise CanonicalPublishError(
                    "CANONICAL_RECOVERY_UNCERTAIN"
                )
            return True
        finally:
            session.close()

    def _committed_entries_match(
        self,
        root_fd: int,
        entries: Mapping[str, _OwnedEntry],
    ) -> bool:
        return all(_entry_matches(root_fd, entry) for entry in entries.values())

    def _compensate(
        self,
        root_fd: int,
        entries: Mapping[str, _OwnedEntry],
        journal_entry: _OwnedEntry | None,
        _created_dirs: list[_OwnedDirectory],
    ) -> None:
        for role in (
            "marker",
            "manifest",
            "file",
            "partial_marker",
            "partial_manifest",
            "partial_file",
            "journal_temp",
        ):
            entry = entries.get(role)
            if entry is not None:
                _unlink_owned(root_fd, entry)
        if journal_entry is not None:
            _unlink_owned(root_fd, journal_entry)

    def _cleanup_committed_transaction(
        self,
        root_fd: int,
        entries: Mapping[str, _OwnedEntry],
        journal_entry: _OwnedEntry | None,
        _created_dirs: list[_OwnedDirectory],
    ) -> None:
        for role in ("partial_marker", "partial_manifest", "partial_file"):
            entry = entries.get(role)
            if entry is not None:
                _unlink_owned(root_fd, entry)
                self._fault(f"after_{role}_unlink")
        if journal_entry is not None:
            self._fault("before_journal_unlink")
            _unlink_owned(root_fd, journal_entry)

    def _published_from_recovery(
        self,
        validation: ValidationResult,
        manifest: PartitionManifest,
        parent_parts: tuple[str, ...],
        names: Mapping[str, str],
    ) -> PublishedPartition:
        return PublishedPartition(
            file_path=(
                self._canonical_anchor.path
                / Path(*parent_parts, names["file"])
            ),
            manifest_path=(
                self._canonical_anchor.path
                / Path(*parent_parts, names["manifest"])
            ),
            prepared_marker_path=(
                self._canonical_anchor.path
                / Path(*parent_parts, names["marker"])
            ),
            partition_manifest=manifest,
            file_checksum=manifest.checksum,
            canonical_logical_fingerprint=(
                validation.canonical_logical_fingerprint
            ),
            data_version=validation.data_version,
        )

    def _partition_parts(
        self,
        validation: ValidationResult,
    ) -> tuple[str, ...]:
        return _partition_parts_from_facts(
            validation.dataset,
            validation.data_version,
            validation.coverage_start,
            validation.coverage_end,
        )

    def _publication_names(
        self,
        expected: PublishExpectation,
        transaction_id: str,
    ) -> dict[str, str]:
        return _publication_names_for(
            expected.manifest_version,
            transaction_id,
        )

    def _open_root(self, anchor: _RootAnchor) -> int:
        try:
            fd, identity = _open_absolute_directory(
                anchor.path,
                create_leaf=False,
            )
        except (OSError, CanonicalStoreError) as exc:
            raise CanonicalStoreError(
                f"{anchor.kind}_ROOT_CHANGED"
            ) from exc
        if identity != anchor.identity:
            os.close(fd)
            raise CanonicalStoreError(f"{anchor.kind}_ROOT_CHANGED")
        return fd

    def _open_staged(self, staged: StagedBatch) -> tuple[int, int]:
        if not isinstance(staged, StagedBatch):
            raise CanonicalStoreError("CANONICAL_STAGED_BATCH_INVALID")
        root_fd = self._open_root(self._staging_anchor)
        try:
            task_identity = _lstat_identity(
                root_fd,
                staged.task_name,
                directory=True,
            )
            if task_identity != staged.task_identity:
                raise CanonicalStoreError(
                    "CANONICAL_STAGED_BATCH_REPLACED"
                )
            task_fd = _open_child_directory(root_fd, staged.task_name)
        finally:
            os.close(root_fd)
        file_fd: int | None = None
        try:
            file_fd = os.open(
                "batch.parquet",
                _FILE_READ_FLAGS,
                dir_fd=task_fd,
            )
            file_stat = os.fstat(file_fd)
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or _Identity.from_stat(file_stat) != staged.file_identity
            ):
                raise CanonicalStoreError(
                    "CANONICAL_STAGED_BATCH_REPLACED"
                )
            return task_fd, file_fd
        except BaseException:
            if file_fd is not None:
                os.close(file_fd)
            os.close(task_fd)
            raise

    def _cleanup_staged(self, staged: StagedBatch) -> None:
        self._cleanup_staged_ownership(
            _StagedOwnership(
                staged.task_name,
                staged.task_identity,
                staged.file_identity,
            )
        )

    def _cleanup_staged_ownership(
        self,
        staged: _StagedOwnership,
    ) -> None:
        try:
            root_fd = self._open_root(self._staging_anchor)
        except CanonicalStoreError:
            return
        try:
            self._cleanup_stage_parts(
                root_fd,
                staged.task_name,
                staged.task_identity,
                staged.file_identity,
            )
        finally:
            os.close(root_fd)

    def _cleanup_stage_parts(
        self,
        root_fd: int,
        task_name: str,
        task_identity: _Identity | None,
        file_identity: _Identity | None,
    ) -> None:
        if task_identity is None:
            return
        try:
            if (
                _lstat_identity(root_fd, task_name, directory=True)
                != task_identity
            ):
                return
            task_fd = _open_child_directory(root_fd, task_name)
        except (FileNotFoundError, CanonicalStoreError):
            return
        quarantine_fd = _open_cleanup_quarantine(root_fd)
        try:
            if file_identity is not None:
                _unlink_owned_from_parent(
                    task_fd,
                    "batch.parquet",
                    file_identity,
                    quarantine_fd,
                )
        finally:
            os.close(task_fd)
            os.close(quarantine_fd)
        quarantine_fd = _open_cleanup_quarantine(root_fd)
        try:
            _quarantine_owned_from_parent(
                root_fd,
                task_name,
                task_identity,
                quarantine_fd,
                directory=True,
            )
        finally:
            os.close(quarantine_fd)

    def _fault(self, point: str) -> None:
        self._fault_injector(point)


def _create_and_anchor_root(path: Path, *, kind: str) -> _RootAnchor:
    if not isinstance(path, Path):
        raise TypeError("roots must be pathlib.Path instances")
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        fd, identity = _open_absolute_directory(absolute, create_leaf=True)
    except (OSError, CanonicalStoreError) as exc:
        raise CanonicalStoreError(f"{kind}_ROOT_UNSAFE") from exc
    os.close(fd)
    return _RootAnchor(path=absolute, identity=identity, kind=kind)


def _open_absolute_directory(
    path: Path,
    *,
    create_leaf: bool,
) -> tuple[int, _Identity]:
    if not path.is_absolute():
        raise CanonicalStoreError("CANONICAL_ROOT_UNSAFE")
    current_fd = os.open("/", _DIR_FLAGS)
    try:
        parts = path.parts[1:]
        for index, part in enumerate(parts):
            is_leaf = index == len(parts) - 1
            try:
                value = os.stat(
                    part,
                    dir_fd=current_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                if not (create_leaf and is_leaf):
                    raise
                os.mkdir(part, mode=0o700, dir_fd=current_fd)
                value = os.stat(
                    part,
                    dir_fd=current_fd,
                    follow_symlinks=False,
                )
            if not stat.S_ISDIR(value.st_mode):
                raise CanonicalStoreError("CANONICAL_ROOT_UNSAFE")
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=current_fd)
            if _Identity.from_stat(os.fstat(next_fd)) != _Identity.from_stat(
                value
            ):
                os.close(next_fd)
                raise CanonicalStoreError("CANONICAL_ROOT_CHANGED")
            os.close(current_fd)
            current_fd = next_fd
        final_stat = os.fstat(current_fd)
        return current_fd, _Identity.from_stat(final_stat)
    except BaseException:
        os.close(current_fd)
        raise


def _open_directory_parts(
    root_fd: int,
    parts: tuple[str, ...],
    *,
    create: bool,
    created: list[_OwnedDirectory] | None,
    on_created: Callable[[_OwnedDirectory], None] | None = None,
) -> int:
    current_fd = os.dup(root_fd)
    traversed: list[str] = []
    try:
        for part in parts:
            require_safe_component(part, field="path_component")
            traversed.append(part)
            try:
                value = os.stat(
                    part,
                    dir_fd=current_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, mode=0o700, dir_fd=current_fd)
                value = os.stat(
                    part,
                    dir_fd=current_fd,
                    follow_symlinks=False,
                )
                os.fsync(current_fd)
                owned_directory = _OwnedDirectory(
                    tuple(traversed),
                    _Identity.from_stat(value),
                )
                if created is not None:
                    created.append(owned_directory)
                if on_created is not None:
                    on_created(owned_directory)
            if not stat.S_ISDIR(value.st_mode):
                raise CanonicalStoreError("CANONICAL_PATH_UNSAFE")
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=current_fd)
            if _Identity.from_stat(os.fstat(next_fd)) != _Identity.from_stat(
                value
            ):
                os.close(next_fd)
                raise CanonicalStoreError("CANONICAL_PATH_CHANGED")
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _open_child_directory(parent_fd: int, name: str) -> int:
    value = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(value.st_mode):
        raise CanonicalStoreError("CANONICAL_PATH_UNSAFE")
    child_fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    if _Identity.from_stat(os.fstat(child_fd)) != _Identity.from_stat(value):
        os.close(child_fd)
        raise CanonicalStoreError("CANONICAL_PATH_CHANGED")
    return child_fd


def _lstat_identity(
    parent_fd: int,
    name: str,
    *,
    directory: bool = False,
) -> _Identity:
    value = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    expected = stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(
        value.st_mode
    )
    if not expected:
        raise CanonicalStoreError("CANONICAL_PATH_UNSAFE")
    return _Identity.from_stat(value)


def _copy_fd_create_only(
    source_fd: int,
    parent_fd: int,
    name: str,
) -> _Identity:
    target_fd = os.open(name, _FILE_CREATE_FLAGS, 0o600, dir_fd=parent_fd)
    try:
        os.lseek(source_fd, 0, os.SEEK_SET)
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                view = view[written:]
        os.fsync(target_fd)
        return _Identity.from_stat(os.fstat(target_fd))
    finally:
        os.close(target_fd)


def _write_bytes_create_only(
    parent_fd: int,
    name: str,
    content: bytes,
) -> _Identity:
    file_fd = os.open(name, _FILE_CREATE_FLAGS, 0o600, dir_fd=parent_fd)
    try:
        view = memoryview(content)
        while view:
            written = os.write(file_fd, view)
            view = view[written:]
        os.fsync(file_fd)
        return _Identity.from_stat(os.fstat(file_fd))
    finally:
        os.close(file_fd)


def _write_journal_temp_create_only(
    parent_fd: int,
    name: str,
    content: bytes,
    fault: Callable[[str], None],
) -> _Identity:
    file_fd = os.open(name, _FILE_CREATE_FLAGS, 0o600, dir_fd=parent_fd)
    try:
        split = max(1, len(content) // 2)
        for index, chunk in enumerate((content[:split], content[split:])):
            view = memoryview(chunk)
            while view:
                written = os.write(file_fd, view)
                view = view[written:]
            if index == 0:
                fault("after_journal_temp_partial_write")
        os.fsync(file_fd)
        return _Identity.from_stat(os.fstat(file_fd))
    finally:
        os.close(file_fd)


def _atomic_rename_no_replace_at(
    source_dir_fd: int,
    source_name: str,
    target_dir_fd: int,
    target_name: str,
) -> None:
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is None:
            raise CanonicalPublishError(
                "CANONICAL_ATOMIC_RENAME_UNAVAILABLE"
            )
        renameatx_np.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameatx_np.restype = ctypes.c_int
        ctypes.set_errno(0)
        result = renameatx_np(
            source_dir_fd,
            os.fsencode(source_name),
            target_dir_fd,
            os.fsencode(target_name),
            0x00000004,  # RENAME_EXCL
        )
    elif sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        ctypes.set_errno(0)
        if renameat2 is not None:
            renameat2.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            renameat2.restype = ctypes.c_int
            result = renameat2(
                source_dir_fd,
                os.fsencode(source_name),
                target_dir_fd,
                os.fsencode(target_name),
                0x00000001,  # RENAME_NOREPLACE
            )
        else:
            syscall_number = {
                "aarch64": 276,
                "amd64": 316,
                "arm64": 276,
                "i386": 353,
                "i686": 353,
                "ppc64le": 357,
                "riscv64": 276,
                "s390x": 347,
                "x86_64": 316,
            }.get(os.uname().machine)
            syscall = getattr(libc, "syscall", None)
            if syscall_number is None or syscall is None:
                raise CanonicalPublishError(
                    "CANONICAL_ATOMIC_RENAME_UNAVAILABLE"
                )
            result = syscall(
                syscall_number,
                source_dir_fd,
                ctypes.c_char_p(os.fsencode(source_name)),
                target_dir_fd,
                ctypes.c_char_p(os.fsencode(target_name)),
                0x00000001,  # RENAME_NOREPLACE
            )
    else:
        raise CanonicalPublishError(
            "CANONICAL_ATOMIC_RENAME_UNAVAILABLE"
        )
    if result == 0:
        return
    code = ctypes.get_errno()
    if code in {errno.ENOSYS, errno.ENOTSUP}:
        raise CanonicalPublishError(
            "CANONICAL_ATOMIC_RENAME_UNAVAILABLE"
        )
    raise OSError(
        code,
        os.strerror(code),
        source_name,
        target_name,
    )


def _link_create_only_at(
    parent_fd: int,
    source_name: str,
    target_name: str,
    identity: _Identity,
) -> None:
    if _lstat_identity(parent_fd, source_name) != identity:
        raise CanonicalPublishError("CANONICAL_PARTIAL_REPLACED")
    try:
        os.link(
            source_name,
            target_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileExistsError as exc:
        raise CanonicalPublishError("CANONICAL_PUBLISH_COLLISION") from exc
    if _lstat_identity(parent_fd, target_name) != identity:
        raise CanonicalPublishError("CANONICAL_PUBLISHED_ENTRY_REPLACED")


def _link_and_record_owned_final(
    owned_entries: dict[str, _OwnedEntry],
    *,
    role: str,
    parent_fd: int,
    parent_parts: tuple[str, ...],
    source_name: str,
    target_name: str,
    identity: _Identity,
) -> None:
    entry = _OwnedEntry(parent_parts, target_name, identity)
    try:
        _link_create_only_at(
            parent_fd,
            source_name,
            target_name,
            identity,
        )
    except BaseException:
        if _optional_lstat_identity(parent_fd, target_name) == identity:
            owned_entries[role] = entry
        raise
    owned_entries[role] = entry


def _require_absent(parent_fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise CanonicalPublishError("CANONICAL_PUBLISH_COLLISION")


def _entry_matches(root_fd: int, entry: _OwnedEntry) -> bool:
    try:
        parent_fd = _open_directory_parts(
            root_fd,
            entry.parent_parts,
            create=False,
            created=None,
        )
    except (FileNotFoundError, CanonicalStoreError):
        return False
    try:
        return _lstat_identity(parent_fd, entry.name) == entry.identity
    except (FileNotFoundError, CanonicalStoreError):
        return False
    finally:
        os.close(parent_fd)


def _directory_matches(
    root_fd: int,
    directory: _OwnedDirectory,
) -> bool:
    try:
        parent_fd = _open_directory_parts(
            root_fd,
            directory.parts[:-1],
            create=False,
            created=None,
        )
    except (FileNotFoundError, CanonicalStoreError):
        return False
    try:
        try:
            actual = _lstat_identity(
                parent_fd,
                directory.parts[-1],
                directory=True,
            )
        except (FileNotFoundError, CanonicalStoreError):
            return False
        return actual == directory.identity
    finally:
        os.close(parent_fd)


def _recovery_entry_content_matches(
    parent_fd: int,
    role: str,
    name: str,
    identity: _Identity,
    record: _JournalRecord,
) -> bool:
    try:
        if role == "file":
            return _sha256_at(parent_fd, name, identity) == (
                record.manifest.checksum
            )
        content = _read_bytes_at(parent_fd, name, identity)
        parsed = json.loads(content)
        if role == "manifest":
            expected: object = record.manifest_document
        elif role == "marker":
            expected = {
                "state": "PREPARED",
                "transaction_id": record.transaction_id,
                "manifest_digest": record.manifest.manifest_digest,
                "file_checksum": record.manifest.checksum,
            }
        else:
            return False
        return (
            content == _canonical_json_bytes(parsed)
            and content == _canonical_json_bytes(expected)
        )
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        CanonicalStoreError,
    ):
        return False


def _read_bytes_at(
    parent_fd: int,
    name: str,
    identity: _Identity,
) -> bytes:
    file_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=parent_fd)
    try:
        if _Identity.from_stat(os.fstat(file_fd)) != identity:
            raise CanonicalStoreError("CANONICAL_OWNERSHIP_CHANGED")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(file_fd)


def _discover_created_directories(
    root_fd: int,
    planned_parts: tuple[tuple[str, ...], ...],
) -> list[_OwnedDirectory]:
    discovered: list[_OwnedDirectory] = []
    for parts in planned_parts:
        try:
            parent_fd = _open_directory_parts(
                root_fd,
                parts[:-1],
                create=False,
                created=None,
            )
        except FileNotFoundError:
            break
        try:
            try:
                identity = _lstat_identity(
                    parent_fd,
                    parts[-1],
                    directory=True,
                )
            except FileNotFoundError:
                break
            discovered.append(_OwnedDirectory(parts, identity))
        finally:
            os.close(parent_fd)
    return discovered


def _directory_intent_plan(
    root_fd: int,
    parent_parts: tuple[str, ...],
) -> list[dict[str, object]]:
    plan: list[dict[str, object]] = []
    current_fd = os.dup(root_fd)
    missing = False
    try:
        for index, part in enumerate(parent_parts, start=1):
            parts = list(parent_parts[:index])
            if missing:
                plan.append({"parts": parts, "preexisting": False})
                continue
            try:
                identity = _lstat_identity(
                    current_fd,
                    part,
                    directory=True,
                )
            except FileNotFoundError:
                missing = True
                plan.append({"parts": parts, "preexisting": False})
                continue
            plan.append(
                {
                    "parts": parts,
                    "preexisting": True,
                    "device": identity.device,
                    "inode": identity.inode,
                }
            )
            next_fd = _open_child_directory(current_fd, part)
            os.close(current_fd)
            current_fd = next_fd
        return plan
    finally:
        os.close(current_fd)


def _final_presence_plan(
    root_fd: int,
    parent_parts: tuple[str, ...],
    names: Mapping[str, str],
) -> dict[str, dict[str, object]]:
    try:
        parent_fd = _open_directory_parts(
            root_fd,
            parent_parts,
            create=False,
            created=None,
        )
    except FileNotFoundError:
        return {
            role: {"present": False}
            for role in ("file", "manifest", "marker")
        }
    try:
        result: dict[str, dict[str, object]] = {}
        for role in ("file", "manifest", "marker"):
            identity = _optional_lstat_identity(
                parent_fd,
                names[role],
            )
            if identity is None:
                result[role] = {"present": False}
            else:
                result[role] = {
                    "present": True,
                    "device": identity.device,
                    "inode": identity.inode,
                }
        return result
    finally:
        os.close(parent_fd)


def _recheck_final_presence_before_link(
    parent_fd: int,
    names: Mapping[str, str],
    recorded: Mapping[str, Mapping[str, object]],
) -> None:
    for role in ("file", "manifest", "marker"):
        actual = _optional_lstat_identity(parent_fd, names[role])
        expected = recorded[role]
        if expected["present"] is True:
            expected_identity = _Identity(
                int(expected["device"]),
                int(expected["inode"]),
            )
            if actual != expected_identity:
                raise CanonicalPublishError(
                    "CANONICAL_PUBLISH_COLLISION"
                )
            raise CanonicalPublishError("CANONICAL_PUBLISH_COLLISION")
        if actual is not None:
            raise CanonicalPublishError("CANONICAL_PUBLISH_COLLISION")


def _optional_lstat_identity(
    parent_fd: int,
    name: str,
) -> _Identity | None:
    try:
        value = os.stat(
            name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    return _Identity.from_stat(value)


def _unlink_owned(root_fd: int, entry: _OwnedEntry) -> None:
    try:
        parent_fd = _open_directory_parts(
            root_fd,
            entry.parent_parts,
            create=False,
            created=None,
        )
    except FileNotFoundError:
        return
    quarantine_fd = _open_cleanup_quarantine(root_fd)
    try:
        _unlink_owned_from_parent(
            parent_fd,
            entry.name,
            entry.identity,
            quarantine_fd,
        )
    finally:
        os.close(quarantine_fd)
        os.close(parent_fd)


def _unlink_owned_from_parent(
    parent_fd: int,
    name: str,
    identity: _Identity,
    quarantine_fd: int,
) -> None:
    _quarantine_owned_from_parent(
        parent_fd,
        name,
        identity,
        quarantine_fd,
        directory=False,
    )


def _open_cleanup_quarantine(root_fd: int) -> int:
    try:
        quarantine_fd = _open_child_directory(
            root_fd,
            _CLEANUP_QUARANTINE_DIR,
        )
    except FileNotFoundError:
        try:
            os.mkdir(
                _CLEANUP_QUARANTINE_DIR,
                mode=0o700,
                dir_fd=root_fd,
            )
        except FileExistsError:
            pass
        os.fsync(root_fd)
        quarantine_fd = _open_child_directory(
            root_fd,
            _CLEANUP_QUARANTINE_DIR,
        )
    try:
        path_stat = os.stat(
            _CLEANUP_QUARANTINE_DIR,
            dir_fd=root_fd,
            follow_symlinks=False,
        )
        fd_stat = os.fstat(quarantine_fd)
        if (
            not stat.S_ISDIR(path_stat.st_mode)
            or not stat.S_ISDIR(fd_stat.st_mode)
            or _Identity.from_stat(path_stat)
            != _Identity.from_stat(fd_stat)
            or path_stat.st_uid != os.geteuid()
            or fd_stat.st_uid != os.geteuid()
            or stat.S_IMODE(path_stat.st_mode) != 0o700
            or stat.S_IMODE(fd_stat.st_mode) != 0o700
        ):
            raise CanonicalPublishError(
                "CANONICAL_CLEANUP_QUARANTINE_UNSAFE"
            )
        return quarantine_fd
    except BaseException:
        os.close(quarantine_fd)
        raise


def _quarantine_owned_from_parent(
    parent_fd: int,
    name: str,
    identity: _Identity,
    quarantine_fd: int,
    *,
    directory: bool,
) -> None:
    # POSIX has no compare-and-unlink primitive.  The public name is touched
    # only by this atomic rename into the store-owned private namespace.
    # Identity is checked after the claim; a mismatched object remains there
    # as evidence and is never deleted.  Non-empty directories are not
    # claimed because their contents are not proven transaction-owned.
    if directory and not _owned_directory_is_empty(
        parent_fd,
        name,
        identity,
    ):
        return
    for _attempt in range(8):
        claim_name = f"claim-{uuid.uuid4().hex}"
        try:
            _atomic_rename_no_replace_at(
                parent_fd,
                name,
                quarantine_fd,
                claim_name,
            )
            break
        except FileExistsError:
            continue
        except FileNotFoundError:
            return
    else:
        raise CanonicalPublishError(
            "CANONICAL_CLEANUP_QUARANTINE_UNAVAILABLE"
        )
    try:
        actual = _lstat_identity(
            quarantine_fd,
            claim_name,
            directory=directory,
        )
    except CanonicalStoreError as exc:
        raise CanonicalPublishError(
            "CANONICAL_OWNERSHIP_CHANGED"
        ) from exc
    if actual != identity:
        raise CanonicalPublishError("CANONICAL_OWNERSHIP_CHANGED")
    if directory:
        try:
            os.rmdir(claim_name, dir_fd=quarantine_fd)
        except OSError as exc:
            if exc.errno not in {39, 66}:  # ENOTEMPTY on Linux/macOS
                raise
        return
    os.unlink(claim_name, dir_fd=quarantine_fd)


def _owned_directory_is_empty(
    parent_fd: int,
    name: str,
    identity: _Identity,
) -> bool:
    try:
        directory_fd = _open_child_directory(parent_fd, name)
    except FileNotFoundError:
        return False
    try:
        if _Identity.from_stat(os.fstat(directory_fd)) != identity:
            raise CanonicalPublishError("CANONICAL_OWNERSHIP_CHANGED")
        with os.scandir(directory_fd) as entries:
            return next(entries, None) is None
    finally:
        os.close(directory_fd)


def _read_json_at(
    parent_fd: int,
    name: str,
) -> tuple[_Identity, object]:
    file_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=parent_fd)
    try:
        value = os.fstat(file_fd)
        if not stat.S_ISREG(value.st_mode):
            raise CanonicalPublishError("CANONICAL_JOURNAL_INVALID")
        if value.st_size > _MAX_JOURNAL_BYTES:
            raise CanonicalPublishError("CANONICAL_JOURNAL_TOO_LARGE")
        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > _MAX_JOURNAL_BYTES:
                raise CanonicalPublishError(
                    "CANONICAL_JOURNAL_TOO_LARGE"
                )
            chunks.append(chunk)
        return _Identity.from_stat(value), json.loads(b"".join(chunks))
    finally:
        os.close(file_fd)


def _journal_payload(
    *,
    transaction_id: str,
    validation: ValidationResult,
    staged: StagedBatch,
    partition_manifest: PartitionManifest,
    manifest_document: dict[str, object],
    parent_parts: tuple[str, ...],
    names: Mapping[str, str],
    directory_plan: list[dict[str, object]],
    final_entries: dict[str, dict[str, object]],
) -> dict[str, object]:
    manifest_facts: dict[str, object] = {
        "coverage_start": _utc_text(partition_manifest.coverage_start),
        "coverage_end": _utc_text(partition_manifest.coverage_end),
        "manifest_version": partition_manifest.manifest_version,
        "manifest_uri": partition_manifest.manifest_uri,
        "manifest_digest": partition_manifest.manifest_digest,
        "file_uri": partition_manifest.file_uri,
        "checksum": partition_manifest.checksum,
        "row_count": partition_manifest.row_count,
    }
    if partition_manifest.overlap_reason is not None:
        manifest_facts["overlap_reason"] = partition_manifest.overlap_reason
    return {
        "journal_version": "canonical-publish-intent-v2",
        "transaction_id": transaction_id,
        "staged": {
            "task_name": staged.task_name,
            "task_device": staged.task_identity.device,
            "task_inode": staged.task_identity.inode,
            "file_device": staged.file_identity.device,
            "file_inode": staged.file_identity.inode,
        },
        "dataset": _dataset_payload(validation.dataset),
        "partition_manifest": manifest_facts,
        "data_version": validation.data_version,
        "canonical_logical_fingerprint": (
            validation.canonical_logical_fingerprint
        ),
        "manifest_document": manifest_document,
        "parent_parts": list(parent_parts),
        "names": dict(names),
        "final_entries": final_entries,
        "created_dirs": directory_plan,
    }


def _journal_temp_transaction_id(name: str) -> str | None:
    prefix = "journal-temp-"
    suffix = ".partial"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    transaction_id = name[len(prefix) : -len(suffix)]
    if not _is_transaction_id(transaction_id):
        return None
    return transaction_id


def _parse_journal(
    payload: object,
    *,
    journal_name: str,
) -> _JournalRecord:
    try:
        if not isinstance(payload, dict) or set(payload) != {
            "journal_version",
            "transaction_id",
            "staged",
            "dataset",
            "partition_manifest",
            "data_version",
            "canonical_logical_fingerprint",
            "manifest_document",
            "parent_parts",
            "names",
            "final_entries",
            "created_dirs",
        }:
            raise ValueError
        if payload["journal_version"] != "canonical-publish-intent-v2":
            raise ValueError
        transaction_id = payload["transaction_id"]
        if (
            not _is_transaction_id(transaction_id)
            or journal_name != f"txn-{transaction_id}.json"
        ):
            raise ValueError
        dataset_data = payload["dataset"]
        manifest_data = payload["partition_manifest"]
        staged_data = payload["staged"]
        if (
            not isinstance(staged_data, dict)
            or set(staged_data)
            != {
                "task_name",
                "task_device",
                "task_inode",
                "file_device",
                "file_inode",
            }
        ):
            raise ValueError
        task_name = require_safe_component(
            staged_data["task_name"],
            field="staged_task_name",
        )
        if not (
            task_name.startswith("canonical-stage-")
            and _is_transaction_id(task_name.removeprefix("canonical-stage-"))
        ):
            raise ValueError
        staged = _StagedOwnership(
            task_name=task_name,
            task_identity=_Identity(
                _require_positive_exact_int(staged_data["task_device"]),
                _require_positive_exact_int(staged_data["task_inode"]),
            ),
            file_identity=_Identity(
                _require_positive_exact_int(staged_data["file_device"]),
                _require_positive_exact_int(staged_data["file_inode"]),
            ),
        )
        if not isinstance(dataset_data, dict):
            raise ValueError
        dataset = DatasetKey(**dataset_data)
        if _dataset_payload(dataset) != dataset_data:
            raise ValueError
        data_version = require_safe_component(
            payload["data_version"],
            field="data_version",
        )
        logical_fingerprint = payload["canonical_logical_fingerprint"]
        if not _is_sha256(logical_fingerprint):
            raise ValueError
        manifest_fields = {
                "coverage_start",
                "coverage_end",
                "manifest_version",
                "manifest_uri",
                "manifest_digest",
                "file_uri",
                "checksum",
                "row_count",
            }
        if not isinstance(manifest_data, dict) or set(manifest_data) not in (
            manifest_fields,
            manifest_fields | {"overlap_reason"},
        ):
            raise ValueError
        coverage_start = _parse_utc(manifest_data["coverage_start"])
        coverage_end = _parse_utc(manifest_data["coverage_end"])
        if coverage_start >= coverage_end:
            raise ValueError
        manifest_version = require_safe_component(
            manifest_data["manifest_version"],
            field="manifest_version",
        )
        checksum = manifest_data["checksum"]
        manifest_digest = manifest_data["manifest_digest"]
        if not _is_sha256(checksum) or not _is_sha256(manifest_digest):
            raise ValueError
        row_count = _require_positive_exact_int(manifest_data["row_count"])
        overlap_reason = manifest_data.get("overlap_reason")
        if (
            overlap_reason is not None
            and overlap_reason not in ALLOWED_OVERLAP_REASONS
        ):
            raise ValueError
        expected_parent_parts = _partition_parts_from_facts(
            dataset,
            data_version,
            coverage_start,
            coverage_end,
        )
        parent_parts_value = payload["parent_parts"]
        if not isinstance(parent_parts_value, list) or not all(
            isinstance(part, str) for part in parent_parts_value
        ):
            raise ValueError
        parent_parts = tuple(parent_parts_value)
        if parent_parts != expected_parent_parts:
            raise ValueError
        names_value = payload["names"]
        if not isinstance(names_value, dict):
            raise ValueError
        names = _publication_names_for(
            manifest_version,
            transaction_id,
        )
        if names_value != names:
            raise ValueError
        for name in names.values():
            require_safe_component(name, field="journal_name_component")
        final_entries_value = payload["final_entries"]
        if (
            not isinstance(final_entries_value, dict)
            or set(final_entries_value) != {"file", "manifest", "marker"}
        ):
            raise ValueError
        preexisting_finals: dict[str, _Identity | None] = {}
        for role in ("file", "manifest", "marker"):
            value = final_entries_value[role]
            if not isinstance(value, dict):
                raise ValueError
            if value.get("present") is False:
                if set(value) != {"present"}:
                    raise ValueError
                preexisting_finals[role] = None
            elif value.get("present") is True:
                if set(value) != {
                    "present",
                    "device",
                    "inode",
                }:
                    raise ValueError
                preexisting_finals[role] = _Identity(
                    _require_positive_exact_int(value["device"]),
                    _require_positive_exact_int(value["inode"]),
                )
            else:
                raise ValueError
        expected_file_uri = Path(
            *parent_parts,
            names["file"],
        ).as_posix()
        expected_manifest_uri = Path(
            *parent_parts,
            names["manifest"],
        ).as_posix()
        if (
            manifest_data["file_uri"] != expected_file_uri
            or manifest_data["manifest_uri"] != expected_manifest_uri
        ):
            raise ValueError
        manifest = PartitionManifest(
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            manifest_version=manifest_version,
            manifest_uri=expected_manifest_uri,
            manifest_digest=manifest_digest,
            file_uri=expected_file_uri,
            checksum=checksum,
            row_count=row_count,
            overlap_reason=overlap_reason,
        )
        manifest_document = payload["manifest_document"]
        if not isinstance(manifest_document, dict):
            raise ValueError
        stored_manifest_document = _validate_stored_manifest_document(
            manifest_document,
            dataset=dataset,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            row_count=row_count,
            data_version=data_version,
            manifest_version=manifest_version,
            file_uri=expected_file_uri,
            manifest_uri=expected_manifest_uri,
            file_checksum=checksum,
            canonical_logical_fingerprint=logical_fingerprint,
            overlap_reason=overlap_reason,
        )
        if stored_manifest_document["manifest_digest"] != manifest_digest:
            raise ValueError
        directory_plan = payload["created_dirs"]
        if (
            not isinstance(directory_plan, list)
            or len(directory_plan) != len(parent_parts)
        ):
            raise ValueError
        created_dir_parts: list[tuple[str, ...]] = []
        preexisting_directories: list[_OwnedDirectory] = []
        for index, item in enumerate(directory_plan, start=1):
            expected_parts = list(parent_parts[:index])
            if not isinstance(item, dict) or item.get("parts") != expected_parts:
                raise ValueError
            if item.get("preexisting") is True:
                if set(item) != {
                    "parts",
                    "preexisting",
                    "device",
                    "inode",
                }:
                    raise ValueError
                preexisting_directories.append(
                    _OwnedDirectory(
                        tuple(expected_parts),
                        _Identity(
                            _require_positive_exact_int(item["device"]),
                            _require_positive_exact_int(item["inode"]),
                        ),
                    )
                )
            elif item.get("preexisting") is False:
                if set(item) != {"parts", "preexisting"}:
                    raise ValueError
                created_dir_parts.append(tuple(expected_parts))
            else:
                raise ValueError
        return _JournalRecord(
            transaction_id=transaction_id,
            dataset=dataset,
            data_version=data_version,
            canonical_logical_fingerprint=logical_fingerprint,
            manifest=manifest,
            manifest_document=stored_manifest_document,
            parent_parts=parent_parts,
            names=names,
            preexisting_finals=preexisting_finals,
            created_dir_parts=tuple(created_dir_parts),
            preexisting_directories=tuple(preexisting_directories),
            staged=staged,
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        DataCoreError,
        OverflowError,
    ) as exc:
        raise CanonicalPublishError("CANONICAL_JOURNAL_INVALID") from exc


def _dataset_payload(key: DatasetKey) -> dict[str, str]:
    return {
        "provider": key.provider,
        "dataset_kind": key.dataset_kind.value,
        "symbol": key.symbol,
        "contract_or_series": key.contract_or_series,
        "frequency": key.frequency.value,
        "adjustment": key.adjustment,
        "schema_version": key.schema_version,
    }


def _write_table(table: pa.Table, destination: object) -> None:
    pq.write_table(
        table,
        destination,
        version="2.6",
        data_page_version="1.0",
        compression="zstd",
        compression_level=3,
        use_dictionary=False,
        row_group_size=65536,
        data_page_size=1048576,
        write_statistics=True,
        coerce_timestamps="us",
        allow_truncated_timestamps=False,
        use_deprecated_int96_timestamps=False,
        write_page_index=False,
        store_schema=True,
    )


def _table_from_bars(bars: tuple[CanonicalBar, ...]) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "provider": bar.provider,
                "dataset_kind": bar.dataset_kind.value,
                "symbol": bar.symbol,
                "contract_or_series": bar.contract_or_series,
                "frequency": bar.frequency.value,
                "bar_end": bar.bar_end,
                "trading_day": bar.trading_day,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "turnover": bar.turnover,
                "open_interest": bar.open_interest,
                "adjustment": bar.adjustment,
                "schema_version": bar.schema_version,
            }
            for bar in bars
        ],
        schema=CANONICAL_PARQUET_SCHEMA,
    )


def validate_parquet_representability(bars: tuple[CanonicalBar, ...]) -> None:
    """Fail closed if canonical rows cannot inhabit the frozen Arrow schema."""
    if not bars:
        raise CanonicalStoreError("CANONICAL_PREFLIGHT_EMPTY_BATCH")
    try:
        table = _table_from_bars(bars)
    except (pa.ArrowException, OverflowError, TypeError, ValueError) as exc:
        raise CanonicalStoreError(
            "CANONICAL_PARQUET_REPRESENTABILITY_INVALID"
        ) from exc
    if table.schema != CANONICAL_PARQUET_SCHEMA or table.num_rows != len(bars):
        raise CanonicalStoreError("CANONICAL_PARQUET_REPRESENTABILITY_INVALID")


def _bars_from_table(table: pa.Table) -> tuple[CanonicalBar, ...]:
    return tuple(
        CanonicalBar(
            provider=row["provider"],
            dataset_kind=row["dataset_kind"],
            symbol=row["symbol"],
            contract_or_series=row["contract_or_series"],
            frequency=row["frequency"],
            bar_end=row["bar_end"],
            trading_day=row["trading_day"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
            turnover=row["turnover"],
            open_interest=row["open_interest"],
            adjustment=row["adjustment"],
            schema_version=row["schema_version"],
        )
        for row in table.to_pylist()
    )


def _logical_fingerprint(batch: ValidatedProviderBatch) -> str:
    payload = {
        "dataset_key": _dataset_payload(batch.dataset),
        "logical_schema": _LOGICAL_SCHEMA,
        "rows": [_logical_row(bar) for bar in batch.bars],
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _logical_row(bar: CanonicalBar) -> dict[str, object]:
    return {
        "provider": bar.provider,
        "dataset_kind": bar.dataset_kind.value,
        "symbol": bar.symbol,
        "contract_or_series": bar.contract_or_series,
        "frequency": bar.frequency.value,
        "bar_end": _utc_text(bar.bar_end),
        "trading_day": bar.trading_day.isoformat(),
        "open": _decimal_identity(bar.open),
        "high": _decimal_identity(bar.high),
        "low": _decimal_identity(bar.low),
        "close": _decimal_identity(bar.close),
        "volume": _decimal_identity(bar.volume),
        "turnover": (
            None if bar.turnover is None else _decimal_identity(bar.turnover)
        ),
        "open_interest": (
            None
            if bar.open_interest is None
            else _decimal_identity(bar.open_interest)
        ),
        "adjustment": bar.adjustment,
        "schema_version": bar.schema_version,
    }


def _decimal_identity(value: Decimal) -> dict[str, object]:
    decimal_tuple = value.as_tuple()
    exponent = decimal_tuple.exponent
    if not isinstance(exponent, int):
        raise CanonicalStoreError("CANONICAL_LOGICAL_DECIMAL_INVALID")
    return {
        "sign": decimal_tuple.sign,
        "coefficient": "".join(str(digit) for digit in decimal_tuple.digits),
        "exponent": exponent,
    }


def _partition_parts_from_facts(
    key: DatasetKey,
    data_version: str,
    coverage_start: datetime,
    coverage_end: datetime,
) -> tuple[str, ...]:
    return (
        "provider",
        require_safe_component(key.provider, field="provider"),
        "dataset_kind",
        require_safe_component(
            key.dataset_kind.value,
            field="dataset_kind",
        ),
        "symbol",
        require_safe_component(key.symbol, field="symbol"),
        "contract_or_series",
        require_safe_component(
            key.contract_or_series,
            field="contract_or_series",
        ),
        "frequency",
        require_safe_component(key.frequency.value, field="frequency"),
        "adjustment",
        require_safe_component(key.adjustment, field="adjustment"),
        "schema_version",
        require_safe_component(
            key.schema_version,
            field="schema_version",
        ),
        "data_version",
        require_safe_component(data_version, field="data_version"),
        (
            f"{_path_timestamp(coverage_start)}"
            f"_{_path_timestamp(coverage_end)}"
        ),
    )


def _publication_names_for(
    manifest_version: str,
    transaction_id: str,
) -> dict[str, str]:
    safe_manifest_version = require_safe_component(
        manifest_version,
        field="manifest_version",
    )
    if not _is_transaction_id(transaction_id):
        raise CanonicalPublishError("CANONICAL_JOURNAL_INVALID")
    return {
        "file": "part-00000.parquet",
        "manifest": (
            f"part-00000.{safe_manifest_version}.manifest.json"
        ),
        "marker": f"part-00000.{safe_manifest_version}.prepared.json",
        "partial_file": f"txn-{transaction_id}.parquet.partial",
        "partial_manifest": f"txn-{transaction_id}.manifest.partial",
        "partial_marker": f"txn-{transaction_id}.prepared.partial",
    }


def _validate_stored_manifest_document(
    document: dict[str, object],
    *,
    dataset: DatasetKey,
    coverage_start: datetime,
    coverage_end: datetime,
    row_count: int,
    data_version: str,
    manifest_version: str,
    file_uri: str,
    manifest_uri: str,
    file_checksum: str,
    canonical_logical_fingerprint: str,
    overlap_reason: str | None = None,
) -> dict[str, object]:
    if set(document) != {
        "manifest_format",
        "manifest_version",
        "profile_id",
        "dataset_key",
        "partition",
        "logical_schema",
        "file_checksum",
        "canonical_logical_fingerprint",
        "writer",
        "manifest_digest",
    }:
        raise ValueError
    writer = document["writer"]
    if (
        not isinstance(writer, dict)
        or set(writer)
        != {
            "pyarrow_version",
            "duckdb_version",
            "parameters",
        }
    ):
        raise ValueError
    pyarrow_version = _require_bounded_writer_version(
        writer["pyarrow_version"]
    )
    duckdb_version = _require_bounded_writer_version(
        writer["duckdb_version"]
    )
    partition: dict[str, object] = {
        "coverage_start": _utc_text(coverage_start),
        "coverage_end": _utc_text(coverage_end),
        "row_count": row_count,
        "data_version": data_version,
        "file_uri": file_uri,
        "manifest_uri": manifest_uri,
    }
    if overlap_reason is not None:
        if overlap_reason not in ALLOWED_OVERLAP_REASONS:
            raise ValueError
        partition["overlap_reason"] = overlap_reason
    payload: dict[str, object] = {
        "manifest_format": CANONICAL_MANIFEST_FORMAT,
        "manifest_version": manifest_version,
        "profile_id": CANONICAL_PARQUET_PROFILE_ID,
        "dataset_key": _dataset_payload(dataset),
        "partition": partition,
        "logical_schema": _LOGICAL_SCHEMA,
        "file_checksum": file_checksum,
        "canonical_logical_fingerprint": (
            canonical_logical_fingerprint
        ),
        "writer": {
            "pyarrow_version": pyarrow_version,
            "duckdb_version": duckdb_version,
            "parameters": dict(CANONICAL_PARQUET_WRITER_PARAMETERS),
        },
    }
    if _canonical_json_bytes(document["writer"]) != _canonical_json_bytes(
        payload["writer"]
    ):
        raise ValueError
    manifest_digest = document["manifest_digest"]
    if (
        not _is_sha256(manifest_digest)
        or manifest_digest != canonical_json_digest(payload)
    ):
        raise ValueError
    expected = {**payload, "manifest_digest": manifest_digest}
    if _canonical_json_bytes(document) != _canonical_json_bytes(expected):
        raise ValueError
    return expected


def _require_bounded_writer_version(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_WRITER_VERSION_LENGTH
        or not all(32 <= ord(character) <= 126 for character in value)
    ):
        raise ValueError
    return value


def _manifest_payload(
    *,
    validation: ValidationResult,
    expected: PublishExpectation,
    file_path: Path,
    manifest_path: Path,
) -> dict[str, object]:
    partition: dict[str, object] = {
        "coverage_start": _utc_text(validation.coverage_start),
        "coverage_end": _utc_text(validation.coverage_end),
        "row_count": validation.row_count,
        "data_version": validation.data_version,
        "file_uri": file_path.as_posix(),
        "manifest_uri": manifest_path.as_posix(),
    }
    if expected.overlap_reason is not None:
        partition["overlap_reason"] = expected.overlap_reason
    return {
        "manifest_format": CANONICAL_MANIFEST_FORMAT,
        "manifest_version": expected.manifest_version,
        "profile_id": CANONICAL_PARQUET_PROFILE_ID,
        "dataset_key": _dataset_payload(validation.dataset),
        "partition": partition,
        "logical_schema": _LOGICAL_SCHEMA,
        "file_checksum": validation.file_checksum,
        "canonical_logical_fingerprint": (
            validation.canonical_logical_fingerprint
        ),
        "writer": {
            "pyarrow_version": pa.__version__,
            "duckdb_version": duckdb.__version__,
            "parameters": dict(CANONICAL_PARQUET_WRITER_PARAMETERS),
        },
    }


def _validate_expectation(
    validation: ValidationResult,
    expected: PublishExpectation,
) -> None:
    if not isinstance(expected, PublishExpectation):
        raise CanonicalPublishError(
            "CANONICAL_PUBLISH_EXPECTATION_INVALID"
        )
    if not (
        expected.dataset == validation.dataset
        and expected.coverage_start == validation.coverage_start
        and expected.coverage_end == validation.coverage_end
        and type(expected.row_count) is int
        and expected.row_count == validation.row_count
        and expected.data_version == validation.data_version
        and (
            expected.file_checksum is None
            or expected.file_checksum == validation.file_checksum
        )
        and (
            expected.canonical_logical_fingerprint is None
            or expected.canonical_logical_fingerprint
            == validation.canonical_logical_fingerprint
        )
    ):
        raise CanonicalPublishError(
            "CANONICAL_PUBLISH_EXPECTATION_MISMATCH"
        )


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_json_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sha256_at(
    parent_fd: int,
    name: str,
    identity: _Identity,
) -> str:
    file_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=parent_fd)
    try:
        if _Identity.from_stat(os.fstat(file_fd)) != identity:
            raise CanonicalStoreError("CANONICAL_OWNERSHIP_CHANGED")
        return _sha256_fd(file_fd)
    finally:
        os.close(file_fd)


def _sha256_fd(file_fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(file_fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(file_fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _row_matches_manifest(row: object, manifest: PartitionManifest) -> bool:
    return (
        row.manifest_uri == manifest.manifest_uri
        and row.manifest_digest == manifest.manifest_digest
        and row.file_uri == manifest.file_uri
        and row.checksum == manifest.checksum
        and row.row_count == manifest.row_count
        and row.overlap_reason == manifest.overlap_reason
    )


def _begin_physical_write_transaction(session: Session) -> None:
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        driver_connection = connection.connection.driver_connection
        if not driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _path_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    return parsed.replace(tzinfo=UTC)


def _is_aware_utc(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and value.utcoffset().total_seconds() == 0
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_transaction_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_positive_exact_int(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError
    return value
