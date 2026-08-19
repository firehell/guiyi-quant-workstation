from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from statistics import median
from types import MappingProxyType
from typing import Protocol
from zoneinfo import ZoneInfo

from .domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesQuery,
)
from .market_data_service import DominantContractSegmentSummary
from .subing_calibration import (
    DirectionalSide,
    HorizonEvaluation,
    SubingCalibration,
    SubingOutcome,
    build_outcomes_at,
)
from .subing_lifecycle import (
    ConfirmationSource,
    LifecycleAvailability,
    LifecycleStage,
    SubingLifecycleSnapshot,
    SubingLifecycleTrace,
    SubingLifecycleTransition,
    evaluate_subing_direction_context,
    evaluate_subing_lifecycle,
)
from .subing_lifecycle_policy import SubingLifecyclePolicy
from .subing_research import (
    SubingDirection,
    SubingFactorResult,
    SubingFactorSnapshot,
    calculate_subing_factor_series,
)


_SHANGHAI = ZoneInfo("Asia/Shanghai")
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


class _MarketDataReader(Protocol):
    def query(self, request: SeriesQuery) -> MarketSeriesResult: ...

    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> DominantContractSegmentSummary: ...


@dataclass(frozen=True, slots=True)
class _SegmentSeries:
    bars: tuple[CanonicalBar, ...]
    factors: tuple[SubingFactorResult, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedProductSeries:
    results: Mapping[BarFrequency, MarketSeriesResult]
    segments: tuple[ResolvedContractSegment, ...]


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

    def add_trace(
        self,
        trace: SubingLifecycleTrace,
        series_5m: _SegmentSeries,
        series_15m: _SegmentSeries,
        *,
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
            entry = any(
                transition.to_stage is LifecycleStage.ENTRY_CONFIRMED
                for transition in boundary_transitions
            )
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
        market_data: _MarketDataReader,
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
        self._market_data = market_data
        self._products = normalized
        self._calibration = calibration
        self._policy = policy

    def run(
        self,
        request: LifecycleResearchRequest,
    ) -> SubingLifecycleResearchResult:
        if not isinstance(request, LifecycleResearchRequest):
            raise TypeError("request must be LifecycleResearchRequest")
        products = self._selected_products(request.symbol)
        accumulator = _ResearchAccumulator()

        for product in products:
            resolved = self._query_product(product, request)
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
            self._validate_segment_coverage(computation_bars, segments)
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
                    calibration=self._calibration,
                    since=request.since,
                    through=request.through,
                )

        return SubingLifecycleResearchResult(
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

    def _selected_products(self, symbol: str | None) -> tuple[str, ...]:
        if symbol is None:
            return self._products
        if symbol not in self._products:
            raise ValueError("symbol is outside the active product scope")
        return (symbol,)

    def _query_product(
        self,
        symbol: str,
        request: LifecycleResearchRequest,
    ) -> _ResolvedProductSeries:
        probe_start, end = _research_window(request.since, request.through)
        probe = {
            frequency: self._market_data.query(
                SeriesQuery(
                    SeriesKind.ACTUAL_DOMINANT,
                    symbol,
                    frequency,
                    probe_start,
                    end,
                )
            )
            for frequency in (BarFrequency.M5, BarFrequency.M15)
        }
        probe_segments = {
            frequency: self._restore_true_segments(
                symbol,
                probe[frequency],
                since=request.since,
                through=request.through,
            )
            for frequency in (BarFrequency.M5, BarFrequency.M15)
        }
        segments = probe_segments[BarFrequency.M5]
        if not segments or segments != probe_segments[BarFrequency.M15]:
            raise ValueError("rank1 segment identity is missing or inconsistent")

        full_start, _ = _research_window(segments[0].start_trading_day, request.through)
        full = {
            frequency: self._market_data.query(
                SeriesQuery(
                    SeriesKind.ACTUAL_DOMINANT,
                    symbol,
                    frequency,
                    full_start,
                    end,
                )
            )
            for frequency in (BarFrequency.M5, BarFrequency.M15)
        }
        full_segments = {
            frequency: self._restore_true_segments(
                symbol,
                full[frequency],
                since=segments[0].start_trading_day,
                through=request.through,
            )
            for frequency in (BarFrequency.M5, BarFrequency.M15)
        }
        if (
            full_segments[BarFrequency.M5] != segments
            or full_segments[BarFrequency.M15] != segments
        ):
            raise ValueError("rank1 probe/full segment identity is inconsistent")
        return _ResolvedProductSeries(MappingProxyType(full), segments)

    def _restore_true_segments(
        self,
        symbol: str,
        result: MarketSeriesResult,
        *,
        since: date,
        through: date,
    ) -> tuple[ResolvedContractSegment, ...]:
        bars = tuple(
            bar for bar in result.bars if since <= bar.trading_day <= through
        )
        raw_segments = result.resolved_contract_segments
        if not bars or not raw_segments:
            raise ValueError("rank1 segment identity is missing or inconsistent")
        self._validate_segment_coverage(
            {BarFrequency.M5: bars},
            raw_segments,
        )

        restored: list[ResolvedContractSegment] = []
        for raw_segment in raw_segments:
            segment_days = tuple(
                bar.trading_day
                for bar in bars
                if raw_segment.start_trading_day
                <= bar.trading_day
                <= raw_segment.end_trading_day
            )
            if not segment_days:
                continue
            representative = segment_days[0]
            summary = self._market_data.dominant_segment_for_day(
                symbol,
                representative,
            )
            if (
                summary.symbol != symbol
                or summary.contract != raw_segment.contract
                or any(
                    not (
                        summary.start_trading_day
                        <= segment_day
                        <= summary.end_trading_day
                    )
                    for segment_day in segment_days
                )
                or not (
                    summary.start_trading_day
                    <= representative
                    <= summary.end_trading_day
                )
            ):
                raise ValueError(
                    "rank1 segment identity conflicts with containing summary"
                )
            segment = ResolvedContractSegment(
                summary.contract,
                summary.start_trading_day,
                summary.end_trading_day,
            )
            if restored and segment == restored[-1]:
                continue
            if restored and segment.start_trading_day <= restored[-1].end_trading_day:
                raise ValueError("rank1 segment summaries overlap")
            restored.append(segment)
        if not restored:
            raise ValueError("rank1 segment identity is missing or inconsistent")
        self._validate_segment_coverage(
            {BarFrequency.M5: bars},
            tuple(restored),
        )
        return tuple(restored)

    @staticmethod
    def _validate_segment_coverage(
        requested: Mapping[BarFrequency, tuple[CanonicalBar, ...]],
        segments: tuple[ResolvedContractSegment, ...],
    ) -> None:
        for frequency, bars in requested.items():
            covered: set[tuple[datetime, date]] = set()
            for segment in segments:
                for bar in bars:
                    if segment.start_trading_day <= bar.trading_day <= segment.end_trading_day:
                        identity = (bar.bar_end, bar.trading_day)
                        if identity in covered:
                            raise ValueError("rank1 segments overlap")
                        covered.add(identity)
            if len(covered) != len(bars):
                raise ValueError(
                    f"rank1 segment identity is incomplete for {frequency.value}"
                )

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

def _research_window(since: date, through: date) -> tuple[datetime, datetime]:
    start = datetime.combine(since - timedelta(days=1), time.min, _SHANGHAI).astimezone(
        UTC
    )
    end = datetime.combine(through + timedelta(days=1), time.max, _SHANGHAI).astimezone(
        UTC
    )
    return start, end


def _ready_factor_snapshots(
    series: _SegmentSeries,
) -> dict[datetime, SubingFactorSnapshot]:
    snapshots: dict[datetime, SubingFactorSnapshot] = {}
    for result in series.factors:
        snapshot = result.snapshot
        if snapshot is not None:
            snapshots[snapshot.bar_end] = snapshot
    return snapshots


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
