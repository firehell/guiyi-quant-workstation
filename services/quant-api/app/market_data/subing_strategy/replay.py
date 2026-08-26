"""Replay authoritative 1m/5m/15m facts through the unified machine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from ..domain import BarFrequency, CanonicalBar, ResolvedContractSegment
from ..subing_calibration import SubingCalibration
from ..subing_lifecycle_policy import SubingLifecyclePolicy
from ..subing_research import SubingFactorResult, SubingFactorStatus
from .direction_context import (
    SubingStrategyContextIdentityError,
    SubingStrategyDirectionContext,
)
from .engine import (
    SubingStrategyDecisionFrame,
    SubingStrategyPendingCancellation,
    SubingStrategySegmentResult,
)
from .entry_projection import (
    SubingStrategyEntryCandidate,
)
from .contracts import SubingStrategyPositionState
from .policy import SubingStrategyPolicy
from .machine import (
    SubingStrategyInterval,
    SubingStrategyMachineError,
    initial_subing_strategy_machine,
    step_subing_strategy_machine,
)
from .stream_contracts import (
    AuthoritativeSegmentTerminal,
    Completed1mBar,
    Completed5mBar,
    Completed15mBar,
)


class SubingStrategyReplayError(SubingStrategyContextIdentityError):
    pass


def build_subing_strategy_frames(
    *,
    bars_15m: Sequence[CanonicalBar],
    factors_15m: Sequence[SubingFactorResult],
    entries_by_boundary: Mapping[
        datetime,
        tuple[SubingStrategyEntryCandidate, ...],
    ],
    direction_contexts: Mapping[date, SubingStrategyDirectionContext],
) -> tuple[SubingStrategyDecisionFrame, ...]:
    bars = tuple(bars_15m)
    factors = tuple(factors_15m)
    if (
        len(bars) != len(factors)
        or any(left.bar_end >= right.bar_end for left, right in zip(bars, bars[1:]))
        or set(entries_by_boundary) != {bar.bar_end for bar in bars}
    ):
        raise SubingStrategyReplayError()
    frames: list[SubingStrategyDecisionFrame] = []
    previous_evaluable: CanonicalBar | None = None
    for bar, factor_result in zip(bars, factors, strict=True):
        candidates = entries_by_boundary[bar.bar_end]
        if any(
            candidate.decision_bar_end != bar.bar_end
            or candidate.confirmed_at > bar.bar_end
            for candidate in candidates
        ):
            raise SubingStrategyReplayError()
        if factor_result.status is not SubingFactorStatus.READY:
            if factor_result.snapshot is not None or candidates:
                raise SubingStrategyReplayError()
            continue
        factor = factor_result.snapshot
        context = direction_contexts.get(bar.trading_day)
        if (
            factor is None
            or factor.timeframe is not BarFrequency.M15
            or factor.bar_end != bar.bar_end
            or factor.trading_day != bar.trading_day
            or context is None
            or context.target_trading_day != bar.trading_day
        ):
            raise SubingStrategyReplayError()
        frames.append(
            SubingStrategyDecisionFrame(
                bar=bar,
                previous_bar=previous_evaluable,
                factor=factor,
                direction_context=context,
                entry_candidates=candidates,
            )
        )
        previous_evaluable = bar
    return tuple(frames)


def replay_subing_strategy_segment(
    *,
    symbol: str,
    segment: ResolvedContractSegment,
    bars_1m: tuple[CanonicalBar, ...],
    bars_5m: tuple[CanonicalBar, ...],
    bars_15m: tuple[CanonicalBar, ...],
    direction_contexts: Mapping[date, SubingStrategyDirectionContext],
    calibration: SubingCalibration,
    lifecycle_policy: SubingLifecyclePolicy,
    strategy_policy: SubingStrategyPolicy,
    terminal_bar_end: datetime | None,
) -> SubingStrategySegmentResult:
    _validate_segment_bars(segment, bars_1m, bars_5m, bars_15m)
    if terminal_bar_end is not None and (
        not bars_15m or terminal_bar_end != bars_15m[-1].bar_end
    ):
        raise SubingStrategyReplayError()
    try:
        state = initial_subing_strategy_machine(
            symbol=symbol,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
            calibration=calibration,
            lifecycle_policy=lifecycle_policy,
            strategy_policy=strategy_policy,
            direction_contexts=direction_contexts,
            intervals=_authoritative_intervals(bars_1m, bars_15m),
        )
        events: list[Completed1mBar | Completed5mBar | Completed15mBar] = [
            *(Completed1mBar(bar) for bar in bars_1m)
        ]
        events.extend(Completed5mBar(bar) for bar in bars_5m)
        events.extend(Completed15mBar(bar) for bar in bars_15m)
        events.sort(
            key=lambda event: (
                event.bar.bar_end,
                0
                if isinstance(event, Completed1mBar)
                else 1
                if isinstance(event, Completed15mBar)
                else 2,
            )
        )
        cancellations: list[SubingStrategyPendingCancellation] = []
        for event in events:
            state, output = step_subing_strategy_machine(state, event)
            cancellations.extend(output.cancellations)
        if terminal_bar_end is not None:
            state, output = step_subing_strategy_machine(
                state,
                AuthoritativeSegmentTerminal(
                    symbol=symbol,
                    contract=segment.contract,
                    segment_start_trading_day=segment.start_trading_day,
                    terminal_bar=bars_15m[-1],
                ),
            )
            cancellations.extend(output.cancellations)
        episodes = (*state.closed_episodes,)
        if state.current_episode is not None:
            episodes = (*episodes, state.current_episode)
        return SubingStrategySegmentResult(
            actions=state.actions,
            episodes=tuple(
                sorted(episodes, key=lambda item: item.entry_action.effective_bar_end)
            ),
            consumed_opportunity_ids=state.consumed_opportunity_ids,
            canceled_pending=tuple(cancellations),
            pending_action=state.pending_action,
            final_position=(
                state.position.state
                if state.position is not None
                else SubingStrategyPositionState.FLAT
            ),
        )
    except (ValueError, SubingStrategyMachineError):
        raise SubingStrategyReplayError() from None


def _validate_segment_bars(
    segment: ResolvedContractSegment,
    bars_1m: tuple[CanonicalBar, ...],
    bars_5m: tuple[CanonicalBar, ...],
    bars_15m: tuple[CanonicalBar, ...],
) -> None:
    if not isinstance(segment, ResolvedContractSegment):
        raise SubingStrategyReplayError()
    for bars in (bars_1m, bars_5m, bars_15m):
        if (
            not bars
            or any(not isinstance(bar, CanonicalBar) for bar in bars)
            or any(left.bar_end >= right.bar_end for left, right in zip(bars, bars[1:]))
            or any(
                not segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
                for bar in bars
            )
        ):
            raise SubingStrategyReplayError()


def _authoritative_intervals(
    bars_1m: tuple[CanonicalBar, ...],
    bars_15m: tuple[CanonicalBar, ...],
) -> tuple[SubingStrategyInterval, ...]:
    intervals: list[SubingStrategyInterval] = []
    previous_end: datetime | None = None
    consumed = 0
    for bar_15m in bars_15m:
        source = tuple(
            bar
            for bar in bars_1m
            if (previous_end is None or bar.bar_end > previous_end)
            and bar.bar_end <= bar_15m.bar_end
        )
        if (
            not source
            or source[-1].bar_end != bar_15m.bar_end
            or source[0].open != bar_15m.open
            or any(bar.trading_day != bar_15m.trading_day for bar in source)
        ):
            raise SubingStrategyReplayError()
        intervals.append(
            SubingStrategyInterval(
                effective_bar_end=bar_15m.bar_end,
                first_1m_bar_end=source[0].bar_end,
                expected_open=bar_15m.open,
            )
        )
        consumed += len(source)
        previous_end = bar_15m.bar_end
    if consumed != len(bars_1m):
        raise SubingStrategyReplayError()
    return tuple(intervals)
