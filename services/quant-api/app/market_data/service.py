from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

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


SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketDataError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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
                contract_bars, _ = self._read_physical(key, request)
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
        return self._result(request, tuple(bars), segments)

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
    ) -> tuple[tuple[CanonicalBar, ...], tuple[CatalogPartition, ...]]:
        partitions = self.catalog.partitions(key, request.start, request.end)
        if not partitions:
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
