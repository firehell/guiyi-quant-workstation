"""Compose segment-local Factor, Lifecycle, entry projection, and reducer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from ..domain import BarFrequency, CanonicalBar, ResolvedContractSegment
from ..subing_calibration import SubingCalibration
from ..subing_lifecycle import evaluate_subing_lifecycle
from ..subing_lifecycle_policy import SubingLifecyclePolicy
from ..subing_research import (
    SubingFactorResult,
    SubingFactorStatus,
    calculate_subing_factor_series,
)
from .direction_context import (
    SubingStrategyContextIdentityError,
    SubingStrategyDirectionContext,
)
from .engine import (
    SubingStrategyDecisionFrame,
    SubingStrategySegmentResult,
    run_subing_strategy_segment,
)
from .entry_projection import (
    SubingStrategyEntryCandidate,
    project_lifecycle_entries,
)
from .policy import SubingStrategyPolicy


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
    bars_5m: tuple[CanonicalBar, ...],
    bars_15m: tuple[CanonicalBar, ...],
    direction_contexts: Mapping[date, SubingStrategyDirectionContext],
    calibration: SubingCalibration,
    lifecycle_policy: SubingLifecyclePolicy,
    strategy_policy: SubingStrategyPolicy,
    terminal_bar_end: datetime | None,
) -> SubingStrategySegmentResult:
    _validate_segment_bars(segment, bars_5m, bars_15m)
    if terminal_bar_end is not None and (
        not bars_15m or terminal_bar_end != bars_15m[-1].bar_end
    ):
        raise SubingStrategyReplayError()
    factors_5m = calculate_subing_factor_series(
        bars_5m,
        timeframe=BarFrequency.M5,
        contract=segment.contract,
        segment_start_trading_day=segment.start_trading_day,
        latest_bar_source="canonical",
    )
    factors_15m = calculate_subing_factor_series(
        bars_15m,
        timeframe=BarFrequency.M15,
        contract=segment.contract,
        segment_start_trading_day=segment.start_trading_day,
        latest_bar_source="canonical",
    )
    if len(factors_5m) != len(bars_5m) or len(factors_15m) != len(bars_15m):
        raise SubingStrategyReplayError()
    trace = evaluate_subing_lifecycle(
        symbol=symbol,
        contract=segment.contract,
        segment_start_trading_day=segment.start_trading_day,
        bars_5m=bars_5m,
        factors_5m=factors_5m,
        bars_15m=bars_15m,
        factors_15m=factors_15m,
        calibration=calibration,
        policy=lifecycle_policy,
    )
    entries = project_lifecycle_entries(trace, bars_15m)
    frames = build_subing_strategy_frames(
        bars_15m=bars_15m,
        factors_15m=factors_15m,
        entries_by_boundary=entries,
        direction_contexts=direction_contexts,
    )
    effective_terminal = (
        terminal_bar_end
        if terminal_bar_end is not None
        and frames
        and frames[-1].bar.bar_end == terminal_bar_end
        else None
    )
    try:
        return run_subing_strategy_segment(
            symbol=symbol,
            contract=segment.contract,
            segment_start=segment.start_trading_day,
            frames=frames,
            policy=strategy_policy,
            terminal_bar_end=effective_terminal,
        )
    except ValueError:
        raise SubingStrategyReplayError() from None


def _validate_segment_bars(
    segment: ResolvedContractSegment,
    bars_5m: tuple[CanonicalBar, ...],
    bars_15m: tuple[CanonicalBar, ...],
) -> None:
    if not isinstance(segment, ResolvedContractSegment):
        raise SubingStrategyReplayError()
    for bars in (bars_5m, bars_15m):
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
