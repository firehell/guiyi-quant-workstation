"""Deterministic state transitions for a single reference-trading stream."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, localcontext
from hashlib import sha256
import json

from .contracts import (
    ActionKind, BoundaryReason, CompletedReferenceBar, ReferenceAction, ReferenceBoundary, ReferenceState,
    ReferenceMark, ReferenceTrade, ReferenceTransition, ReturnPolicy, Side, TradeStatus,
)


def _trade_id(action: ReferenceAction) -> str:
    value = f"{action.stream.stream_id}|{action.source_action_id}".encode()
    return f"reference-trade:{sha256(value).hexdigest()}"


def _return(entry: Decimal, exit_: Decimal, side: Side, policy: ReturnPolicy) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        ratio = (
            exit_ / entry - Decimal("1")
            if policy is ReturnPolicy.RATIO_MINUS_ONE
            else (exit_ - entry) / entry
        )
        return ratio * Decimal("100") if side is Side.LONG else -ratio * Decimal("100")


def _validate_stream(state: ReferenceState, item: ReferenceAction | ReferenceBoundary) -> None:
    if item.stream != state.stream:
        raise ValueError("input belongs to a different stream")


def _validate_open_match(trade: ReferenceTrade, action: ReferenceAction) -> None:
    if action.entry_action_id != trade.entry_action_id:
        raise ValueError("CLOSE must explicitly reference current entry_action_id")
    if (action.physical_contract, action.owner_segment_id, action.calculation_segment_id) != (
        trade.physical_contract, trade.owner_segment_id, trade.calculation_segment_id,
    ):
        raise ValueError("CLOSE must match entry physical contract and segments")
    if action.bar_end < trade.entry_bar_end:
        raise ValueError("CLOSE bar_end cannot precede entry")


def _input_hash(
    actions: tuple[ReferenceAction, ...], boundaries: tuple[ReferenceBoundary, ...],
    completed: CompletedReferenceBar | None, return_policy: ReturnPolicy,
) -> str:
    """Hash just this bounded input batch; durable deduplication remains P3 work."""
    def action_wire(action: ReferenceAction) -> tuple[object, ...]:
        return (
            action.stream.stream_id, action.source_action_id, action.physical_contract,
            action.owner_segment_id, action.calculation_segment_id, action.bar_end.isoformat(),
            action.trading_day.isoformat(), action.sequence, action.kind.value, str(action.reference_price),
            action.entry_action_id, action.reference_price_type,
        )

    def boundary_wire(boundary: ReferenceBoundary) -> tuple[object, ...]:
        return (
            boundary.stream.stream_id, boundary.reason.value, boundary.physical_contract,
            boundary.owner_segment_id, boundary.calculation_segment_id, boundary.bar_end.isoformat(),
            boundary.trading_day.isoformat(),
        )

    completed_wire = None if completed is None else (
        completed.physical_contract, completed.owner_segment_id, completed.calculation_segment_id,
        completed.bar_end.isoformat(), completed.trading_day.isoformat(), str(completed.reference_price),
    )
    wire = {
        "actions": [action_wire(action) for action in actions],
        "boundaries": [boundary_wire(boundary) for boundary in boundaries],
        "completed": completed_wire,
        "return_policy": return_policy.value,
    }
    return sha256(json.dumps(wire, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def reduce_reference(
    state: ReferenceState,
    *,
    actions: tuple[ReferenceAction, ...] = (),
    boundaries: tuple[ReferenceBoundary, ...] = (),
    completed_bar_end: datetime | None = None,
    completed_trading_day: date | None = None,
    completed_reference_price: Decimal | None = None,
    completed_bar: CompletedReferenceBar | None = None,
    return_policy: ReturnPolicy | str = ReturnPolicy.RATIO_MINUS_ONE,
) -> ReferenceTransition:
    """Apply one already-validated completed input batch without side effects."""
    if not isinstance(state, ReferenceState):
        raise TypeError("state must be ReferenceState")
    return_policy = ReturnPolicy(return_policy)
    actions = tuple(actions)
    boundaries = tuple(boundaries)
    for action in actions:
        if not isinstance(action, ReferenceAction):
            raise TypeError("actions must contain ReferenceAction")
        _validate_stream(state, action)
    for boundary in boundaries:
        if not isinstance(boundary, ReferenceBoundary):
            raise TypeError("boundaries must contain ReferenceBoundary")
        _validate_stream(state, boundary)
    keys = [(action.bar_end, action.sequence) for action in actions]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise ValueError("actions must be strictly increasing by bar_end and sequence")
    source_ids = [action.source_action_id for action in actions]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("actions must not repeat source_action_id")
    boundary_keys = [
        (boundary.bar_end, boundary.physical_contract, boundary.owner_segment_id, boundary.calculation_segment_id)
        for boundary in boundaries
    ]
    if len(boundary_keys) != len(set(boundary_keys)):
        raise ValueError("boundaries must not repeat a segment at the same bar_end")
    if completed_bar is not None:
        if not isinstance(completed_bar, CompletedReferenceBar):
            raise TypeError("completed_bar must be CompletedReferenceBar")
        if any(value is not None for value in (completed_bar_end, completed_trading_day, completed_reference_price)):
            raise ValueError("completed_bar cannot be combined with legacy completed fields")
        completed_bar_end = completed_bar.bar_end
        completed_trading_day = completed_bar.trading_day
        completed_reference_price = completed_bar.reference_price
    if completed_bar_end is not None:
        from .contracts import _day, _instant
        _instant(completed_bar_end, "completed_bar_end")
        _day(completed_trading_day, "completed_trading_day")
        if completed_reference_price is not None:
            from .contracts import _price
            _price(completed_reference_price, "completed_reference_price")

    input_hash = _input_hash(actions, boundaries, completed_bar, return_policy)
    positions = [*(action.bar_end for action in actions), *(boundary.bar_end for boundary in boundaries)]
    target = completed_bar_end
    if completed_bar_end is not None and any(position > completed_bar_end for position in positions):
        raise ValueError("completed_bar_end must cover every input")
    if state.recording_start is not None:
        if any(position < state.recording_start for position in positions) or (
            completed_bar_end is not None and completed_bar_end < state.recording_start
        ):
            raise ValueError("input must not precede recording_start")
    if target is not None and state.computed_through is not None:
        if target < state.computed_through:
            raise ValueError("input must not precede computed_through")
        if target == state.computed_through:
            if state.last_input_hash == input_hash:
                return ReferenceTransition(state=state, changed_trades=(), marks=(), diagnostics=())
            raise ValueError("input conflicts with computed_through")
    if state.computed_through is not None and any(position <= state.computed_through for position in positions):
        raise ValueError("input must strictly follow computed_through")

    entries = [*((action.bar_end, 0, action.sequence, action) for action in actions), *((boundary.bar_end, 1, 0, boundary) for boundary in boundaries)]
    event_keys = [entry[:3] for entry in entries]
    if state.last_event_key is not None and event_keys and min(event_keys) <= state.last_event_key:
        if state.last_input_hash == input_hash:
            return ReferenceTransition(state=state, changed_trades=(), marks=(), diagnostics=())
        raise ValueError("input must strictly follow the prior event")

    current = state.open_trade
    changed: list[ReferenceTrade] = []
    marks: list[ReferenceMark] = []
    diagnostics: list[str] = []
    for _, _, _, item in sorted(entries, key=lambda entry: entry[:3]):
        if isinstance(item, ReferenceBoundary):
            if current is None:
                continue
            if (item.physical_contract, item.owner_segment_id, item.calculation_segment_id) != (
                current.physical_contract, current.owner_segment_id, current.calculation_segment_id,
            ):
                continue
            status = {
                BoundaryReason.ROLLOVER: TradeStatus.ROLLOVER_INTERRUPTED,
                BoundaryReason.DATA_INTERRUPTED: TradeStatus.DATA_INTERRUPTED,
                BoundaryReason.OBSERVATION_INTERRUPTED: TradeStatus.OBSERVATION_INTERRUPTED,
            }[item.reason]
            changed.append(replace(
                current, status=status, mark_bar_end=None, mark_trading_day=None,
                mark_reference_price=None, mark_return=None,
            ))
            current = None
            continue
        action = item
        if action.kind is ActionKind.HINT:
            continue
        if action.kind in (ActionKind.OPEN_LONG, ActionKind.OPEN_SHORT):
            if current is not None:
                raise ValueError("OPEN requires FLAT state")
            side = Side.LONG if action.kind is ActionKind.OPEN_LONG else Side.SHORT
            current = ReferenceTrade(
                reference_trade_id=_trade_id(action), stream=action.stream, side=side,
                physical_contract=action.physical_contract, owner_segment_id=action.owner_segment_id,
                calculation_segment_id=action.calculation_segment_id, entry_action_id=action.source_action_id,
                entry_bar_end=action.bar_end, entry_trading_day=action.trading_day,
                entry_reference_price=action.reference_price,
            )
            changed.append(current)
            continue
        if current is None:
            diagnostics.append("NO_OBSERVED_ENTRY" if state.stream.recording_mode.value == "forward_observation" else "NO_ENTRY")
            continue
        _validate_open_match(current, action)
        closed = replace(
            current, status=TradeStatus.CLOSED, exit_action_id=action.source_action_id,
            exit_bar_end=action.bar_end, exit_trading_day=action.trading_day,
            exit_reference_price=action.reference_price,
            reference_return=_return(
                current.entry_reference_price, action.reference_price, current.side, return_policy,
            ),
            holding_bars=current.holding_bars + int(
                action.bar_end > (current.mark_bar_end or current.entry_bar_end)
            ),
            mark_bar_end=None, mark_trading_day=None, mark_reference_price=None, mark_return=None,
        )
        changed.append(closed)
        current = None

    computed_through = state.computed_through
    if completed_bar_end is not None:
        if computed_through is not None and completed_bar_end < computed_through:
            raise ValueError("completed_bar_end must not move backwards")
        computed_through = completed_bar_end
        if current is not None:
            if completed_reference_price is None:
                raise ValueError("OPEN completed bar requires completed_reference_price")
            if completed_bar is not None and (
                completed_bar.physical_contract,
                completed_bar.owner_segment_id,
                completed_bar.calculation_segment_id,
            ) != (
                current.physical_contract,
                current.owner_segment_id,
                current.calculation_segment_id,
            ):
                raise ValueError("completed_bar must match OPEN physical contract and segments")
            holding_bars = current.holding_bars + int(completed_bar_end > current.entry_bar_end)
            mark_return = _return(
                current.entry_reference_price, completed_reference_price, current.side, return_policy,
            )
            current = replace(
                current, holding_bars=holding_bars, mark_bar_end=completed_bar_end,
                mark_trading_day=completed_trading_day, mark_reference_price=completed_reference_price,
                mark_return=mark_return,
            )
            marks.append(ReferenceMark(
                reference_trade_id=current.reference_trade_id, bar_end=completed_bar_end,
                trading_day=completed_trading_day, reference_price=completed_reference_price,
                holding_bars=holding_bars, reference_return=mark_return,
            ))
    elif target is not None:
        computed_through = target
    return ReferenceTransition(
        state=ReferenceState(
            stream=state.stream, recording_start=state.recording_start, computed_through=computed_through,
            open_trade=current, last_input_hash=input_hash,
            last_event_key=max(event_keys) if event_keys else state.last_event_key,
        ),
        changed_trades=tuple(changed), marks=tuple(marks), diagnostics=tuple(diagnostics),
    )
