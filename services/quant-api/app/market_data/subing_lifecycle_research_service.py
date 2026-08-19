from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
    SubingLifecycleTrace,
    SubingLifecycleTransition,
    evaluate_subing_lifecycle,
)
from .subing_lifecycle_policy import SubingLifecyclePolicy
from .subing_research import (
    SubingDirection,
    SubingFactorResult,
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


@dataclass(frozen=True, slots=True)
class _SegmentSeries:
    bars: tuple[CanonicalBar, ...]
    factors: tuple[SubingFactorResult, ...]


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
        counts = {key: 0 for key in _FUNNEL_KEYS}
        confirmations = {key: 0 for key in _CONFIRMATION_KEYS}
        overlaps = {key: 0 for key in _OVERLAP_KEYS}
        lead_bars: list[int] = []
        trading_day_spans = {"SAME_DAY": 0, "CROSS_DAY": 0}
        risk_reasons: dict[str, int] = {}
        recovery_reasons: dict[str, int] = {}
        close_reasons: dict[str, int] = {}
        outcomes: dict[int, list[SubingOutcome]] = {
            horizon: [] for horizon in _HORIZONS
        }
        segment_count = 0

        for product in products:
            results = self._query_product(product, request)
            segments = results[BarFrequency.M5].resolved_contract_segments
            if not segments or (
                segments != results[BarFrequency.M15].resolved_contract_segments
            ):
                raise ValueError("rank1 segment identity is missing or inconsistent")
            requested = {
                frequency: tuple(
                    bar
                    for bar in results[frequency].bars
                    if request.since <= bar.trading_day <= request.through
                )
                for frequency in (BarFrequency.M5, BarFrequency.M15)
            }
            self._validate_segment_coverage(requested, segments)
            for segment in segments:
                series = {
                    frequency: self._segment_series(
                        requested[frequency],
                        segment=segment,
                        frequency=frequency,
                    )
                    for frequency in (BarFrequency.M5, BarFrequency.M15)
                }
                if not series[BarFrequency.M5].bars and not series[BarFrequency.M15].bars:
                    continue
                segment_count += 1
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
                self._aggregate_trace(
                    trace,
                    series[BarFrequency.M5],
                    counts=counts,
                    confirmations=confirmations,
                    overlaps=overlaps,
                    lead_bars=lead_bars,
                    trading_day_spans=trading_day_spans,
                    risk_reasons=risk_reasons,
                    recovery_reasons=recovery_reasons,
                    close_reasons=close_reasons,
                    outcomes=outcomes,
                )

        return SubingLifecycleResearchResult(
            products=products,
            segment_count=segment_count,
            evaluable_boundary_count=counts["DATA_READY"],
            funnel_counts=MappingProxyType(counts),
            confirmation_source_counts=MappingProxyType(confirmations),
            v1_v2_overlap_counts=MappingProxyType(overlaps),
            v2_to_v1_lead_bars=tuple(lead_bars),
            confirmed_trading_day_span_counts=MappingProxyType(trading_day_spans),
            risk_reason_counts=MappingProxyType(dict(sorted(risk_reasons.items()))),
            recovery_reason_counts=MappingProxyType(
                dict(sorted(recovery_reasons.items()))
            ),
            close_reason_counts=MappingProxyType(dict(sorted(close_reasons.items()))),
            horizon_summary=MappingProxyType(
                {
                    horizon: _evaluate_horizon(outcomes[horizon])
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
    ) -> dict[BarFrequency, MarketSeriesResult]:
        start, end = _research_window(request.since, request.through)
        return {
            frequency: self._market_data.query(
                SeriesQuery(
                    SeriesKind.ACTUAL_DOMINANT,
                    symbol,
                    frequency,
                    start,
                    end,
                )
            )
            for frequency in (BarFrequency.M5, BarFrequency.M15)
        }

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

    @staticmethod
    def _aggregate_trace(
        trace: SubingLifecycleTrace,
        series_5m: _SegmentSeries,
        *,
        counts: dict[str, int],
        confirmations: dict[str, int],
        overlaps: dict[str, int],
        lead_bars: list[int],
        trading_day_spans: dict[str, int],
        risk_reasons: dict[str, int],
        recovery_reasons: dict[str, int],
        close_reasons: dict[str, int],
        outcomes: dict[int, list[SubingOutcome]],
    ) -> None:
        transitions_by_time: dict[datetime, list[SubingLifecycleTransition]] = {}
        for transition in trace.transitions:
            transitions_by_time.setdefault(transition.transition_at, []).append(
                transition
            )
            if transition.to_stage is LifecycleStage.CLOSED:
                for reason in transition.reason_codes:
                    close_reasons[reason] = close_reasons.get(reason, 0) + 1
            elif transition.to_stage is LifecycleStage.EXIT_RISK:
                for reason in transition.reason_codes:
                    risk_reasons[reason] = risk_reasons.get(reason, 0) + 1
            elif (
                transition.from_stage is LifecycleStage.EXIT_RISK
                and transition.to_stage is LifecycleStage.CONTINUATION
            ):
                for reason in transition.reason_codes:
                    recovery_reasons[reason] = recovery_reasons.get(reason, 0) + 1

        bar_index = {bar.bar_end: index for index, bar in enumerate(series_5m.bars)}
        snapshots = trace.snapshots
        for snapshot_index, snapshot in enumerate(snapshots):
            if snapshot.availability is not LifecycleAvailability.READY:
                continue
            if snapshot.observed_at is None:
                raise ValueError("ready lifecycle boundary is missing observed_at")
            counts["DATA_READY"] += 1
            if snapshot.direction in {SubingDirection.LONG, SubingDirection.SHORT}:
                counts["DIRECTION_CONTEXT_ALIGNED"] += 1
            boundary_transitions = transitions_by_time.get(snapshot.observed_at, [])
            setup = any(
                transition.to_stage is LifecycleStage.SETUP_ARMED
                for transition in boundary_transitions
            )
            entry = any(
                transition.to_stage is LifecycleStage.ENTRY_CONFIRMED
                for transition in boundary_transitions
            )
            trigger = (
                snapshot.triggered_at == snapshot.observed_at
                or (entry and snapshot.formal_v1_matched)
            )
            counts["SETUP_ARMED"] += int(setup)
            counts["TRIGGER_OBSERVED"] += int(trigger)
            counts["ENTRY_CONFIRMED"] += int(entry)

            v1 = snapshot.formal_v1_matched
            if v1 and entry:
                overlaps["V1_AND_V2"] += 1
            elif entry:
                overlaps["V2_ONLY"] += 1
            elif v1:
                overlaps["V1_ONLY"] += 1

            if not entry:
                continue
            source = snapshot.confirmation_source
            if source is None:
                raise ValueError("entry confirmation source is missing")
            confirmations[source.name] += 1
            opportunity_key = snapshot.opportunity_key
            if opportunity_key is None:
                raise ValueError("entry confirmation opportunity is missing")
            related = tuple(
                later
                for later in snapshots[snapshot_index:]
                if later.opportunity_key == opportunity_key
            )
            trading_day_spans[
                "CROSS_DAY"
                if any(later.crossed_trading_day for later in related)
                else "SAME_DAY"
            ] += 1
            if source is not ConfirmationSource.FORMAL_V1:
                late_v1_index = next(
                    (
                        index
                        for index in range(snapshot_index + 1, len(snapshots))
                        if snapshots[index].opportunity_key == opportunity_key
                        and snapshots[index].formal_v1_matched
                    ),
                    None,
                )
                if late_v1_index is not None:
                    lead_bars.append(
                        sum(
                            later.availability is LifecycleAvailability.READY
                            for later in snapshots[
                                snapshot_index + 1 : late_v1_index + 1
                            ]
                        )
                    )
            observed_at = snapshot.observed_at
            if observed_at is None or observed_at not in bar_index:
                raise ValueError("entry confirmation boundary is not aligned")
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
                    outcomes[horizon].append(outcome)


def _research_window(since: date, through: date) -> tuple[datetime, datetime]:
    start = datetime.combine(since - timedelta(days=1), time.min, _SHANGHAI).astimezone(
        UTC
    )
    end = datetime.combine(through + timedelta(days=1), time.max, _SHANGHAI).astimezone(
        UTC
    )
    return start, end


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
