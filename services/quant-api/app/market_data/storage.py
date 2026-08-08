from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import pyarrow as pa
import pyarrow.parquet as pq

from app.market_data.domain import (
    BarFrequency,
    DERIVED_FREQUENCIES,
    CanonicalBar,
    DatasetKey,
)


CANONICAL_SCHEMA_VERSION = "canonical-bar-v2"
CANONICAL_COLUMNS = (
    "bar_end",
    "trading_day",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "open_interest",
)
CANONICAL_SCHEMA = pa.schema(
    [
        pa.field("bar_end", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("trading_day", pa.date32(), nullable=False),
        pa.field("open", pa.decimal128(38, 18), nullable=False),
        pa.field("high", pa.decimal128(38, 18), nullable=False),
        pa.field("low", pa.decimal128(38, 18), nullable=False),
        pa.field("close", pa.decimal128(38, 18), nullable=False),
        pa.field("volume", pa.decimal128(38, 18), nullable=False),
        pa.field("turnover", pa.decimal128(38, 18), nullable=True),
        pa.field("open_interest", pa.decimal128(38, 18), nullable=True),
    ]
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class StorageError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    source_kind: str
    source_digest: str
    source_1m_digests: tuple[str, ...] = ()
    session_digest: str | None = None

    def __post_init__(self) -> None:
        if self.source_kind not in {
            "rqdata",
            "legacy_staging",
            "bootstrap_mixed",
            "derived_1m",
        }:
            raise StorageError("SOURCE_KIND_INVALID")
        _require_digest(self.source_digest)
        for digest in self.source_1m_digests:
            _require_digest(digest)
        if self.source_kind == "derived_1m":
            if not self.source_1m_digests or self.session_digest is None:
                raise StorageError("DERIVED_LINEAGE_REQUIRED")
            _require_digest(self.session_digest)
        elif self.source_1m_digests or self.session_digest is not None:
            raise StorageError("DIRECT_LINEAGE_INVALID")


@dataclass(frozen=True, slots=True)
class PublishRequest:
    dataset: DatasetKey
    year: int
    month: int
    bars: tuple[CanonicalBar, ...]
    expected_bar_ends: tuple[datetime, ...]
    source: SourceMetadata

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12 or self.year < 1990:
            raise StorageError("PARTITION_MONTH_INVALID")
        bars = tuple(self.bars)
        expected = tuple(_utc(item) for item in self.expected_bar_ends)
        if not bars or not expected:
            raise StorageError("EMPTY_PARTITION")
        if self.dataset.frequency in DERIVED_FREQUENCIES:
            if self.source.source_kind != "derived_1m":
                raise StorageError("DERIVED_SOURCE_INVALID")
        elif self.source.source_kind == "derived_1m":
            raise StorageError("DIRECT_SOURCE_INVALID")
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "expected_bar_ends", expected)


@dataclass(frozen=True, slots=True)
class PublishedPartition:
    dataset: DatasetKey
    year: int
    month: int
    parquet_path: Path
    manifest_path: Path
    coverage_start: datetime
    coverage_end: datetime
    row_count: int
    checksum: str
    manifest_digest: str


@dataclass(frozen=True, slots=True)
class StagedPublication:
    partition: PublishedPartition
    parquet_backup: Path
    manifest_backup: Path
    had_parquet: bool
    had_manifest: bool


BoundaryValidator = Callable[[DatasetKey, CanonicalBar], bool]
FaultHook = Callable[[str], None]


class CanonicalMonthlyStore:
    def __init__(
        self,
        root: Path,
        *,
        boundary_validator: BoundaryValidator | None = None,
        fault_hook: FaultHook | None = None,
    ) -> None:
        self.root = root.resolve()
        self.boundary_validator = boundary_validator
        self.fault_hook = fault_hook

    def publish(self, request: PublishRequest) -> PublishedPartition:
        staged = self.stage(request)
        self.finalize(staged)
        return staged.partition

    def stage(self, request: PublishRequest) -> StagedPublication:
        """Replace the file pair while retaining the prior pair for DB rollback."""
        self._validate_logical(request)
        directory = self._month_directory(request.dataset, request.year, request.month)
        directory.mkdir(parents=True, exist_ok=True)
        parquet_path = directory / "part.parquet"
        manifest_path = directory / "manifest.json"
        token = uuid.uuid4().hex
        parquet_tmp = directory / f"part.{token}.tmp"
        manifest_tmp = directory / f"manifest.{token}.tmp"
        parquet_backup = directory / f"part.{token}.bak"
        manifest_backup = directory / f"manifest.{token}.bak"
        had_parquet = parquet_path.exists()
        had_manifest = manifest_path.exists()
        try:
            table = _to_table(request.bars)
            pq.write_table(
                table,
                parquet_tmp,
                compression="zstd",
                use_dictionary=False,
                version="2.6",
            )
            checksum = _file_digest(parquet_tmp)
            physical = pq.ParquetFile(parquet_tmp).read()
            if (
                not physical.schema.equals(CANONICAL_SCHEMA, check_metadata=False)
                or physical.num_rows != len(request.bars)
            ):
                raise StorageError("PHYSICAL_CONSISTENCY_INVALID")
            payload = self._manifest_payload(request, checksum=checksum)
            manifest_bytes = _json_bytes(payload)
            manifest_tmp.write_bytes(manifest_bytes)
            _sync_file(parquet_tmp)
            _sync_file(manifest_tmp)
            self._fault("before_replace")
            try:
                if had_parquet:
                    os.replace(parquet_path, parquet_backup)
                if had_manifest:
                    os.replace(manifest_path, manifest_backup)
                os.replace(parquet_tmp, parquet_path)
                self._fault("after_parquet_replace")
                os.replace(manifest_tmp, manifest_path)
                self._fault("after_manifest_replace")
                _sync_directory(directory)
            except Exception:
                if not had_parquet or parquet_backup.exists():
                    parquet_path.unlink(missing_ok=True)
                if not had_manifest or manifest_backup.exists():
                    manifest_path.unlink(missing_ok=True)
                if parquet_backup.exists():
                    os.replace(parquet_backup, parquet_path)
                if manifest_backup.exists():
                    os.replace(manifest_backup, manifest_path)
                _sync_directory(directory)
                raise
            return StagedPublication(
                partition=PublishedPartition(
                    dataset=request.dataset,
                    year=request.year,
                    month=request.month,
                    parquet_path=parquet_path,
                    manifest_path=manifest_path,
                    coverage_start=request.bars[0].bar_end
                    - _frequency_delta(request.dataset.frequency),
                    coverage_end=request.bars[-1].bar_end,
                    row_count=len(request.bars),
                    checksum=checksum,
                    manifest_digest=hashlib.sha256(manifest_bytes).hexdigest(),
                ),
                parquet_backup=parquet_backup,
                manifest_backup=manifest_backup,
                had_parquet=had_parquet,
                had_manifest=had_manifest,
            )
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError("ATOMIC_PUBLISH_FAILED") from exc
        finally:
            for path in (parquet_tmp, manifest_tmp):
                path.unlink(missing_ok=True)

    def finalize(self, staged: StagedPublication) -> None:
        staged.parquet_backup.unlink(missing_ok=True)
        staged.manifest_backup.unlink(missing_ok=True)

    def rollback(self, staged: StagedPublication) -> None:
        """Restore the prior file pair after a failed Catalog transaction."""
        partition = staged.partition
        partition.parquet_path.unlink(missing_ok=True)
        partition.manifest_path.unlink(missing_ok=True)
        if staged.had_parquet and staged.parquet_backup.exists():
            os.replace(staged.parquet_backup, partition.parquet_path)
        if staged.had_manifest and staged.manifest_backup.exists():
            os.replace(staged.manifest_backup, partition.manifest_path)
        _sync_directory(partition.parquet_path.parent)
        self.finalize(staged)

    def read_month(self, dataset: DatasetKey, year: int, month: int) -> tuple[CanonicalBar, ...]:
        directory = self._month_directory(dataset, year, month)
        parquet_path = directory / "part.parquet"
        manifest_path = directory / "manifest.json"
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            table = pq.ParquetFile(parquet_path).read()
        except (OSError, ValueError, pa.ArrowException) as exc:
            raise StorageError("PARTITION_UNREADABLE") from exc
        if not table.schema.equals(CANONICAL_SCHEMA, check_metadata=False):
            raise StorageError("PHYSICAL_CONSISTENCY_INVALID")
        expected_key = {
            "kind": dataset.kind.value,
            "symbol": dataset.symbol,
            "series_or_contract": dataset.series_or_contract,
            "frequency": dataset.frequency.value,
        }
        if (
            payload.get("dataset_key") != expected_key
            or payload.get("schema_version") != CANONICAL_SCHEMA_VERSION
            or payload.get("row_count") != table.num_rows
            or payload.get("parquet_checksum") != _file_digest(parquet_path)
        ):
            raise StorageError("PHYSICAL_CONSISTENCY_INVALID")
        records = table.to_pylist()
        return tuple(CanonicalBar(**record) for record in records)

    def _month_directory(self, dataset: DatasetKey, year: int, month: int) -> Path:
        candidate = self.root.joinpath(
            *dataset.relative_root.parts,
            f"year={year:04d}",
            f"month={month:02d}",
        ).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise StorageError("CANONICAL_ROOT_ESCAPE")
        return candidate

    def _validate_logical(self, request: PublishRequest) -> None:
        ends = tuple(bar.bar_end for bar in request.bars)
        if any(previous >= current for previous, current in zip(ends, ends[1:])):
            raise StorageError("BAR_END_NOT_STRICTLY_INCREASING")
        if ends != request.expected_bar_ends:
            raise StorageError("TARGET_WINDOW_INCOMPLETE")
        for bar in request.bars:
            if bar.trading_day.year != request.year or bar.trading_day.month != request.month:
                raise StorageError("PARTITION_MONTH_MISMATCH")
            if self.boundary_validator is not None and not self.boundary_validator(request.dataset, bar):
                raise StorageError("SESSION_BOUNDARY_INVALID")

    def _manifest_payload(self, request: PublishRequest, *, checksum: str) -> dict[str, object]:
        payload: dict[str, object] = {
            "dataset_key": {
                "kind": request.dataset.kind.value,
                "symbol": request.dataset.symbol,
                "series_or_contract": request.dataset.series_or_contract,
                "frequency": request.dataset.frequency.value,
            },
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "source_kind": request.source.source_kind,
            "coverage_start": (
                request.bars[0].bar_end - _frequency_delta(request.dataset.frequency)
            ).isoformat(),
            "coverage_end": request.bars[-1].bar_end.isoformat(),
            "row_count": len(request.bars),
            "parquet_checksum": checksum,
            "source_digest": request.source.source_digest,
        }
        if request.source.source_kind == "derived_1m":
            payload["source_1m_digests"] = list(request.source.source_1m_digests)
            payload["session_digest"] = request.source.session_digest
        return payload

    def _fault(self, stage: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(stage)


def _to_table(bars: Sequence[CanonicalBar]) -> pa.Table:
    records = [bar.as_record() for bar in bars]
    try:
        return pa.Table.from_pylist(records, schema=CANONICAL_SCHEMA)
    except (pa.ArrowException, ValueError, TypeError) as exc:
        raise StorageError("CANONICAL_SCHEMA_INVALID") from exc


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _require_digest(value: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StorageError("DIGEST_INVALID")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StorageError("EXPECTED_BAR_END_INVALID")
    return value.astimezone(UTC)


def _sync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _frequency_delta(frequency: BarFrequency) -> timedelta:
    return {
        BarFrequency.M1: timedelta(minutes=1),
        BarFrequency.M5: timedelta(minutes=5),
        BarFrequency.M15: timedelta(minutes=15),
        BarFrequency.M30: timedelta(minutes=30),
        BarFrequency.H1: timedelta(hours=1),
        BarFrequency.D1: timedelta(days=1),
        BarFrequency.W1: timedelta(days=7),
    }[frequency]
