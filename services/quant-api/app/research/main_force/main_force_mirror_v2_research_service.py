"""Read-only retrospective comparison for Main Force Mirror V2."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from types import MappingProxyType
from typing import Final, Literal, Protocol, TypeAlias

from guiyi_quant.indicators.main_force_mirror_v2 import MainForceMirrorV2Point

from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    ContractTradingDayQuery,
    MarketSeriesResult,
    SeriesKind,
    SeriesPageQuery,
    normalize_contract_for_symbol,
)
from app.market_data.main_force_mirror_v2_service import (
    MainForceMirrorV2Error,
    MainForceMirrorV2PageResult,
    _contracts_for_bars,
)


HORIZONS = (1, 3, 5, 10)
COHORTS = (
    "instant_pressure",
    "accumulated_pressure",
    "member_aligned",
    "member_strong_aligned",
    "member_divergent",
    "member_neutral",
    "member_unavailable",
    "all_caution",
    "caution_member_aligned",
    "caution_member_strong_aligned",
    "caution_member_divergent",
)
SENSITIVITY_THRESHOLDS = tuple(
    Decimal(value) for value in ("0.5", "1.0", "1.5", "2.0", "2.5")
)
KNOWN_RETROSPECTIVE_END: Final = date(2026, 8, 20)


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2ResearchRequest:
    symbol: str
    series_kind: SeriesKind
    contract: str | None
    frequency: BarFrequency
    since: date
    through: date

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be non-empty")
        symbol = self.symbol.strip().lower()
        if not symbol.isascii() or not symbol.isalpha():
            raise ValueError("symbol must contain ASCII letters only")
        try:
            series_kind = SeriesKind(self.series_kind)
            frequency = BarFrequency(self.frequency)
        except (TypeError, ValueError) as exc:
            raise ValueError("research identity is unsupported") from exc
        if series_kind not in {SeriesKind.ACTUAL_DOMINANT, SeriesKind.CONTRACT}:
            raise ValueError("series kind is unsupported")
        if frequency is not BarFrequency.H1:
            raise ValueError("frequency must be 60m")
        contract = self.contract
        if series_kind is SeriesKind.CONTRACT:
            contract = normalize_contract_for_symbol(symbol, contract)
            if contract is None:
                raise ValueError("contract code is required and must match symbol")
        elif contract is not None:
            raise ValueError("contract is forbidden for actual-dominant series")
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise ValueError("trading-day window is invalid")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "series_kind", series_kind)
        object.__setattr__(self, "contract", contract)
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2HorizonSummary:
    horizon_bars: int
    sample_count: int
    median_directional_return: Decimal | None
    median_reversal_return: Decimal | None
    hit_rate: Decimal | None
    median_mfe: Decimal | None
    median_mae: Decimal | None


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2GroupSpread:
    horizon_bars: int
    top_group: str
    bottom_group: str
    directional_return_spread: Decimal | None
    top_sample_count: int
    bottom_sample_count: int


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2SensitivitySummary:
    member_strength_threshold: Decimal
    by_product: Mapping[str, Mapping[int, MainForceMirrorV2HorizonSummary]]
    pooled: Mapping[int, MainForceMirrorV2HorizonSummary]


HorizonMap: TypeAlias = Mapping[int, MainForceMirrorV2HorizonSummary]
CohortMap: TypeAlias = Mapping[str, HorizonMap]
StateMap: TypeAlias = Mapping[str, CohortMap]
ProductMap: TypeAlias = Mapping[str, StateMap]
YearlyMap: TypeAlias = Mapping[int, ProductMap]


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2ResearchResult:
    indicator_code: str
    indicator_version: str
    parameters_hash: str
    research_protocol: Literal["main_force_mirror_v2_retrospective_v1"]
    evaluation_classification: Literal[
        "retrospective_walk_forward_diagnostic"
    ]
    requested_since: date
    requested_through: date
    prospective_oos_starts_after: date
    member_dataset_id: str | None
    products: tuple[str, ...]
    member_coverage: Decimal | None
    caution_ready_bars: int
    caution_events: int
    caution_events_per_1000_ready_bars: Decimal | None
    yearly: YearlyMap
    by_product: ProductMap
    pooled: CohortMap
    top_bottom_spreads: Mapping[int, MainForceMirrorV2GroupSpread]
    sensitivity: Mapping[Decimal, MainForceMirrorV2SensitivitySummary]


class MainForceMirrorV2ResearchError(RuntimeError):
    """Stable read-only research failure without storage details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _MarketDataReader(Protocol):
    def query_actual_dominant_trading_days(
        self, request: ActualDominantTradingDayQuery
    ) -> MarketSeriesResult: ...

    def query_contract_trading_days(
        self, request: ContractTradingDayQuery
    ) -> MarketSeriesResult: ...


class _MirrorPageReader(Protocol):
    def query_page(self, request: SeriesPageQuery) -> MainForceMirrorV2PageResult: ...


@dataclass(frozen=True, slots=True)
class _Observation:
    index: int
    product: str
    year: int
    state: str
    cohort: str
    direction: int


@dataclass(frozen=True, slots=True)
class _Outcome:
    directional_return: Decimal
    reversal_return: Decimal
    mfe: Decimal
    mae: Decimal


class MainForceMirrorV2ResearchService:
    """Compare frozen V2 states without changing the V2 calculation path."""

    def __init__(
        self,
        *,
        market_data: _MarketDataReader,
        mirror_service: _MirrorPageReader,
    ) -> None:
        if not callable(
            getattr(market_data, "query_actual_dominant_trading_days", None)
        ) or not callable(getattr(market_data, "query_contract_trading_days", None)):
            raise TypeError("market_data must implement the read-only query contract")
        if not callable(getattr(mirror_service, "query_page", None)):
            raise TypeError("mirror_service must implement query_page")
        self.market_data = market_data
        self.mirror_service = mirror_service

    def run(
        self, request: MainForceMirrorV2ResearchRequest
    ) -> MainForceMirrorV2ResearchResult:
        if not isinstance(request, MainForceMirrorV2ResearchRequest):
            raise TypeError("request must be MainForceMirrorV2ResearchRequest")
        market = self._query_market(request)
        bars = tuple(
            bar
            for bar in market.bars
            if request.since <= bar.trading_day <= request.through
        )
        if not bars:
            raise MainForceMirrorV2ResearchError("MFM_V2_RESEARCH_MARKET_UNAVAILABLE")
        market_contracts = self._market_contracts(request, bars, market)
        page_identity, points = self._query_points(
            request,
            bars,
            market_contracts,
        )
        observations = _observations(request.symbol, points)
        pooled = _summarize_cohorts(observations, bars, points)
        yearly = _yearly(observations, bars, points)
        by_product = _by_product(observations, bars, points)
        caution_ready_bars = sum(point.caution_ready for point in points)
        caution_events = sum(point.caution is not None for point in points)
        member_ready = sum(
            point.member is not None and point.member.status == "ready"
            for point in points
        )
        return MainForceMirrorV2ResearchResult(
            indicator_code=page_identity.indicator_code,
            indicator_version=page_identity.indicator_version,
            parameters_hash=page_identity.parameters_hash,
            research_protocol="main_force_mirror_v2_retrospective_v1",
            evaluation_classification="retrospective_walk_forward_diagnostic",
            requested_since=request.since,
            requested_through=request.through,
            prospective_oos_starts_after=max(
                request.through, KNOWN_RETROSPECTIVE_END
            ),
            member_dataset_id=page_identity.member_dataset.dataset_id,
            products=(request.symbol,),
            member_coverage=(
                None
                if page_identity.member_dataset.status == "unavailable"
                else _ratio(member_ready, len(points))
            ),
            caution_ready_bars=caution_ready_bars,
            caution_events=caution_events,
            caution_events_per_1000_ready_bars=(
                None
                if caution_ready_bars == 0
                else _rounded(
                    Decimal(caution_events * 1000) / Decimal(caution_ready_bars)
                )
            ),
            yearly=yearly,
            by_product=by_product,
            pooled=pooled,
            top_bottom_spreads=_top_bottom_spreads(observations, bars, points),
            sensitivity=_sensitivity(request.symbol, bars, points),
        )

    def _query_market(
        self, request: MainForceMirrorV2ResearchRequest
    ) -> MarketSeriesResult:
        if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            return self.market_data.query_actual_dominant_trading_days(
                ActualDominantTradingDayQuery(
                    request.symbol,
                    request.frequency,
                    request.since,
                    request.through,
                )
            )
        assert request.contract is not None
        return self.market_data.query_contract_trading_days(
            ContractTradingDayQuery(
                request.symbol,
                request.contract,
                request.frequency,
                request.since,
                request.through,
            )
        )

    def _query_points(
        self,
        request: MainForceMirrorV2ResearchRequest,
        bars: tuple[CanonicalBar, ...],
        market_contracts: tuple[str, ...],
    ) -> tuple[MainForceMirrorV2PageResult, tuple[MainForceMirrorV2Point, ...]]:
        wanted = {bar.bar_end for bar in bars}
        points_by_end: dict[datetime, MainForceMirrorV2Point] = {}
        before = bars[-1].bar_end + timedelta(microseconds=1)
        identity: MainForceMirrorV2PageResult | None = None
        while True:
            page_request = SeriesPageQuery(
                series_kind=request.series_kind,
                symbol=request.symbol,
                contract=request.contract,
                frequency=request.frequency,
                before=before,
                limit=2000,
            )
            page = self.mirror_service.query_page(page_request)
            if dict(page.request_identity) != _page_request_identity(page_request):
                raise MainForceMirrorV2ResearchError(
                    "MFM_V2_RESEARCH_IDENTITY_CONFLICT"
                )
            if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
                try:
                    page_contracts = _contracts_for_bars(
                        page.points,  # type: ignore[arg-type]
                        page.resolved_contract_segments,
                    )
                except MainForceMirrorV2Error:
                    raise MainForceMirrorV2ResearchError(
                        "MFM_V2_RESEARCH_IDENTITY_CONFLICT"
                    ) from None
                if any(
                    point.physical_contract != contract
                    for point, contract in zip(
                        page.points,
                        page_contracts,
                        strict=True,
                    )
                ):
                    raise MainForceMirrorV2ResearchError(
                        "MFM_V2_RESEARCH_IDENTITY_CONFLICT"
                    )
            if identity is None:
                identity = page
            elif (
                page.indicator_code != identity.indicator_code
                or page.indicator_version != identity.indicator_version
                or page.parameters_hash != identity.parameters_hash
                or page.member_dataset != identity.member_dataset
            ):
                raise MainForceMirrorV2ResearchError(
                    "MFM_V2_RESEARCH_IDENTITY_CONFLICT"
                )
            for point in page.points:
                if point.bar_end in wanted:
                    points_by_end[point.bar_end] = point
            if len(points_by_end) == len(wanted):
                break
            if not page.has_more_before or page.next_before is None:
                raise MainForceMirrorV2ResearchError(
                    "MFM_V2_RESEARCH_POINT_COVERAGE_INCOMPLETE"
                )
            if page.next_before >= before:
                raise MainForceMirrorV2ResearchError(
                    "MFM_V2_RESEARCH_CURSOR_INVALID"
                )
            before = page.next_before
        assert identity is not None
        points = tuple(points_by_end[bar.bar_end] for bar in bars)
        for bar, point, market_contract in zip(
            bars,
            points,
            market_contracts,
            strict=True,
        ):
            if (
                point.bar_end != bar.bar_end
                or point.trading_day != bar.trading_day
                or point.physical_contract != market_contract
            ):
                raise MainForceMirrorV2ResearchError(
                    "MFM_V2_RESEARCH_IDENTITY_CONFLICT"
                )
        return identity, points

    @staticmethod
    def _market_contracts(
        request: MainForceMirrorV2ResearchRequest,
        bars: tuple[CanonicalBar, ...],
        market: MarketSeriesResult,
    ) -> tuple[str, ...]:
        if request.series_kind is SeriesKind.CONTRACT:
            assert request.contract is not None
            return (request.contract,) * len(bars)
        try:
            return _contracts_for_bars(bars, market.resolved_contract_segments)
        except MainForceMirrorV2Error:
            raise MainForceMirrorV2ResearchError(
                "MFM_V2_RESEARCH_IDENTITY_CONFLICT"
            ) from None


def _observations(
    product: str,
    points: tuple[MainForceMirrorV2Point, ...],
) -> tuple[_Observation, ...]:
    observations: list[_Observation] = []
    for index, point in enumerate(points):
        pressure_state = point.pressure_state
        instant_direction = _sign(point.instant_pressure)
        accumulated_direction = _sign(point.accumulated_pressure)
        if point.pressure_ready and pressure_state and instant_direction:
            observations.append(
                _Observation(
                    index,
                    product,
                    point.trading_day.year,
                    pressure_state,
                    "instant_pressure",
                    instant_direction,
                )
            )
        if point.accumulated_ready and pressure_state and accumulated_direction:
            observations.append(
                _Observation(
                    index,
                    product,
                    point.trading_day.year,
                    pressure_state,
                    "accumulated_pressure",
                    accumulated_direction,
                )
            )
            member = point.member
            relation = (
                "unavailable"
                if member is None or member.status != "ready"
                else member.relation_to_accumulated
            )
            cohort = {
                "aligned": "member_aligned",
                "divergent": "member_divergent",
                "neutral": "member_neutral",
                "unavailable": "member_unavailable",
            }.get(relation)
            if cohort is not None:
                observations.append(
                    _Observation(
                        index,
                        product,
                        point.trading_day.year,
                        pressure_state,
                        cohort,
                        accumulated_direction,
                    )
                )
            if (
                relation == "aligned"
                and member is not None
                and member.strength is not None
                and _raw_member_strength(member) >= Decimal("2.0")
            ):
                observations.append(
                    _Observation(
                        index,
                        product,
                        point.trading_day.year,
                        pressure_state,
                        "member_strong_aligned",
                        accumulated_direction,
                    )
                )
        caution_direction = _caution_direction(point)
        if caution_direction is None or point.caution is None:
            continue
        observations.append(
            _Observation(
                index,
                product,
                point.trading_day.year,
                point.caution,
                "all_caution",
                caution_direction,
            )
        )
        relation = (
            "unavailable"
            if point.member is None or point.member.status != "ready"
            else point.member.relation_to_caution
        )
        caution_cohort = {
            "aligned": "caution_member_aligned",
            "strong_aligned": "caution_member_strong_aligned",
            "divergent": "caution_member_divergent",
        }.get(relation)
        if caution_cohort is not None:
            observations.append(
                _Observation(
                    index,
                    product,
                    point.trading_day.year,
                    point.caution,
                    caution_cohort,
                    caution_direction,
                )
            )
    return tuple(observations)


def _sign(value: float | None) -> int | None:
    if value is None or value == 0:
        return None
    return 1 if value > 0 else -1


def _caution_direction(point: MainForceMirrorV2Point) -> int | None:
    if point.caution == "long_chase_caution":
        return 1
    if point.caution == "short_chase_caution":
        return -1
    return None


def _outcome(
    observation: _Observation,
    horizon: int,
    bars: tuple[CanonicalBar, ...],
    points: tuple[MainForceMirrorV2Point, ...],
) -> _Outcome | None:
    target_index = observation.index + horizon
    if target_index >= len(bars):
        return None
    source_contract = points[observation.index].physical_contract
    if source_contract is None or any(
        point.physical_contract != source_contract
        for point in points[observation.index : target_index + 1]
    ):
        return None
    source = bars[observation.index].close
    if source == 0:
        return None
    direction = Decimal(observation.direction)
    directional = ((bars[target_index].close - source) / source) * direction
    future = bars[observation.index + 1 : target_index + 1]
    metric_direction = (
        -observation.direction
        if _is_warning_cohort(observation.cohort)
        else observation.direction
    )
    if metric_direction > 0:
        mfe = max(Decimal(0), max((bar.high - source) / source for bar in future))
        mae = max(Decimal(0), max((source - bar.low) / source for bar in future))
    else:
        mfe = max(Decimal(0), max((source - bar.low) / source for bar in future))
        mae = max(Decimal(0), max((bar.high - source) / source for bar in future))
    return _Outcome(
        directional_return=directional,
        reversal_return=-directional,
        mfe=mfe,
        mae=mae,
    )


def _summary(
    observations: tuple[_Observation, ...],
    horizon: int,
    bars: tuple[CanonicalBar, ...],
    points: tuple[MainForceMirrorV2Point, ...],
) -> MainForceMirrorV2HorizonSummary:
    outcomes = tuple(
        outcome
        for observation in observations
        if (outcome := _outcome(observation, horizon, bars, points)) is not None
    )
    if not outcomes:
        return MainForceMirrorV2HorizonSummary(
            horizon,
            0,
            None,
            None,
            None,
            None,
            None,
        )
    return MainForceMirrorV2HorizonSummary(
        horizon_bars=horizon,
        sample_count=len(outcomes),
        median_directional_return=_rounded(
            _median(tuple(value.directional_return for value in outcomes))
        ),
        median_reversal_return=_rounded(
            _median(tuple(value.reversal_return for value in outcomes))
        ),
        hit_rate=_ratio(
            sum(
                (
                    value.reversal_return > 0
                    if _is_warning_cohort(observations[0].cohort)
                    else value.directional_return > 0
                )
                for value in outcomes
            ),
            len(outcomes),
        ),
        median_mfe=_rounded(_median(tuple(value.mfe for value in outcomes))),
        median_mae=_rounded(_median(tuple(value.mae for value in outcomes))),
    )


def _summarize_cohorts(
    observations: tuple[_Observation, ...],
    bars: tuple[CanonicalBar, ...],
    points: tuple[MainForceMirrorV2Point, ...],
) -> CohortMap:
    return MappingProxyType(
        {
            cohort: MappingProxyType(
                {
                    horizon: _summary(
                        tuple(item for item in observations if item.cohort == cohort),
                        horizon,
                        bars,
                        points,
                    )
                    for horizon in HORIZONS
                }
            )
            for cohort in COHORTS
        }
    )


def _yearly(
    observations: tuple[_Observation, ...],
    bars: tuple[CanonicalBar, ...],
    points: tuple[MainForceMirrorV2Point, ...],
) -> YearlyMap:
    grouped: dict[int, dict[str, dict[str, list[_Observation]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for item in observations:
        grouped[item.year][item.product][item.state].append(item)
    return MappingProxyType(
        {
            year: MappingProxyType(
                {
                    product: MappingProxyType(
                        {
                            state: _summarize_cohorts(tuple(items), bars, points)
                            for state, items in sorted(states.items())
                        }
                    )
                    for product, states in sorted(products.items())
                }
            )
            for year, products in sorted(grouped.items())
        }
    )


def _by_product(
    observations: tuple[_Observation, ...],
    bars: tuple[CanonicalBar, ...],
    points: tuple[MainForceMirrorV2Point, ...],
) -> ProductMap:
    grouped: dict[str, dict[str, list[_Observation]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in observations:
        grouped[item.product][item.state].append(item)
    return MappingProxyType(
        {
            product: MappingProxyType(
                {
                    state: _summarize_cohorts(tuple(items), bars, points)
                    for state, items in sorted(states.items())
                }
            )
            for product, states in sorted(grouped.items())
        }
    )


def _top_bottom_spreads(
    observations: tuple[_Observation, ...],
    bars: tuple[CanonicalBar, ...],
    points: tuple[MainForceMirrorV2Point, ...],
) -> Mapping[int, MainForceMirrorV2GroupSpread]:
    result: dict[int, MainForceMirrorV2GroupSpread] = {}
    for horizon in HORIZONS:
        available: list[tuple[str, Decimal, int]] = []
        for cohort in COHORTS:
            outcomes = tuple(
                outcome
                for observation in observations
                if observation.cohort == cohort
                and (
                    outcome := _outcome(observation, horizon, bars, points)
                )
                is not None
            )
            if outcomes:
                available.append(
                    (
                        cohort,
                        _median(
                            tuple(
                                value.directional_return for value in outcomes
                            )
                        ),
                        len(outcomes),
                    )
                )
        if not available:
            result[horizon] = MainForceMirrorV2GroupSpread(
                horizon, "", "", None, 0, 0
            )
            continue
        ordered = sorted(
            available,
            key=lambda item: (
                item[1],
                item[0],
            ),
        )
        bottom_group, bottom_median, bottom_count = ordered[0]
        top_group, top_median, top_count = ordered[-1]
        result[horizon] = MainForceMirrorV2GroupSpread(
            horizon_bars=horizon,
            top_group=top_group,
            bottom_group=bottom_group,
            directional_return_spread=_rounded(top_median - bottom_median),
            top_sample_count=top_count,
            bottom_sample_count=bottom_count,
        )
    return MappingProxyType(result)


def _sensitivity(
    product: str,
    bars: tuple[CanonicalBar, ...],
    points: tuple[MainForceMirrorV2Point, ...],
) -> Mapping[Decimal, MainForceMirrorV2SensitivitySummary]:
    result: dict[Decimal, MainForceMirrorV2SensitivitySummary] = {}
    for threshold in SENSITIVITY_THRESHOLDS:
        observations = tuple(
            _Observation(
                index,
                product,
                point.trading_day.year,
                point.caution or "",
                "caution_member_strong_aligned",
                direction,
            )
            for index, point in enumerate(points)
            if (direction := _caution_direction(point)) is not None
            and point.member is not None
            and point.member.status == "ready"
            and point.member.direction
            == ("long" if direction > 0 else "short")
            and point.member.strength is not None
            and _raw_member_strength(point.member) >= threshold
        )
        summaries = MappingProxyType(
            {
                horizon: _summary(observations, horizon, bars, points)
                for horizon in HORIZONS
            }
        )
        result[threshold] = MainForceMirrorV2SensitivitySummary(
            member_strength_threshold=threshold,
            by_product=MappingProxyType({product: summaries}),
            pooled=summaries,
        )
    return MappingProxyType(result)


def _median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def _raw_member_strength(member: object) -> Decimal:
    raw = getattr(member, "raw_strength", None)
    if isinstance(raw, Decimal):
        return raw
    return Decimal(str(getattr(member, "strength")))


def _page_request_identity(request: SeriesPageQuery) -> dict[str, object]:
    return {
        "series_kind": request.series_kind.value,
        "symbol": request.symbol,
        "contract": request.contract,
        "frequency": request.frequency.value,
        "before": request.before.isoformat() if request.before else None,
        "limit": request.limit,
    }


def _is_warning_cohort(cohort: str) -> bool:
    return cohort == "all_caution" or cohort.startswith("caution_member_")


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return _rounded(Decimal(numerator) / Decimal(denominator))


def _rounded(value: Decimal) -> Decimal:
    rounded = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return Decimal(0) if rounded == 0 else rounded.normalize()
