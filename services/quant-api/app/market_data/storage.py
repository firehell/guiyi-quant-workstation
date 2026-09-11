"""Canonical month storage with immutable content-addressed candidates.

Catalog alone selects the active URI. Legacy fixed-path writes are restricted to
an explicitly selected offline repair shadow; normal publication never replaces.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Protocol
import uuid

import pyarrow as pa
import pyarrow.parquet as pq

from app.market_data.domain import BarFrequency, CanonicalBar, ContractError, DatasetKey


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


PartitionBoundaryValidator = Callable[[DatasetKey, tuple[CanonicalBar, ...]], bool]


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

    def __init__(self, root: Path, *, boundary_validator: PartitionBoundaryValidator | None = None) -> None:
        self.root = root.absolute()
        if ".." in self.root.parts:
            raise StorageError("CANONICAL_ROOT_ESCAPE")
        # 可选：按交易 session 边界拒绝越界 bar（维护管道注入）
        self.boundary_validator = boundary_validator

    def publish(self, request: PublishRequest) -> PublishedPartition:
        """Install a validated immutable candidate without changing any Catalog pointer."""
        return self._publish(request, legacy_shadow=False)

    def publish_legacy_shadow(self, request: PublishRequest) -> PublishedPartition:
        """Only for the offline 0045 shadow; caller must validate its authorized root."""
        return self._publish(request, legacy_shadow=True)

    def _publish(self, request: PublishRequest, *, legacy_shadow: bool) -> PublishedPartition:
        self._validate(request)
        directory = self._month_directory(request.dataset, request.year, request.month)
        temporary = f"part.{uuid.uuid4().hex}.tmp"
        directory_fd = self._directory_fd(directory, create=True)
        try:
            expected = pa.Table.from_pylist([bar.as_record() for bar in request.bars], schema=CANONICAL_SCHEMA)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            with os.fdopen(fd, "wb") as stream:
                pq.write_table(expected, stream, compression="zstd", use_dictionary=False, version="2.6")
                stream.flush()
                os.fsync(stream.fileno())
            payload = self._read_bytes(directory_fd, temporary)
            physical = pq.ParquetFile(pa.BufferReader(payload)).read()
            if not physical.equals(expected, check_metadata=False):
                raise StorageError("PHYSICAL_CONSISTENCY_INVALID")
            name = "part.parquet" if legacy_shadow else f"part.{hashlib.sha256(payload).hexdigest()}.parquet"
            if legacy_shadow:
                os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            else:
                try:
                    os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
                except FileExistsError:
                    if self._read_bytes(directory_fd, name) != payload:
                        raise StorageError("IMMUTABLE_PARTITION_CONFLICT") from None
            if self._read_bytes(directory_fd, name) != payload:
                raise StorageError("PHYSICAL_CONSISTENCY_INVALID")
            os.fsync(directory_fd)
            return PublishedPartition(request.dataset, request.year, request.month, directory / name, request.bars[0].bar_end - _frequency_delta(request.dataset.frequency), request.bars[-1].bar_end, len(request.bars))
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError("ATOMIC_PUBLISH_FAILED") from exc
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            finally:
                os.close(directory_fd)

    def _directory_fd(self, directory: Path, *, create: bool = False) -> int:
        """Walk every component without following links; sync each created entry.

        Missing root ancestors belong to the explicitly requested root path. Open
        existing ancestors read-only and create only missing path components,
        syncing every parent before proceeding, including existing entries from
        an interrupted or concurrent creation. Read-only access never fsyncs.
        """
        try:
            parts = directory.relative_to(self.root).parts
            if ".." in parts:
                raise StorageError("CANONICAL_ROOT_ESCAPE")
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            fd = os.open(self.root.anchor, flags)
            try:
                for part in (*self.root.parts[1:], *parts):
                    try:
                        child = os.open(part, flags, dir_fd=fd)
                    except FileNotFoundError:
                        if not create:
                            raise
                        try:
                            os.mkdir(part, dir_fd=fd)
                        except FileExistsError:
                            # A concurrent publisher may have created this entry.
                            pass
                        child = os.open(part, flags, dir_fd=fd)
                    if create:
                        try:
                            # Existing entries may come from an interrupted or
                            # concurrent mkdir whose parent was never synced.
                            os.fsync(fd)
                        except BaseException:
                            os.close(child)
                            raise
                    os.close(fd)
                    fd = child
                return fd
            except BaseException:
                os.close(fd)
                raise
        except (ValueError, OSError) as exc:
            raise StorageError("PARTITION_UNREADABLE") from exc

    @staticmethod
    def _read_bytes(directory_fd: int, name: str) -> bytes:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise StorageError("PARTITION_UNREADABLE")
            return stream.read()

    def _read_path(self, path: Path) -> tuple[CanonicalBar, ...]:
        try:
            fd = self._directory_fd(path.parent)
            try:
                payload = self._read_bytes(fd, path.name)
            finally:
                os.close(fd)
            if path.name != "part.parquet":
                if path.name != f"part.{hashlib.sha256(payload).hexdigest()}.parquet":
                    raise StorageError("PARTITION_CONTENT_HASH_MISMATCH")
            table = pq.ParquetFile(pa.BufferReader(payload)).read()
            if not table.schema.equals(CANONICAL_SCHEMA, check_metadata=False):
                raise StorageError("PHYSICAL_CONSISTENCY_INVALID")
            return tuple(CanonicalBar(**record) for record in table.to_pylist())
        except (OSError, pa.ArrowException, ContractError, TypeError, ValueError) as exc:
            raise StorageError("PARTITION_UNREADABLE") from exc

    def read_month(self, dataset: DatasetKey, year: int, month: int) -> tuple[CanonicalBar, ...]:
        """读取指定月 ``part.parquet``；schema 不符或 IO 失败映射为 ``StorageError``。"""
        return self._read_path(self.month_path(dataset, year, month))

    def read_catalog_partition(
        self,
        partition: CatalogPartitionLike,
    ) -> tuple[CanonicalBar, ...]:
        """Read one Catalog partition only when URI, rows and coverage match disk."""
        directory = self._month_directory(partition.dataset, partition.year, partition.month)
        path = partition.file_path
        if path.parent != directory or not re.fullmatch(r"part(?:\.[0-9a-f]{64})?\.parquet", path.name):
            raise StorageError("PARTITION_CATALOG_MISMATCH")
        values = self._read_path(path)
        if not values:
            raise StorageError("PARTITION_EMPTY")
        self._validate(PublishRequest(partition.dataset, partition.year, partition.month, values, tuple(bar.bar_end for bar in values)))
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
        """Return only the legacy fixed path; active readers must use the Catalog URI."""
        return self._month_directory(dataset, year, month) / "part.parquet"

    def _month_directory(self, dataset: DatasetKey, year: int, month: int) -> Path:
        """拼接月分区目录并校验仍在 ``canonical_root`` 内（防路径注入）。"""
        path = self.root.joinpath(*dataset.relative_root.parts, f"year={year:04d}", f"month={month:02d}")
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
        if self.boundary_validator is not None and not self.boundary_validator(request.dataset, request.bars):
            raise StorageError("SESSION_BOUNDARY_INVALID")


def _frequency_delta(frequency: BarFrequency) -> timedelta:
    """单根 bar 的时间宽度，用于由首根 ``bar_end`` 反推 ``coverage_start``。"""
    return {BarFrequency.M1: timedelta(minutes=1), BarFrequency.M5: timedelta(minutes=5), BarFrequency.M15: timedelta(minutes=15), BarFrequency.M30: timedelta(minutes=30), BarFrequency.H1: timedelta(hours=1), BarFrequency.D1: timedelta(days=1), BarFrequency.W1: timedelta(days=7)}[frequency]


def _utc(value: object) -> datetime:
    """将期望 bar_end 规范为 UTC；非法输入视为 ``EXPECTED_BAR_END_INVALID``。"""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StorageError("EXPECTED_BAR_END_INVALID")
    return value.astimezone(UTC)
