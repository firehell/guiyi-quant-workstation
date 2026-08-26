"""Pure causal 15m reducer for one physical SuBing Strategy segment."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from ..domain import BarFrequency, CanonicalBar, normalize_contract_for_symbol
from ..subing_research import MacdCross, SubingDirection, SubingFactorSnapshot
from ..subing_structure import ConfirmedPivot
from .contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyFillBasis,
    SubingStrategyPositionState,
    subing_strategy_action_id,
    subing_strategy_episode_id,
)
from .direction_context import SubingStrategyDirectionContext
from .entry_projection import SubingStrategyEntryCandidate
from .policy import SubingStrategyPolicy

if TYPE_CHECKING:
    from ..aggregation import SessionWindow
    from ..subing_calibration import SubingCalibration
    from ..subing_lifecycle_policy import SubingLifecyclePolicy
    from .machine import SubingStrategyInterval


@dataclass(frozen=True, slots=True)
class SubingStrategyDecisionFrame:
    bar: CanonicalBar
    previous_bar: CanonicalBar | None
    factor: SubingFactorSnapshot
    direction_context: SubingStrategyDirectionContext
    entry_candidates: tuple[SubingStrategyEntryCandidate, ...]


@dataclass(frozen=True, slots=True)
class SubingStrategyPendingAction:
    kind: SubingStrategyActionKind
    decision_at: datetime
    candidate: SubingStrategyEntryCandidate | None
    direction_context: SubingStrategyDirectionContext | None
    episode_id: str | None
    opportunity_id: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubingStrategyPendingCancellation:
    kind: SubingStrategyActionKind
    decision_at: datetime
    opportunity_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class SubingStrategyPosition:
    state: SubingStrategyPositionState
    entry_action: SubingStrategyAction
    bound_reference_pivot: ConfirmedPivot | None


@dataclass(frozen=True, slots=True)
class SubingStrategySegmentResult:
    actions: tuple[SubingStrategyAction, ...]
    episodes: tuple[SubingStrategyEpisode, ...]
    consumed_opportunity_ids: tuple[str, ...]
    canceled_pending: tuple[SubingStrategyPendingCancellation, ...]
    pending_action: SubingStrategyPendingAction | None
    final_position: SubingStrategyPositionState


def exit_reason_codes(
    *,
    position: SubingStrategyPosition,
    frame: SubingStrategyDecisionFrame,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if position.state is SubingStrategyPositionState.LONG:
        if frame.bar.close < frame.factor.ema21:
            reasons.append("EMA21_BREACH_LONG")
        if frame.previous_bar is not None and frame.bar.close < frame.previous_bar.low:
            reasons.append("PREVIOUS_BAR_LOW_BREACH")
        pivot = position.bound_reference_pivot
        if pivot is not None and frame.bar.close < pivot.price:
            reasons.append("BOUND_LOW_PIVOT_BREACH")
        if (
            frame.factor.macd_cross is MacdCross.DEAD
            and frame.factor.macd_cross_level > 0
        ):
            reasons.append("MACD_HIGH_DEAD_CROSS")
    elif position.state is SubingStrategyPositionState.SHORT:
        if frame.bar.close > frame.factor.ema21:
            reasons.append("EMA21_BREACH_SHORT")
        if frame.previous_bar is not None and frame.bar.close > frame.previous_bar.high:
            reasons.append("PREVIOUS_BAR_HIGH_BREACH")
        pivot = position.bound_reference_pivot
        if pivot is not None and frame.bar.close > pivot.price:
            reasons.append("BOUND_HIGH_PIVOT_BREACH")
        if (
            frame.factor.macd_cross is MacdCross.GOLDEN
            and frame.factor.macd_cross_level < 0
        ):
            reasons.append("MACD_LOW_GOLDEN_CROSS")
    return tuple(reasons)


def run_subing_strategy_segment(
    *,
    symbol: str,
    contract: str,
    segment_start: date,
    frames: Sequence[SubingStrategyDecisionFrame],
    first_1m_bars: Sequence[CanonicalBar],
    intervals: Sequence[SubingStrategyInterval],
    sessions: Sequence[SessionWindow],
    calibration: SubingCalibration,
    lifecycle_policy: SubingLifecyclePolicy,
    policy: SubingStrategyPolicy,
    terminal_bar_end: datetime | None,
) -> SubingStrategySegmentResult:
    """Reduce one physical segment prefix without reading beyond each frame."""
    frame_tuple = tuple(frames)
    first_minutes = tuple(first_1m_bars)
    interval_tuple = tuple(intervals)
    from .machine import (
        SubingStrategyInterval,
        authoritative_subing_strategy_intervals,
        replay_subing_strategy_frames,
    )

    _validate_reducer_inputs(
        symbol=symbol,
        contract=contract,
        segment_start=segment_start,
        frames=frame_tuple,
        policy=policy,
        terminal_bar_end=terminal_bar_end,
    )
    authoritative_intervals = authoritative_subing_strategy_intervals(
        bars_1m=first_minutes,
        bars_15m=tuple(frame.bar for frame in frame_tuple),
        sessions=sessions,
    )
    if (
        len(first_minutes) != len(frame_tuple)
        or len(interval_tuple) != len(frame_tuple)
        or any(
            type(interval) is not SubingStrategyInterval for interval in interval_tuple
        )
        or any(
            interval.effective_bar_end != frame.bar.bar_end
            or interval.first_1m_bar_end != minute.bar_end
            or interval.expected_open != frame.bar.open
            or minute.trading_day != frame.bar.trading_day
            or minute.open != frame.bar.open
            for minute, frame, interval in zip(
                first_minutes,
                frame_tuple,
                interval_tuple,
                strict=True,
            )
        )
        or interval_tuple != authoritative_intervals
    ):
        raise ValueError("SUBING_STRATEGY_FIRST_1M_IDENTITY_INVALID")
    return replay_subing_strategy_frames(
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start,
        frames=frame_tuple,
        first_1m_bars=first_minutes,
        intervals=interval_tuple,
        calibration=calibration,
        lifecycle_policy=lifecycle_policy,
        strategy_policy=policy,
        terminal_bar_end=terminal_bar_end,
    )


def decide_completed_15m(
    *,
    frame: SubingStrategyDecisionFrame,
    position: SubingStrategyPosition | None,
    pending_action: SubingStrategyPendingAction | None,
    consumed_opportunity_ids: frozenset[str],
) -> tuple[SubingStrategyPendingAction | None, tuple[str, ...]]:
    """Decide exactly once at a completed 15m boundary; never apply an Action."""

    pending = pending_action
    if position is not None:
        reasons = exit_reason_codes(position=position, frame=frame)
        if reasons:
            pending = _pending_close(position, frame=frame, reasons=reasons)
    newly_consumed: list[str] = []
    eligible_entry: SubingStrategyEntryCandidate | None = None
    seen = set(consumed_opportunity_ids)
    for candidate in frame.entry_candidates:
        if candidate.opportunity_id in seen:
            continue
        seen.add(candidate.opportunity_id)
        newly_consumed.append(candidate.opportunity_id)
        if (
            position is None
            and pending is None
            and eligible_entry is None
            and _context_allows_entry(candidate, frame.direction_context)
        ):
            eligible_entry = candidate
    if eligible_entry is not None:
        pending = _pending_open(eligible_entry, context=frame.direction_context)
    return pending, tuple(newly_consumed)


def apply_pending_next_open(
    pending: SubingStrategyPendingAction,
    *,
    first_1m_bar: CanonicalBar,
    effective_bar_end: datetime,
    symbol: str,
    contract: str,
    segment_start: date,
    position: SubingStrategyPosition | None,
) -> tuple[
    SubingStrategyAction,
    SubingStrategyPosition | None,
    tuple[SubingStrategyAction, SubingStrategyAction] | None,
]:
    """Apply a pending decision from the authoritative first completed 1m Bar."""

    if (
        not isinstance(first_1m_bar, CanonicalBar)
        or first_1m_bar.bar_end >= effective_bar_end
        or pending.decision_at >= effective_bar_end
    ):
        raise ValueError("SUBING_STRATEGY_FIRST_1M_IDENTITY_INVALID")
    effective_open_at = first_1m_bar.bar_end - timedelta(minutes=1)
    if pending.kind in {
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.OPEN_SHORT,
    }:
        if (
            position is not None
            or pending.candidate is None
            or pending.direction_context is None
        ):
            raise ValueError("SUBING_STRATEGY_PENDING_INVALID")
        action = _open_action(
            pending,
            first_1m_bar=first_1m_bar,
            effective_open_at=effective_open_at,
            effective_bar_end=effective_bar_end,
            symbol=symbol,
            contract=contract,
            segment_start=segment_start,
        )
        return (
            action,
            SubingStrategyPosition(
                state=(
                    SubingStrategyPositionState.LONG
                    if action.kind is SubingStrategyActionKind.OPEN_LONG
                    else SubingStrategyPositionState.SHORT
                ),
                entry_action=action,
                bound_reference_pivot=action.bound_reference_pivot,
            ),
            None,
        )
    if position is None or pending.episode_id != position.entry_action.episode_id:
        raise ValueError("SUBING_STRATEGY_PENDING_INVALID")
    close = _close_action(
        position,
        symbol=symbol,
        contract=contract,
        segment_start=segment_start,
        trading_day=first_1m_bar.trading_day,
        decision_at=pending.decision_at,
        effective_open_at=effective_open_at,
        effective_bar_end=effective_bar_end,
        reference_price=first_1m_bar.open,
        fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
        reason_codes=pending.reason_codes,
    )
    return close, None, (position.entry_action, close)


def finalize_segment(
    *,
    position: SubingStrategyPosition,
    pending_action: SubingStrategyPendingAction | None,
    terminal_bar: CanonicalBar,
    symbol: str,
    contract: str,
    segment_start: date,
) -> SubingStrategyAction:
    """Close one remaining position on the authoritative terminal 15m close."""

    reasons = (pending_action.reason_codes if pending_action is not None else ()) + (
        "CONTRACT_SEGMENT_END",
    )
    return _close_action(
        position,
        symbol=symbol,
        contract=contract,
        segment_start=segment_start,
        trading_day=terminal_bar.trading_day,
        decision_at=(
            pending_action.decision_at
            if pending_action is not None
            else terminal_bar.bar_end
        ),
        effective_open_at=None,
        effective_bar_end=terminal_bar.bar_end,
        reference_price=terminal_bar.close,
        fill_basis=SubingStrategyFillBasis.SEGMENT_TERMINAL_CLOSE,
        reason_codes=reasons,
    )


def _validate_reducer_inputs(
    *,
    symbol: str,
    contract: str,
    segment_start: date,
    frames: tuple[SubingStrategyDecisionFrame, ...],
    policy: SubingStrategyPolicy,
    terminal_bar_end: datetime | None,
) -> None:
    if (
        not isinstance(policy, SubingStrategyPolicy)
        or not isinstance(symbol, str)
        or symbol != symbol.strip().lower()
        or not symbol.isascii()
        or not symbol.isalpha()
        or normalize_contract_for_symbol(symbol, contract) != contract
        or type(segment_start) is not date
        or any(not isinstance(frame, SubingStrategyDecisionFrame) for frame in frames)
        or any(
            left.bar.bar_end >= right.bar.bar_end
            for left, right in zip(frames, frames[1:])
        )
    ):
        raise ValueError("SUBING_STRATEGY_SEGMENT_INPUT_INVALID")
    if terminal_bar_end is not None and (
        not isinstance(terminal_bar_end, datetime)
        or not frames
        or terminal_bar_end.tzinfo is None
        or terminal_bar_end.utcoffset() is None
        or terminal_bar_end.astimezone(UTC) != frames[-1].bar.bar_end
    ):
        raise ValueError("SUBING_STRATEGY_TERMINAL_INVALID")
    for index, frame in enumerate(frames):
        expected_previous = frames[index - 1].bar if index else None
        context = frame.direction_context
        if (
            frame.previous_bar != expected_previous
            or frame.factor.timeframe is not BarFrequency.M15
            or frame.factor.bar_end != frame.bar.bar_end
            or frame.factor.trading_day != frame.bar.trading_day
            or frame.factor.contract != contract
            or frame.factor.segment_start_trading_day != segment_start
            or frame.bar.trading_day < segment_start
            or context.symbol != symbol
            or context.target_trading_day != frame.bar.trading_day
            or type(frame.entry_candidates) is not tuple
            or any(
                candidate.decision_bar_end != frame.bar.bar_end
                or candidate.opportunity_key.symbol != symbol
                or candidate.opportunity_key.contract != contract
                or candidate.opportunity_key.segment_start_trading_day != segment_start
                for candidate in frame.entry_candidates
            )
        ):
            raise ValueError("SUBING_STRATEGY_FRAME_IDENTITY_INVALID")


def _context_allows_entry(
    candidate: SubingStrategyEntryCandidate,
    context: SubingStrategyDirectionContext,
) -> bool:
    from .contracts import SubingStrategyDirection

    return (
        candidate.direction is SubingDirection.LONG
        and context.direction is SubingStrategyDirection.LONG_ONLY
    ) or (
        candidate.direction is SubingDirection.SHORT
        and context.direction is SubingStrategyDirection.SHORT_ONLY
    )


def _pending_open(
    candidate: SubingStrategyEntryCandidate,
    *,
    context: SubingStrategyDirectionContext,
) -> SubingStrategyPendingAction:
    return SubingStrategyPendingAction(
        kind=(
            SubingStrategyActionKind.OPEN_LONG
            if candidate.direction is SubingDirection.LONG
            else SubingStrategyActionKind.OPEN_SHORT
        ),
        decision_at=candidate.decision_bar_end,
        candidate=candidate,
        direction_context=context,
        episode_id=None,
        opportunity_id=candidate.opportunity_id,
        reason_codes=(),
    )


def _pending_close(
    position: SubingStrategyPosition,
    *,
    frame: SubingStrategyDecisionFrame,
    reasons: tuple[str, ...],
) -> SubingStrategyPendingAction:
    return SubingStrategyPendingAction(
        kind=(
            SubingStrategyActionKind.CLOSE_LONG
            if position.state is SubingStrategyPositionState.LONG
            else SubingStrategyActionKind.CLOSE_SHORT
        ),
        decision_at=frame.bar.bar_end,
        candidate=None,
        direction_context=None,
        episode_id=position.entry_action.episode_id,
        opportunity_id=position.entry_action.opportunity_id,
        reason_codes=reasons,
    )


def _open_action(
    pending: SubingStrategyPendingAction,
    *,
    first_1m_bar: CanonicalBar,
    effective_open_at: datetime,
    effective_bar_end: datetime,
    symbol: str,
    contract: str,
    segment_start: date,
) -> SubingStrategyAction:
    candidate = pending.candidate
    context = pending.direction_context
    assert candidate is not None and context is not None
    identity = _action_identity(
        symbol=symbol,
        contract=contract,
        segment_start=segment_start,
        opportunity_id=candidate.opportunity_id,
        kind=pending.kind,
        decision_at=pending.decision_at,
        effective_bar_end=effective_bar_end,
        fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
    )
    return SubingStrategyAction(
        action_id=subing_strategy_action_id(identity),
        episode_id=subing_strategy_episode_id(identity),
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        kind=pending.kind,
        symbol=symbol,
        contract=contract,
        trading_day=first_1m_bar.trading_day,
        segment_start_trading_day=segment_start,
        opportunity_id=candidate.opportunity_id,
        decision_at=pending.decision_at,
        effective_open_at=effective_open_at,
        effective_bar_end=effective_bar_end,
        reference_price=first_1m_bar.open,
        fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
        confirmation_source=candidate.confirmation_source,
        reason_codes=(),
        direction_context_source_day=context.source_trading_day,
        direction_context_target_day=context.target_trading_day,
        bound_reference_pivot=candidate.bound_reference_pivot,
    )


def _close_action(
    position: SubingStrategyPosition,
    *,
    symbol: str,
    contract: str,
    segment_start: date,
    trading_day: date,
    decision_at: datetime,
    effective_open_at: datetime | None,
    effective_bar_end: datetime,
    reference_price: Decimal,
    fill_basis: SubingStrategyFillBasis,
    reason_codes: tuple[str, ...],
) -> SubingStrategyAction:
    kind = (
        SubingStrategyActionKind.CLOSE_LONG
        if position.state is SubingStrategyPositionState.LONG
        else SubingStrategyActionKind.CLOSE_SHORT
    )
    identity = _action_identity(
        symbol=symbol,
        contract=contract,
        segment_start=segment_start,
        opportunity_id=position.entry_action.opportunity_id,
        kind=kind,
        decision_at=decision_at,
        effective_bar_end=effective_bar_end,
        fill_basis=fill_basis,
    )
    return SubingStrategyAction(
        action_id=subing_strategy_action_id(identity),
        episode_id=position.entry_action.episode_id,
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        kind=kind,
        symbol=symbol,
        contract=contract,
        trading_day=trading_day,
        segment_start_trading_day=segment_start,
        opportunity_id=position.entry_action.opportunity_id,
        decision_at=decision_at,
        effective_open_at=effective_open_at,
        effective_bar_end=effective_bar_end,
        reference_price=reference_price,
        fill_basis=fill_basis,
        confirmation_source=None,
        reason_codes=reason_codes,
        direction_context_source_day=None,
        direction_context_target_day=None,
        bound_reference_pivot=position.bound_reference_pivot,
    )


def _action_identity(
    *,
    symbol: str,
    contract: str,
    segment_start: date,
    opportunity_id: str,
    kind: SubingStrategyActionKind,
    decision_at: datetime,
    effective_bar_end: datetime,
    fill_basis: SubingStrategyFillBasis,
) -> dict[str, object]:
    return {
        "strategy_id": "subing_strategy_v1",
        "formula_version": "subing_strategy_15m_v1",
        "symbol": symbol,
        "contract": contract,
        "segment_start_trading_day": segment_start.isoformat(),
        "opportunity_id": opportunity_id,
        "kind": kind.value,
        "decision_at": decision_at.astimezone(UTC).isoformat(),
        "effective_bar_end": effective_bar_end.astimezone(UTC).isoformat(),
        "fill_basis": fill_basis.value,
    }
