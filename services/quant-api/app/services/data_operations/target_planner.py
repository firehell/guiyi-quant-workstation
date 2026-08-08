"""Unique activity-universe / Catalog-gap target planner for historical updates.

``TargetExpander`` remains the expert CLI explicit-target expander. This module is
the only retained-universe catch-up planner; it replaces ``build_refresh_targets``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Callable, Protocol, Sequence

from app.data_core.contracts import BarFrequency, DatasetKind
from app.data_core.historical_sync import plan_missing_windows
from app.services.data_operations.contracts import (
    DEFAULT_ADJUSTMENT,
    DEFAULT_PROVIDER,
    DEFAULT_SCHEMA_VERSION,
    CliArgumentInvalid,
    DataTarget,
    HistoricalUpdateRequest,
)
from app.services.trading_session_clock import SHANGHAI

DIRECT_FREQUENCIES = (
    BarFrequency.M1,
    BarFrequency.D1,
    BarFrequency.W1,
)
DERIVED_FREQUENCIES = (
    BarFrequency.M5,
    BarFrequency.M15,
    BarFrequency.M30,
    BarFrequency.H1,
)
MAPPING_OVERLAP_TRADING_DAYS = 5


class _MappingRow(Protocol):
    symbol: str
    trading_day: date
    actual_contract: str


class _PartitionLike(Protocol):
    coverage_start: datetime
    coverage_end: datetime


class _CatalogLike(Protocol):
    def list_effective_partitions(self, key: object) -> Sequence[_PartitionLike]: ...


@dataclass(frozen=True, slots=True)
class PlannedProductWindow:
    symbol: str
    since_day: date
    through_day: date
    start: datetime
    end: datetime
    weekly_end_day: date


@dataclass(frozen=True, slots=True)
class HistoricalUpdatePlan:
    request: HistoricalUpdateRequest
    products: tuple[str, ...]
    windows: tuple[PlannedProductWindow, ...]
    direct_targets: tuple[DataTarget, ...]
    aggregate_targets: tuple[DataTarget, ...]
    apply: bool


@dataclass(frozen=True, slots=True)
class _CoverageProbe:
    provider: str
    dataset_kind: DatasetKind
    symbol: str
    contract_or_series: str
    frequency: BarFrequency
    adjustment: str
    schema_version: str


class HistoricalUpdateTargetPlanner:
    """Plan exact Direct/Aggregate targets from activity pool + Catalog gaps."""

    def __init__(
        self,
        *,
        list_mappings: Callable[[str, date, date], Sequence[_MappingRow]],
        covered_windows: Callable[
            [_CoverageProbe], Sequence[tuple[datetime, datetime]]
        ]
        | None = None,
        list_gaps: Callable[[_CoverageProbe], Sequence[object]] | None = None,
        latest_completed_day: Callable[[str], date] | None = None,
        mapping_overlap_trading_days: int = MAPPING_OVERLAP_TRADING_DAYS,
    ) -> None:
        self._list_mappings = list_mappings
        self._covered_windows = covered_windows
        self._list_gaps = list_gaps or (lambda _probe: ())
        self._latest_completed_day = latest_completed_day
        self._mapping_overlap_trading_days = mapping_overlap_trading_days

    def plan(self, request: HistoricalUpdateRequest) -> HistoricalUpdatePlan:
        products = _normalize_products(request.products)
        if not products:
            raise CliArgumentInvalid(facts={"field": "products", "reason": "empty"})
        windows: list[PlannedProductWindow] = []
        direct: list[DataTarget] = []
        aggregate: list[DataTarget] = []
        for symbol in products:
            through_day = request.through
            if through_day is None:
                if self._latest_completed_day is None:
                    raise CliArgumentInvalid(
                        facts={"field": "through", "reason": "required_without_clock"}
                    )
                through_day = self._latest_completed_day(symbol)
            since_day = request.since
            if since_day is None:
                since_day = self._resolve_catchup_since(
                    symbol=symbol,
                    through_day=through_day,
                )
            if since_day > through_day:
                continue
            start, end = inclusive_trading_days_to_half_open(since_day, through_day)
            weekly_end_day = complete_week_end(through_day=through_day, today=through_day)
            mappings = tuple(self._list_mappings(symbol, since_day, through_day))
            if not mappings:
                raise CliArgumentInvalid(
                    facts={
                        "field": "main_contract_map",
                        "symbol": symbol,
                        "reason": "missing",
                    }
                )
            identity = build_identity_targets(
                products=(symbol,),
                mappings=mappings,
                start=start,
                end=end,
                weekly_end_day=weekly_end_day,
            )
            self._reject_gap_intersections(identity)
            missing_direct = materialize_missing_targets(
                identity, covered_windows=self._covered_windows
            )
            # Derived missing is planned from full identity 1m windows, never from
            # only this-round direct missing (1m complete + 15m hole must repair).
            derived_identity = derive_aggregate_targets(identity)
            self._reject_gap_intersections(derived_identity)
            missing_derived = materialize_missing_targets(
                derived_identity, covered_windows=self._covered_windows
            )
            windows.append(
                PlannedProductWindow(
                    symbol=symbol,
                    since_day=since_day,
                    through_day=through_day,
                    start=start,
                    end=end,
                    weekly_end_day=weekly_end_day,
                )
            )
            # Covered windows (with or without explicit --since) are NOOP.
            # --since is only a missing-detection lower bound, never force-refresh.
            if not missing_direct and not missing_derived:
                continue
            direct.extend(missing_direct)
            aggregate.extend(missing_derived)
        return HistoricalUpdatePlan(
            request=request,
            products=products,
            windows=tuple(windows),
            direct_targets=tuple(direct),
            aggregate_targets=tuple(aggregate),
            apply=request.apply,
        )

    def _resolve_catchup_since(self, *, symbol: str, through_day: date) -> date:
        """Earliest Catalog coverage hole, with mapping overlap (never fixed 10d).

        Continuous 1m is the primary probe. When it has no hole, still return the
        first known coverage day so independent derived / actual_dominant missing
        can be discovered by later filters (empty filters → product NOOP).
        """
        probe_end = inclusive_trading_days_to_half_open(through_day, through_day)[1]
        continuous = _CoverageProbe(
            provider=DEFAULT_PROVIDER,
            dataset_kind=DatasetKind.CONTINUOUS,
            symbol=symbol,
            contract_or_series=f"{symbol.upper()}.MAIN",
            frequency=BarFrequency.M1,
            adjustment=DEFAULT_ADJUSTMENT,
            schema_version=DEFAULT_SCHEMA_VERSION,
        )
        covered = ()
        if self._covered_windows is not None:
            covered = tuple(self._covered_windows(continuous))
        if not covered:
            raise CliArgumentInvalid(code="HISTORICAL_UPDATE_START_REQUIRED")
        # Existing datasets are planned from the first known Catalog coverage,
        # never from an arbitrary lookback that could hide an older backlog.
        probe_start = min(window[0] for window in covered)
        missing = plan_missing_windows(
            dataset=_probe_to_key(continuous),
            start=probe_start,
            end=probe_end,
            covered_windows=covered,
        )
        earliest_candidates: list[datetime] = []
        if missing:
            earliest_candidates.append(min(window[0] for window in missing))
        # Independent derived holes on continuous MAIN (1m may already be complete).
        for frequency in DERIVED_FREQUENCIES:
            derived_probe = _CoverageProbe(
                provider=DEFAULT_PROVIDER,
                dataset_kind=DatasetKind.CONTINUOUS,
                symbol=symbol,
                contract_or_series=f"{symbol.upper()}.MAIN",
                frequency=frequency,
                adjustment=DEFAULT_ADJUSTMENT,
                schema_version=DEFAULT_SCHEMA_VERSION,
            )
            derived_covered = ()
            if self._covered_windows is not None:
                derived_covered = tuple(self._covered_windows(derived_probe))
            derived_missing = plan_missing_windows(
                dataset=_probe_to_key(derived_probe),
                start=probe_start,
                end=probe_end,
                covered_windows=derived_covered,
            )
            if derived_missing:
                earliest_candidates.append(min(window[0] for window in derived_missing))
        if not earliest_candidates:
            # Continuous MAIN direct+derived may be complete while expected
            # actual_dominant (or its derived) still has holes. Probe map-expected
            # identities from first known coverage through watermark.
            probe_start_day = probe_start.astimezone(SHANGHAI).date()
            mappings = tuple(self._list_mappings(symbol, probe_start_day, through_day))
            if mappings:
                weekly_end_day = complete_week_end(
                    through_day=through_day, today=through_day
                )
                identity = build_identity_targets(
                    products=(symbol,),
                    mappings=mappings,
                    start=probe_start,
                    end=probe_end,
                    weekly_end_day=weekly_end_day,
                )
                for target in (*identity, *derive_aggregate_targets(identity)):
                    probe = _probe_from_target(target)
                    covered = ()
                    if self._covered_windows is not None:
                        covered = tuple(self._covered_windows(probe))
                    hole = plan_missing_windows(
                        dataset=_probe_to_key(probe),
                        start=target.start,
                        end=target.end,
                        covered_windows=covered,
                    )
                    if hole:
                        earliest_candidates.append(min(window[0] for window in hole))
        if not earliest_candidates:
            # All expected continuous + actual_dominant identities covered.
            return through_day + timedelta(days=1)
        earliest = min(earliest_candidates).astimezone(SHANGHAI).date()
        overlap = max(0, self._mapping_overlap_trading_days)
        return earliest - timedelta(days=overlap)

    def _reject_gap_intersections(self, targets: Sequence[DataTarget]) -> None:
        for target in targets:
            probe = _probe_from_target(target)
            for gap in self._list_gaps(probe):
                gap_start = getattr(gap, "gap_start", None)
                gap_end = getattr(gap, "gap_end", None)
                if (
                    isinstance(gap_start, datetime)
                    and isinstance(gap_end, datetime)
                    and gap_start < target.end
                    and target.start < gap_end
                ):
                    raise CliArgumentInvalid(
                        code="HISTORICAL_UPDATE_DATA_GAP",
                        facts={
                            "symbol": target.symbol,
                            "frequency": target.frequency.value,
                        },
                    )

    def _filter_missing(self, targets: Sequence[DataTarget]) -> tuple[DataTarget, ...]:
        """Compat wrapper: materialize exact missing sub-windows."""
        return materialize_missing_targets(
            targets, covered_windows=self._covered_windows
        )


def materialize_missing_targets(
    targets: Sequence[DataTarget],
    *,
    covered_windows: Callable[[_CoverageProbe], Sequence[tuple[datetime, datetime]]]
    | None,
) -> tuple[DataTarget, ...]:
    """Split each target into Catalog-uncovered exact sub-window targets.

    When coverage probing is unavailable, returns the original targets unchanged.
    """
    if covered_windows is None:
        return tuple(targets)
    exact: list[DataTarget] = []
    for target in targets:
        probe = _CoverageProbe(
            provider=target.provider,
            dataset_kind=target.dataset_kind,
            symbol=target.symbol,
            contract_or_series=target.contract_or_series,
            frequency=target.frequency,
            adjustment=target.adjustment,
            schema_version=target.schema_version,
        )
        missing = plan_missing_windows(
            dataset=_probe_to_key(probe),
            start=target.start,
            end=target.end,
            covered_windows=covered_windows(probe),
        )
        for window_start, window_end in missing:
            exact.append(
                _data_target(
                    dataset_kind=target.dataset_kind,
                    symbol=target.symbol,
                    contract_or_series=target.contract_or_series,
                    frequency=target.frequency,
                    start=window_start,
                    end=window_end,
                    provider=target.provider,
                    adjustment=target.adjustment,
                    schema_version=target.schema_version,
                )
            )
    return tuple(exact)


def build_identity_targets(
    *,
    products: Sequence[str],
    mappings: Sequence[_MappingRow],
    start: datetime,
    end: datetime,
    weekly_end_day: date | None = None,
) -> tuple[DataTarget, ...]:
    """Expand continuous + actual_dominant Direct targets for a half-open window."""
    active = _normalize_products(products)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise CliArgumentInvalid(facts={"field": "window", "reason": "invalid"})
    rows_by_symbol: dict[str, list[_MappingRow]] = {symbol: [] for symbol in active}
    for row in mappings:
        symbol = str(row.symbol).strip().lower()
        if symbol not in rows_by_symbol:
            raise CliArgumentInvalid(
                facts={"field": "main_contract_map", "reason": "outside_universe"}
            )
        rows_by_symbol[symbol].append(row)
    missing = tuple(
        symbol for symbol, rows in rows_by_symbol.items() if not rows
    )
    if missing:
        raise CliArgumentInvalid(
            facts={
                "field": "main_contract_map",
                "reason": "missing",
                "symbols": ",".join(missing),
            }
        )
    targets: list[DataTarget] = []
    for symbol in active:
        for frequency in DIRECT_FREQUENCIES:
            targets.append(
                _data_target(
                    dataset_kind=DatasetKind.CONTINUOUS,
                    symbol=symbol,
                    contract_or_series=f"{symbol.upper()}.MAIN",
                    frequency=frequency,
                    start=start,
                    end=end,
                )
            )
        actual_windows = _actual_dominant_windows(
            rows_by_symbol[symbol], start=start, end=end
        )
        for contract, actual_start, actual_end in actual_windows:
            for frequency in DIRECT_FREQUENCIES:
                if (
                    frequency is BarFrequency.W1
                    and weekly_end_day is not None
                    and actual_start >= _trading_day_start(weekly_end_day + timedelta(days=1))
                ):
                    continue
                targets.append(
                    _data_target(
                        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                        symbol=symbol,
                        contract_or_series=contract,
                        frequency=frequency,
                        start=actual_start,
                        end=actual_end,
                    )
                )
    return tuple(targets)


def _actual_dominant_windows(
    rows: Sequence[_MappingRow], *, start: datetime, end: datetime
) -> tuple[tuple[str, datetime, datetime], ...]:
    """Split actual-dominant targets at every rank-1 mapping transition."""
    ordered = sorted(rows, key=lambda item: item.trading_day)
    windows: list[tuple[str, datetime, datetime]] = []
    for index, row in enumerate(ordered):
        contract = str(row.actual_contract).strip().upper()
        if not contract:
            raise CliArgumentInvalid(
                facts={"field": "main_contract_map", "reason": "blank_contract"}
            )
        candidate_start = max(start, _trading_day_start(row.trading_day))
        next_start = (
            _trading_day_start(ordered[index + 1].trading_day)
            if index + 1 < len(ordered)
            else end
        )
        candidate_end = min(end, next_start)
        if candidate_start >= candidate_end:
            continue
        if windows and windows[-1][0] == contract and windows[-1][2] == candidate_start:
            prior = windows.pop()
            windows.append((contract, prior[1], candidate_end))
        else:
            windows.append((contract, candidate_start, candidate_end))
    if not windows:
        raise CliArgumentInvalid(
            facts={"field": "main_contract_map", "reason": "no_rank_one_window"}
        )
    return tuple(windows)


def _trading_day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=SHANGHAI).astimezone(UTC)


def derive_aggregate_targets(
    direct_targets: Sequence[DataTarget],
) -> tuple[DataTarget, ...]:
    derived: list[DataTarget] = []
    for target in direct_targets:
        if target.frequency is not BarFrequency.M1:
            continue
        for frequency in DERIVED_FREQUENCIES:
            derived.append(
                _data_target(
                    dataset_kind=target.dataset_kind,
                    symbol=target.symbol,
                    contract_or_series=target.contract_or_series,
                    frequency=frequency,
                    start=target.start,
                    end=target.end,
                    provider=target.provider,
                    adjustment=target.adjustment,
                    schema_version=target.schema_version,
                )
            )
    return tuple(derived)


def inclusive_trading_days_to_half_open(
    since_day: date,
    through_day: date,
) -> tuple[datetime, datetime]:
    if since_day > through_day:
        raise CliArgumentInvalid(facts={"field": "window", "reason": "inverted"})
    start = datetime.combine(since_day, time.min, tzinfo=SHANGHAI).astimezone(UTC)
    end = datetime.combine(
        through_day + timedelta(days=1),
        time.min,
        tzinfo=SHANGHAI,
    ).astimezone(UTC)
    return start, end


def complete_week_end(*, through_day: date, today: date) -> date:
    """Last trading day belonging to a fully completed ISO week."""
    current_week = today.isocalendar()[:2]
    cursor = through_day
    while cursor.isocalendar()[:2] >= current_week:
        cursor -= timedelta(days=1)
    return cursor


def covered_windows_from_catalog(
    catalog: _CatalogLike,
    probe: _CoverageProbe,
) -> tuple[tuple[datetime, datetime], ...]:
    from app.data_core.contracts import DatasetKey

    key = DatasetKey(
        provider=probe.provider,
        dataset_kind=probe.dataset_kind,
        symbol=probe.symbol,
        contract_or_series=probe.contract_or_series,
        frequency=probe.frequency,
        adjustment=probe.adjustment,
        schema_version=probe.schema_version,
    )
    return tuple(
        (item.coverage_start, item.coverage_end)
        for item in catalog.list_effective_partitions(key)
    )


def _data_target(
    *,
    dataset_kind: DatasetKind,
    symbol: str,
    contract_or_series: str,
    frequency: BarFrequency,
    start: datetime,
    end: datetime,
    provider: str = DEFAULT_PROVIDER,
    adjustment: str = DEFAULT_ADJUSTMENT,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
) -> DataTarget:
    return DataTarget(
        provider=provider,
        dataset_kind=dataset_kind,
        symbol=symbol.lower(),
        contract_or_series=contract_or_series.upper(),
        frequency=frequency,
        adjustment=adjustment,
        schema_version=schema_version,
        start=start,
        end=end,
    )


def _normalize_products(products: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(product).strip().lower() for product in products)
    if any(not item for item in normalized):
        raise CliArgumentInvalid(facts={"field": "products", "reason": "blank"})
    return normalized


def _probe_to_key(probe: _CoverageProbe) -> object:
    from app.data_core.contracts import DatasetKey

    return DatasetKey(
        provider=probe.provider,
        dataset_kind=probe.dataset_kind,
        symbol=probe.symbol,
        contract_or_series=probe.contract_or_series,
        frequency=probe.frequency,
        adjustment=probe.adjustment,
        schema_version=probe.schema_version,
    )


def _probe_from_target(target: DataTarget) -> _CoverageProbe:
    return _CoverageProbe(
        provider=target.provider,
        dataset_kind=target.dataset_kind,
        symbol=target.symbol,
        contract_or_series=target.contract_or_series,
        frequency=target.frequency,
        adjustment=target.adjustment,
        schema_version=target.schema_version,
    )
