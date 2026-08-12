"""共享的只读市场研究统计。

本模块不执行 I/O。EMA 与 ATR 的算法只委托给 quant-core；此处只组合已经确认的
Canonical 日线或周线，并把缺失、不足窗口和无效分母显式表示为 ``None``。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Sequence

from guiyi_quant.indicators.atr import atr_series
from guiyi_quant.indicators.ema import ema_series

from app.market_data.domain import CanonicalBar


Trend = Literal["up", "down", "neutral", "unavailable"]


@dataclass(frozen=True, slots=True)
class ResearchMetrics:
    """Product Research 与 Radar 复用的一组冻结研究指标。"""

    price_change_1d: Decimal | None
    price_change_5d: Decimal | None
    daily_trend: Trend
    weekly_trend: Trend
    position20: Decimal | None
    distance_to_20d_high: Decimal | None
    distance_to_20d_low: Decimal | None
    volume_ratio20: Decimal | None
    oi_change_1d: Decimal | None
    turnover_change_5d: Decimal | None
    atr14_percentile252: Decimal | None


def calculate_research_metrics(
    daily_bars: Sequence[CanonicalBar],
    weekly_bars: Sequence[CanonicalBar],
) -> ResearchMetrics:
    """计算 P0 冻结的共享研究指标，不以缺失数据替代为零。"""
    daily = tuple(daily_bars)
    weekly = tuple(weekly_bars)
    return ResearchMetrics(
        price_change_1d=_change(daily, 1, field="close"),
        price_change_5d=_change(daily, 5, field="close"),
        daily_trend=_trend(daily),
        weekly_trend=_trend(weekly),
        position20=_position20(daily),
        distance_to_20d_high=_distance_to_extreme(daily, field="high"),
        distance_to_20d_low=_distance_to_extreme(daily, field="low"),
        volume_ratio20=_ratio_to_prior_mean(daily, field="volume", window=20),
        oi_change_1d=_change(daily, 1, field="open_interest"),
        turnover_change_5d=_ratio_to_prior_mean(
            daily,
            field="turnover",
            window=5,
            subtract_one=True,
        ),
        atr14_percentile252=_atr_percentile(daily),
    )


def _change(
    bars: Sequence[CanonicalBar],
    offset: int,
    *,
    field: Literal["close", "open_interest"],
) -> Decimal | None:
    if len(bars) <= offset:
        return None
    current = _finite_decimal(getattr(bars[-1], field))
    previous = _finite_decimal(getattr(bars[-1 - offset], field))
    return _relative_change(current, previous)


def _trend(bars: Sequence[CanonicalBar]) -> Trend:
    if len(bars) < 2:
        return "unavailable"
    series = ema_series(
        [float(item.close) for item in bars],
        period=21,
        seed_policy="sma_window",
    )
    latest, previous = series.points[-1], series.points[-2]
    if not (
        latest.ready
        and latest.valid
        and latest.value is not None
        and previous.ready
        and previous.valid
        and previous.value is not None
    ):
        return "unavailable"
    close = bars[-1].close
    latest_ema = Decimal(str(latest.value))
    previous_ema = Decimal(str(previous.value))
    if close > latest_ema and latest_ema > previous_ema:
        return "up"
    if close < latest_ema and latest_ema < previous_ema:
        return "down"
    return "neutral"


def _position20(bars: Sequence[CanonicalBar]) -> Decimal | None:
    if len(bars) < 20:
        return None
    window = bars[-20:]
    highest = max(item.high for item in window)
    lowest = min(item.low for item in window)
    denominator = highest - lowest
    return None if denominator == 0 else (window[-1].close - lowest) / denominator


def _distance_to_extreme(
    bars: Sequence[CanonicalBar],
    *,
    field: Literal["high", "low"],
) -> Decimal | None:
    if len(bars) < 20:
        return None
    extreme = (
        max(item.high for item in bars[-20:])
        if field == "high"
        else min(item.low for item in bars[-20:])
    )
    return _relative_change(bars[-1].close, extreme)


def _ratio_to_prior_mean(
    bars: Sequence[CanonicalBar],
    *,
    field: Literal["volume", "turnover"],
    window: int,
    subtract_one: bool = False,
) -> Decimal | None:
    if len(bars) <= window:
        return None
    current = _finite_decimal(getattr(bars[-1], field))
    prior = [_finite_decimal(getattr(item, field)) for item in bars[-1 - window : -1]]
    if current is None or any(value is None for value in prior):
        return None
    values = [value for value in prior if value is not None]
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    if mean == 0:
        return None
    ratio = current / mean
    return ratio - Decimal("1") if subtract_one else ratio


def _atr_percentile(bars: Sequence[CanonicalBar]) -> Decimal | None:
    if not bars:
        return None
    series = atr_series(
        [float(item.high) for item in bars],
        [float(item.low) for item in bars],
        [float(item.close) for item in bars],
        period=14,
        smoothing_policy="wilder_sma_seed",
    )
    ready = [
        Decimal(str(point.value))
        for point in series.points
        if point.ready and point.valid and point.value is not None
    ]
    if not ready:
        return None
    latest = ready[-1]
    baseline = ready[-253:-1]
    if len(baseline) < 20:
        return None
    return Decimal(sum(value <= latest for value in baseline)) / Decimal(len(baseline))


def _relative_change(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous <= 0:
        return None
    return current / previous - Decimal("1")


def _finite_decimal(value: Decimal | None) -> Decimal | None:
    return value if value is not None and value.is_finite() else None
