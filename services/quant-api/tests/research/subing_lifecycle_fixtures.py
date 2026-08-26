from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal


from app.market_data.subing_lifecycle import (
    ConfirmationSource,
    SubingLifecycleMachineState,
    SubingOpportunityKey,
    evaluate_subing_lifecycle,
    initial_subing_lifecycle_state,
    step_subing_lifecycle_15m,
    step_subing_lifecycle_5m,
)
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_calibration import SubingCalibration
from app.market_data.subing_lifecycle_policy import (
    SubingLifecyclePolicy,
    load_subing_lifecycle_policy,
)
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingDirection,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
)


_SEGMENT_START = date(2026, 8, 3)
_START = datetime(2026, 8, 3, 1, tzinfo=UTC)


def _bar(
    minutes: int,
    *,
    close: str = "100",
    high: str | None = None,
    low: str | None = None,
    trading_day: date = _SEGMENT_START,
) -> CanonicalBar:
    close_value = Decimal(close)
    return CanonicalBar(
        bar_end=_START + timedelta(minutes=minutes),
        trading_day=trading_day,
        open=close_value,
        high=Decimal(high) if high is not None else close_value + Decimal("1"),
        low=Decimal(low) if low is not None else close_value - Decimal("1"),
        close=close_value,
        volume=Decimal("100"),
        turnover=None,
        open_interest=Decimal("1000"),
    )


def _factor(
    bar: CanonicalBar,
    timeframe: BarFrequency,
    *,
    direction: SubingDirection = SubingDirection.LONG,
    cross: MacdCross = MacdCross.NONE,
    contract: str = "JM2701",
    segment_start: date = _SEGMENT_START,
    status: SubingFactorStatus = SubingFactorStatus.READY,
    volume_ratio: Decimal | None = Decimal("1"),
    ema21: str | None = None,
    slope5: str | None = None,
    slope10: str | None = None,
) -> SubingFactorResult:
    if status is SubingFactorStatus.INSUFFICIENT_DATA:
        return SubingFactorResult(status=status, snapshot=None)
    long = direction is SubingDirection.LONG
    slope5_value = (
        Decimal(slope5) if slope5 is not None else Decimal("2") if long else Decimal("-2")
    )
    slope10_value = (
        Decimal(slope10)
        if slope10 is not None
        else Decimal("1") if long else Decimal("-1")
    )
    ema21_value = (
        Decimal(ema21)
        if ema21 is not None
        else bar.close - Decimal("1") if long else bar.close + Decimal("1")
    )
    price_side = (
        PriceSide.ABOVE
        if bar.close > ema21_value
        else PriceSide.BELOW if bar.close < ema21_value else PriceSide.EQUAL
    )
    return SubingFactorResult(
        status=SubingFactorStatus.READY,
        snapshot=SubingFactorSnapshot(
            timeframe=timeframe,
            bar_end=bar.bar_end,
            trading_day=bar.trading_day,
            contract=contract,
            segment_start_trading_day=segment_start,
            bar_source="canonical",
            close=bar.close,
            ema21=ema21_value,
            price_side=price_side,
            slope_5_raw=slope5_value,
            slope_10_raw=slope10_value,
            slope_5_bps_per_bar=slope5_value,
            slope_10_bps_per_bar=slope10_value,
            macd_dif=Decimal("1"),
            macd_dea=Decimal("1"),
            macd_histogram=Decimal("0"),
            macd_cross=cross,
            macd_cross_level=Decimal("1"),
            macd_zero_distance_abs=Decimal("1"),
            macd_zero_distance_bps=Decimal("1"),
            volume=bar.volume,
            previous_volume=bar.volume,
            volume_ratio_prev=volume_ratio,
        ),
    )


def _accepted_calibration() -> SubingCalibration:
    return SubingCalibration(
        calibration_id="subing_intraday_v1",
        accepted_timeframes=frozenset({BarFrequency.M5, BarFrequency.M15}),
        slope_flat_threshold_bps_per_bar={
            BarFrequency.M5: Decimal("0.688190651160584793944957992"),
            BarFrequency.M15: Decimal("1.329531078893356968545882036"),
        },
    )


def _evaluate(
    bars_5m: tuple[CanonicalBar, ...],
    *,
    factors_5m: tuple[SubingFactorResult, ...] | None = None,
    bars_15m: tuple[CanonicalBar, ...],
    factors_15m: tuple[SubingFactorResult, ...] | None = None,
    calibration: SubingCalibration | None = None,
    policy: SubingLifecyclePolicy | None = None,
):
    if not bars_5m:
        return _evaluate_raw(
            bars_5m,
            factors_5m=factors_5m,
            bars_15m=bars_15m,
            factors_15m=factors_15m,
            calibration=calibration,
            policy=policy,
        )
    reset_bar = replace(
        bars_5m[0],
        bar_end=bars_5m[0].bar_end - timedelta(minutes=5),
    )
    effective_factors = (
        factors_5m
        if factors_5m is not None
        else tuple(_factor(bar, BarFrequency.M5) for bar in bars_5m)
    )
    trace = _evaluate_raw(
        (reset_bar, *bars_5m),
        factors_5m=(
            _factor(
                reset_bar,
                BarFrequency.M5,
                status=SubingFactorStatus.INSUFFICIENT_DATA,
            ),
            *effective_factors,
        ),
        bars_15m=bars_15m,
        factors_15m=factors_15m,
        calibration=calibration,
        policy=policy,
    )
    return replace(trace, snapshots=trace.snapshots[1:])


def _with_lifecycle_reset(
    bars: tuple[CanonicalBar, ...],
    factors: tuple[SubingFactorResult, ...],
) -> tuple[tuple[CanonicalBar, ...], tuple[SubingFactorResult, ...]]:
    reset = replace(bars[0], bar_end=bars[0].bar_end - timedelta(minutes=5))
    return (
        (reset, *bars),
        (
            _factor(
                reset,
                BarFrequency.M5,
                status=SubingFactorStatus.INSUFFICIENT_DATA,
            ),
            *factors,
        ),
    )


def _evaluate_raw(
    bars_5m: tuple[CanonicalBar, ...],
    *,
    factors_5m: tuple[SubingFactorResult, ...] | None = None,
    bars_15m: tuple[CanonicalBar, ...],
    factors_15m: tuple[SubingFactorResult, ...] | None = None,
    calibration: SubingCalibration | None = None,
    policy: SubingLifecyclePolicy | None = None,
):
    return evaluate_subing_lifecycle(
        symbol="JM",
        contract="JM2701",
        segment_start_trading_day=_SEGMENT_START,
        bars_5m=bars_5m,
        factors_5m=(
            factors_5m
            if factors_5m is not None
            else tuple(_factor(bar, BarFrequency.M5) for bar in bars_5m)
        ),
        bars_15m=bars_15m,
        factors_15m=(
            factors_15m
            if factors_15m is not None
            else tuple(_factor(bar, BarFrequency.M15) for bar in bars_15m)
        ),
        calibration=calibration or _accepted_calibration(),
        policy=policy or load_subing_lifecycle_policy(),
    )


def _stream_lifecycle_prefixes(
    bars_5m: tuple[CanonicalBar, ...],
    *,
    factors_5m: tuple[SubingFactorResult, ...],
    bars_15m: tuple[CanonicalBar, ...],
    factors_15m: tuple[SubingFactorResult, ...],
    calibration: SubingCalibration | None = None,
    policy: SubingLifecyclePolicy | None = None,
) -> tuple[SubingLifecycleMachineState, ...]:
    effective_calibration = calibration or _accepted_calibration()
    effective_policy = policy or load_subing_lifecycle_policy()
    state = initial_subing_lifecycle_state(
        symbol="JM",
        contract="JM2701",
        segment_start_trading_day=_SEGMENT_START,
    )
    states: list[SubingLifecycleMachineState] = []
    anchor_index = 0
    for bar_5m, factor_5m in zip(bars_5m, factors_5m):
        while (
            anchor_index < len(bars_15m)
            and bars_15m[anchor_index].bar_end <= bar_5m.bar_end
        ):
            state = step_subing_lifecycle_15m(
                state,
                bar=bars_15m[anchor_index],
                factor=factors_15m[anchor_index],
            )
            anchor_index += 1
        state, snapshot = step_subing_lifecycle_5m(
            state,
            bar=bar_5m,
            factor=factor_5m,
            calibration=effective_calibration,
            policy=effective_policy,
        )
        assert snapshot == state.snapshots[-1]
        states.append(state)
    return tuple(states)


def _long_pivot_prefix() -> tuple[CanonicalBar, ...]:
    return (
        _bar(5, close="100", high="101", low="99"),
        _bar(10, close="100", high="102", low="99"),
        _bar(15, close="105", high="110", low="100"),
        _bar(20, close="102", high="103", low="99"),
        _bar(25, close="108", high="109", low="101"),
        _bar(30, close="111", high="115", low="109"),
    )


def _short_pivot_prefix() -> tuple[CanonicalBar, ...]:
    return (
        _bar(5, close="100", high="101", low="99"),
        _bar(10, close="100", high="101", low="98"),
        _bar(15, close="95", high="100", low="90"),
        _bar(20, close="98", high="101", low="97"),
        _bar(25, close="92", high="99", low="91"),
        _bar(30, close="89", high="91", low="85"),
    )


def _long_trace_with_protective_pivot(
    source: ConfirmationSource,
):
    """Return a real Lifecycle trace whose prior LOW predates the opportunity."""

    prefix = (
        _bar(5, close="100", high="101", low="99"),
        _bar(10, close="100", high="102", low="98"),
        _bar(15, close="95", high="103", low="90"),
        _bar(20, close="100", high="104", low="97"),
        _bar(25, close="102", high="105", low="98"),
        _bar(30, close="108", high="110", low="99"),
        _bar(35, close="105", high="106", low="100"),
        _bar(40, close="106", high="107", low="101"),
    )
    if source is ConfirmationSource.FORMAL_V1:
        bars = (*prefix[:5], _bar(30, close="100", high="101", low="99"))
        factors = tuple(
            _factor(
                bar,
                BarFrequency.M5,
                direction=(
                    SubingDirection.LONG
                    if index == len(bars) - 1
                    else SubingDirection.SHORT
                ),
                cross=(MacdCross.GOLDEN if index == len(bars) - 1 else MacdCross.NONE),
                volume_ratio=(
                    Decimal("3") if index == len(bars) - 1 else Decimal("1")
                ),
            )
            for index, bar in enumerate(bars)
        )
        return _evaluate(
            bars,
            factors_5m=factors,
            bars_15m=(_bar(0), _bar(15), _bar(30)),
        )

    setup = _bar(45, close="108", high="109", low="107")
    if source is ConfirmationSource.MOMENTUM_HOLD:
        bars = (
            *prefix[:5],
            _bar(30, close="100", high="101", low="99"),
            _bar(35, close="101", high="102", low="100"),
            _bar(40, close="102", high="103", low="101"),
            _bar(45, close="103", high="104", low="102"),
        )
        factors = tuple(
            _factor(
                bar,
                BarFrequency.M5,
                direction=(
                    SubingDirection.LONG if index >= 5 else SubingDirection.SHORT
                ),
                cross=(MacdCross.GOLDEN if index == 6 else MacdCross.NONE),
            )
            for index, bar in enumerate(bars)
        )
        return _evaluate(
            bars,
            factors_5m=factors,
            bars_15m=(_bar(0), _bar(15), _bar(30), _bar(45)),
        )

    breakout = _bar(50, close="111", high="112", low="110")
    if source is ConfirmationSource.PIVOT_BREAK_HOLD:
        tail = (
            setup,
            breakout,
            _bar(55, close="112", high="113", low="111"),
            _bar(60, close="113", high="114", low="112"),
        )
    else:
        tail = (
            setup,
            breakout,
            _bar(55, close="111", high="112", low="109"),
            _bar(60, close="111", high="111.5", low="110"),
            _bar(65, close="113", high="114", low="112"),
        )
    bars = (*prefix, *tail)
    factors = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            direction=(
                SubingDirection.LONG if bar.bar_end >= setup.bar_end else SubingDirection.SHORT
            ),
        )
        for bar in bars
    )
    return _evaluate(
        bars,
        factors_5m=factors,
        bars_15m=tuple(_bar(minutes) for minutes in (0, 15, 30, 45, 60)),
    )


def _opportunity_key(
    *,
    direction: SubingDirection = SubingDirection.LONG,
    origin_at: datetime = datetime(2026, 8, 19, 1, 5, tzinfo=timezone.utc),
) -> SubingOpportunityKey:
    return SubingOpportunityKey(
        policy_id="subing_lifecycle_v2_research_v1",
        symbol="JM",
        contract="JM2701",
        segment_start_trading_day=date(2026, 8, 3),
        direction=direction,
        origin_at=origin_at,
    )
