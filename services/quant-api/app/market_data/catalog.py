from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session
from sqlalchemy.engine import CursorResult

from app.market_data.domain import DatasetKey
from app.market_data.storage import PublishedPartition
from app.models import (
    ContractSpec,
    DataGap,
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


@dataclass(frozen=True, slots=True)
class CatalogPartition:
    dataset: DatasetKey
    year: int
    month: int
    coverage_start: datetime
    coverage_end: datetime
    file_path: Path
    manifest_path: Path
    row_count: int
    checksum: str
    manifest_digest: str


@dataclass(frozen=True, slots=True)
class MainMapFact:
    symbol: str
    trade_date: date
    contract: str


class MarketCatalog:
    def __init__(self, session: Session, canonical_root: Path) -> None:
        self.session = session
        self.canonical_root = canonical_root.resolve()

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
            "manifest_uri": self._relative_uri(partition.manifest_path),
            "row_count": partition.row_count,
            "checksum": partition.checksum,
            "manifest_digest": partition.manifest_digest,
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

    def add_gap(
        self,
        key: DatasetKey,
        start: datetime,
        end: datetime,
        reason_code: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        dataset = self.dataset_row(key, create=True)
        assert dataset is not None
        row = self.session.scalar(
            select(DataGap).where(
                DataGap.dataset_id == dataset.id,
                DataGap.gap_start == start,
                DataGap.gap_end == end,
            )
        )
        if row is None:
            self.session.add(
                DataGap(
                    dataset_id=dataset.id,
                    gap_start=start,
                    gap_end=end,
                    reason_code=reason_code,
                    details=dict(details or {}),
                )
            )
        else:
            row.reason_code = reason_code
            row.details = dict(details or {})
        self.session.flush()

    def has_gap(self, key: DatasetKey, start: datetime, end: datetime) -> bool:
        dataset = self.dataset_row(key)
        if dataset is None:
            return False
        return (
            self.session.scalar(
                select(DataGap.id)
                .where(
                    DataGap.dataset_id == dataset.id,
                    DataGap.gap_end > start,
                    DataGap.gap_start < end,
                )
                .limit(1)
            )
            is not None
        )

    def clear_gaps(self, key: DatasetKey, start: datetime, end: datetime) -> int:
        dataset = self.dataset_row(key)
        if dataset is None:
            return 0
        result = cast(CursorResult[Any], self.session.execute(
            delete(DataGap).where(
                DataGap.dataset_id == dataset.id,
                DataGap.gap_start >= start,
                DataGap.gap_end <= end,
            )
        ))
        return int(result.rowcount or 0)

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

    def upsert_contract_specs(self, rows: Iterable[Mapping[str, Any]]) -> None:
        optional = (
            "long_margin_rate",
            "short_margin_rate",
            "open_fee",
            "close_fee",
            "close_today_fee",
            "fee_type",
        )
        for values in rows:
            contract = str(values["contract_code"]).strip().upper()
            trade_date = values["trade_date"]
            row = self.session.scalar(
                select(ContractSpec).where(
                    ContractSpec.contract_code == contract,
                    ContractSpec.trade_date == trade_date,
                )
            )
            payload = {
                "symbol": str(values["symbol"]).strip().lower(),
                "exchange_code": str(values["exchange_code"]).strip().upper(),
                "price_tick": Decimal(values["price_tick"]),
                "contract_multiplier": Decimal(values["contract_multiplier"]),
                **{field: values.get(field) for field in optional},
            }
            if row is None:
                self.session.add(
                    ContractSpec(
                        contract_code=contract,
                        trade_date=trade_date,
                        **payload,
                    )
                )
            else:
                for field, value in payload.items():
                    setattr(row, field, value)
        self.session.flush()

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

    def missing_contract_spec_days(self, symbol: str, start: date, end: date) -> tuple[date, ...]:
        rows = self.session.scalars(
            select(MainContractMap.trade_date)
            .where(
                MainContractMap.symbol == symbol.strip().lower(),
                MainContractMap.trade_date >= start,
                MainContractMap.trade_date <= end,
                ~exists().where(
                    ContractSpec.contract_code == MainContractMap.contract_code,
                    ContractSpec.trade_date == MainContractMap.trade_date,
                ),
            )
            .order_by(MainContractMap.trade_date)
        )
        return tuple(rows)

    def _partition(self, key: DatasetKey, row: MarketPartition) -> CatalogPartition:
        return CatalogPartition(
            dataset=key,
            year=row.year,
            month=row.month,
            coverage_start=_aware(row.coverage_start),
            coverage_end=_aware(row.coverage_end),
            file_path=self._resolve_uri(row.file_uri),
            manifest_path=self._resolve_uri(row.manifest_uri),
            row_count=row.row_count,
            checksum=row.checksum,
            manifest_digest=row.manifest_digest,
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
