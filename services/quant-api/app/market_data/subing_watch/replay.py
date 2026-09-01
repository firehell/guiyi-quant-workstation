"""Read-only physical-segment replay for the frozen SuBing Watch kernel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from guiyi_quant.indicators.subing_watch_15m import (
    SubingWatchKernelHigherTimeframe,
    SubingWatchPolicy as SubingWatchKernelPolicy,
    SubingWatchKernelState,
    initial_subing_watch_kernel_state,
    step_subing_watch_15m,
)

from ..domain import CanonicalBar
from .contracts import (
    SubingWatchEvaluation,
    SubingWatchPolicy,
    SubingWatchSourceIdentity,
    from_kernel_evaluation,
    to_subing_watch_kernel_bar,
)


class SubingWatchReplayError(ValueError):
    code = "SUBING_WATCH_REPLAY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingWatchSegmentProjection:
    identity: SubingWatchSourceIdentity
    policy: SubingWatchPolicy
    source_mode: Literal["canonical", "canonical_live"]
    coverage: tuple[datetime, datetime]
    evaluations: tuple[SubingWatchEvaluation, ...]
    final_state: SubingWatchKernelState
    latest_higher_timeframe: SubingWatchKernelHigherTimeframe | None


def replay_subing_watch_segment(
    identity: SubingWatchSourceIdentity,
    bars_15m: tuple[CanonicalBar, ...],
    completed_60m: tuple[CanonicalBar, ...],
    policy: SubingWatchPolicy,
    *,
    source_mode: Literal["canonical", "canonical_live"] = "canonical",
) -> SubingWatchSegmentProjection:
    """Replay exactly one rank-1 physical segment through the only Watch step."""

    if (
        type(identity) is not SubingWatchSourceIdentity
        or type(policy) is not SubingWatchPolicy
        or type(bars_15m) is not tuple
        or not bars_15m
        or type(completed_60m) is not tuple
        or source_mode not in {"canonical", "canonical_live"}
    ):
        raise SubingWatchReplayError()
    unique_15m = _unique_segment_bars(identity, bars_15m)
    higher = _project_completed_60m(identity, completed_60m)

    first_kernel_bar = to_subing_watch_kernel_bar(
        unique_15m[0],
        source_identity=identity,
    )
    state = initial_subing_watch_kernel_state(
        first_kernel_bar.identity,
        cast(SubingWatchKernelPolicy, policy),
    )
    evaluations: list[SubingWatchEvaluation] = []
    higher_index = 0
    latest_higher: SubingWatchKernelHigherTimeframe | None = None
    for bar in unique_15m:
        while higher_index < len(higher) and higher[higher_index].bar_end <= bar.bar_end.isoformat():
            latest_higher = higher[higher_index]
            higher_index += 1
        kernel_bar = to_subing_watch_kernel_bar(bar, source_identity=identity)
        state, evaluation = step_subing_watch_15m(
            state,
            kernel_bar,
            higher_timeframe=latest_higher,
        )
        evaluations.append(
            from_kernel_evaluation(evaluation, source_mode=source_mode)
        )
    return SubingWatchSegmentProjection(
        identity=identity,
        policy=policy,
        source_mode=source_mode,
        coverage=(unique_15m[0].bar_end, unique_15m[-1].bar_end),
        evaluations=tuple(evaluations),
        final_state=state,
        latest_higher_timeframe=latest_higher,
    )


def _unique_segment_bars(
    identity: SubingWatchSourceIdentity,
    bars: tuple[CanonicalBar, ...],
) -> tuple[CanonicalBar, ...]:
    unique: list[CanonicalBar] = []
    previous: CanonicalBar | None = None
    for bar in bars:
        if (
            type(bar) is not CanonicalBar
            or bar.trading_day < identity.segment_start_trading_day
            or (previous is not None and bar.bar_end < previous.bar_end)
        ):
            raise SubingWatchReplayError()
        if previous is not None and bar.bar_end == previous.bar_end:
            if bar != previous:
                raise SubingWatchReplayError()
            continue
        unique.append(bar)
        previous = bar
    return tuple(unique)


def _project_completed_60m(
    identity: SubingWatchSourceIdentity,
    bars: tuple[CanonicalBar, ...],
) -> tuple[SubingWatchKernelHigherTimeframe, ...]:
    """Prepare causal 60m facts; Candidate alignment remains owned by the kernel."""

    if not bars:
        return ()
    deduped = _unique_segment_bars(identity, bars)

    closes: tuple[float, ...] = ()
    latest_ma21: tuple[float, ...] = ()
    projected: list[SubingWatchKernelHigherTimeframe] = []
    for bar in deduped:
        kernel_bar = to_subing_watch_kernel_bar(bar, source_identity=identity)
        closes = (*closes, kernel_bar.close)[-21:]
        ma21 = sum(closes) / 21 if len(closes) == 21 else None
        if ma21 is not None:
            latest_ma21 = (*latest_ma21, ma21)[-5:]
        slope = _ma21_slope(latest_ma21, ma21)
        projected.append(
            SubingWatchKernelHigherTimeframe(
                identity=kernel_bar.identity,
                bar_end=kernel_bar.bar_end,
                close=kernel_bar.close,
                ma21=ma21,
                ma21_slope_5_bps_per_bar=slope,
                ready=ma21 is not None and slope is not None,
                valid=ma21 is not None and slope is not None,
            )
        )
    return tuple(projected)


def _ma21_slope(values: tuple[float, ...], current: float | None) -> float | None:
    if len(values) != 5 or current in {None, 0.0}:
        return None
    assert current is not None
    slope = sum((index - 2) * value for index, value in enumerate(values)) / 10
    return round(slope / current * 10_000, 6)
