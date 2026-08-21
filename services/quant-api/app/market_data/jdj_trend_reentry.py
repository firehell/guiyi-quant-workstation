"""Pure TREND_REENTRY_6 reducer for exact JDJ 1m contexts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from .domain import normalize_contract_for_symbol
from .jdj_context import (
    JdjBarContext,
    JdjContextError,
    valid_context_fact_identity as _valid_context_fact_identity,
)
from .jdj_events import (
    _JDJ_SOURCE_KIND,
    _JDJ_TREND_REENTRY_CANDIDATE_ID,
    _JDJ_TREND_REENTRY_SOURCE_EVENT_KIND,
    JdjDirection,
    JdjSetupKind,
    JdjTrendReentryTriggerEvent,
    _canonical_trend_reentry_event_id,
)
from .n_structure_state import NStructureKind


class _ReentryPhase(StrEnum):
    WAIT_TREND_SIDE = "wait_trend_side"
    WAIT_EXCURSION = "wait_excursion"
    IN_EXCURSION = "in_excursion"
    WAIT_REACTION = "wait_reaction"
    ARMED = "armed"


@dataclass(frozen=True, slots=True)
class JdjTrendReentryTrace:
    events: tuple[JdjTrendReentryTriggerEvent, ...]
    ambiguous_count: int
    invalidated_count: int

    def __post_init__(self) -> None:
        if (
            type(self.events) is not tuple
            or any(
                not isinstance(event, JdjTrendReentryTriggerEvent)
                for event in self.events
            )
            or tuple(sorted(self.events, key=_event_order_key)) != self.events
            or len({event.event_id for event in self.events})
            != len(self.events)
            or type(self.ambiguous_count) is not int
            or self.ambiguous_count < 0
            or type(self.invalidated_count) is not int
            or self.invalidated_count < 0
        ):
            raise JdjContextError()


@dataclass(slots=True)
class _ReentryState:
    phase: _ReentryPhase = _ReentryPhase.WAIT_TREND_SIDE
    direction: JdjDirection | None = None
    excursion_started_at: datetime | None = None
    excursion_extreme: Decimal | None = None
    reclaimed_at: datetime | None = None
    reaction_at: datetime | None = None
    trend_snapshot_observed_at: datetime | None = None


def reduce_jdj_trend_reentry_6(
    contexts: Sequence[JdjBarContext],
    *,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
) -> JdjTrendReentryTrace:
    """Reduce exact contexts without positions, exits, or execution claims."""

    if not isinstance(contexts, Sequence):
        raise JdjContextError()
    series = tuple(contexts)
    _validate_inputs(
        series,
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
    )

    events: list[JdjTrendReentryTriggerEvent] = []
    ambiguous_count = 0
    invalidated_count = 0
    active_trading_day: date | None = None
    state = _ReentryState()

    for index, context in enumerate(series):
        if context.bar.trading_day != active_trading_day:
            active_trading_day = context.bar.trading_day
            state = _ReentryState()
            continue

        ema20 = context.ema20
        if ema20 is None:
            continue

        if state.phase is _ReentryPhase.WAIT_TREND_SIDE:
            direction = _trend_side_direction(context, ema20)
            if direction is not None:
                state = _ReentryState(
                    phase=_ReentryPhase.WAIT_EXCURSION,
                    direction=direction,
                )
            continue

        direction = state.direction
        if direction is None:
            raise JdjContextError()
        expected_trend = _expected_trend(direction)
        if context.trend_kind is not expected_trend:
            if state.phase is _ReentryPhase.ARMED:
                invalidated_count += 1
            state = _ReentryState()
            continue

        if state.phase is _ReentryPhase.WAIT_EXCURSION:
            if _is_opposite_ema_side(context, ema20, direction):
                state = _start_excursion(context, direction)
            continue

        if state.phase is _ReentryPhase.IN_EXCURSION:
            if _is_opposite_ema_side(context, ema20, direction):
                _extend_excursion(state, context, direction)
            else:
                state.phase = _ReentryPhase.WAIT_REACTION
                state.reclaimed_at = context.bar.bar_end
            continue

        if state.phase is _ReentryPhase.WAIT_REACTION:
            if _is_opposite_ema_side(context, ema20, direction):
                state = _start_excursion(context, direction)
                continue
            if not _is_ema_reaction(context, ema20, direction):
                continue
            if not _reaction_preserves_extreme(state, context, direction):
                state = _ReentryState()
                continue
            snapshot_at = context.trend_snapshot_observed_at
            if snapshot_at is None:
                raise JdjContextError()
            state.phase = _ReentryPhase.ARMED
            state.reaction_at = context.bar.bar_end
            state.trend_snapshot_observed_at = snapshot_at
            continue

        if state.phase is not _ReentryPhase.ARMED:
            raise JdjContextError()

        previous = series[index - 1].bar
        if direction is JdjDirection.LONG:
            price_triggered = context.bar.high > previous.high
            ema_invalidated = context.bar.close <= ema20
            trigger_level = previous.high
        else:
            price_triggered = context.bar.low < previous.low
            ema_invalidated = context.bar.close >= ema20
            trigger_level = previous.low

        if price_triggered and ema_invalidated:
            ambiguous_count += 1
            state = _ReentryState()
            continue
        if ema_invalidated:
            invalidated_count += 1
            state = _ReentryState()
            continue
        if not price_triggered:
            continue

        events.append(
            _build_event(
                state,
                context=context,
                index=index,
                direction=direction,
                trigger_level=trigger_level,
                symbol=symbol,
                contract=contract,
                segment_start_trading_day=segment_start_trading_day,
            )
        )
        state = _ReentryState()

    return JdjTrendReentryTrace(
        events=tuple(events),
        ambiguous_count=ambiguous_count,
        invalidated_count=invalidated_count,
    )


def _trend_side_direction(
    context: JdjBarContext,
    ema20: Decimal,
) -> JdjDirection | None:
    if (
        context.trend_kind is NStructureKind.BULL
        and context.bar.close > ema20
    ):
        return JdjDirection.LONG
    if (
        context.trend_kind is NStructureKind.BEAR
        and context.bar.close < ema20
    ):
        return JdjDirection.SHORT
    return None


def _expected_trend(direction: JdjDirection) -> NStructureKind:
    if direction is JdjDirection.LONG:
        return NStructureKind.BULL
    return NStructureKind.BEAR


def _is_opposite_ema_side(
    context: JdjBarContext,
    ema20: Decimal,
    direction: JdjDirection,
) -> bool:
    if direction is JdjDirection.LONG:
        return context.bar.close <= ema20
    return context.bar.close >= ema20


def _start_excursion(
    context: JdjBarContext,
    direction: JdjDirection,
) -> _ReentryState:
    extreme = (
        context.bar.low
        if direction is JdjDirection.LONG
        else context.bar.high
    )
    return _ReentryState(
        phase=_ReentryPhase.IN_EXCURSION,
        direction=direction,
        excursion_started_at=context.bar.bar_end,
        excursion_extreme=extreme,
    )


def _extend_excursion(
    state: _ReentryState,
    context: JdjBarContext,
    direction: JdjDirection,
) -> None:
    extreme = state.excursion_extreme
    if extreme is None:
        raise JdjContextError()
    if direction is JdjDirection.LONG:
        state.excursion_extreme = min(extreme, context.bar.low)
    else:
        state.excursion_extreme = max(extreme, context.bar.high)


def _is_ema_reaction(
    context: JdjBarContext,
    ema20: Decimal,
    direction: JdjDirection,
) -> bool:
    if not context.bar.low <= ema20 <= context.bar.high:
        return False
    if direction is JdjDirection.LONG:
        return context.bar.close > ema20
    return context.bar.close < ema20


def _reaction_preserves_extreme(
    state: _ReentryState,
    context: JdjBarContext,
    direction: JdjDirection,
) -> bool:
    extreme = state.excursion_extreme
    if extreme is None:
        raise JdjContextError()
    if direction is JdjDirection.LONG:
        return context.bar.low > extreme
    return context.bar.high < extreme


def _build_event(
    state: _ReentryState,
    *,
    context: JdjBarContext,
    index: int,
    direction: JdjDirection,
    trigger_level: Decimal,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
) -> JdjTrendReentryTriggerEvent:
    excursion_started_at = state.excursion_started_at
    excursion_extreme = state.excursion_extreme
    reclaimed_at = state.reclaimed_at
    reaction_at = state.reaction_at
    snapshot_at = state.trend_snapshot_observed_at
    if (
        excursion_started_at is None
        or excursion_extreme is None
        or reclaimed_at is None
        or reaction_at is None
        or snapshot_at is None
    ):
        raise JdjContextError()
    event_id = _canonical_trend_reentry_event_id(
        candidate_id=_JDJ_TREND_REENTRY_CANDIDATE_ID,
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        direction=direction,
        excursion_started_at=excursion_started_at,
        excursion_extreme=excursion_extreme,
        reclaimed_at=reclaimed_at,
        reaction_at=reaction_at,
        observed_at=context.bar.bar_end,
        trigger_level=trigger_level,
    )
    return JdjTrendReentryTriggerEvent(
        event_id=event_id,
        source_kind=_JDJ_SOURCE_KIND,
        setup_kind=JdjSetupKind.TREND_REENTRY_6,
        candidate_id=_JDJ_TREND_REENTRY_CANDIDATE_ID,
        source_event_kind=_JDJ_TREND_REENTRY_SOURCE_EVENT_KIND,
        direction=direction,
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        trading_day=context.bar.trading_day,
        observed_at=context.bar.bar_end,
        segment_bar_index=index,
        trend_snapshot_observed_at=snapshot_at,
        excursion_started_at=excursion_started_at,
        excursion_extreme=excursion_extreme,
        reclaimed_at=reclaimed_at,
        reaction_at=reaction_at,
        trigger_level=trigger_level,
        observation_close=context.bar.close,
    )


def _validate_inputs(
    contexts: tuple[JdjBarContext, ...],
    *,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
) -> None:
    if (
        type(symbol) is not str
        or not symbol
        or symbol.lower() != symbol
        or not symbol.isalpha()
        or normalize_contract_for_symbol(symbol, contract) != contract
        or type(segment_start_trading_day) is not date
        or any(not isinstance(context, JdjBarContext) for context in contexts)
        or any(
            previous.bar.bar_end >= current.bar.bar_end
            for previous, current in zip(contexts, contexts[1:])
        )
        or any(
            previous.bar.trading_day > current.bar.trading_day
            for previous, current in zip(contexts, contexts[1:])
        )
        or any(
            context.bar.trading_day < segment_start_trading_day
            or not _valid_context_fact_identity(
                context,
                previous=(contexts[index - 1] if index > 0 else None),
                contract=contract,
                segment_start_trading_day=segment_start_trading_day,
            )
            for index, context in enumerate(contexts)
        )
        or _ema_readiness_regresses(contexts)
    ):
        raise JdjContextError()


def _ema_readiness_regresses(
    contexts: tuple[JdjBarContext, ...],
) -> bool:
    ready_seen = False
    for context in contexts:
        if context.ema20 is not None:
            ready_seen = True
        elif ready_seen:
            return True
    return False


def _event_order_key(
    event: JdjTrendReentryTriggerEvent,
) -> tuple[datetime, int, str]:
    return (event.observed_at, event.segment_bar_index, event.event_id)
