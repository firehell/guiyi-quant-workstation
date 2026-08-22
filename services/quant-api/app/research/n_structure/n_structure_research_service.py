"""Read-only historical reducer for N Structure V1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType
from typing import Protocol

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    ResolvedContractSegment,
    normalize_contract_for_symbol,
)
from app.market_data.market_data_service import MarketDataError
from app.research.n_structure.n_structure_pattern import NDirection
from app.research.n_structure.n_structure_policy import NStructurePolicy, is_exact_n_structure_policy
from app.research.n_structure.n_structure_segment import evaluate_n_structure_segment
from app.research.n_structure.n_structure_state import NStructureTransitionReason
from app.market_data.price_outcome import (
    PriceDirection,
    PriceDirectionalOutcome,
    PriceHorizonEvaluation,
    build_price_outcomes_at,
    summarize_price_outcomes,
)


_HORIZONS = (3, 5, 8)


class NStructureSourceUnavailableError(RuntimeError):
    code = "N_STRUCTURE_SOURCE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class NStructureSegmentIdentityError(ValueError):
    code = "N_STRUCTURE_SEGMENT_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


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


@dataclass(frozen=True, slots=True)
class NStructureCompletionResearchEvent:
    event_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    observed_at: datetime
    trading_day: date
    segment_bar_index: int
    direction: NDirection

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
            or not isinstance(self.direction, NDirection)
        ):
            raise ValueError("MULTI_CANDIDATE_EVENT_INVALID")


@dataclass(frozen=True, slots=True)
class _NStructureResearchProjection:
    result: NStructureResearchResult
    completion_events: tuple[NStructureCompletionResearchEvent, ...]


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
    completion_events: list[NStructureCompletionResearchEvent] = field(
        default_factory=list
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
        if not is_exact_n_structure_policy(policy):
            raise ValueError("N structure policy identity is invalid")
        self._segment_loader = segment_loader
        self._products = normalized
        self._policy = policy

    def run(self, request: NStructureResearchRequest) -> NStructureResearchResult:
        return self._project(request).result

    def completion_events(
        self,
        request: NStructureResearchRequest,
    ) -> tuple[NStructureCompletionResearchEvent, ...]:
        return self._project(request).completion_events

    def _project(
        self,
        request: NStructureResearchRequest,
    ) -> _NStructureResearchProjection:
        if not isinstance(request, NStructureResearchRequest):
            raise TypeError("request must be NStructureResearchRequest")
        products = self._selected_products(request.symbol)
        accumulator = _Accumulator()
        for product in products:
            try:
                loaded = self._segment_loader.load(
                    symbol=product,
                    frequencies=(BarFrequency.M5,),
                    since=request.since,
                    through=request.through,
                )
            except ActualDominantResearchSegmentIdentityError:
                raise NStructureSegmentIdentityError() from None
            except MarketDataError:
                raise NStructureSourceUnavailableError() from None
            result = loaded.results.get(BarFrequency.M5)
            if result is None:
                raise NStructureSegmentIdentityError()
            bars_by_segment = _partition_segment_bars(
                result.bars,
                segments=loaded.segments,
                through=request.through,
            )
            for segment, bars in zip(
                loaded.segments,
                bars_by_segment,
                strict=True,
            ):
                if not bars:
                    continue
                self._add_segment(
                    accumulator,
                    bars,
                    symbol=product,
                    segment=segment,
                    since=request.since,
                    through=request.through,
                )
        research_result = NStructureResearchResult(
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
                    horizon: summarize_price_outcomes(
                        accumulator.outcomes[horizon]
                    )
                    for horizon in _HORIZONS
                }
            ),
        )
        return _NStructureResearchProjection(
            research_result,
            tuple(accumulator.completion_events),
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
        symbol: str,
        segment: ResolvedContractSegment,
        since: date,
        through: date,
    ) -> None:
        segment_trace = evaluate_n_structure_segment(
            bars,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
            segment_end_trading_day=segment.end_trading_day,
            policy=self._policy,
        )
        swings = segment_trace.swings
        patterns = segment_trace.patterns
        structures = segment_trace.structures
        days_by_time = {bar.bar_end: bar.trading_day for bar in bars}
        bar_index = {bar.bar_end: index for index, bar in enumerate(bars)}
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
        accumulator.incomplete_attempt_replaced_count += sum(
            requested(replaced_at)
            for replaced_at in patterns.incomplete_attempt_replaced_at
        )

        for pattern in patterns.patterns:
            if not requested(pattern.completed_at):
                continue
            accumulator.completed_n_counts[pattern.direction.value] += 1
            index = bar_index.get(pattern.completed_at)
            if index is None:
                raise ValueError("N completion is not aligned with its source bar")
            if bars[index].close != pattern.completion_bar_close:
                raise ValueError("N completion entry is not aligned with its bar")
            accumulator.completion_events.append(
                NStructureCompletionResearchEvent(
                    event_id=pattern.n_id,
                    symbol=symbol,
                    contract=segment.contract,
                    segment_start_trading_day=segment.start_trading_day,
                    observed_at=pattern.completed_at,
                    trading_day=bars[index].trading_day,
                    segment_bar_index=index,
                    direction=pattern.direction,
                )
            )
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
            if reason is NStructureTransitionReason.BULL_STRUCTURE_ESTABLISHED:
                accumulator.structure_established_counts["bull"] += 1
            elif reason is NStructureTransitionReason.BEAR_STRUCTURE_ESTABLISHED:
                accumulator.structure_established_counts["bear"] += 1
            elif reason is NStructureTransitionReason.RANGE_STRUCTURE_ESTABLISHED:
                accumulator.structure_established_counts["range"] += 1
            elif reason is NStructureTransitionReason.BULL_STRUCTURE_BROKEN:
                accumulator.structure_break_counts["bull"] += 1
            elif reason is NStructureTransitionReason.BEAR_STRUCTURE_BROKEN:
                accumulator.structure_break_counts["bear"] += 1


def _partition_segment_bars(
    bars: Sequence[CanonicalBar],
    *,
    segments: Sequence[ResolvedContractSegment],
    through: date,
) -> tuple[tuple[CanonicalBar, ...], ...]:
    grouped: list[list[CanonicalBar]] = [[] for _ in segments]
    segment_index = 0
    for bar in bars:
        if bar.trading_day > through:
            continue
        while (
            segment_index < len(segments)
            and bar.trading_day > segments[segment_index].end_trading_day
        ):
            segment_index += 1
        if (
            segment_index >= len(segments)
            or bar.trading_day
            < segments[segment_index].start_trading_day
        ):
            raise NStructureSegmentIdentityError()
        grouped[segment_index].append(bar)
    return tuple(tuple(segment_bars) for segment_bars in grouped)


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
