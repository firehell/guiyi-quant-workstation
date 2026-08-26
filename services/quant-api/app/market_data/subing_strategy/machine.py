"""One pure incremental semantic owner for Historical and completed-Live SuBing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal

from ..domain import BarFrequency, CanonicalBar, normalize_contract_for_symbol
from ..subing_calibration import SubingCalibration, is_accepted_subing_calibration
from ..subing_lifecycle import (
    SubingLifecycleMachineState,
    SubingLifecycleTrace,
    _advance_batch_15m_error,
    initial_subing_lifecycle_state,
    step_subing_lifecycle_5m,
    step_subing_lifecycle_15m,
)
from ..subing_lifecycle_policy import SubingLifecyclePolicy
from ..subing_research import (
    SubingFactorStatus,
    SubingFactorStreamState,
    initial_subing_factor_state,
    step_subing_factor,
)
from .contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyPositionState,
)
from .direction_context import SubingStrategyDirectionContext
from .engine import (
    SubingStrategyDecisionFrame,
    SubingStrategyPendingAction,
    SubingStrategyPendingCancellation,
    SubingStrategyPosition,
    SubingStrategySegmentResult,
    apply_pending_next_open,
    decide_completed_15m,
    finalize_segment,
)
from .entry_projection import project_lifecycle_entries
from .policy import SubingStrategyPolicy
from .stream_contracts import (
    AuthoritativeSegmentTerminal,
    Completed1mBar,
    Completed5mBar,
    Completed15mBar,
    SubingStrategyStepOutput,
    SubingStrategyStreamInput,
)


class SubingStrategyMachineError(ValueError):
    code = "SUBING_STRATEGY_MACHINE_UNAVAILABLE"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"{self.code}:{reason}")


@dataclass(frozen=True, slots=True)
class SubingStrategySourceIdentity:
    """Authoritative caller context kept outside the locked completed-Bar facts."""

    symbol: str
    contract: str
    segment_start_trading_day: date

    def __post_init__(self) -> None:
        if (
            not isinstance(self.symbol, str)
            or self.symbol != self.symbol.strip().lower()
            or not self.symbol.isascii()
            or not self.symbol.isalpha()
            or normalize_contract_for_symbol(self.symbol, self.contract)
            != self.contract
            or type(self.segment_start_trading_day) is not date
        ):
            raise SubingStrategyMachineError("SOURCE_IDENTITY_INVALID")


@dataclass(frozen=True, slots=True)
class SubingStrategyInterval:
    effective_bar_end: datetime
    first_1m_bar_end: datetime
    expected_open: Decimal

    def __post_init__(self) -> None:
        if (
            not _aware(self.effective_bar_end)
            or not _aware(self.first_1m_bar_end)
            or self.first_1m_bar_end >= self.effective_bar_end
            or not isinstance(self.expected_open, Decimal)
            or not self.expected_open.is_finite()
            or self.expected_open <= 0
        ):
            raise SubingStrategyMachineError("INTERVAL_IDENTITY_INVALID")


@dataclass(frozen=True, slots=True)
class SubingStrategyWatermarks:
    latest_1m: CanonicalBar | None = None
    latest_5m: CanonicalBar | None = None
    latest_15m: CanonicalBar | None = None
    terminal_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SubingStrategyMachineState:
    symbol: str
    contract: str
    segment_start_trading_day: date
    factor_5m: SubingFactorStreamState
    factor_15m: SubingFactorStreamState
    lifecycle: SubingLifecycleMachineState
    calibration: SubingCalibration
    lifecycle_policy: SubingLifecyclePolicy
    strategy_policy: SubingStrategyPolicy
    direction_contexts: tuple[tuple[date, SubingStrategyDirectionContext], ...]
    intervals: tuple[SubingStrategyInterval, ...]
    position: SubingStrategyPosition | None = None
    pending_action: SubingStrategyPendingAction | None = None
    consumed_opportunity_ids: tuple[str, ...] = ()
    current_episode: SubingStrategyEpisode | None = None
    closed_episodes: tuple[SubingStrategyEpisode, ...] = ()
    actions: tuple[SubingStrategyAction, ...] = ()
    previous_15m_bar: CanonicalBar | None = None
    completed_15m_bars: tuple[CanonicalBar, ...] = ()
    pending_boundary_15m: Completed15mBar | None = None
    pending_boundary_5m: Completed5mBar | None = None
    watermarks: SubingStrategyWatermarks = SubingStrategyWatermarks()


@dataclass(frozen=True, slots=True)
class _CompletedCompatibilityDecision:
    frame: SubingStrategyDecisionFrame


def initial_subing_strategy_machine(
    *,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
    calibration: SubingCalibration,
    lifecycle_policy: SubingLifecyclePolicy,
    strategy_policy: SubingStrategyPolicy,
    direction_contexts: Mapping[date, SubingStrategyDirectionContext],
    intervals: Sequence[SubingStrategyInterval],
    latest_bar_source: str = "canonical",
) -> SubingStrategyMachineState:
    normalized_intervals = tuple(intervals)
    normalized_contexts = tuple(sorted(direction_contexts.items()))
    if (
        not isinstance(symbol, str)
        or symbol != symbol.strip().lower()
        or not symbol.isascii()
        or not symbol.isalpha()
        or normalize_contract_for_symbol(symbol, contract) != contract
        or type(segment_start_trading_day) is not date
        or not is_accepted_subing_calibration(calibration)
        or not isinstance(lifecycle_policy, SubingLifecyclePolicy)
        or not isinstance(strategy_policy, SubingStrategyPolicy)
        or any(
            type(item) is not SubingStrategyInterval for item in normalized_intervals
        )
        or any(
            left.effective_bar_end >= right.effective_bar_end
            or left.first_1m_bar_end >= right.first_1m_bar_end
            or left.effective_bar_end >= right.first_1m_bar_end
            for left, right in zip(normalized_intervals, normalized_intervals[1:])
        )
        or any(
            type(day) is not date
            or not isinstance(context, SubingStrategyDirectionContext)
            or context.symbol != symbol
            or context.target_trading_day != day
            for day, context in normalized_contexts
        )
    ):
        raise SubingStrategyMachineError("INITIAL_STATE_INVALID")
    return SubingStrategyMachineState(
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        factor_5m=initial_subing_factor_state(
            timeframe=BarFrequency.M5,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            latest_bar_source=latest_bar_source,
        ),
        factor_15m=initial_subing_factor_state(
            timeframe=BarFrequency.M15,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            latest_bar_source=latest_bar_source,
        ),
        lifecycle=initial_subing_lifecycle_state(
            symbol=symbol,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
        ),
        calibration=calibration,
        lifecycle_policy=lifecycle_policy,
        strategy_policy=strategy_policy,
        direction_contexts=normalized_contexts,
        intervals=normalized_intervals,
    )


def replay_subing_strategy_frames(
    *,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
    frames: tuple[SubingStrategyDecisionFrame, ...],
    first_1m_bars: tuple[CanonicalBar, ...],
    intervals: tuple[SubingStrategyInterval, ...],
    calibration: SubingCalibration,
    lifecycle_policy: SubingLifecyclePolicy,
    strategy_policy: SubingStrategyPolicy,
    terminal_bar_end: datetime | None,
) -> SubingStrategySegmentResult:
    """Feed frozen Stage 1 frames through the one unified step machine."""

    state = initial_subing_strategy_machine(
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        calibration=calibration,
        lifecycle_policy=lifecycle_policy,
        strategy_policy=strategy_policy,
        direction_contexts={
            frame.bar.trading_day: frame.direction_context for frame in frames
        },
        intervals=intervals,
    )
    source_identity = SubingStrategySourceIdentity(
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
    )
    canceled: list[SubingStrategyPendingCancellation] = []
    for frame, first_minute in zip(frames, first_1m_bars, strict=True):
        state, output = step_subing_strategy_machine(
            state,
            Completed1mBar(first_minute),
            source_identity=source_identity,
        )
        canceled.extend(output.cancellations)
        state, output = step_subing_strategy_machine(
            state,
            _CompletedCompatibilityDecision(frame),
            source_identity=source_identity,
        )
        canceled.extend(output.cancellations)
    if terminal_bar_end is not None and frames:
        state, output = step_subing_strategy_machine(
            state,
            AuthoritativeSegmentTerminal(
                symbol=symbol,
                contract=contract,
                segment_start_trading_day=segment_start_trading_day,
                terminal_bar=frames[-1].bar,
            ),
            source_identity=source_identity,
        )
        canceled.extend(output.cancellations)
    return subing_strategy_segment_result(
        state,
        canceled_pending=tuple(canceled),
    )


def step_subing_strategy_machine(
    state: SubingStrategyMachineState,
    event: SubingStrategyStreamInput | _CompletedCompatibilityDecision,
    *,
    source_identity: SubingStrategySourceIdentity,
) -> tuple[SubingStrategyMachineState, SubingStrategyStepOutput]:
    if not isinstance(state, SubingStrategyMachineState) or not isinstance(
        event,
        (
            Completed1mBar,
            Completed5mBar,
            Completed15mBar,
            AuthoritativeSegmentTerminal,
            _CompletedCompatibilityDecision,
        ),
    ):
        raise SubingStrategyMachineError("INPUT_INVALID")
    if (
        not isinstance(source_identity, SubingStrategySourceIdentity)
        or source_identity.symbol != state.symbol
        or source_identity.contract != state.contract
        or source_identity.segment_start_trading_day != state.segment_start_trading_day
    ):
        raise SubingStrategyMachineError("SOURCE_IDENTITY_MISMATCH")
    if state.watermarks.terminal_at is not None:
        raise SubingStrategyMachineError("SEGMENT_TERMINATED")
    if isinstance(event, _CompletedCompatibilityDecision):
        return _step_compatibility_decision(state, event.frame)
    if isinstance(event, AuthoritativeSegmentTerminal):
        return _step_terminal(state, event)
    if event.bar.trading_day < state.segment_start_trading_day:
        raise SubingStrategyMachineError("STALE_SEGMENT_INPUT")
    pending_boundary = (
        state.pending_boundary_15m.bar.bar_end
        if state.pending_boundary_15m is not None
        else state.pending_boundary_5m.bar.bar_end
        if state.pending_boundary_5m is not None
        else None
    )
    if pending_boundary is not None and event.bar.bar_end > pending_boundary:
        raise SubingStrategyMachineError("BOUNDARY_COMPANION_MISSING")
    duplicate = _duplicate_status(state, event)
    if duplicate == "same":
        return state, SubingStrategyStepOutput(
            actions=(), cancellations=(), state_changed=False
        )
    if duplicate == "conflict":
        raise SubingStrategyMachineError("CONFLICTING_DUPLICATE")
    if duplicate == "stale":
        raise SubingStrategyMachineError("STALE_INPUT")
    state, missed = _cancel_missed_open_before(state, event.bar.bar_end)
    if isinstance(event, Completed1mBar):
        return _step_1m(state, event, missed)
    if isinstance(event, Completed5mBar):
        return _step_5m(state, event, missed)
    return _step_15m(state, event, missed)


def _step_compatibility_decision(
    state: SubingStrategyMachineState,
    frame: SubingStrategyDecisionFrame,
) -> tuple[SubingStrategyMachineState, SubingStrategyStepOutput]:
    if (
        state.pending_boundary_5m is not None
        or state.pending_boundary_15m is not None
        or not _is_shared_boundary(state, frame.bar.bar_end)
        or frame.previous_bar != state.previous_15m_bar
    ):
        raise SubingStrategyMachineError("COMPATIBILITY_FRAME_IDENTITY_INVALID")
    pending, newly_consumed = decide_completed_15m(
        frame=frame,
        position=state.position,
        pending_action=state.pending_action,
        consumed_opportunity_ids=frozenset(state.consumed_opportunity_ids),
    )
    state = replace(
        state,
        pending_action=pending,
        consumed_opportunity_ids=(
            *state.consumed_opportunity_ids,
            *newly_consumed,
        ),
        previous_15m_bar=frame.bar,
        completed_15m_bars=(*state.completed_15m_bars, frame.bar),
        watermarks=replace(state.watermarks, latest_15m=frame.bar),
    )
    return _refresh_episodes(state), SubingStrategyStepOutput(
        actions=(),
        cancellations=(),
        state_changed=True,
    )


def subing_strategy_segment_result(
    state: SubingStrategyMachineState,
    *,
    canceled_pending: tuple[SubingStrategyPendingCancellation, ...],
) -> SubingStrategySegmentResult:
    episodes = (*state.closed_episodes,)
    if state.current_episode is not None:
        episodes = (*episodes, state.current_episode)
    return SubingStrategySegmentResult(
        actions=state.actions,
        episodes=tuple(
            sorted(episodes, key=lambda item: item.entry_action.effective_bar_end)
        ),
        consumed_opportunity_ids=state.consumed_opportunity_ids,
        canceled_pending=canceled_pending,
        pending_action=state.pending_action,
        final_position=(
            state.position.state
            if state.position is not None
            else SubingStrategyPositionState.FLAT
        ),
    )


def _step_1m(
    state: SubingStrategyMachineState,
    event: Completed1mBar,
    cancellations: tuple[SubingStrategyPendingCancellation, ...],
) -> tuple[SubingStrategyMachineState, SubingStrategyStepOutput]:
    interval = _containing_interval(state, event.bar.bar_end)
    actions: tuple[SubingStrategyAction, ...] = ()
    pending_action = state.pending_action
    if pending_action is not None and interval is not None:
        if event.bar.bar_end == interval.first_1m_bar_end:
            if event.bar.open != interval.expected_open:
                raise SubingStrategyMachineError("SOURCE_IDENTITY_INCONSISTENT")
            action, position, _ = apply_pending_next_open(
                pending_action,
                first_1m_bar=event.bar,
                effective_bar_end=interval.effective_bar_end,
                symbol=state.symbol,
                contract=state.contract,
                segment_start=state.segment_start_trading_day,
                position=state.position,
            )
            actions = (action,)
            state = replace(
                state,
                position=position,
                pending_action=None,
                actions=(*state.actions, action),
            )
        elif event.bar.bar_end > interval.first_1m_bar_end:
            cancellation = _cancel_pending(pending_action)
            cancellations = (*cancellations, cancellation)
            state = replace(state, pending_action=None)
    state = replace(
        state,
        watermarks=replace(state.watermarks, latest_1m=event.bar),
    )
    state = _refresh_episodes(state)
    return state, SubingStrategyStepOutput(
        actions=actions,
        cancellations=cancellations,
        state_changed=True,
    )


def _step_5m(
    state: SubingStrategyMachineState,
    event: Completed5mBar,
    cancellations: tuple[SubingStrategyPendingCancellation, ...],
) -> tuple[SubingStrategyMachineState, SubingStrategyStepOutput]:
    if _is_shared_boundary(state, event.bar.bar_end):
        pending = state.pending_boundary_15m
        state = replace(state, pending_boundary_5m=event)
        if pending is None:
            return state, SubingStrategyStepOutput(
                actions=(), cancellations=cancellations, state_changed=True
            )
        return _process_shared_boundary(state, cancellations)
    state = _advance_5m(state, event.bar)
    return state, SubingStrategyStepOutput(
        actions=(), cancellations=cancellations, state_changed=True
    )


def _step_15m(
    state: SubingStrategyMachineState,
    event: Completed15mBar,
    cancellations: tuple[SubingStrategyPendingCancellation, ...],
) -> tuple[SubingStrategyMachineState, SubingStrategyStepOutput]:
    if not _is_shared_boundary(state, event.bar.bar_end):
        raise SubingStrategyMachineError("UNSCHEDULED_15M_BOUNDARY")
    pending = state.pending_boundary_5m
    state = replace(state, pending_boundary_15m=event)
    if pending is None:
        return state, SubingStrategyStepOutput(
            actions=(), cancellations=cancellations, state_changed=True
        )
    return _process_shared_boundary(state, cancellations)


def _process_shared_boundary(
    state: SubingStrategyMachineState,
    cancellations: tuple[SubingStrategyPendingCancellation, ...],
) -> tuple[SubingStrategyMachineState, SubingStrategyStepOutput]:
    event_15m = state.pending_boundary_15m
    event_5m = state.pending_boundary_5m
    if (
        event_15m is None
        or event_5m is None
        or event_15m.bar.bar_end != event_5m.bar.bar_end
    ):
        raise SubingStrategyMachineError("BOUNDARY_COMPANION_MISSING")
    factor_15m, result_15m = step_subing_factor(state.factor_15m, event_15m.bar)
    try:
        lifecycle = step_subing_lifecycle_15m(
            state.lifecycle,
            bar=event_15m.bar,
            factor=result_15m,
        )
    except ValueError as exc:
        if str(exc) != "SUBING_FACTOR_UNAVAILABLE":
            raise SubingStrategyMachineError("SOURCE_IDENTITY_INCONSISTENT") from None
        lifecycle = _advance_batch_15m_error(
            state.lifecycle,
            bar=event_15m.bar,
            error="SUBING_FACTOR_UNAVAILABLE",
        )
    state = replace(state, factor_15m=factor_15m, lifecycle=lifecycle)
    state = _advance_5m(state, event_5m.bar)
    completed = (*state.completed_15m_bars, event_15m.bar)
    pending = state.pending_action
    consumed = state.consumed_opportunity_ids
    previous = state.previous_15m_bar
    candidates = project_lifecycle_entries(_trace(state), completed)[
        event_15m.bar.bar_end
    ]
    if result_15m.status is SubingFactorStatus.READY:
        context = dict(state.direction_contexts).get(event_15m.bar.trading_day)
        if context is None or result_15m.snapshot is None:
            raise SubingStrategyMachineError("DIRECTION_CONTEXT_UNAVAILABLE")
        frame = SubingStrategyDecisionFrame(
            bar=event_15m.bar,
            previous_bar=previous,
            factor=result_15m.snapshot,
            direction_context=context,
            entry_candidates=candidates,
        )
        pending, newly_consumed = decide_completed_15m(
            frame=frame,
            position=state.position,
            pending_action=pending,
            consumed_opportunity_ids=frozenset(consumed),
        )
        consumed = (*consumed, *newly_consumed)
        previous = event_15m.bar
    elif candidates:
        raise SubingStrategyMachineError("FACTOR_UNAVAILABLE_AT_DECISION")
    state = replace(
        state,
        pending_action=pending,
        consumed_opportunity_ids=consumed,
        previous_15m_bar=previous,
        completed_15m_bars=completed,
        pending_boundary_15m=None,
        pending_boundary_5m=None,
        watermarks=replace(
            state.watermarks,
            latest_5m=event_5m.bar,
            latest_15m=event_15m.bar,
        ),
    )
    state = _refresh_episodes(state)
    return state, SubingStrategyStepOutput(
        actions=(), cancellations=cancellations, state_changed=True
    )


def _advance_5m(
    state: SubingStrategyMachineState,
    bar: CanonicalBar,
) -> SubingStrategyMachineState:
    factor, result = step_subing_factor(state.factor_5m, bar)
    lifecycle, _ = step_subing_lifecycle_5m(
        state.lifecycle,
        bar=bar,
        factor=result,
        calibration=state.calibration,
        policy=state.lifecycle_policy,
    )
    return replace(
        state,
        factor_5m=factor,
        lifecycle=lifecycle,
        watermarks=replace(state.watermarks, latest_5m=bar),
    )


def _step_terminal(
    state: SubingStrategyMachineState,
    event: AuthoritativeSegmentTerminal,
) -> tuple[SubingStrategyMachineState, SubingStrategyStepOutput]:
    if (
        event.symbol != state.symbol
        or event.contract != state.contract
        or event.segment_start_trading_day != state.segment_start_trading_day
        or state.pending_boundary_5m is not None
        or state.pending_boundary_15m is not None
        or state.watermarks.latest_15m != event.terminal_bar
    ):
        raise SubingStrategyMachineError("TERMINAL_IDENTITY_INVALID")
    actions: tuple[SubingStrategyAction, ...] = ()
    cancellations: tuple[SubingStrategyPendingCancellation, ...] = ()
    pending = state.pending_action
    position = state.position
    if pending is not None and pending.kind in {
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.OPEN_SHORT,
    }:
        cancellations = (_cancel_pending(pending),)
        pending = None
    elif position is not None:
        action = finalize_segment(
            position=position,
            pending_action=pending,
            terminal_bar=event.terminal_bar,
            symbol=state.symbol,
            contract=state.contract,
            segment_start=state.segment_start_trading_day,
        )
        actions = (action,)
        state = replace(state, actions=(*state.actions, action))
        position = None
        pending = None
    state = replace(
        state,
        position=position,
        pending_action=pending,
        watermarks=replace(state.watermarks, terminal_at=event.terminal_bar.bar_end),
    )
    state = _refresh_episodes(state)
    return state, SubingStrategyStepOutput(
        actions=actions, cancellations=cancellations, state_changed=True
    )


def _cancel_missed_open_before(
    state: SubingStrategyMachineState,
    boundary: datetime,
) -> tuple[SubingStrategyMachineState, tuple[SubingStrategyPendingCancellation, ...]]:
    pending = state.pending_action
    if pending is None:
        return state, ()
    intervals = tuple(
        interval
        for interval in state.intervals
        if pending.decision_at < interval.effective_bar_end <= boundary
    )
    if not intervals:
        return state, ()
    interval = intervals[0]
    latest = state.watermarks.latest_1m
    if latest is not None and latest.bar_end == interval.first_1m_bar_end:
        return state, ()
    cancellation = _cancel_pending(pending)
    return replace(state, pending_action=None), (cancellation,)


def _cancel_pending(
    pending: SubingStrategyPendingAction,
) -> SubingStrategyPendingCancellation:
    return SubingStrategyPendingCancellation(
        kind=pending.kind,
        decision_at=pending.decision_at,
        opportunity_id=pending.opportunity_id,
        reason_code="NEXT_BAR_OPEN_UNAVAILABLE",
    )


def _refresh_episodes(state: SubingStrategyMachineState) -> SubingStrategyMachineState:
    entries = {
        action.episode_id: action
        for action in state.actions
        if action.kind
        in {SubingStrategyActionKind.OPEN_LONG, SubingStrategyActionKind.OPEN_SHORT}
    }
    exits = {
        action.episode_id: action
        for action in state.actions
        if action.kind
        in {SubingStrategyActionKind.CLOSE_LONG, SubingStrategyActionKind.CLOSE_SHORT}
    }
    closed: list[SubingStrategyEpisode] = []
    current: SubingStrategyEpisode | None = None
    for episode_id, entry in entries.items():
        if (
            not state.completed_15m_bars
            or state.completed_15m_bars[-1].bar_end < entry.effective_bar_end
        ):
            continue
        exit_action = exits.get(episode_id)
        episode = SubingStrategyEpisode.from_actions(
            entry_action=entry,
            exit_action=exit_action,
            completed_15m_bars=state.completed_15m_bars,
            latest_reference_price=(
                None if exit_action is not None else state.completed_15m_bars[-1].close
            ),
        )
        if exit_action is None:
            current = episode
        else:
            closed.append(episode)
    closed.sort(key=lambda item: item.entry_action.effective_bar_end)
    return replace(state, current_episode=current, closed_episodes=tuple(closed))


def _trace(state: SubingStrategyMachineState) -> SubingLifecycleTrace:
    if not state.lifecycle.snapshots:
        raise SubingStrategyMachineError("LIFECYCLE_UNAVAILABLE")
    return SubingLifecycleTrace(
        formula_version=state.lifecycle.formula_version,
        policy_id=state.lifecycle.policy_id,
        symbol=state.symbol,
        contract=state.contract,
        segment_start_trading_day=state.segment_start_trading_day,
        confirmed_pivots=state.lifecycle.confirmed_pivots,
        completed_opportunities=state.lifecycle.completed_opportunities,
        transitions=state.lifecycle.transitions,
        snapshots=state.lifecycle.snapshots,
        current_snapshot=state.lifecycle.snapshots[-1],
    )


def _is_shared_boundary(state: SubingStrategyMachineState, value: datetime) -> bool:
    return any(interval.effective_bar_end == value for interval in state.intervals)


def _containing_interval(
    state: SubingStrategyMachineState,
    value: datetime,
) -> SubingStrategyInterval | None:
    matches = tuple(
        interval
        for interval in state.intervals
        if interval.first_1m_bar_end <= value <= interval.effective_bar_end
    )
    if len(matches) > 1:
        raise SubingStrategyMachineError("INTERVAL_IDENTITY_INVALID")
    return matches[0] if matches else None


def _duplicate_status(
    state: SubingStrategyMachineState,
    event: Completed1mBar | Completed5mBar | Completed15mBar,
) -> str | None:
    buffered = (
        state.pending_boundary_5m.bar
        if isinstance(event, Completed5mBar) and state.pending_boundary_5m is not None
        else state.pending_boundary_15m.bar
        if isinstance(event, Completed15mBar) and state.pending_boundary_15m is not None
        else None
    )
    latest = (
        state.watermarks.latest_1m
        if isinstance(event, Completed1mBar)
        else state.watermarks.latest_5m
        if isinstance(event, Completed5mBar)
        else state.watermarks.latest_15m
    )
    observed = buffered or latest
    if observed is None:
        return None
    if event.bar.bar_end == observed.bar_end:
        return "same" if event.bar == observed else "conflict"
    return "stale" if event.bar.bar_end < observed.bar_end else None


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )
