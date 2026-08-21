"""Pure TREND_FOLLOW reducer for exact JDJ 1m contexts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.market_data.domain import normalize_contract_for_symbol
from .jdj_context import (
    JdjBarContext,
    JdjContextError,
    valid_context_fact_identity as _valid_context_fact_identity,
)
from .jdj_events import (
    _JDJ_SOURCE_KIND,
    _JDJ_TREND_FOLLOW_CANDIDATE_ID,
    _JDJ_TREND_FOLLOW_SOURCE_EVENT_KIND,
    JdjDirection,
    JdjSetupKind,
    JdjTrendFollowTriggerEvent,
    _canonical_trend_follow_event_id,
)
from app.research.n_structure.n_structure_state import NStructureKind


@dataclass(frozen=True, slots=True)
class JdjTrendFollowTrace:
    events: tuple[JdjTrendFollowTriggerEvent, ...]
    ambiguous_count: int
    invalidated_count: int

    def __post_init__(self) -> None:
        if (
            type(self.events) is not tuple
            or any(
                not isinstance(event, JdjTrendFollowTriggerEvent)
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


@dataclass(frozen=True, slots=True)
class _ArmedTrendFollow:
    direction: JdjDirection
    reaction_at: datetime
    ema20_at_reaction: Decimal
    trend_snapshot_observed_at: datetime


def reduce_jdj_trend_follow(
    contexts: Sequence[JdjBarContext],
    *,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
) -> JdjTrendFollowTrace:
    """Reduce exact contexts without fills, positions, or execution claims."""

    if not isinstance(contexts, Sequence):
        raise JdjContextError()
    series = tuple(contexts)
    _validate_inputs(
        series,
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
    )

    events: list[JdjTrendFollowTriggerEvent] = []
    ambiguous_count = 0
    invalidated_count = 0
    active_trading_day: date | None = None
    armed: _ArmedTrendFollow | None = None

    for index, context in enumerate(series):
        if context.bar.trading_day != active_trading_day:
            active_trading_day = context.bar.trading_day
            armed = None
            continue

        if armed is None:
            armed = _reaction_state(context)
            continue

        ema20 = context.ema20
        if ema20 is None:
            raise JdjContextError()
        expected_trend = (
            NStructureKind.BULL
            if armed.direction is JdjDirection.LONG
            else NStructureKind.BEAR
        )
        if context.trend_kind is not expected_trend:
            invalidated_count += 1
            armed = None
            continue

        previous = series[index - 1].bar
        if armed.direction is JdjDirection.LONG:
            price_triggered = context.bar.high > previous.high
            ema_invalidated = context.bar.close <= ema20
            trigger_level = previous.high
        else:
            price_triggered = context.bar.low < previous.low
            ema_invalidated = context.bar.close >= ema20
            trigger_level = previous.low

        if price_triggered and ema_invalidated:
            ambiguous_count += 1
            armed = None
            continue
        if ema_invalidated:
            invalidated_count += 1
            armed = None
            continue
        if not price_triggered:
            continue

        event_id = _canonical_trend_follow_event_id(
            candidate_id=_JDJ_TREND_FOLLOW_CANDIDATE_ID,
            symbol=symbol,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            direction=armed.direction,
            reaction_at=armed.reaction_at,
            observed_at=context.bar.bar_end,
            trigger_level=trigger_level,
        )
        events.append(
            JdjTrendFollowTriggerEvent(
                event_id=event_id,
                source_kind=_JDJ_SOURCE_KIND,
                setup_kind=JdjSetupKind.TREND_FOLLOW,
                candidate_id=_JDJ_TREND_FOLLOW_CANDIDATE_ID,
                source_event_kind=_JDJ_TREND_FOLLOW_SOURCE_EVENT_KIND,
                direction=armed.direction,
                symbol=symbol,
                contract=contract,
                segment_start_trading_day=segment_start_trading_day,
                trading_day=context.bar.trading_day,
                observed_at=context.bar.bar_end,
                segment_bar_index=index,
                trend_snapshot_observed_at=(
                    armed.trend_snapshot_observed_at
                ),
                reaction_at=armed.reaction_at,
                ema20_at_reaction=armed.ema20_at_reaction,
                trigger_level=trigger_level,
                observation_close=context.bar.close,
            )
        )
        armed = None

    return JdjTrendFollowTrace(
        events=tuple(events),
        ambiguous_count=ambiguous_count,
        invalidated_count=invalidated_count,
    )


def _reaction_state(context: JdjBarContext) -> _ArmedTrendFollow | None:
    ema20 = context.ema20
    snapshot_at = context.trend_snapshot_observed_at
    if ema20 is None or snapshot_at is None:
        return None
    if (
        context.trend_kind is NStructureKind.BULL
        and context.bar.low <= ema20 <= context.bar.high
        and context.bar.close > ema20
    ):
        return _ArmedTrendFollow(
            direction=JdjDirection.LONG,
            reaction_at=context.bar.bar_end,
            ema20_at_reaction=ema20,
            trend_snapshot_observed_at=snapshot_at,
        )
    if (
        context.trend_kind is NStructureKind.BEAR
        and context.bar.low <= ema20 <= context.bar.high
        and context.bar.close < ema20
    ):
        return _ArmedTrendFollow(
            direction=JdjDirection.SHORT,
            reaction_at=context.bar.bar_end,
            ema20_at_reaction=ema20,
            trend_snapshot_observed_at=snapshot_at,
        )
    return None


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
    event: JdjTrendFollowTriggerEvent,
) -> tuple[datetime, int, str]:
    return (event.observed_at, event.segment_bar_index, event.event_id)
