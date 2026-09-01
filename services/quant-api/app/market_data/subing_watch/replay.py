"""Read-only physical-segment replay for the frozen SuBing Watch kernel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, cast

from guiyi_quant.indicators.subing_watch_15m import (
    SubingWatchKernelError,
    SubingWatchKernelEvaluation,
    SubingWatchKernelHigherTimeframe,
    SubingWatchPolicy as SubingWatchKernelPolicy,
    SubingWatchKernelState,
    initial_subing_watch_kernel_state,
    step_subing_watch_15m,
    subing_watch_ma21_slope_5_bps_per_bar,
)

from ..domain import CanonicalBar
from .contracts import (
    SubingWatchContractError,
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
    higher_timeframe_live_start_index: int | None = None,
    higher_timeframe_live_trading_day: date | None = None,
) -> SubingWatchSegmentProjection:
    """Replay exactly one rank-1 physical segment through the only Watch step."""

    if (
        type(identity) is not SubingWatchSourceIdentity
        or type(policy) is not SubingWatchPolicy
        or type(bars_15m) is not tuple
        or not bars_15m
        or type(completed_60m) is not tuple
        or source_mode not in {"canonical", "canonical_live"}
        or (
            (higher_timeframe_live_start_index is None)
            != (higher_timeframe_live_trading_day is None)
        )
        or (
            higher_timeframe_live_start_index is not None
            and (
                type(higher_timeframe_live_start_index) is not int
                or not 0 <= higher_timeframe_live_start_index <= len(completed_60m)
                or type(higher_timeframe_live_trading_day) is not date
            )
        )
    ):
        raise SubingWatchReplayError()
    unique_15m = _unique_segment_bars(identity, bars_15m)

    first_kernel_bar = to_subing_watch_kernel_bar(
        unique_15m[0],
        source_identity=identity,
    )
    state = initial_subing_watch_kernel_state(
        first_kernel_bar.identity,
        cast(SubingWatchKernelPolicy, policy),
    )
    kernel_evaluations: list[SubingWatchKernelEvaluation] = []
    higher = _IncrementalHigherTimeframeProjector(
        identity,
        completed_60m,
        live_start_index=higher_timeframe_live_start_index,
        live_trading_day=higher_timeframe_live_trading_day,
    )
    latest_higher: SubingWatchKernelHigherTimeframe | None = None
    for index, bar in enumerate(unique_15m):
        latest_higher = higher.advance(bar.bar_end)
        kernel_bar = (
            first_kernel_bar
            if index == 0
            else to_subing_watch_kernel_bar(bar, source_identity=identity)
        )
        state, evaluation = step_subing_watch_15m(
            state,
            kernel_bar,
            higher_timeframe=latest_higher,
        )
        kernel_evaluations.append(evaluation)
    effective_source_mode: Literal["canonical", "canonical_live"] = (
        "canonical_live"
        if source_mode == "canonical_live" or higher.live_fact_adopted
        else "canonical"
    )
    evaluations = tuple(
        from_kernel_evaluation(evaluation, source_mode=effective_source_mode)
        for evaluation in kernel_evaluations
    )
    return SubingWatchSegmentProjection(
        identity=identity,
        policy=policy,
        source_mode=effective_source_mode,
        coverage=(unique_15m[0].bar_end, unique_15m[-1].bar_end),
        evaluations=evaluations,
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
            or (previous is not None and bar.trading_day < previous.trading_day)
        ):
            raise SubingWatchReplayError()
        if previous is not None and bar.bar_end == previous.bar_end:
            if bar != previous:
                raise SubingWatchReplayError()
            continue
        unique.append(bar)
        previous = bar
    return tuple(unique)


class _IncrementalHigherTimeframeProjector:
    """Consume each causal H1 input once and retain only bounded formula state."""

    def __init__(
        self,
        identity: SubingWatchSourceIdentity,
        bars: tuple[CanonicalBar, ...],
        *,
        live_start_index: int | None = None,
        live_trading_day: date | None = None,
    ) -> None:
        self._identity = identity
        self._bars: tuple[object, ...] = bars
        self._live_start_index = live_start_index
        self._live_trading_day = live_trading_day
        self._index = 0
        self._previous: CanonicalBar | None = None
        self._closes: tuple[float, ...] = ()
        self._latest_ma21: tuple[float, ...] = ()
        self._latest: SubingWatchKernelHigherTimeframe | None = None
        self._unavailable = False
        self.live_fact_adopted = False

    def advance(self, cutoff: datetime) -> SubingWatchKernelHigherTimeframe | None:
        if self._unavailable:
            return None
        while self._index < len(self._bars):
            raw_bar = self._bars[self._index]
            bar_end = _readable_aware_bar_end(raw_bar)
            if bar_end is None:
                self._freeze_unavailable()
                break
            if bar_end > cutoff.astimezone(UTC):
                break
            source_index = self._index
            self._index += 1
            try:
                adopted = self._consume(raw_bar, source_index=source_index)
            except (
                SubingWatchReplayError,
                SubingWatchContractError,
                SubingWatchKernelError,
            ):
                self._freeze_unavailable()
                break
            if (
                adopted
                and self._live_start_index is not None
                and source_index >= self._live_start_index
            ):
                self.live_fact_adopted = True
        return self._latest

    def _consume(self, raw_bar: object, *, source_index: int) -> bool:
        if type(raw_bar) is not CanonicalBar or type(raw_bar.trading_day) is not date:
            raise SubingWatchReplayError()
        bar = raw_bar
        previous = self._previous
        if (
            bar.trading_day < self._identity.segment_start_trading_day
            or (
                self._live_start_index is not None
                and source_index >= self._live_start_index
                and bar.trading_day != self._live_trading_day
            )
            or (previous is not None and bar.bar_end < previous.bar_end)
            or (previous is not None and bar.trading_day < previous.trading_day)
        ):
            raise SubingWatchReplayError()
        if previous is not None and bar.bar_end == previous.bar_end:
            if bar != previous:
                raise SubingWatchReplayError()
            return False

        kernel_bar = to_subing_watch_kernel_bar(bar, source_identity=self._identity)
        closes = (*self._closes, kernel_bar.close)[-21:]
        ma21 = sum(closes) / 21 if len(closes) == 21 else None
        latest_ma21 = self._latest_ma21
        if ma21 is not None:
            latest_ma21 = (*latest_ma21, ma21)[-5:]
        slope = subing_watch_ma21_slope_5_bps_per_bar(latest_ma21, ma21)
        latest = SubingWatchKernelHigherTimeframe(
            identity=kernel_bar.identity,
            bar_end=kernel_bar.bar_end,
            close=kernel_bar.close,
            ma21=ma21,
            ma21_slope_5_bps_per_bar=slope,
            ready=ma21 is not None and slope is not None,
            valid=ma21 is not None and slope is not None,
        )
        self._previous = bar
        self._closes = closes
        self._latest_ma21 = latest_ma21
        self._latest = latest
        return True

    def _freeze_unavailable(self) -> None:
        self._unavailable = True
        self._latest = None


def _readable_aware_bar_end(bar: object) -> datetime | None:
    value = getattr(bar, "bar_end", None)
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        return None
    return value.astimezone(UTC)
