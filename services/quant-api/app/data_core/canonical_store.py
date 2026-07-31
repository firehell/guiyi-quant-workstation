from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Callable, Mapping
import uuid

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy.orm import Session

from app.data_core.bar_schema import CanonicalBar
from app.data_core.catalog import HistoricalCatalog, PartitionManifest
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

    @classmethod
    def from_validation(
        cls,
        validation: ValidationResult,
        *,
        manifest_version: str,
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
        )


@dataclass(frozen=True, slots=True)
class PublishedPartition:
    file_path: Path
    manifest_path: Path
    commit_marker_path: Path
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
        self.recover_pending_publications()

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

    def publish(
        self,
        staged: StagedBatch,
        expected: PublishExpectation,
    ) -> PublishedPartition:
        validation = self.validate(staged)
        _validate_expectation(validation, expected)
        root_fd = self._open_root(self._canonical_anchor)
        created_dirs: list[_OwnedDirectory] = []
        owned_entries: dict[str, _OwnedEntry] = {}
        journal_entry: _OwnedEntry | None = None
        transaction_id = uuid.uuid4().hex
        commit_attempted = False
        partition_manifest: PartitionManifest | None = None
        published: PublishedPartition | None = None
        session: Session | None = None
        try:
            parent_parts = self._partition_parts(validation)
            parent_fd = _open_directory_parts(
                root_fd,
                parent_parts,
                create=True,
                created=created_dirs,
            )
            journal_fd = _open_directory_parts(
                root_fd,
                (_JOURNAL_DIR,),
                create=True,
                created=created_dirs,
            )
            try:
                names = self._publication_names(
                    expected,
                    transaction_id,
                )
                for name in (
                    names["file"],
                    names["manifest"],
                    names["marker"],
                ):
                    _require_absent(parent_fd, name)

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
                checksum = _sha256_at(
                    parent_fd,
                    names["partial_file"],
                    partial_file,
                )
                if checksum != validation.file_checksum:
                    raise CanonicalPublishError(
                        "CANONICAL_PUBLISH_FILE_CHECKSUM_MISMATCH"
                    )

                relative_file = Path(*parent_parts, names["file"])
                relative_manifest = Path(*parent_parts, names["manifest"])
                relative_marker = Path(*parent_parts, names["marker"])
                manifest_payload = _manifest_payload(
                    validation=validation,
                    expected=expected,
                    file_path=relative_file,
                    manifest_path=relative_manifest,
                )
                manifest_digest = _digest_json(manifest_payload)
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
                marker_document = {
                    "transaction_id": transaction_id,
                    "manifest_digest": manifest_digest,
                    "file_checksum": checksum,
                }
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
                partition_manifest = PartitionManifest(
                    coverage_start=validation.coverage_start,
                    coverage_end=validation.coverage_end,
                    manifest_version=expected.manifest_version,
                    manifest_uri=relative_manifest.as_posix(),
                    manifest_digest=manifest_digest,
                    file_uri=relative_file.as_posix(),
                    checksum=checksum,
                    row_count=validation.row_count,
                )
                journal_payload = _journal_payload(
                    transaction_id=transaction_id,
                    validation=validation,
                    staged=staged,
                    partition_manifest=partition_manifest,
                    parent_parts=parent_parts,
                    names=names,
                    owned_entries=owned_entries,
                    created_dirs=created_dirs,
                )
                journal_name = f"txn-{transaction_id}.json"
                journal_identity = _write_bytes_create_only(
                    journal_fd,
                    journal_name,
                    _canonical_json_bytes(journal_payload),
                )
                journal_entry = _OwnedEntry(
                    (_JOURNAL_DIR,),
                    journal_name,
                    journal_identity,
                )
                os.fsync(parent_fd)
                os.fsync(journal_fd)
                self._fault("after_journal_fsync")

                session = self._new_owned_session()
                _begin_physical_write_transaction(session)
                self._fault("metadata_registration")
                HistoricalCatalog(session).register_partition(
                    validation.dataset,
                    partition_manifest,
                )
                self._fault("after_metadata_registration")

                self._fault("file_rename")
                owned_entries["file"] = _OwnedEntry(
                    parent_parts,
                    names["file"],
                    partial_file,
                )
                _link_create_only_at(
                    parent_fd,
                    names["partial_file"],
                    names["file"],
                    partial_file,
                )
                self._fault("after_file_link")

                self._fault("manifest_rename")
                owned_entries["manifest"] = _OwnedEntry(
                    parent_parts,
                    names["manifest"],
                    partial_manifest,
                )
                _link_create_only_at(
                    parent_fd,
                    names["partial_manifest"],
                    names["manifest"],
                    partial_manifest,
                )
                self._fault("after_manifest_link")
                os.fsync(parent_fd)

                owned_entries["marker"] = _OwnedEntry(
                    parent_parts,
                    names["marker"],
                    partial_marker,
                )
                _link_create_only_at(
                    parent_fd,
                    names["partial_marker"],
                    names["marker"],
                    partial_marker,
                )
                os.fsync(parent_fd)
                self._fault("after_commit_marker")

                self._fault("metadata_commit")
                commit_attempted = True
                session.commit()
                self._fault("after_metadata_commit")
                published = PublishedPartition(
                    file_path=self._canonical_anchor.path / relative_file,
                    manifest_path=(
                        self._canonical_anchor.path / relative_manifest
                    ),
                    commit_marker_path=(
                        self._canonical_anchor.path / relative_marker
                    ),
                    partition_manifest=partition_manifest,
                    file_checksum=checksum,
                    canonical_logical_fingerprint=(
                        validation.canonical_logical_fingerprint
                    ),
                    data_version=validation.data_version,
                )
            finally:
                os.close(journal_fd)
                os.close(parent_fd)
        except BaseException as exc:
            if session is not None:
                try:
                    session.rollback()
                except Exception:
                    commit_attempted = True
            if (
                commit_attempted
                and partition_manifest is not None
                and self._metadata_matches(
                    validation.dataset,
                    partition_manifest,
                )
            ):
                if not self._committed_entries_match(
                    root_fd,
                    owned_entries,
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
            if published is not None:
                self._cleanup_committed_transaction(
                    root_fd,
                    owned_entries,
                    journal_entry,
                    created_dirs,
                )
            os.close(root_fd)
            self._cleanup_staged(staged)
        if published is None:
            raise CanonicalPublishError("CANONICAL_RECOVERY_UNCERTAIN")
        return published

    def recover_pending_publications(self) -> None:
        root_fd = self._open_root(self._canonical_anchor)
        try:
            try:
                journal_fd = _open_directory_parts(
                    root_fd,
                    (_JOURNAL_DIR,),
                    create=False,
                    created=None,
                )
            except FileNotFoundError:
                return
            try:
                journal_names = sorted(
                    name
                    for name in os.listdir(journal_fd)
                    if name.startswith("txn-") and name.endswith(".json")
                )
                for name in journal_names:
                    identity, payload = _read_json_at(journal_fd, name)
                    self._recover_one(
                        root_fd,
                        _OwnedEntry((_JOURNAL_DIR,), name, identity),
                        payload,
                    )
            finally:
                os.close(journal_fd)
        finally:
            os.close(root_fd)

    def _recover_one(
        self,
        root_fd: int,
        journal_entry: _OwnedEntry,
        payload: object,
    ) -> None:
        (
            dataset,
            manifest,
            entries,
            created_dirs,
            staged,
        ) = _parse_journal(payload)
        metadata_matches = self._metadata_matches(dataset, manifest)
        if metadata_matches:
            required = {
                role: entry
                for role, entry in entries.items()
                if role in {"file", "manifest", "marker"}
            }
            if set(required) != {"file", "manifest", "marker"} or not (
                self._committed_entries_match(root_fd, required)
            ):
                raise CanonicalPublishError(
                    "CANONICAL_RECOVERY_UNCERTAIN"
                )
            self._cleanup_committed_transaction(
                root_fd,
                entries,
                journal_entry,
                created_dirs,
            )
            self._cleanup_staged_ownership(staged)
            return
        self._compensate(
            root_fd,
            entries,
            journal_entry,
            created_dirs,
        )
        self._cleanup_staged_ownership(staged)

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
        created_dirs: list[_OwnedDirectory],
    ) -> None:
        for role in (
            "marker",
            "manifest",
            "file",
            "partial_marker",
            "partial_manifest",
            "partial_file",
        ):
            entry = entries.get(role)
            if entry is not None:
                _unlink_owned(root_fd, entry)
        if journal_entry is not None:
            _unlink_owned(root_fd, journal_entry)
        _rmdir_owned_reverse(root_fd, created_dirs)

    def _cleanup_committed_transaction(
        self,
        root_fd: int,
        entries: Mapping[str, _OwnedEntry],
        journal_entry: _OwnedEntry | None,
        created_dirs: list[_OwnedDirectory],
    ) -> None:
        for role in ("partial_marker", "partial_manifest", "partial_file"):
            entry = entries.get(role)
            if entry is not None:
                _unlink_owned(root_fd, entry)
        if journal_entry is not None:
            _unlink_owned(root_fd, journal_entry)
        journal_dirs = [
            item for item in created_dirs if item.parts == (_JOURNAL_DIR,)
        ]
        _rmdir_owned_reverse(root_fd, journal_dirs)

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
            commit_marker_path=(
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
        key = validation.dataset
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
            require_safe_component(
                validation.data_version,
                field="data_version",
            ),
            (
                f"{_path_timestamp(validation.coverage_start)}"
                f"_{_path_timestamp(validation.coverage_end)}"
            ),
        )

    def _publication_names(
        self,
        expected: PublishExpectation,
        transaction_id: str,
    ) -> dict[str, str]:
        manifest_version = require_safe_component(
            expected.manifest_version,
            field="manifest_version",
        )
        return {
            "file": "part-00000.parquet",
            "manifest": f"part-00000.{manifest_version}.manifest.json",
            "marker": f"part-00000.{manifest_version}.committed.json",
            "partial_file": f".txn-{transaction_id}.parquet.partial",
            "partial_manifest": f".txn-{transaction_id}.manifest.partial",
            "partial_marker": f".txn-{transaction_id}.marker.partial",
        }

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
        try:
            if file_identity is not None:
                _unlink_owned_from_parent(
                    task_fd,
                    "batch.parquet",
                    file_identity,
                )
        finally:
            os.close(task_fd)
        try:
            if (
                _lstat_identity(root_fd, task_name, directory=True)
                == task_identity
            ):
                os.rmdir(task_name, dir_fd=root_fd)
        except (FileNotFoundError, OSError, CanonicalStoreError):
            pass

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
                if created is not None:
                    created.append(
                        _OwnedDirectory(
                            tuple(traversed),
                            _Identity.from_stat(value),
                        )
                    )
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
    try:
        _unlink_owned_from_parent(parent_fd, entry.name, entry.identity)
    finally:
        os.close(parent_fd)


def _unlink_owned_from_parent(
    parent_fd: int,
    name: str,
    identity: _Identity,
) -> None:
    try:
        actual = _lstat_identity(parent_fd, name)
    except FileNotFoundError:
        return
    if actual != identity:
        raise CanonicalPublishError("CANONICAL_OWNERSHIP_CHANGED")
    os.unlink(name, dir_fd=parent_fd)


def _rmdir_owned_reverse(
    root_fd: int,
    directories: list[_OwnedDirectory],
) -> None:
    for directory in reversed(directories):
        parent_parts = directory.parts[:-1]
        name = directory.parts[-1]
        try:
            parent_fd = _open_directory_parts(
                root_fd,
                parent_parts,
                create=False,
                created=None,
            )
        except FileNotFoundError:
            continue
        try:
            try:
                actual = _lstat_identity(
                    parent_fd,
                    name,
                    directory=True,
                )
            except FileNotFoundError:
                continue
            if actual != directory.identity:
                raise CanonicalPublishError("CANONICAL_OWNERSHIP_CHANGED")
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError as exc:
                if exc.errno not in {39, 66}:  # ENOTEMPTY on Linux/macOS
                    raise
        finally:
            os.close(parent_fd)


def _read_json_at(
    parent_fd: int,
    name: str,
) -> tuple[_Identity, object]:
    file_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=parent_fd)
    try:
        value = os.fstat(file_fd)
        if not stat.S_ISREG(value.st_mode):
            raise CanonicalPublishError("CANONICAL_JOURNAL_INVALID")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
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
    parent_parts: tuple[str, ...],
    names: Mapping[str, str],
    owned_entries: Mapping[str, _OwnedEntry],
    created_dirs: list[_OwnedDirectory],
) -> dict[str, object]:
    return {
        "journal_version": "canonical-publish-journal-v1",
        "transaction_id": transaction_id,
        "staged": {
            "task_name": staged.task_name,
            "task_device": staged.task_identity.device,
            "task_inode": staged.task_identity.inode,
            "file_device": staged.file_identity.device,
            "file_inode": staged.file_identity.inode,
        },
        "dataset": _dataset_payload(validation.dataset),
        "partition_manifest": {
            "coverage_start": _utc_text(partition_manifest.coverage_start),
            "coverage_end": _utc_text(partition_manifest.coverage_end),
            "manifest_version": partition_manifest.manifest_version,
            "manifest_uri": partition_manifest.manifest_uri,
            "manifest_digest": partition_manifest.manifest_digest,
            "file_uri": partition_manifest.file_uri,
            "checksum": partition_manifest.checksum,
            "row_count": partition_manifest.row_count,
        },
        "parent_parts": list(parent_parts),
        "names": dict(names),
        "owned_entries": {
            role: _owned_entry_payload(entry)
            for role, entry in owned_entries.items()
        },
        "created_dirs": [
            {
                "parts": list(item.parts),
                "device": item.identity.device,
                "inode": item.identity.inode,
            }
            for item in created_dirs
        ],
    }


def _parse_journal(
    payload: object,
) -> tuple[
    DatasetKey,
    PartitionManifest,
    dict[str, _OwnedEntry],
    list[_OwnedDirectory],
    _StagedOwnership,
]:
    try:
        if (
            not isinstance(payload, dict)
            or payload["journal_version"]
            != "canonical-publish-journal-v1"
        ):
            raise ValueError
        dataset_data = payload["dataset"]
        manifest_data = payload["partition_manifest"]
        staged_data = payload["staged"]
        staged = _StagedOwnership(
            task_name=require_safe_component(
                staged_data["task_name"],
                field="staged_task_name",
            ),
            task_identity=_Identity(
                staged_data["task_device"],
                staged_data["task_inode"],
            ),
            file_identity=_Identity(
                staged_data["file_device"],
                staged_data["file_inode"],
            ),
        )
        dataset = DatasetKey(**dataset_data)
        manifest = PartitionManifest(
            coverage_start=_parse_utc(manifest_data["coverage_start"]),
            coverage_end=_parse_utc(manifest_data["coverage_end"]),
            manifest_version=manifest_data["manifest_version"],
            manifest_uri=manifest_data["manifest_uri"],
            manifest_digest=manifest_data["manifest_digest"],
            file_uri=manifest_data["file_uri"],
            checksum=manifest_data["checksum"],
            row_count=manifest_data["row_count"],
        )
        entries = {
            role: _owned_entry_from_payload(entry)
            for role, entry in payload["owned_entries"].items()
        }
        parent_parts = tuple(payload["parent_parts"])
        names = payload["names"]
        for role in ("file", "manifest", "marker"):
            source_role = {
                "file": "partial_file",
                "manifest": "partial_manifest",
                "marker": "partial_marker",
            }[role]
            source = entries[source_role]
            entries[role] = _OwnedEntry(
                parent_parts,
                names[role],
                source.identity,
            )
        directories = [
            _OwnedDirectory(
                tuple(item["parts"]),
                _Identity(item["device"], item["inode"]),
            )
            for item in payload["created_dirs"]
        ]
        return dataset, manifest, entries, directories, staged
    except (KeyError, TypeError, ValueError, DataCoreError) as exc:
        raise CanonicalPublishError("CANONICAL_JOURNAL_INVALID") from exc


def _owned_entry_payload(entry: _OwnedEntry) -> dict[str, object]:
    return {
        "parent_parts": list(entry.parent_parts),
        "name": entry.name,
        "device": entry.identity.device,
        "inode": entry.identity.inode,
    }


def _owned_entry_from_payload(payload: object) -> _OwnedEntry:
    if not isinstance(payload, dict):
        raise ValueError
    return _OwnedEntry(
        tuple(payload["parent_parts"]),
        payload["name"],
        _Identity(payload["device"], payload["inode"]),
    )


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


def _manifest_payload(
    *,
    validation: ValidationResult,
    expected: PublishExpectation,
    file_path: Path,
    manifest_path: Path,
) -> dict[str, object]:
    return {
        "manifest_format": CANONICAL_MANIFEST_FORMAT,
        "manifest_version": expected.manifest_version,
        "profile_id": CANONICAL_PARQUET_PROFILE_ID,
        "dataset_key": _dataset_payload(validation.dataset),
        "partition": {
            "coverage_start": _utc_text(validation.coverage_start),
            "coverage_end": _utc_text(validation.coverage_end),
            "row_count": validation.row_count,
            "data_version": validation.data_version,
            "file_uri": file_path.as_posix(),
            "manifest_uri": manifest_path.as_posix(),
        },
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


def _digest_json(value: object) -> str:
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
