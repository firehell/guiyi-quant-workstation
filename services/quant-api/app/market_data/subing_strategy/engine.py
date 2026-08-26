"""Pure causal 15m reducer for one physical SuBing Strategy segment."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

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
    policy: SubingStrategyPolicy,
    terminal_bar_end: datetime | None,
) -> SubingStrategySegmentResult:
    """Reduce one physical segment prefix without reading beyond each frame."""
    frame_tuple = tuple(frames)
    _validate_reducer_inputs(
        symbol=symbol,
        contract=contract,
        segment_start=segment_start,
        frames=frame_tuple,
        policy=policy,
        terminal_bar_end=terminal_bar_end,
    )
    actions: list[SubingStrategyAction] = []
    closed_pairs: list[tuple[SubingStrategyAction, SubingStrategyAction]] = []
    consumed: list[str] = []
    consumed_set: set[str] = set()
    canceled: list[SubingStrategyPendingCancellation] = []
    pending: SubingStrategyPendingAction | None = None
    position: SubingStrategyPosition | None = None

    for frame in frame_tuple:
        if pending is not None:
            applied, position, closed_pair = _apply_pending(
                pending,
                frame=frame,
                symbol=symbol,
                contract=contract,
                segment_start=segment_start,
                position=position,
            )
            actions.append(applied)
            if closed_pair is not None:
                closed_pairs.append(closed_pair)
            pending = None

        if position is not None:
            reasons = exit_reason_codes(position=position, frame=frame)
            if reasons:
                pending = _pending_close(position, frame=frame, reasons=reasons)

        eligible_entry: SubingStrategyEntryCandidate | None = None
        for candidate in frame.entry_candidates:
            if candidate.opportunity_id in consumed_set:
                continue
            consumed_set.add(candidate.opportunity_id)
            consumed.append(candidate.opportunity_id)
            if (
                position is None
                and pending is None
                and eligible_entry is None
                and _context_allows_entry(candidate, frame.direction_context)
            ):
                eligible_entry = candidate
        if eligible_entry is not None:
            pending = _pending_open(
                eligible_entry,
                context=frame.direction_context,
            )

    if terminal_bar_end is not None and frame_tuple:
        final_frame = frame_tuple[-1]
        if pending is not None and pending.kind in {
            SubingStrategyActionKind.OPEN_LONG,
            SubingStrategyActionKind.OPEN_SHORT,
        }:
            canceled.append(
                SubingStrategyPendingCancellation(
                    kind=pending.kind,
                    decision_at=pending.decision_at,
                    opportunity_id=pending.opportunity_id,
                    reason_code="NEXT_BAR_UNAVAILABLE",
                )
            )
            pending = None
        elif position is not None:
            reasons = (
                pending.reason_codes if pending is not None else ()
            ) + ("CONTRACT_SEGMENT_END",)
            terminal_close = _close_action(
                position,
                symbol=symbol,
                contract=contract,
                segment_start=segment_start,
                trading_day=final_frame.bar.trading_day,
                decision_at=(
                    pending.decision_at if pending is not None else final_frame.bar.bar_end
                ),
                effective_bar_end=final_frame.bar.bar_end,
                reference_price=final_frame.bar.close,
                fill_basis=SubingStrategyFillBasis.SEGMENT_TERMINAL_CLOSE,
                reason_codes=reasons,
            )
            actions.append(terminal_close)
            closed_pairs.append((position.entry_action, terminal_close))
            position = None
            pending = None

    bars = tuple(frame.bar for frame in frame_tuple)
    episodes = [
        SubingStrategyEpisode.from_actions(
            entry_action=entry,
            exit_action=exit_action,
            completed_15m_bars=bars,
            latest_reference_price=None,
        )
        for entry, exit_action in closed_pairs
    ]
    if position is not None:
        episodes.append(
            SubingStrategyEpisode.from_actions(
                entry_action=position.entry_action,
                exit_action=None,
                completed_15m_bars=bars,
                latest_reference_price=bars[-1].close,
            )
        )
    episodes.sort(key=lambda episode: episode.entry_action.effective_bar_end)
    return SubingStrategySegmentResult(
        actions=tuple(actions),
        episodes=tuple(episodes),
        consumed_opportunity_ids=tuple(consumed),
        canceled_pending=tuple(canceled),
        pending_action=pending,
        final_position=(
            position.state if position is not None else SubingStrategyPositionState.FLAT
        ),
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
            or context.physical_contract not in {None, contract}
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


def _apply_pending(
    pending: SubingStrategyPendingAction,
    *,
    frame: SubingStrategyDecisionFrame,
    symbol: str,
    contract: str,
    segment_start: date,
    position: SubingStrategyPosition | None,
) -> tuple[
    SubingStrategyAction,
    SubingStrategyPosition | None,
    tuple[SubingStrategyAction, SubingStrategyAction] | None,
]:
    if pending.kind in {
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.OPEN_SHORT,
    }:
        if position is not None or pending.candidate is None or pending.direction_context is None:
            raise ValueError("SUBING_STRATEGY_PENDING_INVALID")
        action = _open_action(
            pending,
            frame=frame,
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
        trading_day=frame.bar.trading_day,
        decision_at=pending.decision_at,
        effective_bar_end=frame.bar.bar_end,
        reference_price=frame.bar.open,
        fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
        reason_codes=pending.reason_codes,
    )
    return close, None, (position.entry_action, close)


def _open_action(
    pending: SubingStrategyPendingAction,
    *,
    frame: SubingStrategyDecisionFrame,
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
        effective_bar_end=frame.bar.bar_end,
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
        trading_day=frame.bar.trading_day,
        segment_start_trading_day=segment_start,
        opportunity_id=candidate.opportunity_id,
        decision_at=pending.decision_at,
        effective_bar_end=frame.bar.bar_end,
        reference_price=frame.bar.open,
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
