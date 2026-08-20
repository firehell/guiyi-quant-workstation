"""Read-only historical reducer for N Structure V1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median
from types import MappingProxyType
from typing import Protocol

from .actual_dominant_research import ActualDominantResearchSeries
from .domain import BarFrequency, CanonicalBar, ResolvedContractSegment
from .n_structure_pattern import (
    NDirection,
    evaluate_n_patterns,
)
from .n_structure_policy import NStructurePolicy
from .n_structure_state import evaluate_n_market_structure
from .n_structure_swing import reduce_n_swings
from .price_outcome import (
    PriceDirection,
    PriceDirectionalOutcome,
    PriceHorizonEvaluation,
    build_price_outcomes_at,
)


_HORIZONS = (3, 5, 8)


class _ResearchSegmentLoader(Protocol):
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries: ...


@dataclass(frozen=True, slots=True)
class NStructureResearchRequest:
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
class NStructureResearchResult:
    products: tuple[str, ...]
    segment_count: int
    evaluable_bar_count: int
    confirmed_pivot_count: int
    ambiguous_outside_reset_count: int
    incomplete_attempt_replaced_count: int
    completed_n_counts: Mapping[str, int]
    n_break_counts: Mapping[str, int]
    range_band_reentry_count: int
    structure_established_counts: Mapping[str, int]
    structure_break_counts: Mapping[str, int]
    horizon_summary: Mapping[int, PriceHorizonEvaluation]


@dataclass(slots=True)
class _Accumulator:
    segment_count: int = 0
    evaluable_bar_count: int = 0
    confirmed_pivot_count: int = 0
    ambiguous_outside_reset_count: int = 0
    incomplete_attempt_replaced_count: int = 0
    completed_n_counts: dict[str, int] = field(
        default_factory=lambda: {"up": 0, "down": 0}
    )
    n_break_counts: dict[str, int] = field(
        default_factory=lambda: {
            "n2_origin_broken": 0,
            "origin_broken": 0,
        }
    )
    range_band_reentry_count: int = 0
    structure_established_counts: dict[str, int] = field(
        default_factory=lambda: {"bull": 0, "bear": 0, "range": 0}
    )
    structure_break_counts: dict[str, int] = field(
        default_factory=lambda: {"bull": 0, "bear": 0}
    )
    outcomes: dict[int, list[PriceDirectionalOutcome]] = field(
        default_factory=lambda: {horizon: [] for horizon in _HORIZONS}
    )


class NStructureResearchService:
    """Run each true rank-1 segment once and aggregate requested-window facts."""

    def __init__(
        self,
        segment_loader: _ResearchSegmentLoader,
        *,
        products: Sequence[str],
        policy: NStructurePolicy,
    ) -> None:
        normalized = tuple(
            dict.fromkeys(product.strip().lower() for product in products)
        )
        if not normalized or any(
            not product or not product.isascii() or not product.isalpha()
            for product in normalized
        ):
            raise ValueError("products must contain ASCII product symbols")
        if (
            not isinstance(policy, NStructurePolicy)
            or policy.policy_id != "n_structure_5m_v1"
            or policy.formula_version != "n_structure_v1"
            or policy.research_only is not True
            or policy.source_timeframe is not BarFrequency.M5
        ):
            raise ValueError("N structure policy identity is invalid")
        self._segment_loader = segment_loader
        self._products = normalized
        self._policy = policy

    def run(self, request: NStructureResearchRequest) -> NStructureResearchResult:
        if not isinstance(request, NStructureResearchRequest):
            raise TypeError("request must be NStructureResearchRequest")
        products = self._selected_products(request.symbol)
        accumulator = _Accumulator()
        for product in products:
            loaded = self._segment_loader.load(
                symbol=product,
                frequencies=(BarFrequency.M5,),
                since=request.since,
                through=request.through,
            )
            result = loaded.results.get(BarFrequency.M5)
            if result is None:
                raise ValueError("5m research series is missing")
            for segment in loaded.segments:
                bars = tuple(
                    bar
                    for bar in result.bars
                    if segment.start_trading_day
                    <= bar.trading_day
                    <= min(segment.end_trading_day, request.through)
                )
                if not bars:
                    continue
                self._add_segment(
                    accumulator,
                    bars,
                    segment=segment,
                    since=request.since,
                    through=request.through,
                )
        return NStructureResearchResult(
            products=products,
            segment_count=accumulator.segment_count,
            evaluable_bar_count=accumulator.evaluable_bar_count,
            confirmed_pivot_count=accumulator.confirmed_pivot_count,
            ambiguous_outside_reset_count=(
                accumulator.ambiguous_outside_reset_count
            ),
            incomplete_attempt_replaced_count=(
                accumulator.incomplete_attempt_replaced_count
            ),
            completed_n_counts=MappingProxyType(accumulator.completed_n_counts),
            n_break_counts=MappingProxyType(accumulator.n_break_counts),
            range_band_reentry_count=accumulator.range_band_reentry_count,
            structure_established_counts=MappingProxyType(
                accumulator.structure_established_counts
            ),
            structure_break_counts=MappingProxyType(
                accumulator.structure_break_counts
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

    def _add_segment(
        self,
        accumulator: _Accumulator,
        bars: tuple[CanonicalBar, ...],
        *,
        segment: ResolvedContractSegment,
        since: date,
        through: date,
    ) -> None:
        swings = reduce_n_swings(
            bars,
            source_timeframe=BarFrequency.M5,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
            segment_end_trading_day=segment.end_trading_day,
        )
        patterns = evaluate_n_patterns(bars, swings, policy=self._policy)
        structures = evaluate_n_market_structure(
            bars,
            swings=swings,
            patterns=patterns,
            policy=self._policy,
        )
        days_by_time = {bar.bar_end: bar.trading_day for bar in bars}
        requested = lambda timestamp: _in_requested_window(  # noqa: E731
            timestamp,
            days_by_time=days_by_time,
            since=since,
            through=through,
        )
        accumulator.segment_count += 1
        accumulator.evaluable_bar_count += sum(
            since <= bar.trading_day <= through for bar in bars
        )
        accumulator.confirmed_pivot_count += sum(
            requested(pivot.confirmed_at) for pivot in swings.pivots
        )
        accumulator.ambiguous_outside_reset_count += sum(
            requested(reset_at) for reset_at in swings.ambiguous_outside_reset_at
        )
        accumulator.incomplete_attempt_replaced_count += (
            patterns.incomplete_attempt_replaced_count
            - _prefix_replacement_count(
                bars,
                segment=segment,
                since=since,
                policy=self._policy,
            )
        )

        for pattern in patterns.patterns:
            if not requested(pattern.completed_at):
                continue
            accumulator.completed_n_counts[pattern.direction.value] += 1
            index = _bar_index(bars, pattern.completed_at)
            if bars[index].close != pattern.completion_bar_close:
                raise ValueError("N completion entry is not aligned with its bar")
            direction = (
                PriceDirection.LONG
                if pattern.direction is NDirection.UP
                else PriceDirection.SHORT
            )
            outcomes = build_price_outcomes_at(
                bars,
                index=index,
                direction=direction,
                horizons=_HORIZONS,
                same_trading_day_only=False,
            )
            for horizon, outcome in outcomes.items():
                if outcome is not None:
                    accumulator.outcomes[horizon].append(outcome)

        for event in patterns.break_events:
            if requested(event.observed_at):
                accumulator.n_break_counts[event.kind.value] += 1
        accumulator.range_band_reentry_count += sum(
            requested(event.observed_at)
            for event in patterns.range_band_reentries
        )
        for transition in structures.transitions:
            if not requested(transition.transition_at):
                continue
            reason = transition.reason_code
            if reason == "BULL_STRUCTURE_ESTABLISHED":
                accumulator.structure_established_counts["bull"] += 1
            elif reason == "BEAR_STRUCTURE_ESTABLISHED":
                accumulator.structure_established_counts["bear"] += 1
            elif reason == "RANGE_STRUCTURE_ESTABLISHED":
                accumulator.structure_established_counts["range"] += 1
            elif reason == "BULL_STRUCTURE_BROKEN":
                accumulator.structure_break_counts["bull"] += 1
            elif reason == "BEAR_STRUCTURE_BROKEN":
                accumulator.structure_break_counts["bear"] += 1


def _prefix_replacement_count(
    bars: tuple[CanonicalBar, ...],
    *,
    segment: ResolvedContractSegment,
    since: date,
    policy: NStructurePolicy,
) -> int:
    prefix = tuple(bar for bar in bars if bar.trading_day < since)
    if not prefix:
        return 0
    swings = reduce_n_swings(
        prefix,
        source_timeframe=BarFrequency.M5,
        contract=segment.contract,
        segment_start_trading_day=segment.start_trading_day,
        segment_end_trading_day=segment.end_trading_day,
    )
    return evaluate_n_patterns(
        prefix,
        swings,
        policy=policy,
    ).incomplete_attempt_replaced_count


def _in_requested_window(
    timestamp: datetime,
    *,
    days_by_time: Mapping[datetime, date],
    since: date,
    through: date,
) -> bool:
    trading_day = days_by_time.get(timestamp)
    if trading_day is None:
        raise ValueError("N fact is not aligned with its source bar")
    return since <= trading_day <= through


def _bar_index(bars: Sequence[CanonicalBar], bar_end: datetime) -> int:
    for index, bar in enumerate(bars):
        if bar.bar_end == bar_end:
            return index
    raise ValueError("N completion is not aligned with its source bar")


def _evaluate_horizon(
    outcomes: Sequence[PriceDirectionalOutcome],
) -> PriceHorizonEvaluation:
    if not outcomes:
        return PriceHorizonEvaluation(0, None, None, None)
    return PriceHorizonEvaluation(
        sample_count=len(outcomes),
        median_directional_return_bps=median(
            outcome.directional_return_bps for outcome in outcomes
        ),
        median_mfe_bps=median(outcome.mfe_bps for outcome in outcomes),
        median_mae_bps=median(outcome.mae_bps for outcome in outcomes),
    )
