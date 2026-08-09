from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.market_data.domain import DatasetKey
from app.market_data.storage import PublishedPartition
from app.models import (
    Instrument,
    MainContractMap,
    MarketDataset,
    MarketPartition,
    TradingCalendar,
)


class CatalogError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_MAINTENANCE_LOCK_KEY = 4_902_608_003_600_001


class MaintenanceLease:
    def release(self) -> None:
        raise NotImplementedError


class _NoopMaintenanceLease(MaintenanceLease):
    def release(self) -> None:
        return None


class _PostgresMaintenanceLease(MaintenanceLease):
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
    dataset: DatasetKey
    year: int
    month: int
    coverage_start: datetime
    coverage_end: datetime
    file_path: Path
    row_count: int


@dataclass(frozen=True, slots=True)
class MainMapFact:
    symbol: str
    trade_date: date
    contract: str


class MarketCatalog:
    def __init__(self, session: Session, canonical_root: Path) -> None:
        self.session = session
        self.canonical_root = canonical_root.resolve()

    def acquire_maintenance_lock(self) -> MaintenanceLease | None:
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

    def dataset_row(self, key: DatasetKey, *, create: bool = False) -> MarketDataset | None:
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
        dataset = self.dataset_row(key)
        if dataset is None:
            return ()
        rows = self.session.scalars(
            select(MarketPartition)
            .where(MarketPartition.dataset_id == dataset.id)
            .order_by(MarketPartition.year, MarketPartition.month)
        )
        return tuple(self._partition(key, row) for row in rows)

    def upsert_main_contracts(self, rows: Iterable[tuple[str, date, str]]) -> None:
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
        rows = self.session.scalars(
            select(MainContractMap)
            .where(
                MainContractMap.symbol == symbol.strip().lower(),
                MainContractMap.trade_date >= start,
                MainContractMap.trade_date <= end,
            )
            .order_by(MainContractMap.trade_date)
        )
        return tuple(
            MainMapFact(row.symbol, row.trade_date, row.contract_code) for row in rows
        )

    def exchange_for_symbol(self, symbol: str) -> str:
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

    def missing_main_map_days(self, symbol: str, start: date, end: date) -> tuple[date, ...]:
        expected = self.trading_days(symbol, start, end)
        mapped = {item.trade_date for item in self.main_map(symbol, start, end)}
        return tuple(day for day in expected if day not in mapped)

    def _partition(self, key: DatasetKey, row: MarketPartition) -> CatalogPartition:
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
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.canonical_root).as_posix()
        except ValueError as exc:
            raise CatalogError("PARTITION_OUTSIDE_CANONICAL_ROOT") from exc

    def _resolve_uri(self, uri: str) -> Path:
        if Path(uri).is_absolute():
            raise CatalogError("ABSOLUTE_PARTITION_URI_FORBIDDEN")
        path = (self.canonical_root / uri).resolve()
        if self.canonical_root not in path.parents:
            raise CatalogError("PARTITION_URI_ESCAPE")
        return path


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
