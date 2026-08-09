"""八表 Catalog 访问层（数据核心 V2 元数据与分区索引）。

``MarketCatalog`` 封装 PostgreSQL 八表中的市场相关表：
``MarketDataset`` / ``MarketPartition``（物理数据集与月分区索引）、
``MainContractMap``（主力映射）、``Instrument`` / ``TradingCalendar``（交易日语义）。

职责边界：
- 将 ``DatasetKey`` 解析为分区列表与 Parquet 相对 URI（禁止绝对路径与根目录逃逸）；
- 提供维护期 advisory lock，避免并发发布破坏分区一致性；
- 不读取 Parquet 内容（由 ``CanonicalMonthlyStore`` 负责）。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.market_data.domain import BarFrequency, DatasetKey, DatasetKind
from app.market_data.session_clock import (
    SessionClockError,
    session_windows_for_trading_day,
)
from app.market_data.storage import PublishedPartition
from app.models import (
    Instrument,
    MainContractMap,
    MarketDataset,
    MarketPartition,
    TradingCalendar,
)


class CatalogError(RuntimeError):
    """Catalog 层配置或路径类错误（如分区 URI 越界、品种无交易所）。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# 全库唯一的维护 advisory lock 键，与业务数据无关联
_MAINTENANCE_LOCK_KEY = 4_902_608_003_600_001
SHANGHAI = ZoneInfo("Asia/Shanghai")


class MaintenanceLease:
    """维护锁租约：调用方须在任务结束时 ``release()`` 释放 PostgreSQL advisory lock。"""

    def release(self) -> None:
        raise NotImplementedError


class _NoopMaintenanceLease(MaintenanceLease):
    """非 PostgreSQL 方言下的空实现（测试/SQLite 不持锁）。"""

    def release(self) -> None:
        return None


class _PostgresMaintenanceLease(MaintenanceLease):
    """持有 ``pg_try_advisory_lock`` 的专用连接，释放时解锁并可选择关闭连接。"""

    def __init__(self, connection: Connection, *, close_on_release: bool) -> None:
        self._connection = connection
        self._close_on_release = close_on_release

    def release(self) -> None:
        try:
            self._connection.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": _MAINTENANCE_LOCK_KEY},
            )
        finally:
            if self._close_on_release:
                self._connection.close()


@dataclass(frozen=True, slots=True)
class CatalogPartition:
    """单个月分区在 Catalog 中的解析结果（含 coverage 与物理文件路径）。"""

    dataset: DatasetKey
    year: int
    month: int
    coverage_start: datetime
    coverage_end: datetime
    file_path: Path
    row_count: int


@dataclass(frozen=True, slots=True)
class MainMapFact:
    """主力映射只读事实行：品种 + 交易日 + 当日 rank-1 合约代码。"""

    symbol: str
    trade_date: date
    contract: str


class MarketCatalog:
    """市场数据 Catalog 门面：数据集注册、分区索引、主力映射与交易日查询。"""

    def __init__(self, session: Session, canonical_root: Path) -> None:
        self.session = session
        self.canonical_root = canonical_root.resolve()

    def acquire_maintenance_lock(self) -> MaintenanceLease | None:
        """尝试获取全局维护锁；未获取到返回 ``None``（另一维护任务进行中）。

        PostgreSQL 使用 session 级 advisory lock；非 PG 方言返回 noop 租约便于单测。
        """
        bind = self.session.get_bind()
        if bind.dialect.name != "postgresql":
            return _NoopMaintenanceLease()
        connection = bind.connect() if isinstance(bind, Engine) else bind
        close_on_release = isinstance(bind, Engine)
        try:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": _MAINTENANCE_LOCK_KEY},
            ).scalar_one()
            if not acquired:
                if close_on_release:
                    connection.close()
                return None
            return _PostgresMaintenanceLease(
                connection,
                close_on_release=close_on_release,
            )
        except Exception:
            if close_on_release:
                connection.close()
            raise

    def dataset_row(
        self, key: DatasetKey, *, create: bool = False
    ) -> MarketDataset | None:
        """按四元组查找 ``MarketDataset``；``create=True`` 时不存在则插入并 flush。"""
        row = self.session.scalar(
            select(MarketDataset).where(
                MarketDataset.kind == key.kind.value,
                MarketDataset.symbol == key.symbol,
                MarketDataset.series_or_contract == key.series_or_contract,
                MarketDataset.frequency == key.frequency.value,
            )
        )
        if row is None and create:
            row = MarketDataset(
                kind=key.kind.value,
                symbol=key.symbol,
                series_or_contract=key.series_or_contract,
                frequency=key.frequency.value,
            )
            self.session.add(row)
            self.session.flush()
        return row

    def register_partition(self, partition: PublishedPartition) -> None:
        """将一次成功发布的月分区写入/更新 ``MarketPartition``（coverage、URI、行数）。"""
        dataset = self.dataset_row(partition.dataset, create=True)
        assert dataset is not None
        row = self.session.scalar(
            select(MarketPartition).where(
                MarketPartition.dataset_id == dataset.id,
                MarketPartition.year == partition.year,
                MarketPartition.month == partition.month,
            )
        )
        values = {
            "coverage_start": partition.coverage_start,
            "coverage_end": partition.coverage_end,
            "file_uri": self._relative_uri(partition.parquet_path),
            "row_count": partition.row_count,
        }
        if row is None:
            self.session.add(
                MarketPartition(
                    dataset_id=dataset.id,
                    year=partition.year,
                    month=partition.month,
                    **values,
                )
            )
        else:
            for field, value in values.items():
                setattr(row, field, value)
        self.session.flush()

    def partitions(
        self,
        key: DatasetKey,
        start: datetime,
        end: datetime,
    ) -> tuple[CatalogPartition, ...]:
        """返回与查询窗口相交的月分区，按年月升序。

        相交条件：``coverage_end > start`` 且 ``coverage_start <= end``（半开窗口友好）。
        数据集未注册时返回空元组，由上层决定视为缺失。
        """
        dataset = self.dataset_row(key)
        if dataset is None:
            return ()
        rows = self.session.scalars(
            select(MarketPartition)
            .where(
                MarketPartition.dataset_id == dataset.id,
                MarketPartition.coverage_end > start,
                MarketPartition.coverage_start <= end,
            )
            .order_by(MarketPartition.year, MarketPartition.month)
        )
        return tuple(self._partition(key, row) for row in rows)

    def all_partitions(self, key: DatasetKey) -> tuple[CatalogPartition, ...]:
        """返回某数据集的全部月分区（维护/审计用，不做时间过滤）。"""
        dataset = self.dataset_row(key)
        if dataset is None:
            return ()
        rows = self.session.scalars(
            select(MarketPartition)
            .where(MarketPartition.dataset_id == dataset.id)
            .order_by(MarketPartition.year, MarketPartition.month)
        )
        return tuple(self._partition(key, row) for row in rows)

    def partitions_before(
        self,
        key: DatasetKey,
        before: datetime | None,
    ) -> tuple[CatalogPartition, ...]:
        """返回游标前可能含目标 bars 的物理分区，按最新月份优先。"""
        dataset = self.dataset_row(key)
        if dataset is None:
            return ()
        statement = select(MarketPartition).where(MarketPartition.dataset_id == dataset.id)
        if before is not None:
            statement = statement.where(MarketPartition.coverage_start < before)
        rows = self.session.scalars(
            statement.order_by(MarketPartition.year.desc(), MarketPartition.month.desc())
        )
        return tuple(self._partition(key, row) for row in rows)

    def contract_partitions_before(
        self,
        symbol: str,
        frequency: BarFrequency,
        before: datetime | None,
    ) -> tuple[CatalogPartition, ...]:
        """返回品种的具体合约分区，按最新月份优先且仅经 Catalog 定位。"""
        statement = (
            select(MarketDataset, MarketPartition)
            .join(MarketPartition, MarketPartition.dataset_id == MarketDataset.id)
            .where(
                MarketDataset.kind == DatasetKind.CONTRACT.value,
                MarketDataset.symbol == symbol.strip().lower(),
                MarketDataset.frequency == frequency.value,
            )
        )
        if before is not None:
            statement = statement.where(MarketPartition.coverage_start < before)
        rows = self.session.execute(
            statement.order_by(MarketPartition.year.desc(), MarketPartition.month.desc())
        )
        return tuple(
            self._partition(
                DatasetKey(
                    kind=DatasetKind.CONTRACT,
                    symbol=dataset.symbol,
                    series_or_contract=dataset.series_or_contract,
                    frequency=frequency,
                ),
                partition,
            )
            for dataset, partition in rows
        )

    def upsert_main_contracts(self, rows: Iterable[tuple[str, date, str]]) -> None:
        """批量写入主力映射：按 (symbol, trade_date) 幂等更新合约代码与规则字段。"""
        for symbol_value, trade_date, contract in rows:
            symbol = symbol_value.strip().lower()
            contract_code = contract.strip().upper()
            row = self.session.scalar(
                select(MainContractMap).where(
                    MainContractMap.symbol == symbol,
                    MainContractMap.trade_date == trade_date,
                )
            )
            if row is None:
                self.session.add(
                    MainContractMap(
                        symbol=symbol,
                        trade_date=trade_date,
                        contract_code=contract_code,
                        rank=1,
                        rule="volume_open_interest",
                    )
                )
            else:
                row.contract_code = contract_code
                row.rank = 1
                row.rule = "volume_open_interest"
        self.session.flush()

    def main_map(self, symbol: str, start: date, end: date) -> tuple[MainMapFact, ...]:
        """查询日期闭区间内的主力映射，按交易日升序。"""
        rows = self.session.scalars(
            select(MainContractMap)
            .where(
                MainContractMap.symbol == symbol.strip().lower(),
                MainContractMap.trade_date >= start,
                MainContractMap.trade_date <= end,
                MainContractMap.rank == 1,
            )
            .order_by(MainContractMap.trade_date)
        )
        return tuple(
            MainMapFact(row.symbol, row.trade_date, row.contract_code) for row in rows
        )

    def main_map_before(
        self,
        symbol: str,
        before: datetime | None,
    ) -> tuple[MainMapFact, ...]:
        """读取游标当日及以前的正式 rank-1 主力映射事实。"""
        statement = select(MainContractMap).where(
            MainContractMap.symbol == symbol.strip().lower(),
            MainContractMap.rank == 1,
        )
        if before is not None:
            statement = statement.where(
                MainContractMap.trade_date <= before.astimezone(SHANGHAI).date()
            )
        rows = self.session.scalars(statement.order_by(MainContractMap.trade_date))
        return tuple(
            MainMapFact(row.symbol, row.trade_date, row.contract_code) for row in rows
        )

    def exchange_for_symbol(self, symbol: str) -> str:
        """解析品种所属交易所代码；无活跃 ``Instrument`` 时 ``INSTRUMENT_EXCHANGE_MISSING``。"""
        exchange = self.session.scalar(
            select(Instrument.exchange_code).where(
                Instrument.symbol == symbol.strip().lower(),
                Instrument.is_active.is_(True),
            )
        )
        if exchange is None:
            raise CatalogError("INSTRUMENT_EXCHANGE_MISSING")
        return exchange

    def trading_days(self, symbol: str, start: date, end: date) -> tuple[date, ...]:
        """经品种反查交易所后，返回区间内 ``is_trading_day=True`` 的日期列表。"""
        exchange = self.exchange_for_symbol(symbol)
        return tuple(
            self.session.scalars(
                select(TradingCalendar.trade_date)
                .where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.trade_date >= start,
                    TradingCalendar.trade_date <= end,
                    TradingCalendar.is_trading_day.is_(True),
                )
                .order_by(TradingCalendar.trade_date)
            )
        )

    def trading_days_overlapping_window(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> tuple[date, ...]:
        """返回实际 Session 与 ``(start, end]`` 相交的交易日。

        夜盘虽发生在前一自然日，但身份属于下一交易日；因此候选范围额外纳入
        ``end`` 自然日后的首个交易日，再以历史 Session 事实精确筛选。
        """
        exchange = self.exchange_for_symbol(symbol)
        start_day = start.astimezone(SHANGHAI).date()
        end_day = end.astimezone(SHANGHAI).date()
        candidates = list(self.trading_days(symbol, start_day, end_day))
        next_day = self.session.scalar(
            select(TradingCalendar.trade_date)
            .where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.trade_date > end_day,
                TradingCalendar.is_trading_day.is_(True),
            )
            .order_by(TradingCalendar.trade_date)
            .limit(1)
        )
        if next_day is not None:
            candidates.append(next_day)
        result: list[date] = []
        for trading_day in tuple(dict.fromkeys(candidates)):
            try:
                windows = session_windows_for_trading_day(
                    self.session,
                    exchange=exchange,
                    symbol=symbol,
                    trading_day=trading_day,
                )
            except SessionClockError as exc:
                if (
                    trading_day > end_day
                    and self.session.scalar(
                        select(MainContractMap.id)
                        .where(
                            MainContractMap.symbol == symbol.strip().lower(),
                            MainContractMap.trade_date == trading_day,
                        )
                        .limit(1)
                    )
                    is None
                ):
                    continue
                raise CatalogError(exc.code) from exc
            if any(window.start < end and start < window.end for window in windows):
                result.append(trading_day)
        return tuple(result)

    def missing_main_map_days(
        self, symbol: str, start: date, end: date
    ) -> tuple[date, ...]:
        """返回交易日历中存在但 ``MainContractMap`` 缺失的日期（actual_dominant 前置检查）。"""
        expected = self.trading_days(symbol, start, end)
        mapped = {item.trade_date for item in self.main_map(symbol, start, end)}
        return tuple(day for day in expected if day not in mapped)

    def _partition(self, key: DatasetKey, row: MarketPartition) -> CatalogPartition:
        """将 ORM 行转为值对象，并将 DB 中的 coverage 规范为 UTC aware。"""
        return CatalogPartition(
            dataset=key,
            year=row.year,
            month=row.month,
            coverage_start=_aware(row.coverage_start),
            coverage_end=_aware(row.coverage_end),
            file_path=self._resolve_uri(row.file_uri),
            row_count=row.row_count,
        )

    def _relative_uri(self, path: Path) -> str:
        """绝对路径必须位于 ``canonical_root`` 下，存库为 POSIX 相对 URI。"""
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.canonical_root).as_posix()
        except ValueError as exc:
            raise CatalogError("PARTITION_OUTSIDE_CANONICAL_ROOT") from exc

    def _resolve_uri(self, uri: str) -> Path:
        """解析库内相对 URI 为绝对路径；禁止绝对 URI 与 ``..`` 逃逸 canonical 根。"""
        if Path(uri).is_absolute():
            raise CatalogError("ABSOLUTE_PARTITION_URI_FORBIDDEN")
        path = (self.canonical_root / uri).resolve()
        if self.canonical_root not in path.parents:
            raise CatalogError("PARTITION_URI_ESCAPE")
        return path


def _aware(value: datetime) -> datetime:
    """naive datetime 视为 UTC；已有偏移则归一化到 UTC。"""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
