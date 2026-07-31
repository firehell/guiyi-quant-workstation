from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
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


class CanonicalStoreError(DataCoreError):
    error_code = "CANONICAL_STORE_ERROR"

    def __init__(self, code: str, *, facts: dict[str, object] | None = None) -> None:
        self.error_code = code
        super().__init__(facts=facts)


class CanonicalPublishError(CanonicalStoreError):
    pass


@dataclass(frozen=True, slots=True)
class StagedBatch:
    source: ValidatedProviderBatch
    task_root: Path
    file_path: Path
    file_checksum: str
    canonical_logical_fingerprint: str


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
        metadata_session: Session,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(staging_root, Path) or not isinstance(
            canonical_root,
            Path,
        ):
            raise TypeError("roots must be pathlib.Path instances")
        self._staging_root = staging_root.resolve(strict=False)
        self._canonical_root = canonical_root.resolve(strict=False)
        self._session = metadata_session
        self._fault_injector = fault_injector or (lambda _point: None)

    def stage(self, batch: ProviderBarBatch) -> StagedBatch:
        validated = validate_provider_batch(batch)
        logical_fingerprint = _logical_fingerprint(validated)
        task_root = (
            self._staging_root
            / f"canonical-stage-{uuid.uuid4().hex}"
        )
        file_path = task_root / "batch.parquet"
        try:
            task_root.mkdir(parents=True, exist_ok=False)
            self._fault("staging_write")
            table = _table_from_bars(validated.bars)
            _write_table(table, file_path)
            checksum = _sha256_file(file_path)
            return StagedBatch(
                source=validated,
                task_root=task_root,
                file_path=file_path,
                file_checksum=checksum,
                canonical_logical_fingerprint=logical_fingerprint,
            )
        except BaseException:
            self._cleanup_staging(task_root)
            raise

    def validate(self, staged: StagedBatch) -> ValidationResult:
        try:
            self._require_staged(staged)
            self._fault("validation")
            table = pq.read_table(staged.file_path)
            if table.schema != CANONICAL_PARQUET_SCHEMA:
                raise CanonicalStoreError(
                    "CANONICAL_STAGED_SCHEMA_MISMATCH"
                )
            bars = _bars_from_table(table)
            if bars != staged.source.bars:
                raise CanonicalStoreError(
                    "CANONICAL_STAGED_CONTENT_MISMATCH"
                )
            checksum = _sha256_file(staged.file_path)
            logical_fingerprint = _logical_fingerprint(staged.source)
            if (
                checksum != staged.file_checksum
                or logical_fingerprint
                != staged.canonical_logical_fingerprint
            ):
                raise CanonicalStoreError(
                    "CANONICAL_STAGED_INTEGRITY_MISMATCH"
                )
            return ValidationResult(
                staged=staged,
                dataset=staged.source.dataset,
                bars=bars,
                coverage_start=staged.source.coverage_start,
                coverage_end=staged.source.coverage_end,
                row_count=len(bars),
                data_version=staged.source.data_version,
                file_checksum=checksum,
                canonical_logical_fingerprint=logical_fingerprint,
            )
        except BaseException:
            if isinstance(staged, StagedBatch):
                self._cleanup_staging(staged.task_root)
            raise

    def publish(
        self,
        staged: StagedBatch,
        expected: PublishExpectation,
    ) -> PublishedPartition:
        created_file = False
        created_manifest = False
        file_path: Path | None = None
        manifest_path: Path | None = None
        partial_file: Path | None = None
        partial_manifest: Path | None = None
        try:
            validation = self.validate(staged)
            _validate_expectation(validation, expected)
            file_path, manifest_path = self._published_paths(
                validation,
                expected,
            )
            if file_path.exists() or manifest_path.exists():
                raise CanonicalPublishError("CANONICAL_PUBLISH_COLLISION")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            suffix = uuid.uuid4().hex
            partial_file = file_path.with_name(
                f".{file_path.name}.{suffix}.partial"
            )
            partial_manifest = manifest_path.with_name(
                f".{manifest_path.name}.{suffix}.partial"
            )
            _copy_create_only(staged.file_path, partial_file)
            checksum = _sha256_file(partial_file)
            if checksum != validation.file_checksum:
                raise CanonicalPublishError(
                    "CANONICAL_PUBLISH_FILE_CHECKSUM_MISMATCH"
                )
            manifest_payload = _manifest_payload(
                validation=validation,
                expected=expected,
                file_path=file_path.relative_to(self._canonical_root),
                manifest_path=manifest_path.relative_to(self._canonical_root),
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
            _write_create_only(
                partial_manifest,
                _canonical_json_bytes(manifest_document),
            )
            partition_manifest = PartitionManifest(
                coverage_start=validation.coverage_start,
                coverage_end=validation.coverage_end,
                manifest_version=expected.manifest_version,
                manifest_uri=manifest_path.relative_to(
                    self._canonical_root
                ).as_posix(),
                manifest_digest=manifest_digest,
                file_uri=file_path.relative_to(
                    self._canonical_root
                ).as_posix(),
                checksum=checksum,
                row_count=validation.row_count,
            )

            _ensure_rollback_capable_transaction(self._session)
            self._fault("metadata_registration")
            HistoricalCatalog(self._session).register_partition(
                validation.dataset,
                partition_manifest,
            )
            self._fault("file_rename")
            _link_create_only(partial_file, file_path)
            created_file = True
            self._fault("manifest_rename")
            _link_create_only(partial_manifest, manifest_path)
            created_manifest = True
            self._fault("metadata_commit")
            self._session.commit()
            return PublishedPartition(
                file_path=file_path,
                manifest_path=manifest_path,
                partition_manifest=partition_manifest,
                file_checksum=checksum,
                canonical_logical_fingerprint=(
                    validation.canonical_logical_fingerprint
                ),
                data_version=validation.data_version,
            )
        except BaseException as exc:
            self._session.rollback()
            if created_manifest and manifest_path is not None:
                _unlink_task_created(manifest_path, self._canonical_root)
            if created_file and file_path is not None:
                _unlink_task_created(file_path, self._canonical_root)
            if isinstance(exc, CanonicalPublishError):
                raise
            if isinstance(exc, CanonicalStoreError):
                raise
            raise CanonicalPublishError(
                "CANONICAL_PUBLISH_FAILED",
                facts={"error_type": type(exc).__name__},
            ) from exc
        finally:
            for partial in (partial_manifest, partial_file):
                if partial is not None:
                    _unlink_task_created(partial, self._canonical_root)
            if isinstance(staged, StagedBatch):
                self._cleanup_staging(staged.task_root)

    def _published_paths(
        self,
        validation: ValidationResult,
        expected: PublishExpectation,
    ) -> tuple[Path, Path]:
        key = validation.dataset
        components = (
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
        )
        window = (
            f"{_path_timestamp(validation.coverage_start)}"
            f"_{_path_timestamp(validation.coverage_end)}"
        )
        partition_root = self._canonical_root.joinpath(*components, window)
        file_path = (partition_root / "part-00000.parquet").resolve(
            strict=False
        )
        manifest_name = (
            f"part-00000.{require_safe_component(expected.manifest_version, field='manifest_version')}"
            ".manifest.json"
        )
        manifest_path = (partition_root / manifest_name).resolve(strict=False)
        _require_within(file_path, self._canonical_root)
        _require_within(manifest_path, self._canonical_root)
        return file_path, manifest_path

    def _require_staged(self, staged: StagedBatch) -> None:
        if not isinstance(staged, StagedBatch):
            raise CanonicalStoreError("CANONICAL_STAGED_BATCH_INVALID")
        task_root = staged.task_root.resolve(strict=False)
        file_path = staged.file_path.resolve(strict=False)
        _require_within(task_root, self._staging_root)
        _require_within(file_path, task_root)
        if (
            not task_root.name.startswith("canonical-stage-")
            or not file_path.is_file()
        ):
            raise CanonicalStoreError("CANONICAL_STAGED_BATCH_INVALID")

    def _cleanup_staging(self, task_root: Path) -> None:
        resolved = task_root.resolve(strict=False)
        try:
            _require_within(resolved, self._staging_root)
        except CanonicalStoreError:
            return
        if not resolved.name.startswith("canonical-stage-"):
            return
        shutil.rmtree(resolved, ignore_errors=True)

    def _fault(self, point: str) -> None:
        self._fault_injector(point)


def _write_table(table: pa.Table, path: Path) -> None:
    pq.write_table(
        table,
        path,
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


def _ensure_rollback_capable_transaction(session: Session) -> None:
    connection = session.connection()
    if connection.dialect.name != "sqlite":
        return
    driver_connection = connection.connection.driver_connection
    if not driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")


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
    key = batch.dataset
    payload = {
        "dataset_key": {
            "provider": key.provider,
            "dataset_kind": key.dataset_kind.value,
            "symbol": key.symbol,
            "contract_or_series": key.contract_or_series,
            "frequency": key.frequency.value,
            "adjustment": key.adjustment,
            "schema_version": key.schema_version,
        },
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
    key = validation.dataset
    return {
        "manifest_format": CANONICAL_MANIFEST_FORMAT,
        "manifest_version": expected.manifest_version,
        "profile_id": CANONICAL_PARQUET_PROFILE_ID,
        "dataset_key": {
            "provider": key.provider,
            "dataset_kind": key.dataset_kind.value,
            "symbol": key.symbol,
            "contract_or_series": key.contract_or_series,
            "frequency": key.frequency.value,
            "adjustment": key.adjustment,
            "schema_version": key.schema_version,
        },
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
    require_safe_component(
        expected.manifest_version,
        field="manifest_version",
    )
    facts_match = (
        expected.dataset == validation.dataset
        and expected.coverage_start == validation.coverage_start
        and expected.coverage_end == validation.coverage_end
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
    )
    if not facts_match:
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _link_create_only(partial: Path, target: Path) -> None:
    try:
        os.link(partial, target)
    except FileExistsError as exc:
        raise CanonicalPublishError("CANONICAL_PUBLISH_COLLISION") from exc


def _copy_create_only(source: Path, target: Path) -> None:
    with source.open("rb") as source_handle, target.open("xb") as target_handle:
        shutil.copyfileobj(source_handle, target_handle)


def _write_create_only(target: Path, content: bytes) -> None:
    with target.open("xb") as handle:
        handle.write(content)


def _unlink_task_created(path: Path, root: Path) -> None:
    resolved = path.resolve(strict=False)
    _require_within(resolved, root)
    try:
        resolved.unlink()
    except FileNotFoundError:
        pass


def _require_within(path: Path, root: Path) -> None:
    if not path.is_relative_to(root):
        raise CanonicalStoreError("CANONICAL_PATH_ESCAPE")


def _path_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
