from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from statistics import median
from types import MappingProxyType

from app.market_data.actual_dominant_research import (
    ActualDominantResearchReader,
    ActualDominantResearchSegmentLoader,
    ActualDominantResearchSegmentIdentityError,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    ResolvedContractSegment,
    normalize_contract_for_symbol,
)
from app.market_data.subing_calibration import (
    DirectionalSide,
    HorizonEvaluation,
    SubingCalibration,
    SubingOutcome,
    build_outcomes_at,
)
from app.market_data.subing_lifecycle import (
    ConfirmationSource,
    LifecycleAvailability,
    LifecycleStage,
    SubingLifecycleSnapshot,
    SubingLifecycleTrace,
    SubingLifecycleTransition,
    SubingOpportunityKey,
    evaluate_subing_direction_context,
    evaluate_subing_lifecycle,
)
from app.market_data.subing_lifecycle_policy import SubingLifecyclePolicy
from app.market_data.subing_research import (
    SubingDirection,
    SubingFactorResult,
    SubingFactorSnapshot,
    calculate_subing_factor_series,
)


_HORIZONS = (3, 5, 8)
_FUNNEL_KEYS = (
    "DATA_READY",
    "DIRECTION_CONTEXT_ALIGNED",
    "SETUP_ARMED",
    "TRIGGER_OBSERVED",
    "ENTRY_CONFIRMED",
)
_FUNNEL_COUNT_UNITS = MappingProxyType(
    {
        "DATA_READY": "boundary_occupancy",
        "DIRECTION_CONTEXT_ALIGNED": "boundary_occupancy",
        "SETUP_ARMED": "boundary_event",
        "TRIGGER_OBSERVED": "boundary_event",
        "ENTRY_CONFIRMED": "boundary_event",
    }
)
_CONFIRMATION_KEYS = tuple(source.name for source in ConfirmationSource)
_OVERLAP_KEYS = ("V1_AND_V2", "V2_ONLY", "V1_ONLY")
_POLICY_ID = "subing_lifecycle_v2_research_v1"
_CANDIDATE_PROJECTION_FORMULA_VERSION = "subing_lifecycle_v2"


@dataclass(frozen=True, slots=True)
class LifecycleResearchRequest:
    since: date
    through: date
    symbol: str | None

    def __post_init__(self) -> None:
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise ValueError("since must not be later than through")
        symbol = self.symbol
        if symbol is not None:
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("symbol must be non-empty")
            symbol = symbol.strip().lower()
            if not symbol.isascii() or not symbol.isalpha():
                raise ValueError("symbol must contain ASCII letters only")
        object.__setattr__(self, "symbol", symbol)


@dataclass(frozen=True, slots=True)
class SubingLifecycleResearchResult:
    products: tuple[str, ...]
    segment_count: int
    evaluable_boundary_count: int
    funnel_counts: Mapping[str, int]
    funnel_count_units: Mapping[str, str]
    confirmation_source_counts: Mapping[str, int]
    v1_v2_overlap_counts: Mapping[str, int]
    v2_to_v1_lead_bars: tuple[int, ...]
    confirmed_trading_day_span_counts: Mapping[str, int]
    risk_reason_counts: Mapping[str, int]
    recovery_reason_counts: Mapping[str, int]
    close_reason_counts: Mapping[str, int]
    horizon_summary: Mapping[int, HorizonEvaluation]


@dataclass(frozen=True, slots=True)
class SubingLifecycleEntryResearchEvent:
    event_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    observed_at: datetime
    trading_day: date
    segment_bar_index: int
    direction: SubingDirection
    opportunity_key: SubingOpportunityKey
    confirmation_source: ConfirmationSource

    def __post_init__(self) -> None:
        if (
            not isinstance(self.event_id, str)
            or not self.event_id
            or not _valid_symbol(self.symbol)
            or normalize_contract_for_symbol(self.symbol, self.contract)
            != self.contract
            or type(self.segment_start_trading_day) is not date
            or not _aware_datetime(self.observed_at)
            or type(self.trading_day) is not date
            or self.trading_day < self.segment_start_trading_day
            or type(self.segment_bar_index) is not int
            or self.segment_bar_index < 0
            or self.direction not in {SubingDirection.LONG, SubingDirection.SHORT}
            or not isinstance(self.opportunity_key, SubingOpportunityKey)
            or self.opportunity_key.symbol.lower() != self.symbol
            or self.opportunity_key.contract != self.contract
            or self.opportunity_key.segment_start_trading_day
            != self.segment_start_trading_day
            or self.opportunity_key.direction is not self.direction
            or not isinstance(self.confirmation_source, ConfirmationSource)
        ):
            raise ValueError("MULTI_CANDIDATE_EVENT_INVALID")


@dataclass(frozen=True, slots=True)
class _SegmentSeries:
    bars: tuple[CanonicalBar, ...]
    factors: tuple[SubingFactorResult, ...]


@dataclass(frozen=True, slots=True)
class _SubingResearchProjection:
    result: SubingLifecycleResearchResult
    entry_events: tuple[SubingLifecycleEntryResearchEvent, ...]


@dataclass(slots=True)
class _ResearchAccumulator:
    funnel_counts: dict[str, int] = field(
        default_factory=lambda: {key: 0 for key in _FUNNEL_KEYS}
    )
    confirmation_source_counts: dict[str, int] = field(
        default_factory=lambda: {key: 0 for key in _CONFIRMATION_KEYS}
    )
    overlap_counts: dict[str, int] = field(
        default_factory=lambda: {key: 0 for key in _OVERLAP_KEYS}
    )
    lead_bars: list[int] = field(default_factory=list)
    trading_day_span_counts: dict[str, int] = field(
        default_factory=lambda: {"SAME_DAY": 0, "CROSS_DAY": 0}
    )
    risk_reason_counts: dict[str, int] = field(default_factory=dict)
    recovery_reason_counts: dict[str, int] = field(default_factory=dict)
    close_reason_counts: dict[str, int] = field(default_factory=dict)
    outcomes: dict[int, list[SubingOutcome]] = field(
        default_factory=lambda: {horizon: [] for horizon in _HORIZONS}
    )
    segment_count: int = 0
    entry_events: list[SubingLifecycleEntryResearchEvent] = field(default_factory=list)

    def add_trace(
        self,
        trace: SubingLifecycleTrace,
        series_5m: _SegmentSeries,
        series_15m: _SegmentSeries,
        *,
        symbol: str,
        segment: ResolvedContractSegment,
        calibration: SubingCalibration,
        since: date,
        through: date,
    ) -> None:
        self.segment_count += 1
        if not trace.snapshots:
            return
        bars_by_time = {bar.bar_end: bar for bar in series_5m.bars}
        factors_5m = _ready_factor_snapshots(series_5m)
        factors_15m = _ready_factor_snapshots(series_15m)
        transitions_by_time: dict[datetime, list[SubingLifecycleTransition]] = {}
        for transition in trace.transitions:
            transitions_by_time.setdefault(transition.transition_at, []).append(
                transition
            )
            bar = bars_by_time.get(transition.transition_at)
            if bar is None or not since <= bar.trading_day <= through:
                continue
            if transition.to_stage is LifecycleStage.CLOSED:
                _increment_reasons(self.close_reason_counts, transition)
            elif transition.to_stage is LifecycleStage.EXIT_RISK:
                _increment_reasons(self.risk_reason_counts, transition)
            elif (
                transition.from_stage is LifecycleStage.EXIT_RISK
                and transition.to_stage is LifecycleStage.CONTINUATION
            ):
                _increment_reasons(self.recovery_reason_counts, transition)

        bar_index = {bar.bar_end: index for index, bar in enumerate(series_5m.bars)}
        snapshots = trace.snapshots
        for snapshot_index, snapshot in enumerate(snapshots):
            if snapshot.availability is not LifecycleAvailability.READY:
                continue
            observed_at = snapshot.observed_at
            if observed_at is None:
                raise ValueError("ready lifecycle boundary is missing observed_at")
            observed_bar = bars_by_time.get(observed_at)
            if observed_bar is None:
                raise ValueError("ready lifecycle boundary is not 5m aligned")
            if not since <= observed_bar.trading_day <= through:
                continue

            self.funnel_counts["DATA_READY"] += 1
            factor_5m = factors_5m.get(observed_at)
            anchor_bar_end = snapshot.anchor_bar_end
            if anchor_bar_end is None:
                raise ValueError("ready lifecycle boundary is missing anchor_bar_end")
            factor_15m = factors_15m.get(anchor_bar_end)
            if factor_5m is None or factor_15m is None:
                raise ValueError("ready lifecycle boundary is missing factor context")
            current_direction = evaluate_subing_direction_context(
                factor_5m,
                factor_15m,
                calibration,
            )
            if current_direction in {SubingDirection.LONG, SubingDirection.SHORT}:
                self.funnel_counts["DIRECTION_CONTEXT_ALIGNED"] += 1

            boundary_transitions = transitions_by_time.get(observed_at, [])
            setup = any(
                transition.to_stage is LifecycleStage.SETUP_ARMED
                for transition in boundary_transitions
            )
            entry_transitions = tuple(
                transition
                for transition in boundary_transitions
                if transition.to_stage is LifecycleStage.ENTRY_CONFIRMED
            )
            if len(entry_transitions) > 1:
                raise ValueError("multiple entry transitions on one lifecycle boundary")
            entry = bool(entry_transitions)
            direct_formal_trigger = (
                entry
                and snapshot.formal_v1_matched
                and snapshot.triggered_at is None
            )
            trigger = snapshot.triggered_at == observed_at or direct_formal_trigger
            self.funnel_counts["SETUP_ARMED"] += int(setup)
            self.funnel_counts["TRIGGER_OBSERVED"] += int(trigger)
            self.funnel_counts["ENTRY_CONFIRMED"] += int(entry)

            v1 = snapshot.formal_v1_matched
            if v1 and entry:
                self.overlap_counts["V1_AND_V2"] += 1
            elif entry:
                self.overlap_counts["V2_ONLY"] += 1
            elif v1:
                self.overlap_counts["V1_ONLY"] += 1

            if not entry:
                continue
            source = snapshot.confirmation_source
            if source is None:
                raise ValueError("entry confirmation source is missing")
            self.confirmation_source_counts[source.name] += 1
            opportunity_key = snapshot.opportunity_key
            if opportunity_key is None:
                raise ValueError("entry confirmation opportunity is missing")
            transition = entry_transitions[0]
            transition_key = transition.opportunity_key
            if (
                transition_key.contract != segment.contract
                or transition_key.segment_start_trading_day
                != segment.start_trading_day
            ):
                raise ValueError("entry transition segment identity is invalid")
            self.entry_events.append(
                SubingLifecycleEntryResearchEvent(
                    event_id=transition.transition_id,
                    symbol=symbol,
                    contract=transition_key.contract,
                    segment_start_trading_day=(
                        transition_key.segment_start_trading_day
                    ),
                    observed_at=transition.transition_at,
                    trading_day=observed_bar.trading_day,
                    segment_bar_index=bar_index[observed_at],
                    direction=transition_key.direction,
                    opportunity_key=transition_key,
                    confirmation_source=source,
                )
            )
            related = tuple(
                later
                for later in snapshots[snapshot_index:]
                if later.opportunity_key == opportunity_key
            )
            self.trading_day_span_counts[
                "CROSS_DAY"
                if any(later.crossed_trading_day for later in related)
                else "SAME_DAY"
            ] += 1
            if source is not ConfirmationSource.FORMAL_V1:
                late_v1_index = _first_later_same_direction_formal(
                    snapshots,
                    transitions_by_time,
                    after_index=snapshot_index,
                    opportunity_key=opportunity_key,
                )
                if late_v1_index is not None:
                    self.lead_bars.append(
                        sum(
                            later.availability is LifecycleAvailability.READY
                            for later in snapshots[
                                snapshot_index + 1 : late_v1_index + 1
                            ]
                        )
                    )
            direction = DirectionalSide(snapshot.direction.value)
            evaluated = build_outcomes_at(
                series_5m.factors,
                series_5m.bars,
                index=bar_index[observed_at],
                direction=direction,
                horizons=_HORIZONS,
            )
            for horizon, outcome in evaluated.items():
                if outcome is not None:
                    self.outcomes[horizon].append(outcome)


class SubingLifecycleResearchService:
    """Recompute segment-local lifecycle research from Historical Canonical only."""

    def __init__(
        self,
        market_data: ActualDominantResearchReader,
        *,
        products: Sequence[str],
        calibration: SubingCalibration,
        policy: SubingLifecyclePolicy,
    ) -> None:
        normalized = tuple(
            dict.fromkeys(product.strip().lower() for product in products)
        )
        if not normalized or any(
            not product or not product.isascii() or not product.isalpha()
            for product in normalized
        ):
            raise ValueError("products must contain ASCII product symbols")
        if getattr(policy, "policy_id", None) != _POLICY_ID:
            raise ValueError("lifecycle policy identity is invalid")
        self._segment_loader = ActualDominantResearchSegmentLoader(market_data)
        self._products = normalized
        self._calibration = calibration
        self._policy = policy

    @property
    def candidate_projection_formula_version(self) -> str:
        """Identity of the unchanged facts consumed by Candidate research."""
        return _CANDIDATE_PROJECTION_FORMULA_VERSION

    def run(
        self,
        request: LifecycleResearchRequest,
    ) -> SubingLifecycleResearchResult:
        return self._project(request).result

    def entry_events(
        self,
        request: LifecycleResearchRequest,
    ) -> tuple[SubingLifecycleEntryResearchEvent, ...]:
        return self._project(request).entry_events

    def _project(
        self,
        request: LifecycleResearchRequest,
    ) -> _SubingResearchProjection:
        if not isinstance(request, LifecycleResearchRequest):
            raise TypeError("request must be LifecycleResearchRequest")
        products = self._selected_products(request.symbol)
        accumulator = _ResearchAccumulator()

        for product in products:
            try:
                resolved = self._segment_loader.load(
                    symbol=product,
                    frequencies=(BarFrequency.M5, BarFrequency.M15),
                    since=request.since,
                    through=request.through,
                )
            except ActualDominantResearchSegmentIdentityError as exc:
                if str(exc) == "rank1 segment identity is incomplete for 15m":
                    raise ActualDominantResearchSegmentIdentityError(
                        "rank1 segment identity is incomplete for 5m"
                    ) from None
                raise
            segments = resolved.segments
            computation_bars = {
                frequency: tuple(
                    bar
                    for bar in resolved.results[frequency].bars
                    if segments[0].start_trading_day
                    <= bar.trading_day
                    <= request.through
                )
                for frequency in (BarFrequency.M5, BarFrequency.M15)
            }
            for segment in segments:
                series = {
                    frequency: self._segment_series(
                        computation_bars[frequency],
                        segment=segment,
                        frequency=frequency,
                    )
                    for frequency in (BarFrequency.M5, BarFrequency.M15)
                }
                if not series[BarFrequency.M5].bars and not series[BarFrequency.M15].bars:
                    continue
                trace = evaluate_subing_lifecycle(
                    symbol=product,
                    contract=segment.contract,
                    segment_start_trading_day=segment.start_trading_day,
                    bars_5m=series[BarFrequency.M5].bars,
                    factors_5m=series[BarFrequency.M5].factors,
                    bars_15m=series[BarFrequency.M15].bars,
                    factors_15m=series[BarFrequency.M15].factors,
                    calibration=self._calibration,
                    policy=self._policy,
                )
                accumulator.add_trace(
                    trace,
                    series[BarFrequency.M5],
                    series[BarFrequency.M15],
                    symbol=product,
                    segment=segment,
                    calibration=self._calibration,
                    since=request.since,
                    through=request.through,
                )

        result = SubingLifecycleResearchResult(
            products=products,
            segment_count=accumulator.segment_count,
            evaluable_boundary_count=accumulator.funnel_counts["DATA_READY"],
            funnel_counts=MappingProxyType(accumulator.funnel_counts),
            funnel_count_units=_FUNNEL_COUNT_UNITS,
            confirmation_source_counts=MappingProxyType(
                accumulator.confirmation_source_counts
            ),
            v1_v2_overlap_counts=MappingProxyType(accumulator.overlap_counts),
            v2_to_v1_lead_bars=tuple(accumulator.lead_bars),
            confirmed_trading_day_span_counts=MappingProxyType(
                accumulator.trading_day_span_counts
            ),
            risk_reason_counts=MappingProxyType(
                dict(sorted(accumulator.risk_reason_counts.items()))
            ),
            recovery_reason_counts=MappingProxyType(
                dict(sorted(accumulator.recovery_reason_counts.items()))
            ),
            close_reason_counts=MappingProxyType(
                dict(sorted(accumulator.close_reason_counts.items()))
            ),
            horizon_summary=MappingProxyType(
                {
                    horizon: _evaluate_horizon(accumulator.outcomes[horizon])
                    for horizon in _HORIZONS
                }
            ),
        )
        return _SubingResearchProjection(result, tuple(accumulator.entry_events))

    def _selected_products(self, symbol: str | None) -> tuple[str, ...]:
        if symbol is None:
            return self._products
        if symbol not in self._products:
            raise ValueError("symbol is outside the active product scope")
        return (symbol,)

    def _segment_series(
        self,
        bars: tuple[CanonicalBar, ...],
        *,
        segment: ResolvedContractSegment,
        frequency: BarFrequency,
    ) -> _SegmentSeries:
        segment_bars = tuple(
            bar
            for bar in bars
            if segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
        )
        factors = calculate_subing_factor_series(
            segment_bars,
            timeframe=frequency,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
            latest_bar_source="canonical",
        )
        return _SegmentSeries(segment_bars, factors)

def _ready_factor_snapshots(
    series: _SegmentSeries,
) -> dict[datetime, SubingFactorSnapshot]:
    snapshots: dict[datetime, SubingFactorSnapshot] = {}
    for result in series.factors:
        snapshot = result.snapshot
        if snapshot is not None:
            snapshots[snapshot.bar_end] = snapshot
    return snapshots


def _valid_symbol(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.isascii()
        and value.isalpha()
        and value == value.lower()
    )


def _aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _increment_reasons(
    counts: dict[str, int],
    transition: SubingLifecycleTransition,
) -> None:
    for reason in transition.reason_codes:
        counts[reason] = counts.get(reason, 0) + 1


def _is_opposite_formal_close(
    transitions: Sequence[SubingLifecycleTransition],
) -> bool:
    return any(
        transition.to_stage is LifecycleStage.CLOSED
        and "OPPOSITE_FORMAL_V1" in transition.reason_codes
        for transition in transitions
    )


def _first_later_same_direction_formal(
    snapshots: Sequence[SubingLifecycleSnapshot],
    transitions_by_time: Mapping[datetime, Sequence[SubingLifecycleTransition]],
    *,
    after_index: int,
    opportunity_key: object,
) -> int | None:
    for index in range(after_index + 1, len(snapshots)):
        candidate = snapshots[index]
        candidate_time = candidate.observed_at
        if candidate_time is None:
            continue
        transitions = transitions_by_time.get(candidate_time, ())
        if _is_opposite_formal_close(transitions) or any(
            transition.to_stage is LifecycleStage.CLOSED
            for transition in transitions
        ):
            return None
        if (
            candidate.opportunity_key == opportunity_key
            and candidate.formal_v1_matched
        ):
            return index
    return None


def _evaluate_horizon(outcomes: Sequence[SubingOutcome]) -> HorizonEvaluation:
    if not outcomes:
        return HorizonEvaluation(0, 0, None, None, None, None)
    ema21_labels = tuple(
        outcome.ema21_failure
        for outcome in outcomes
        if outcome.ema21_failure is not None
    )
    return HorizonEvaluation(
        sample_count=len(outcomes),
        ema21_sample_count=len(ema21_labels),
        median_directional_return_bps=median(
            outcome.directional_return_bps for outcome in outcomes
        ),
        median_mfe_bps=median(outcome.mfe_bps for outcome in outcomes),
        median_mae_bps=median(outcome.mae_bps for outcome in outcomes),
        ema21_failure_rate=(
            None
            if not ema21_labels
            else Decimal(sum(ema21_labels)) / Decimal(len(ema21_labels))
        ),
    )
