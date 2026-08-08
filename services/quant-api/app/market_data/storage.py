from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import uuid

import pyarrow as pa
import pyarrow.parquet as pq

from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey


CANONICAL_COLUMNS = ("bar_end", "trading_day", "open", "high", "low", "close", "volume", "turnover", "open_interest")
CANONICAL_SCHEMA = pa.schema([
    pa.field("bar_end", pa.timestamp("us", tz="UTC"), nullable=False), pa.field("trading_day", pa.date32(), nullable=False),
    *[pa.field(name, pa.decimal128(38, 18), nullable=name in {"turnover", "open_interest"}) for name in CANONICAL_COLUMNS[2:]],
])


class StorageError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PublishRequest:
    dataset: DatasetKey
    year: int
    month: int
    bars: tuple[CanonicalBar, ...]
    expected_bar_ends: tuple[datetime, ...]


@dataclass(frozen=True, slots=True)
class PublishedPartition:
    dataset: DatasetKey
    year: int
    month: int
    parquet_path: Path
    coverage_start: datetime
    coverage_end: datetime
    row_count: int


BoundaryValidator = Callable[[DatasetKey, CanonicalBar], bool]


class CanonicalMonthlyStore:
    def __init__(self, root: Path, *, boundary_validator: BoundaryValidator | None = None) -> None:
        self.root = root.resolve()
        self.boundary_validator = boundary_validator

    def publish(self, request: PublishRequest) -> PublishedPartition:
        self._validate(request)
        directory = self._month_directory(request.dataset, request.year, request.month)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "part.parquet"
        temporary = directory / f"part.{uuid.uuid4().hex}.tmp"
        try:
            pq.write_table(pa.Table.from_pylist([bar.as_record() for bar in request.bars], schema=CANONICAL_SCHEMA), temporary, compression="zstd", use_dictionary=False, version="2.6")
            physical = pq.ParquetFile(temporary).read()
            if not physical.schema.equals(CANONICAL_SCHEMA, check_metadata=False) or physical.num_rows != len(request.bars):
                raise StorageError("PHYSICAL_CONSISTENCY_INVALID")
            os.replace(temporary, path)
            return PublishedPartition(request.dataset, request.year, request.month, path, request.bars[0].bar_end - _frequency_delta(request.dataset.frequency), request.bars[-1].bar_end, len(request.bars))
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError("ATOMIC_PUBLISH_FAILED") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def read_month(self, dataset: DatasetKey, year: int, month: int) -> tuple[CanonicalBar, ...]:
        try:
            table = pq.ParquetFile(self._month_directory(dataset, year, month) / "part.parquet").read()
        except (OSError, pa.ArrowException) as exc:
            raise StorageError("PARTITION_UNREADABLE") from exc
        if not table.schema.equals(CANONICAL_SCHEMA, check_metadata=False):
            raise StorageError("PHYSICAL_CONSISTENCY_INVALID")
        return tuple(CanonicalBar(**record) for record in table.to_pylist())

    def _month_directory(self, dataset: DatasetKey, year: int, month: int) -> Path:
        path = self.root.joinpath(*dataset.relative_root.parts, f"year={year:04d}", f"month={month:02d}").resolve()
        if path != self.root and self.root not in path.parents:
            raise StorageError("CANONICAL_ROOT_ESCAPE")
        return path

    def _validate(self, request: PublishRequest) -> None:
        if not request.bars or not request.expected_bar_ends or not 1 <= request.month <= 12:
            raise StorageError("EMPTY_PARTITION")
        ends = tuple(bar.bar_end for bar in request.bars)
        if any(left >= right for left, right in zip(ends, ends[1:])):
            raise StorageError("BAR_END_NOT_STRICTLY_INCREASING")
        expected_ends = tuple(_utc(item) for item in request.expected_bar_ends)
        if ends != expected_ends:
            raise StorageError("TARGET_WINDOW_INCOMPLETE")
        for bar in request.bars:
            if bar.trading_day.year != request.year or bar.trading_day.month != request.month:
                raise StorageError("PARTITION_MONTH_MISMATCH")
            if self.boundary_validator is not None and not self.boundary_validator(request.dataset, bar):
                raise StorageError("SESSION_BOUNDARY_INVALID")


def _frequency_delta(frequency: BarFrequency) -> timedelta:
    return {BarFrequency.M1: timedelta(minutes=1), BarFrequency.M5: timedelta(minutes=5), BarFrequency.M15: timedelta(minutes=15), BarFrequency.M30: timedelta(minutes=30), BarFrequency.H1: timedelta(hours=1), BarFrequency.D1: timedelta(days=1), BarFrequency.W1: timedelta(days=7)}[frequency]


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StorageError("EXPECTED_BAR_END_INVALID")
    return value.astimezone(UTC)
