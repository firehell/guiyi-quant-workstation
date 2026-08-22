from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal


from app.market_data.subing_lifecycle import (
    SubingOpportunityKey,
    evaluate_subing_lifecycle,
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
