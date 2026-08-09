from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.market_data.catalog import CatalogPartition, MainMapFact, MarketCatalog
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    DatasetKey,
    DatasetKind,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesQuery,
)
from app.market_data.storage import CanonicalMonthlyStore, StorageError
from app.models import Instrument, MainContractMap, MarketDataset, MarketPartition


SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketDataError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DatasetCoverageSummary:
    kind: str
    symbol: str
    series_or_contract: str
    frequency: str
    start: datetime
    end: datetime
    row_count: int
    partition_count: int


@dataclass(frozen=True, slots=True)
class DominantContractSummary:
    symbol: str
    product_name: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date


class MarketDataService:
    def __init__(self, catalog: MarketCatalog, store: CanonicalMonthlyStore) -> None:
        self.catalog = catalog
        self.store = store

    def query(self, request: SeriesQuery) -> MarketSeriesResult:
        if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            return self._actual_dominant(request)
        assert request.physical_key is not None
        bars, _ = self._read_physical(request.physical_key, request)
        return self._result(request, bars, (),)

    def _actual_dominant(self, request: SeriesQuery) -> MarketSeriesResult:
        start_day = _local_date(request.start)
        end_day = _local_date(request.end)
        mappings = self.catalog.main_map(
            request.symbol,
            start_day,
            end_day,
        )
        if not mappings:
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        trading_days = self.catalog.trading_days(
            request.symbol,
            start_day,
            end_day,
        )
        if not trading_days:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        missing_days = self.catalog.missing_main_map_days(
            request.symbol,
            start_day,
            end_day,
        )
        if missing_days:
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        if request.frequency is BarFrequency.W1:
            selected = self._weekly_mappings(request, mappings)
        else:
            selected = mappings
        segments = _segments(selected)
        bars: list[CanonicalBar] = []
        mapping_by_day = {row.trade_date: row.contract for row in selected}
        for contract in dict.fromkeys(row.contract for row in selected):
            key = DatasetKey(
                DatasetKind.CONTRACT,
                request.symbol,
                contract,
                request.frequency,
            )
            try:
                contract_bars, _ = self._read_physical(
                    key,
                    request,
                    require_window_coverage=False,
                )
            except MarketDataError as exc:
                if exc.code == "DATASET_OR_PARTITION_MISSING":
                    raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING") from exc
                raise
            bars.extend(
                bar
                for bar in contract_bars
                if mapping_by_day.get(bar.trading_day) == contract
            )
        bars.sort(key=lambda item: item.bar_end)
        if not bars:
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        if {item.trade_date for item in selected} - {bar.trading_day for bar in bars}:
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        return self._result(request, tuple(bars), segments)

    def list_dataset_coverage(
        self,
        symbol: str | None = None,
    ) -> tuple[DatasetCoverageSummary, ...]:
        query = select(MarketDataset)
        if symbol:
            query = query.where(MarketDataset.symbol == symbol.strip().lower())
        items: list[DatasetCoverageSummary] = []
        for dataset in self.catalog.session.scalars(
            query.order_by(MarketDataset.symbol, MarketDataset.frequency)
        ):
            partitions = tuple(
                self.catalog.session.scalars(
                    select(MarketPartition)
                    .where(MarketPartition.dataset_id == dataset.id)
                    .order_by(MarketPartition.year, MarketPartition.month)
                )
            )
            if not partitions:
                continue
            items.append(
                DatasetCoverageSummary(
                    kind=dataset.kind,
                    symbol=dataset.symbol,
                    series_or_contract=dataset.series_or_contract,
                    frequency=dataset.frequency,
                    start=partitions[0].coverage_start,
                    end=partitions[-1].coverage_end,
                    row_count=sum(item.row_count for item in partitions),
                    partition_count=len(partitions),
                )
            )
        return tuple(items)

    def list_latest_dominants(self) -> tuple[DominantContractSummary, ...]:
        mappings = self.catalog.session.scalars(
            select(MainContractMap).order_by(
                MainContractMap.symbol,
                MainContractMap.trade_date.desc(),
            )
        )
        latest: dict[str, MainContractMap] = {}
        for row in mappings:
            latest.setdefault(row.symbol, row)
        instruments = {
            row.symbol: row for row in self.catalog.session.scalars(select(Instrument))
        }
        return tuple(
            DominantContractSummary(
                symbol=symbol,
                product_name=(
                    instruments[symbol].name if symbol in instruments else symbol.upper()
                ),
                exchange=(
                    instruments[symbol].exchange_code if symbol in instruments else ""
                ),
                actual_contract=row.contract_code,
                dominant_mapping_date=row.trade_date,
            )
            for symbol, row in sorted(latest.items())
        )

    def _weekly_mappings(
        self,
        request: SeriesQuery,
        mappings: tuple[MainMapFact, ...],
    ) -> tuple[MainMapFact, ...]:
        request_days = self.catalog.trading_days(
            request.symbol,
            _local_date(request.start),
            _local_date(request.end),
        )
        grouped: dict[tuple[int, int], list[date]] = {}
        for day in request_days:
            iso = day.isocalendar()
            grouped.setdefault((iso.year, iso.week), []).append(day)
        mapping_by_day = {row.trade_date: row for row in mappings}
        selected: list[MainMapFact] = []
        for days in grouped.values():
            candidate_day = days[-1]
            monday = candidate_day - timedelta(days=candidate_day.isoweekday() - 1)
            full_week = self.catalog.trading_days(
                request.symbol,
                monday,
                monday + timedelta(days=6),
            )
            if not full_week or full_week[-1] != candidate_day:
                continue
            owner = mapping_by_day.get(candidate_day)
            if owner is None:
                raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
            selected.append(owner)
        if not selected:
            raise MarketDataError("COMPLETE_WEEK_MISSING")
        return tuple(selected)

    def _read_physical(
        self,
        key: DatasetKey,
        request: SeriesQuery,
        *,
        require_window_coverage: bool = True,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[CatalogPartition, ...]]:
        partitions = self.catalog.partitions(key, request.start, request.end)
        if not partitions:
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        partition_months = {(partition.year, partition.month) for partition in partitions}
        if require_window_coverage:
            if partition_months != _months_between(
                min(partition_months),
                max(partition_months),
            ):
                raise MarketDataError("DATASET_OR_PARTITION_MISSING")
            if (
                min(partition.coverage_start for partition in partitions) > request.start
                or max(partition.coverage_end for partition in partitions) < request.end
            ):
                raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        bars: list[CanonicalBar] = []
        for partition in partitions:
            try:
                values = self.store.read_month(key, partition.year, partition.month)
            except StorageError as exc:
                raise MarketDataError("PARTITION_INTEGRITY_INVALID") from exc
            if len(values) != partition.row_count:
                raise MarketDataError("PARTITION_INTEGRITY_INVALID")
            bars.extend(
                bar for bar in values if request.start < bar.bar_end <= request.end
            )
        bars.sort(key=lambda item: item.bar_end)
        if not bars:
            raise MarketDataError("QUERY_WINDOW_EMPTY")
        if any(previous.bar_end >= current.bar_end for previous, current in zip(bars, bars[1:])):
            raise MarketDataError("BAR_IDENTITY_CONFLICT")
        return tuple(bars), partitions

    def _result(
        self,
        request: SeriesQuery,
        bars: tuple[CanonicalBar, ...],
        segments: tuple[ResolvedContractSegment, ...],
    ) -> MarketSeriesResult:
        identity = {
            "series_kind": request.series_kind.value,
            "symbol": request.symbol,
            "contract": request.contract,
            "frequency": request.frequency.value,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        }
        return MarketSeriesResult(
            request_identity=identity,
            bars=bars,
            coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None,
            resolved_contract_segments=segments,
        )


def _segments(mappings: tuple[MainMapFact, ...]) -> tuple[ResolvedContractSegment, ...]:
    if not mappings:
        return ()
    result: list[ResolvedContractSegment] = []
    contract = mappings[0].contract
    start = mappings[0].trade_date
    end = start
    for row in mappings[1:]:
        if row.contract != contract:
            result.append(ResolvedContractSegment(contract, start, end))
            contract = row.contract
            start = row.trade_date
        end = row.trade_date
    result.append(ResolvedContractSegment(contract, start, end))
    return tuple(result)


def _local_date(value: datetime) -> date:
    return value.astimezone(SHANGHAI).date()


def _months_between(
    start: tuple[int, int],
    end: tuple[int, int],
) -> set[tuple[int, int]]:
    cursor = start
    end_month = end
    result: set[tuple[int, int]] = set()
    while cursor <= end_month:
        result.add(cursor)
        year, month = cursor
        cursor = (year + 1, 1) if month == 12 else (year, month + 1)
    return result
