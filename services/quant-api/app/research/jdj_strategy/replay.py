"""Deterministic, research-only active-product JDJ 1m reference replay."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256

from app.market_data.domain import CanonicalBar, ResolvedContractSegment
from app.research.jdj.jdj_context import (
    JdjBarContext,
    valid_context_fact_identity,
)
from app.research.jdj.jdj_events import (
    JdjDirection,
    JdjKeyLevelBreakoutTriggerEvent,
    JdjSetupKind,
    JdjTrendFollowTriggerEvent,
    JdjTrendReentryTriggerEvent,
    JdjTriggerEvent,
)
from app.research.n_structure.n_structure_state import NStructureKind

from .contract import JdjV1Config
from .engine import JdjAction, JdjActionKind, JdjReferenceReplay


class JdjStrategyReplayError(ValueError):
    code = "JDJ_STRATEGY_REPLAY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(slots=True)
class _Episode:
    episode_id: str
    source_event_ids: list[str]
    consumed_source_event_ids: set[str]
    primary_setup: str
    supporting_setups: tuple[str, ...]
    direction: JdjDirection
    contract: str
    trading_day: date
    segment_start_trading_day: date
    quantity: int
    weighted_average_cost: Decimal
    protective_stop: Decimal
    target_1: Decimal
    partial_profit_taken: bool = False
    add_count: int = 0
    realized_pnl: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class _Pending:
    kind: JdjActionKind
    decision_at: datetime
    source_events: tuple[JdjTriggerEvent, ...]
    primary_setup: str | None
    supporting_setups: tuple[str, ...]
    direction: JdjDirection
    contract: str
    trading_day: date
    segment_start_trading_day: date
    quantity: int
    limit_price: Decimal | None
    stop_price: Decimal
    target_price: Decimal
    reward_risk: Decimal | None
    reason: str
    episode_id: str | None


_SETUP_PRIORITY = {
    JdjSetupKind.KEY_LEVEL_BREAKOUT: 0,
    JdjSetupKind.TREND_REENTRY_6: 1,
    JdjSetupKind.TREND_FOLLOW: 2,
}


def run_jdj_reference_segment(
    *,
    symbol: str,
    segment: ResolvedContractSegment,
    bars_1m: Sequence[CanonicalBar],
    contexts: Sequence[JdjBarContext],
    candidate_events: Sequence[JdjTriggerEvent],
    contract_multiplier: Decimal,
    terminal_bar_end_by_day: Mapping[date, datetime],
    config: JdjV1Config,
) -> JdjReferenceReplay:
    """Replay one validated physical-contract segment without external writes."""

    bars = tuple(bars_1m)
    facts = tuple(contexts)
    events = tuple(candidate_events)
    _validate_inputs(
        symbol,
        segment,
        bars,
        facts,
        events,
        contract_multiplier=contract_multiplier,
        terminal_bar_end_by_day=terminal_bar_end_by_day,
        config=config,
    )
    if not bars:
        return JdjReferenceReplay(actions=())

    events_by_time: dict[datetime, list[JdjTriggerEvent]] = {}
    duplicate_ids_by_time: dict[datetime, set[str]] = {}
    seen_event_ids: set[str] = set()
    for event in sorted(events, key=lambda item: (item.observed_at, item.event_id)):
        if event.event_id in seen_event_ids:
            duplicate_ids_by_time.setdefault(event.observed_at, set()).add(event.event_id)
            continue
        seen_event_ids.add(event.event_id)
        events_by_time.setdefault(event.observed_at, []).append(event)

    actions: list[JdjAction] = []
    pending: _Pending | None = None
    episode: _Episode | None = None
    last_closed_episode: _Episode | None = None
    cash_equity = config.profile.historical_reference_start_equity
    active_day: date | None = None
    day_start_equity = cash_equity
    daily_pause_triggered = False
    daily_stop_triggered = False
    pause_remaining = 0
    day_high: Decimal | None = None
    day_low: Decimal | None = None

    for index, (bar, context) in enumerate(zip(bars, facts, strict=True)):
        if bar.trading_day != active_day:
            active_day = bar.trading_day
            day_start_equity = _marked_equity(cash_equity, episode, bar.close, contract_multiplier)
            daily_pause_triggered = False
            daily_stop_triggered = False
            pause_remaining = 0
            day_high = None
            day_low = None
            last_closed_episode = None

        day_high = bar.high if day_high is None else max(day_high, bar.high)
        day_low = bar.low if day_low is None else min(day_low, bar.low)

        if pending is not None:
            episode_before_fill = episode
            filled_actions, episode, cash_delta = _resolve_pending(
                pending,
                bar=bar,
                episode=episode,
                contract_multiplier=contract_multiplier,
            )
            actions.extend(filled_actions)
            cash_equity += cash_delta
            pending = None
            if episode_before_fill is not None and episode is None:
                last_closed_episode = episode_before_fill

        bar_events = tuple(events_by_time.get(bar.bar_end, ()))
        for duplicate_id in sorted(duplicate_ids_by_time.get(bar.bar_end, ())):
            source = next(event for event in bar_events if event.event_id == duplicate_id)
            actions.append(
                _rejected(
                    (source,),
                    reason="SOURCE_EVENT_ALREADY_SEEN",
                    episode=episode,
                )
            )

        pause_active = pause_remaining > 0
        pause_triggered_now = False
        current_equity = _marked_equity(
            cash_equity,
            episode,
            bar.close,
            contract_multiplier,
        )
        drawdown = (
            (day_start_equity - current_equity) / day_start_equity
            if day_start_equity > 0
            else Decimal("0")
        )
        if drawdown >= config.core.daily_stop_drawdown_fraction:
            if not daily_stop_triggered:
                daily_stop_triggered = True
                risk_episode = episode or last_closed_episode
                if risk_episode is None:
                    raise JdjStrategyReplayError()
                actions.append(
                    _daily_action(
                        JdjActionKind.DAILY_STOP,
                        reason="DAILY_DRAWDOWN_STOP",
                        bar=bar,
                        episode=risk_episode,
                    )
                )
            if episode is not None:
                pending = _exit_pending(episode, bar, reason="DAILY_STOP")
            _reject_all(bar_events, actions, episode, "DAILY_STOP_ACTIVE")
            if pause_active:
                pause_remaining -= 1
            continue
        if (
            drawdown > config.core.daily_pause_drawdown_fraction
            and not daily_pause_triggered
        ):
            daily_pause_triggered = True
            pause_remaining = config.core.daily_pause_bars
            risk_episode = episode or last_closed_episode
            if risk_episode is None:
                raise JdjStrategyReplayError()
            actions.append(
                _daily_action(
                    JdjActionKind.DAILY_PAUSE,
                    reason="DAILY_DRAWDOWN_PAUSE",
                    bar=bar,
                    episode=risk_episode,
                )
            )
            pause_triggered_now = True

        terminal_guard = _terminal_guard(
            index,
            bars,
            terminal_bar_end_by_day=terminal_bar_end_by_day,
        )
        if terminal_guard:
            if episode is not None:
                pending = _exit_pending(episode, bar, reason="SESSION_FLATTEN")
            _reject_all(bar_events, actions, episode, "SESSION_TERMINAL_GUARD")
            if pause_active:
                pause_remaining -= 1
            continue

        if episode is not None:
            exit_reason = _completed_bar_exit_reason(episode, context)
            if exit_reason is not None:
                pending = _exit_pending(episode, bar, reason=exit_reason)
                _reject_all(bar_events, actions, episode, exit_reason)
            elif _target_reached(episode, bar.close) and not episode.partial_profit_taken:
                take_quantity = _floor_quantity(
                    Decimal(episode.quantity) * config.profile.first_profit_take_fraction
                )
                if take_quantity > 0:
                    pending = _Pending(
                        kind=JdjActionKind.REDUCE,
                        decision_at=bar.bar_end,
                        source_events=(),
                        primary_setup=episode.primary_setup,
                        supporting_setups=episode.supporting_setups,
                        direction=episode.direction,
                        contract=episode.contract,
                        trading_day=bar.trading_day,
                        segment_start_trading_day=episode.segment_start_trading_day,
                        quantity=take_quantity,
                        limit_price=None,
                        stop_price=episode.protective_stop,
                        target_price=episode.target_1,
                        reward_risk=None,
                        reason="TARGET_1_PARTIAL_PROFIT",
                        episode_id=episode.episode_id,
                    )
                _reject_all(
                    bar_events,
                    actions,
                    episode,
                    "RISK_ACTION_PRECEDENCE" if take_quantity > 0 else "OPEN_EPISODE_EVENT_REJECTED",
                )
            elif pause_triggered_now or pause_active:
                _reject_all(bar_events, actions, episode, "DAILY_PAUSE_ACTIVE")
            else:
                pending = _consider_adds(
                    bar_events,
                    actions=actions,
                    episode=episode,
                    bar=bar,
                    current_equity=current_equity,
                    config=config,
                    contract_multiplier=contract_multiplier,
                )
        elif daily_stop_triggered:
            _reject_all(bar_events, actions, None, "DAILY_STOP_ACTIVE")
        elif pause_triggered_now or pause_active:
            _reject_all(bar_events, actions, None, "DAILY_PAUSE_ACTIVE")
        elif bar_events:
            pending = _consider_entry(
                bar_events,
                actions=actions,
                bars=bars,
                context=context,
                day_high=day_high,
                day_low=day_low,
                current_equity=current_equity,
                config=config,
                contract_multiplier=contract_multiplier,
            )

        if pause_active:
            pause_remaining -= 1

    return JdjReferenceReplay(actions=tuple(actions))


def _validate_inputs(
    symbol: str,
    segment: ResolvedContractSegment,
    bars: tuple[CanonicalBar, ...],
    contexts: tuple[JdjBarContext, ...],
    events: tuple[JdjTriggerEvent, ...],
    *,
    contract_multiplier: Decimal,
    terminal_bar_end_by_day: Mapping[date, datetime],
    config: JdjV1Config,
) -> None:
    event_types = (
        JdjTrendFollowTriggerEvent,
        JdjTrendReentryTriggerEvent,
        JdjKeyLevelBreakoutTriggerEvent,
    )
    if (
        not isinstance(symbol, str)
        or not symbol
        or symbol != symbol.strip().lower()
        or not isinstance(segment, ResolvedContractSegment)
        or not isinstance(config, JdjV1Config)
        or not isinstance(contract_multiplier, Decimal)
        or not contract_multiplier.is_finite()
        or contract_multiplier <= 0
        or len(bars) != len(contexts)
        or any(not isinstance(bar, CanonicalBar) for bar in bars)
        or any(not isinstance(context, JdjBarContext) for context in contexts)
        or any(context.bar != bar for bar, context in zip(bars, contexts, strict=True))
        or any(left.bar_end >= right.bar_end for left, right in zip(bars, bars[1:]))
        or any(not isinstance(event, event_types) for event in events)
        or any(
            not (
                segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
            )
            for bar in bars
        )
    ):
        raise JdjStrategyReplayError()
    bars_by_day: dict[date, set[datetime]] = {}
    for bar in bars:
        bars_by_day.setdefault(bar.trading_day, set()).add(bar.bar_end)
    days = set(bars_by_day)
    if set(terminal_bar_end_by_day) != days or any(
        day not in terminal_bar_end_by_day
        or not isinstance(terminal_bar_end_by_day[day], datetime)
        or terminal_bar_end_by_day[day].tzinfo is None
        or terminal_bar_end_by_day[day].astimezone(UTC) not in bars_by_day[day]
        for day in days
    ):
        raise JdjStrategyReplayError()
    indexed_bars = {bar.bar_end: bar for bar in bars}
    for event in events:
        observed_bar = indexed_bars.get(event.observed_at)
        if (
            event.symbol != symbol
            or event.contract != segment.contract
            or event.segment_start_trading_day != segment.start_trading_day
            or not (
                segment.start_trading_day
                <= event.trading_day
                <= segment.end_trading_day
            )
            or observed_bar is None
            or observed_bar.trading_day != event.trading_day
        ):
            raise JdjStrategyReplayError()
    previous: JdjBarContext | None = None
    for context in contexts:
        if not valid_context_fact_identity(
            context,
            previous=previous,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
        ):
            raise JdjStrategyReplayError()
        previous = context


def _consider_entry(
    events: tuple[JdjTriggerEvent, ...],
    *,
    actions: list[JdjAction],
    bars: tuple[CanonicalBar, ...],
    context: JdjBarContext,
    day_high: Decimal,
    day_low: Decimal,
    current_equity: Decimal,
    config: JdjV1Config,
    contract_multiplier: Decimal,
) -> _Pending | None:
    directions = {event.direction for event in events}
    if len(directions) != 1:
        actions.append(_rejected(events, reason="AMBIGUOUS_DIRECTION", episode=None))
        return None
    ordered = _ordered_events(events)
    primary = ordered[0]
    stop = _structural_stop(primary, bars)
    target = _known_target(
        direction=primary.direction,
        entry_reference=primary.observation_close,
        contract=primary.contract,
        segment_start_trading_day=primary.segment_start_trading_day,
        context=context,
        day_high=day_high,
        day_low=day_low,
    )
    if target is None:
        actions.append(
            _rejected(
                ordered,
                reason="TARGET_UNAVAILABLE",
                episode=None,
                stop=stop,
            )
        )
        return None
    risk = _directional_distance(primary.direction, primary.observation_close, stop)
    reward = _directional_distance(primary.direction, target, primary.observation_close)
    if risk <= 0 or reward <= 0:
        actions.append(
            _rejected(
                ordered,
                reason="STRUCTURAL_LEVEL_INVALID",
                episode=None,
                stop=stop,
                target=target,
            )
        )
        return None
    reward_risk = reward / risk
    if reward_risk < config.core.minimum_reward_risk:
        actions.append(
            _rejected(
                ordered,
                reason="REWARD_RISK_BELOW_MINIMUM",
                episode=None,
                stop=stop,
                target=target,
                reward_risk=reward_risk,
            )
        )
        return None
    boundary = _admissible_boundary(target, stop, config.core.minimum_reward_risk)
    per_contract_risk = abs(boundary - stop) * contract_multiplier
    quantity = _floor_quantity(
        current_equity * config.profile.base_risk_fraction / per_contract_risk
    )
    if quantity < 1:
        actions.append(
            _rejected(
                ordered,
                reason="QUANTITY_BELOW_ONE",
                episode=None,
                stop=stop,
                target=target,
                reward_risk=reward_risk,
            )
        )
        return None
    if (
        Decimal(quantity) * per_contract_risk
        > current_equity * config.core.max_planned_trade_risk_fraction
    ):
        actions.append(
            _rejected(
                ordered,
                reason="EPISODE_RISK_LIMIT",
                episode=None,
                stop=stop,
                target=target,
                reward_risk=reward_risk,
            )
        )
        return None
    return _Pending(
        kind=JdjActionKind.ENTRY,
        decision_at=primary.observed_at,
        source_events=ordered,
        primary_setup=primary.setup_kind.value,
        supporting_setups=tuple(event.setup_kind.value for event in ordered[1:]),
        direction=primary.direction,
        contract=primary.contract,
        trading_day=primary.trading_day,
        segment_start_trading_day=primary.segment_start_trading_day,
        quantity=quantity,
        limit_price=boundary,
        stop_price=stop,
        target_price=target,
        reward_risk=reward_risk,
        reason="ENTRY_AUTHORIZED",
        episode_id=None,
    )


def _consider_adds(
    events: tuple[JdjTriggerEvent, ...],
    *,
    actions: list[JdjAction],
    episode: _Episode,
    bar: CanonicalBar,
    current_equity: Decimal,
    config: JdjV1Config,
    contract_multiplier: Decimal,
) -> _Pending | None:
    if not events:
        return None
    fresh = tuple(
        event for event in events if event.event_id not in episode.consumed_source_event_ids
    )
    if not fresh:
        _reject_all(events, actions, episode, "SOURCE_EVENT_ALREADY_CONSUMED")
        return None
    add_candidates = tuple(
        event
        for event in fresh
        if event.direction is episode.direction
        and isinstance(event, JdjTrendFollowTriggerEvent)
    )
    if not add_candidates:
        _reject_all(events, actions, episode, "OPEN_EPISODE_EVENT_REJECTED")
        return None
    candidate = min(add_candidates, key=lambda event: event.event_id)
    extras = tuple(event for event in events if event is not candidate)
    if not episode.partial_profit_taken:
        _reject_all(events, actions, episode, "ADD_PARTIAL_PROFIT_REQUIRED")
        return None
    if episode.realized_pnl <= 0:
        _reject_all(events, actions, episode, "ADD_PROFIT_REQUIRED")
        return None
    if episode.add_count >= config.core.max_add_count:
        _reject_all(events, actions, episode, "ADD_COUNT_LIMIT")
        return None
    quantity = _floor_quantity(
        Decimal(episode.quantity) * config.core.add_fraction_of_current_qty
    )
    if quantity < 1:
        _reject_all(events, actions, episode, "ADD_QUANTITY_BELOW_ONE")
        return None
    boundary = _admissible_boundary(
        episode.target_1,
        episode.protective_stop,
        config.core.minimum_reward_risk,
    )
    existing_risk = (
        abs(episode.weighted_average_cost - episode.protective_stop)
        * Decimal(episode.quantity)
        * contract_multiplier
    )
    added_risk = (
        abs(boundary - episode.protective_stop)
        * Decimal(quantity)
        * contract_multiplier
    )
    if existing_risk + added_risk > (
        current_equity * config.core.max_planned_trade_risk_fraction
    ):
        _reject_all(events, actions, episode, "EPISODE_RISK_LIMIT")
        return None
    _reject_all(extras, actions, episode, "OPEN_EPISODE_EVENT_REJECTED")
    return _Pending(
        kind=JdjActionKind.ADD,
        decision_at=bar.bar_end,
        source_events=(candidate,),
        primary_setup=candidate.setup_kind.value,
        supporting_setups=(),
        direction=episode.direction,
        contract=episode.contract,
        trading_day=bar.trading_day,
        segment_start_trading_day=episode.segment_start_trading_day,
        quantity=quantity,
        limit_price=boundary,
        stop_price=episode.protective_stop,
        target_price=episode.target_1,
        reward_risk=None,
        reason="ADD_AUTHORIZED",
        episode_id=episode.episode_id,
    )


def _resolve_pending(
    pending: _Pending,
    *,
    bar: CanonicalBar,
    episode: _Episode | None,
    contract_multiplier: Decimal,
) -> tuple[list[JdjAction], _Episode | None, Decimal]:
    if pending.kind in (JdjActionKind.ENTRY, JdjActionKind.ADD):
        assert pending.limit_price is not None
        fill = _limit_fill(pending.direction, pending.limit_price, bar)
        if fill is None:
            return (
                [
                    _action_from_pending(
                        pending,
                        kind=JdjActionKind.REJECTED,
                        episode=episode,
                        effective_bar_end=bar.bar_end,
                        reference_price=None,
                        quantity=0,
                        reason=(
                            "ENTRY_LIMIT_EXPIRED"
                            if pending.kind is JdjActionKind.ENTRY
                            else "ADD_LIMIT_EXPIRED"
                        ),
                        fill_basis=None,
                    )
                ],
                episode,
                Decimal("0"),
            )
        fill_price, basis = fill
        if pending.kind is JdjActionKind.ENTRY:
            episode_id = _identity(
                "episode",
                *(event.event_id for event in pending.source_events),
                bar.bar_end.isoformat(),
            )
            episode = _Episode(
                episode_id=episode_id,
                source_event_ids=[event.event_id for event in pending.source_events],
                consumed_source_event_ids={event.event_id for event in pending.source_events},
                primary_setup=pending.primary_setup or "",
                supporting_setups=pending.supporting_setups,
                direction=pending.direction,
                contract=pending.contract,
                trading_day=pending.trading_day,
                segment_start_trading_day=pending.segment_start_trading_day,
                quantity=pending.quantity,
                weighted_average_cost=fill_price,
                protective_stop=pending.stop_price,
                target_1=pending.target_price,
            )
        else:
            if episode is None or episode.episode_id != pending.episode_id:
                raise JdjStrategyReplayError()
            total_quantity = episode.quantity + pending.quantity
            episode.weighted_average_cost = (
                episode.weighted_average_cost * Decimal(episode.quantity)
                + fill_price * Decimal(pending.quantity)
            ) / Decimal(total_quantity)
            episode.quantity = total_quantity
            episode.add_count += 1
            episode.protective_stop = episode.weighted_average_cost
            episode.source_event_ids.extend(
                event.event_id for event in pending.source_events
            )
            episode.consumed_source_event_ids.update(
                event.event_id for event in pending.source_events
            )
        assert episode is not None
        return (
            [
                _action_from_pending(
                    pending,
                    kind=pending.kind,
                    episode=episode,
                    effective_bar_end=bar.bar_end,
                    reference_price=fill_price,
                    quantity=pending.quantity,
                    reason=pending.reason,
                    fill_basis=basis,
                )
            ],
            episode,
            Decimal("0"),
        )

    if episode is None or episode.episode_id != pending.episode_id:
        raise JdjStrategyReplayError()
    quantity = min(pending.quantity, episode.quantity)
    pnl = _realized_pnl(
        episode.direction,
        episode.weighted_average_cost,
        bar.open,
        quantity,
        contract_multiplier,
    )
    episode.realized_pnl += pnl
    episode.quantity -= quantity
    if pending.kind is JdjActionKind.REDUCE:
        episode.partial_profit_taken = True
        episode.protective_stop = episode.weighted_average_cost
    action = _action_from_pending(
        pending,
        kind=pending.kind,
        episode=episode,
        effective_bar_end=bar.bar_end,
        reference_price=bar.open,
        quantity=quantity,
        reason=pending.reason,
        fill_basis="next_open",
    )
    if pending.kind is JdjActionKind.EXIT:
        episode = None
    return [action], episode, pnl


def _action_from_pending(
    pending: _Pending,
    *,
    kind: JdjActionKind,
    episode: _Episode | None,
    effective_bar_end: datetime,
    reference_price: Decimal | None,
    quantity: int,
    reason: str,
    fill_basis: str | None,
) -> JdjAction:
    position_after = episode.quantity if episode is not None else 0
    stop = episode.protective_stop if episode is not None else pending.stop_price
    return JdjAction(
        event_id=_identity(
            "action",
            kind.value,
            pending.decision_at.isoformat(),
            effective_bar_end.isoformat(),
            reason,
            pending.episode_id or "episode-pending",
            pending.contract,
            pending.segment_start_trading_day.isoformat(),
            pending.trading_day.isoformat(),
            *(event.event_id for event in pending.source_events),
        ),
        episode_id=episode.episode_id if episode is not None else pending.episode_id,
        kind=kind,
        source_event_ids=tuple(event.event_id for event in pending.source_events),
        primary_setup=pending.primary_setup,
        supporting_setups=pending.supporting_setups,
        direction=pending.direction,
        contract=pending.contract,
        trading_day=pending.trading_day,
        segment_start_trading_day=pending.segment_start_trading_day,
        decision_at=pending.decision_at,
        effective_bar_end=effective_bar_end,
        reference_price=reference_price,
        quantity=quantity,
        position_quantity_after=position_after,
        stop_price=stop,
        target_price=pending.target_price,
        reward_risk=pending.reward_risk,
        reason=reason,
        fill_basis=fill_basis,
    )


def _rejected(
    events: tuple[JdjTriggerEvent, ...],
    *,
    reason: str,
    episode: _Episode | None,
    stop: Decimal | None = None,
    target: Decimal | None = None,
    reward_risk: Decimal | None = None,
) -> JdjAction:
    ordered = _ordered_events(events)
    primary = ordered[0]
    return JdjAction(
        event_id=_identity("action", "rejected", reason, *(event.event_id for event in ordered)),
        episode_id=episode.episode_id if episode is not None else None,
        kind=JdjActionKind.REJECTED,
        source_event_ids=tuple(event.event_id for event in ordered),
        primary_setup=primary.setup_kind.value,
        supporting_setups=tuple(event.setup_kind.value for event in ordered[1:]),
        direction=primary.direction if len({event.direction for event in ordered}) == 1 else None,
        contract=primary.contract,
        trading_day=primary.trading_day,
        segment_start_trading_day=primary.segment_start_trading_day,
        decision_at=primary.observed_at,
        effective_bar_end=None,
        reference_price=None,
        quantity=0,
        position_quantity_after=episode.quantity if episode is not None else 0,
        stop_price=stop if stop is not None else (episode.protective_stop if episode else None),
        target_price=target if target is not None else (episode.target_1 if episode else None),
        reward_risk=reward_risk,
        reason=reason,
        fill_basis=None,
    )


def _daily_action(
    kind: JdjActionKind,
    *,
    reason: str,
    bar: CanonicalBar,
    episode: _Episode,
) -> JdjAction:
    return JdjAction(
        event_id=_identity(
            "action",
            kind.value,
            reason,
            episode.episode_id,
            episode.contract,
            episode.segment_start_trading_day.isoformat(),
            bar.trading_day.isoformat(),
            bar.bar_end.isoformat(),
        ),
        episode_id=episode.episode_id,
        kind=kind,
        source_event_ids=(),
        primary_setup=episode.primary_setup,
        supporting_setups=episode.supporting_setups,
        direction=episode.direction,
        contract=episode.contract,
        trading_day=bar.trading_day,
        segment_start_trading_day=episode.segment_start_trading_day,
        decision_at=bar.bar_end,
        effective_bar_end=None,
        reference_price=None,
        quantity=0,
        position_quantity_after=episode.quantity,
        stop_price=episode.protective_stop,
        target_price=episode.target_1,
        reward_risk=None,
        reason=reason,
        fill_basis=None,
    )


def _exit_pending(episode: _Episode, bar: CanonicalBar, *, reason: str) -> _Pending:
    return _Pending(
        kind=JdjActionKind.EXIT,
        decision_at=bar.bar_end,
        source_events=(),
        primary_setup=episode.primary_setup,
        supporting_setups=episode.supporting_setups,
        direction=episode.direction,
        contract=episode.contract,
        trading_day=bar.trading_day,
        segment_start_trading_day=episode.segment_start_trading_day,
        quantity=episode.quantity,
        limit_price=None,
        stop_price=episode.protective_stop,
        target_price=episode.target_1,
        reward_risk=None,
        reason=reason,
        episode_id=episode.episode_id,
    )


def _reject_all(
    events: tuple[JdjTriggerEvent, ...],
    actions: list[JdjAction],
    episode: _Episode | None,
    reason: str,
) -> None:
    if events:
        actions.append(_rejected(events, reason=reason, episode=episode))


def _ordered_events(events: tuple[JdjTriggerEvent, ...]) -> tuple[JdjTriggerEvent, ...]:
    return tuple(sorted(events, key=lambda event: (_SETUP_PRIORITY[event.setup_kind], event.event_id)))


def _structural_stop(event: JdjTriggerEvent, bars: tuple[CanonicalBar, ...]) -> Decimal:
    if isinstance(event, JdjTrendReentryTriggerEvent):
        return event.excursion_extreme
    if isinstance(event, JdjKeyLevelBreakoutTriggerEvent):
        return event.key_level_price
    reaction = next((bar for bar in bars if bar.bar_end == event.reaction_at), None)
    if reaction is None:
        raise JdjStrategyReplayError()
    return reaction.low if event.direction is JdjDirection.LONG else reaction.high


def _known_target(
    *,
    direction: JdjDirection,
    entry_reference: Decimal,
    contract: str,
    segment_start_trading_day: date,
    context: JdjBarContext,
    day_high: Decimal,
    day_low: Decimal,
) -> Decimal | None:
    levels: list[Decimal] = []
    pivot = (
        context.eligible_high_pivot
        if direction is JdjDirection.LONG
        else context.eligible_low_pivot
    )
    if pivot is not None and (
        pivot.contract != contract
        or pivot.segment_start_trading_day != segment_start_trading_day
        or pivot.confirmed_at > context.bar.bar_end
    ):
        pivot = None
    if direction is JdjDirection.LONG:
        if pivot is not None:
            levels.append(pivot.price)
        levels.append(day_high)
        favorable = [level for level in levels if level > entry_reference]
    else:
        if pivot is not None:
            levels.append(pivot.price)
        levels.append(day_low)
        favorable = [level for level in levels if level < entry_reference]
    return min(favorable, key=lambda level: abs(level - entry_reference)) if favorable else None


def _admissible_boundary(target: Decimal, stop: Decimal, ratio: Decimal) -> Decimal:
    return (target + ratio * stop) / (Decimal("1") + ratio)


def _directional_distance(
    direction: JdjDirection,
    favorable: Decimal,
    adverse: Decimal,
) -> Decimal:
    return favorable - adverse if direction is JdjDirection.LONG else adverse - favorable


def _limit_fill(
    direction: JdjDirection,
    limit_price: Decimal,
    bar: CanonicalBar,
) -> tuple[Decimal, str] | None:
    if direction is JdjDirection.LONG:
        if bar.open <= limit_price:
            return bar.open, "better_open"
        if bar.low <= limit_price:
            return limit_price, "limit_touch"
    else:
        if bar.open >= limit_price:
            return bar.open, "better_open"
        if bar.high >= limit_price:
            return limit_price, "limit_touch"
    return None


def _completed_bar_exit_reason(
    episode: _Episode,
    context: JdjBarContext,
) -> str | None:
    close = context.bar.close
    if (
        episode.direction is JdjDirection.LONG
        and close <= episode.protective_stop
    ) or (
        episode.direction is JdjDirection.SHORT
        and close >= episode.protective_stop
    ):
        return "PROTECTIVE_STOP_CROSSED"
    if context.ema20 is not None and (
        (episode.direction is JdjDirection.LONG and close <= context.ema20)
        or (episode.direction is JdjDirection.SHORT and close >= context.ema20)
    ):
        return "EMA20_LOST"
    supporting_trend = (
        NStructureKind.BULL
        if episode.direction is JdjDirection.LONG
        else NStructureKind.BEAR
    )
    if context.trend_kind is not supporting_trend:
        return "TREND_CONTEXT_LOST"
    return None


def _target_reached(episode: _Episode, close: Decimal) -> bool:
    return (
        close >= episode.target_1
        if episode.direction is JdjDirection.LONG
        else close <= episode.target_1
    )


def _terminal_guard(
    index: int,
    bars: tuple[CanonicalBar, ...],
    *,
    terminal_bar_end_by_day: Mapping[date, datetime],
) -> bool:
    bar = bars[index]
    terminal = terminal_bar_end_by_day[bar.trading_day].astimezone(UTC)
    if bar.bar_end == terminal:
        return True
    return (
        index + 1 < len(bars)
        and bars[index + 1].trading_day == bar.trading_day
        and bars[index + 1].bar_end == terminal
    )


def _marked_equity(
    cash_equity: Decimal,
    episode: _Episode | None,
    mark: Decimal,
    contract_multiplier: Decimal,
) -> Decimal:
    if episode is None:
        return cash_equity
    return cash_equity + _realized_pnl(
        episode.direction,
        episode.weighted_average_cost,
        mark,
        episode.quantity,
        contract_multiplier,
    )


def _realized_pnl(
    direction: JdjDirection,
    cost: Decimal,
    price: Decimal,
    quantity: int,
    contract_multiplier: Decimal,
) -> Decimal:
    move = price - cost if direction is JdjDirection.LONG else cost - price
    return move * Decimal(quantity) * contract_multiplier


def _floor_quantity(value: Decimal) -> int:
    if not value.is_finite() or value <= 0:
        return 0
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _identity(prefix: str, *parts: str) -> str:
    payload = "|".join((prefix, *parts)).encode("utf-8")
    return f"jdj-{prefix}-{sha256(payload).hexdigest()}"
