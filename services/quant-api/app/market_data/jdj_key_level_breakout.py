"""Pure KEY_LEVEL_BREAKOUT reducer for exact JDJ 1m contexts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from .domain import normalize_contract_for_symbol
from .jdj_context import JdjBarContext, JdjContextError
from .jdj_events import (
    _JDJ_KEY_LEVEL_BREAKOUT_CANDIDATE_ID,
    _JDJ_KEY_LEVEL_BREAKOUT_SOURCE_EVENT_KIND,
    _JDJ_SOURCE_KIND,
    JdjDirection,
    JdjKeyLevelBreakoutTriggerEvent,
    JdjSetupKind,
    _canonical_key_level_breakout_event_id,
)
from .n_structure_state import NStructureKind
from .n_structure_swing import NSwingPivot


class _KeyLevelPhase(StrEnum):
    WAIT_ORIGIN_SIDE = "wait_origin_side"
    WAIT_FIRST_BREAK = "wait_first_break"
    WAIT_RETEST = "wait_retest"
    ARMED = "armed"


@dataclass(frozen=True, slots=True)
class JdjKeyLevelBreakoutTrace:
    events: tuple[JdjKeyLevelBreakoutTriggerEvent, ...]
    ambiguous_count: int
    invalidated_count: int
    expired_no_retest_count: int
    expired_context_lost_count: int

    def __post_init__(self) -> None:
        if (
            type(self.events) is not tuple
            or any(
                not isinstance(event, JdjKeyLevelBreakoutTriggerEvent)
                for event in self.events
            )
            or tuple(sorted(self.events, key=_event_order_key)) != self.events
            or len({event.event_id for event in self.events})
            != len(self.events)
            or not _valid_count(self.ambiguous_count)
            or not _valid_count(self.invalidated_count)
            or not _valid_count(self.expired_no_retest_count)
            or not _valid_count(self.expired_context_lost_count)
        ):
            raise JdjContextError()


@dataclass(slots=True)
class _KeyLevelState:
    phase: _KeyLevelPhase
    direction: JdjDirection
    trend_epoch: int
    key_level_pivot_id: str
    key_level_price: Decimal
    key_level_confirmed_at: datetime
    first_break_at: datetime | None = None
    retest_at: datetime | None = None
    trend_snapshot_observed_at: datetime | None = None


def reduce_jdj_key_level_breakout(
    contexts: Sequence[JdjBarContext],
    *,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
) -> JdjKeyLevelBreakoutTrace:
    """Reduce exact contexts without chasing, fills, or EMA semantics."""

    if not isinstance(contexts, Sequence):
        raise JdjContextError()
    series = tuple(contexts)
    _validate_inputs(
        series,
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
    )

    events: list[JdjKeyLevelBreakoutTriggerEvent] = []
    ambiguous_count = 0
    invalidated_count = 0
    expired_no_retest_count = 0
    expired_context_lost_count = 0
    active_trading_day: date | None = None
    consumed_pivots: set[str] = set()
    state: _KeyLevelState | None = None

    for index, context in enumerate(series):
        if context.bar.trading_day != active_trading_day:
            if state is not None:
                if state.phase is _KeyLevelPhase.WAIT_RETEST:
                    expired_no_retest_count += 1
                elif state.phase is _KeyLevelPhase.ARMED:
                    invalidated_count += 1
            active_trading_day = context.bar.trading_day
            consumed_pivots = set()
            state = None
            continue

        if state is None or state.phase in (
            _KeyLevelPhase.WAIT_ORIGIN_SIDE,
            _KeyLevelPhase.WAIT_FIRST_BREAK,
        ):
            state = _reduce_before_first_break(
                state,
                context=context,
                previous=series[index - 1],
                consumed_pivots=consumed_pivots,
            )
            continue

        if not _active_context_matches(state, context):
            consumed_pivots.add(state.key_level_pivot_id)
            if state.phase is _KeyLevelPhase.WAIT_RETEST:
                expired_context_lost_count += 1
            else:
                invalidated_count += 1
            state = None
            continue

        if state.phase is _KeyLevelPhase.WAIT_RETEST:
            if _accepted_retest(state, context):
                snapshot_at = context.trend_snapshot_observed_at
                if snapshot_at is None:
                    raise JdjContextError()
                state.phase = _KeyLevelPhase.ARMED
                state.retest_at = context.bar.bar_end
                state.trend_snapshot_observed_at = snapshot_at
            elif _failed_retest(state, context):
                consumed_pivots.add(state.key_level_pivot_id)
                state = None
            continue

        if state.phase is not _KeyLevelPhase.ARMED:
            raise JdjContextError()

        previous = series[index - 1].bar
        if state.direction is JdjDirection.LONG:
            price_triggered = context.bar.high > previous.high
            level_invalidated = context.bar.close <= state.key_level_price
            trigger_level = previous.high
        else:
            price_triggered = context.bar.low < previous.low
            level_invalidated = context.bar.close >= state.key_level_price
            trigger_level = previous.low

        if price_triggered and level_invalidated:
            ambiguous_count += 1
            consumed_pivots.add(state.key_level_pivot_id)
            state = None
            continue
        if level_invalidated:
            invalidated_count += 1
            consumed_pivots.add(state.key_level_pivot_id)
            state = None
            continue
        if not price_triggered:
            continue

        events.append(
            _build_event(
                state,
                context=context,
                index=index,
                trigger_level=trigger_level,
                symbol=symbol,
                contract=contract,
                segment_start_trading_day=segment_start_trading_day,
            )
        )
        consumed_pivots.add(state.key_level_pivot_id)
        state = None

    return JdjKeyLevelBreakoutTrace(
        events=tuple(events),
        ambiguous_count=ambiguous_count,
        invalidated_count=invalidated_count,
        expired_no_retest_count=expired_no_retest_count,
        expired_context_lost_count=expired_context_lost_count,
    )


def _reduce_before_first_break(
    state: _KeyLevelState | None,
    *,
    context: JdjBarContext,
    previous: JdjBarContext,
    consumed_pivots: set[str],
) -> _KeyLevelState | None:
    candidate = _eligible_candidate(context)
    if candidate is None:
        return None
    direction, pivot = candidate
    if pivot.pivot_id in consumed_pivots:
        return None
    if state is None or state.key_level_pivot_id != pivot.pivot_id:
        state = _state_for_pivot(direction, pivot)

    if state.phase is _KeyLevelPhase.WAIT_ORIGIN_SIDE:
        if _is_origin_side(state, context.bar.close):
            state.phase = _KeyLevelPhase.WAIT_FIRST_BREAK
        return state

    if state.phase is not _KeyLevelPhase.WAIT_FIRST_BREAK:
        raise JdjContextError()
    if _is_first_break(
        state,
        previous_close=previous.bar.close,
        current_close=context.bar.close,
    ):
        state.phase = _KeyLevelPhase.WAIT_RETEST
        state.first_break_at = context.bar.bar_end
    return state


def _eligible_candidate(
    context: JdjBarContext,
) -> tuple[JdjDirection, NSwingPivot] | None:
    if context.trend_kind is NStructureKind.BULL:
        pivot = context.eligible_high_pivot
        if pivot is not None:
            return (JdjDirection.LONG, pivot)
    elif context.trend_kind is NStructureKind.BEAR:
        pivot = context.eligible_low_pivot
        if pivot is not None:
            return (JdjDirection.SHORT, pivot)
    return None


def _state_for_pivot(
    direction: JdjDirection,
    pivot: NSwingPivot,
) -> _KeyLevelState:
    return _KeyLevelState(
        phase=_KeyLevelPhase.WAIT_ORIGIN_SIDE,
        direction=direction,
        trend_epoch=pivot.epoch,
        key_level_pivot_id=pivot.pivot_id,
        key_level_price=pivot.price,
        key_level_confirmed_at=pivot.confirmed_at,
    )


def _is_origin_side(state: _KeyLevelState, close: Decimal) -> bool:
    if state.direction is JdjDirection.LONG:
        return close <= state.key_level_price
    return close >= state.key_level_price


def _is_first_break(
    state: _KeyLevelState,
    *,
    previous_close: Decimal,
    current_close: Decimal,
) -> bool:
    if state.direction is JdjDirection.LONG:
        return (
            previous_close <= state.key_level_price
            and current_close > state.key_level_price
        )
    return (
        previous_close >= state.key_level_price
        and current_close < state.key_level_price
    )


def _active_context_matches(
    state: _KeyLevelState,
    context: JdjBarContext,
) -> bool:
    expected_trend = (
        NStructureKind.BULL
        if state.direction is JdjDirection.LONG
        else NStructureKind.BEAR
    )
    return (
        context.trend_kind is expected_trend
        and context.trend_epoch == state.trend_epoch
    )


def _accepted_retest(
    state: _KeyLevelState,
    context: JdjBarContext,
) -> bool:
    if state.direction is JdjDirection.LONG:
        return (
            context.bar.low <= state.key_level_price
            and context.bar.close > state.key_level_price
        )
    return (
        context.bar.high >= state.key_level_price
        and context.bar.close < state.key_level_price
    )


def _failed_retest(
    state: _KeyLevelState,
    context: JdjBarContext,
) -> bool:
    if state.direction is JdjDirection.LONG:
        return context.bar.close <= state.key_level_price
    return context.bar.close >= state.key_level_price


def _build_event(
    state: _KeyLevelState,
    *,
    context: JdjBarContext,
    index: int,
    trigger_level: Decimal,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
) -> JdjKeyLevelBreakoutTriggerEvent:
    first_break_at = state.first_break_at
    retest_at = state.retest_at
    snapshot_at = state.trend_snapshot_observed_at
    if (
        first_break_at is None
        or retest_at is None
        or snapshot_at is None
    ):
        raise JdjContextError()
    event_id = _canonical_key_level_breakout_event_id(
        candidate_id=_JDJ_KEY_LEVEL_BREAKOUT_CANDIDATE_ID,
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        direction=state.direction,
        trend_epoch=state.trend_epoch,
        key_level_pivot_id=state.key_level_pivot_id,
        key_level_price=state.key_level_price,
        key_level_confirmed_at=state.key_level_confirmed_at,
        first_break_at=first_break_at,
        retest_at=retest_at,
        observed_at=context.bar.bar_end,
        trigger_level=trigger_level,
    )
    return JdjKeyLevelBreakoutTriggerEvent(
        event_id=event_id,
        source_kind=_JDJ_SOURCE_KIND,
        setup_kind=JdjSetupKind.KEY_LEVEL_BREAKOUT,
        candidate_id=_JDJ_KEY_LEVEL_BREAKOUT_CANDIDATE_ID,
        source_event_kind=_JDJ_KEY_LEVEL_BREAKOUT_SOURCE_EVENT_KIND,
        direction=state.direction,
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        trading_day=context.bar.trading_day,
        observed_at=context.bar.bar_end,
        segment_bar_index=index,
        trend_snapshot_observed_at=snapshot_at,
        trend_epoch=state.trend_epoch,
        key_level_pivot_id=state.key_level_pivot_id,
        key_level_price=state.key_level_price,
        key_level_confirmed_at=state.key_level_confirmed_at,
        first_break_at=first_break_at,
        retest_at=retest_at,
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
        or _trend_epoch_regresses(contexts)
        or _pivot_identity_drifts(contexts)
        or _pivot_projection_regresses(contexts)
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
    ):
        raise JdjContextError()


def _valid_context_fact_identity(
    context: JdjBarContext,
    *,
    previous: JdjBarContext | None,
    contract: str,
    segment_start_trading_day: date,
) -> bool:
    snapshot_at = context.trend_snapshot_observed_at
    pivots = (
        context.eligible_high_pivot,
        context.eligible_low_pivot,
    )
    if (
        previous is None
        or previous.bar.trading_day != context.bar.trading_day
    ):
        return (
            snapshot_at is None
            and context.trend_kind is NStructureKind.UNDEFINED
            and all(pivot is None for pivot in pivots)
        )
    if snapshot_at is None:
        return (
            context.trend_kind is NStructureKind.UNDEFINED
            and all(pivot is None for pivot in pivots)
        )
    strict_before_boundary = previous.bar.bar_end
    if snapshot_at > strict_before_boundary:
        return False
    for pivot in pivots:
        if pivot is not None and (
            pivot.contract != contract
            or pivot.segment_start_trading_day
            != segment_start_trading_day
            or pivot.confirmed_at > strict_before_boundary
        ):
            return False
    return True


def _trend_epoch_regresses(
    contexts: tuple[JdjBarContext, ...],
) -> bool:
    maximum_epoch: int | None = None
    for context in contexts:
        current_epoch = context.trend_epoch
        if current_epoch is None:
            continue
        if maximum_epoch is not None and current_epoch < maximum_epoch:
            return True
        maximum_epoch = current_epoch
    return False


def _pivot_projection_regresses(
    contexts: tuple[JdjBarContext, ...],
) -> bool:
    active_trading_day: date | None = None
    latest: dict[tuple[int, str], NSwingPivot] = {}
    for context in contexts:
        if context.bar.trading_day != active_trading_day:
            active_trading_day = context.bar.trading_day
            latest = {}
        epoch = context.trend_epoch
        if epoch is None:
            continue
        for kind, pivot in (
            ("high", context.eligible_high_pivot),
            ("low", context.eligible_low_pivot),
        ):
            key = (epoch, kind)
            previous = latest.get(key)
            if previous is not None and (
                pivot is None
                or _pivot_order_key(pivot) < _pivot_order_key(previous)
            ):
                return True
            if pivot is not None and (
                previous is None
                or _pivot_order_key(pivot) > _pivot_order_key(previous)
            ):
                latest[key] = pivot
    return False


def _pivot_identity_drifts(
    contexts: tuple[JdjBarContext, ...],
) -> bool:
    facts_by_id: dict[str, NSwingPivot] = {}
    for context in contexts:
        for pivot in (
            context.eligible_high_pivot,
            context.eligible_low_pivot,
        ):
            if pivot is None:
                continue
            previous = facts_by_id.get(pivot.pivot_id)
            if previous is not None and previous != pivot:
                return True
            facts_by_id[pivot.pivot_id] = pivot
    return False


def _pivot_order_key(
    pivot: NSwingPivot,
) -> tuple[datetime, datetime, str]:
    return (pivot.confirmed_at, pivot.pivot_time, pivot.pivot_id)


def _valid_count(value: object) -> bool:
    return type(value) is int and value >= 0


def _event_order_key(
    event: JdjKeyLevelBreakoutTriggerEvent,
) -> tuple[datetime, int, str]:
    return (event.observed_at, event.segment_bar_index, event.event_id)
