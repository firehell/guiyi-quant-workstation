"""Canonical Parquet 月分区存储（数据核心 V2 物理层）。

``CanonicalMonthlyStore`` 负责 canonical 根目录下的读写：
- 目录布局由 ``DatasetKey.relative_root`` + ``year=YYYY/month=MM/part.parquet`` 决定；
- 发布采用「写临时文件 → 校验 schema/行数 → ``os.replace`` 原子替换」，失败不覆盖旧分区；
- 读取时校验 schema 与 Catalog 登记一致，由 ``MarketDataService`` 再比对 ``row_count``。

本层不关心 RQData 或 SQL，只保证物理文件形态与发布前完整性校验。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from typing import Protocol
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
    """存储层失败：发布校验、路径逃逸、文件不可读或物理一致性错误。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PublishRequest:
    """单月分区发布请求：须携带完整 ``expected_bar_ends`` 以证明目标窗口无缺口。"""

    dataset: DatasetKey
    year: int
    month: int
    bars: tuple[CanonicalBar, ...]
    expected_bar_ends: tuple[datetime, ...]


@dataclass(frozen=True, slots=True)
class PublishedPartition:
    """发布成功后的分区描述，供 ``MarketCatalog.register_partition`` 登记。"""

    dataset: DatasetKey
    year: int
    month: int
    parquet_path: Path
    coverage_start: datetime
    coverage_end: datetime
    row_count: int


BoundaryValidator = Callable[[DatasetKey, CanonicalBar], bool]


class CatalogPartitionLike(Protocol):
    """Catalog partition fields required by the physical integrity boundary."""

    @property
    def dataset(self) -> DatasetKey: ...

    @property
    def year(self) -> int: ...

    @property
    def month(self) -> int: ...

    @property
    def coverage_start(self) -> datetime: ...

    @property
    def coverage_end(self) -> datetime: ...

    @property
    def file_path(self) -> Path: ...

    @property
    def row_count(self) -> int: ...


class CanonicalMonthlyStore:
    """Canonical 月分区 Parquet 存储：原子发布与严格 schema 读取。"""

    def __init__(self, root: Path, *, boundary_validator: BoundaryValidator | None = None) -> None:
        self.root = root.resolve()
        # 可选：按交易 session 边界拒绝越界 bar（维护管道注入）
        self.boundary_validator = boundary_validator

    def publish(self, request: PublishRequest) -> PublishedPartition:
        """校验后写入月分区；仅在校验通过时用 ``os.replace`` 替换 ``part.parquet``。

        失败时删除临时文件，保留上一版有效 canonical（V2 原子发布要求）。
        """
        self._validate(request)
        directory = self._month_directory(request.dataset, request.year, request.month)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "part.parquet"
        temporary = directory / f"part.{uuid.uuid4().hex}.tmp"
        try:
            pq.write_table(pa.Table.from_pylist([bar.as_record() for bar in request.bars], schema=CANONICAL_SCHEMA), temporary, compression="zstd", use_dictionary=False, version="2.6")
            # 写后回读：防止 pyarrow 写出与预期 schema/行数不一致的静默损坏
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
        """读取指定月 ``part.parquet``；schema 不符或 IO 失败映射为 ``StorageError``。"""
        try:
            table = pq.ParquetFile(self._month_directory(dataset, year, month) / "part.parquet").read()
        except (OSError, pa.ArrowException) as exc:
            raise StorageError("PARTITION_UNREADABLE") from exc
        if not table.schema.equals(CANONICAL_SCHEMA, check_metadata=False):
            raise StorageError("PHYSICAL_CONSISTENCY_INVALID")
        return tuple(CanonicalBar(**record) for record in table.to_pylist())

    def read_catalog_partition(
        self,
        partition: CatalogPartitionLike,
    ) -> tuple[CanonicalBar, ...]:
        """Read one Catalog partition only when URI, rows and coverage match disk."""
        expected_path = self.month_path(
            partition.dataset,
            partition.year,
            partition.month,
        )
        if partition.file_path != expected_path or not expected_path.is_file():
            raise StorageError("PARTITION_CATALOG_MISMATCH")
        values = self.read_month(
            partition.dataset,
            partition.year,
            partition.month,
        )
        if not values:
            raise StorageError("PARTITION_EMPTY")
        if partition.row_count != len(values):
            raise StorageError("PARTITION_ROW_COUNT_MISMATCH")
        if (
            partition.coverage_start
            != values[0].bar_end - _frequency_delta(partition.dataset.frequency)
            or partition.coverage_end != values[-1].bar_end
        ):
            raise StorageError("PARTITION_COVERAGE_MISMATCH")
        return values

    def month_path(self, dataset: DatasetKey, year: int, month: int) -> Path:
        """Return the authoritative physical path for a month partition."""
        return self._month_directory(dataset, year, month) / "part.parquet"

    def _month_directory(self, dataset: DatasetKey, year: int, month: int) -> Path:
        """拼接月分区目录并校验仍在 ``canonical_root`` 内（防路径注入）。"""
        path = self.root.joinpath(*dataset.relative_root.parts, f"year={year:04d}", f"month={month:02d}").resolve()
        if path != self.root and self.root not in path.parents:
            raise StorageError("CANONICAL_ROOT_ESCAPE")
        return path

    def _validate(self, request: PublishRequest) -> None:
        """发布前完整性校验：非空、bar_end 严格递增、与 expected 完全一致、归属正确月份。"""
        if not request.bars or not request.expected_bar_ends or not 1 <= request.month <= 12:
            raise StorageError("EMPTY_PARTITION")
        ends = tuple(bar.bar_end for bar in request.bars)
        if any(left >= right for left, right in zip(ends, ends[1:])):
            raise StorageError("BAR_END_NOT_STRICTLY_INCREASING")
        expected_ends = tuple(_utc(item) for item in request.expected_bar_ends)
        # 与维护层计算的期望 bar_end 序列必须逐根相等，禁止缺 bar 或多余 bar
        if ends != expected_ends:
            raise StorageError("TARGET_WINDOW_INCOMPLETE")
        for bar in request.bars:
            if bar.trading_day.year != request.year or bar.trading_day.month != request.month:
                raise StorageError("PARTITION_MONTH_MISMATCH")
            if self.boundary_validator is not None and not self.boundary_validator(request.dataset, bar):
                raise StorageError("SESSION_BOUNDARY_INVALID")


def _frequency_delta(frequency: BarFrequency) -> timedelta:
    """单根 bar 的时间宽度，用于由首根 ``bar_end`` 反推 ``coverage_start``。"""
    return {BarFrequency.M1: timedelta(minutes=1), BarFrequency.M5: timedelta(minutes=5), BarFrequency.M15: timedelta(minutes=15), BarFrequency.M30: timedelta(minutes=30), BarFrequency.H1: timedelta(hours=1), BarFrequency.D1: timedelta(days=1), BarFrequency.W1: timedelta(days=7)}[frequency]


def _utc(value: object) -> datetime:
    """将期望 bar_end 规范为 UTC；非法输入视为 ``EXPECTED_BAR_END_INVALID``。"""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StorageError("EXPECTED_BAR_END_INVALID")
    return value.astimezone(UTC)
