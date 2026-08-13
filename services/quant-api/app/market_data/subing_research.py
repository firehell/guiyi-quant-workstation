from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from guiyi_quant.indicators import (
    IndicatorPoint,
    ema_series,
    get_indicator,
    macd_series,
    require_formal_policy,
)

from .domain import BarFrequency, CanonicalBar


class SubingFactorStatus(StrEnum):
    READY = "ready"
    INSUFFICIENT_DATA = "insufficient_data"


class PriceSide(StrEnum):
    ABOVE = "above"
    BELOW = "below"
    EQUAL = "equal"
    UNAVAILABLE = "unavailable"


class MacdCross(StrEnum):
    GOLDEN = "golden"
    DEAD = "dead"
    NONE = "none"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SubingFactorSnapshot:
    timeframe: BarFrequency
    bar_end: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    bar_source: str
    close: Decimal
    ema21: Decimal
    price_side: PriceSide
    slope_5_raw: Decimal
    slope_10_raw: Decimal
    slope_5_bps_per_bar: Decimal
    slope_10_bps_per_bar: Decimal
    macd_dif: Decimal
    macd_dea: Decimal
    macd_histogram: Decimal
    macd_cross: MacdCross
    macd_cross_level: Decimal
    macd_zero_distance_abs: Decimal
    macd_zero_distance_bps: Decimal
    volume: Decimal
    previous_volume: Decimal
    volume_ratio_prev: Decimal | None


@dataclass(frozen=True, slots=True)
class SubingFactorResult:
    status: SubingFactorStatus
    snapshot: SubingFactorSnapshot | None


def calculate_subing_factor_series(
    bars: Sequence[CanonicalBar],
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    latest_bar_source: str,
) -> tuple[SubingFactorResult, ...]:
    """Calculate aligned, segment-local SuBing Factor observations."""

    _validate_inputs(
        bars,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        latest_bar_source=latest_bar_source,
    )
    if not bars:
        return ()

    closes = [float(bar.close) for bar in bars]
    bar_ends = [bar.bar_end.isoformat() for bar in bars]
    ema = ema_series(
        closes,
        21,
        bar_ends=bar_ends,
        seed_policy="sma_window",
        indicator_code="ema21",
    )

    policy = require_formal_policy(
        "web_macd_legacy_v1",
        consumer="subing_factor_observation",
    )
    definition = get_indicator("macd")
    assert policy.policy_id == definition.formal_policy_id
    parameters = definition.default_parameters
    assert definition.seed_policy is not None
    assert definition.histogram_scale is not None
    macd = macd_series(
        closes,
        int(parameters["fast"]),
        int(parameters["slow"]),
        int(parameters["signal"]),
        ema_seed_policy=definition.seed_policy,
        histogram_scale=definition.histogram_scale,
        bar_ends=bar_ends,
        round_digits=int(parameters["round_digits"]),
    )

    results = tuple(
        _result_at(
            bars,
            index=index,
            timeframe=timeframe,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            bar_source=latest_bar_source,
            ema_points=ema.points,
            dif_points=macd.dif.points,
            dea_points=macd.dea.points,
            histogram_points=macd.histogram.points,
        )
        for index in range(len(bars))
    )
    return results


def calculate_subing_factor(
    bars: Sequence[CanonicalBar],
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    latest_bar_source: str,
) -> SubingFactorResult:
    """Return the latest aligned SuBing Factor result."""

    results = calculate_subing_factor_series(
        bars,
        timeframe=timeframe,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        latest_bar_source=latest_bar_source,
    )
    if not results:
        return _insufficient()
    return results[-1]


def _result_at(
    bars: Sequence[CanonicalBar],
    *,
    index: int,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    bar_source: str,
    ema_points: Sequence[IndicatorPoint],
    dif_points: Sequence[IndicatorPoint],
    dea_points: Sequence[IndicatorPoint],
    histogram_points: Sequence[IndicatorPoint],
) -> SubingFactorResult:
    if index < 9:
        return _insufficient()

    ema_window = ema_points[index - 9 : index + 1]
    current_dif = dif_points[index]
    previous_dif = dif_points[index - 1]
    current_dea = dea_points[index]
    previous_dea = dea_points[index - 1]
    current_histogram = histogram_points[index]
    required_points = (
        *ema_window,
        current_dif,
        previous_dif,
        current_dea,
        previous_dea,
        current_histogram,
    )
    if len(ema_window) != 10 or not all(_point_has_value(point) for point in required_points):
        return _insufficient()

    bar = bars[index]
    previous_bar = bars[index - 1]
    if bar.close == 0:
        return _insufficient()

    ema_values = tuple(_point_decimal(point) for point in ema_window)
    ema21 = ema_values[-1]
    slope_5_raw = _regression_slope(ema_values[-5:])
    slope_10_raw = _regression_slope(ema_values)
    ema_5_mean = sum(ema_values[-5:], Decimal(0)) / Decimal(5)
    ema_10_mean = sum(ema_values, Decimal(0)) / Decimal(10)
    if ema_5_mean == 0 or ema_10_mean == 0:
        return _insufficient()

    dif = _point_decimal(current_dif)
    previous_dif_value = _point_decimal(previous_dif)
    dea = _point_decimal(current_dea)
    previous_dea_value = _point_decimal(previous_dea)
    histogram = _point_decimal(current_histogram)
    cross_level = (dif + dea) / Decimal(2)
    zero_distance_abs = abs(cross_level)

    if bar.close > ema21:
        price_side = PriceSide.ABOVE
    elif bar.close < ema21:
        price_side = PriceSide.BELOW
    else:
        price_side = PriceSide.EQUAL

    if previous_dif_value <= previous_dea_value and dif > dea:
        cross = MacdCross.GOLDEN
    elif previous_dif_value >= previous_dea_value and dif < dea:
        cross = MacdCross.DEAD
    else:
        cross = MacdCross.NONE

    volume_ratio = None
    if previous_bar.volume > 0:
        volume_ratio = bar.volume / previous_bar.volume

    return SubingFactorResult(
        status=SubingFactorStatus.READY,
        snapshot=SubingFactorSnapshot(
            timeframe=timeframe,
            bar_end=bar.bar_end,
            trading_day=bar.trading_day,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            bar_source=bar_source,
            close=bar.close,
            ema21=ema21,
            price_side=price_side,
            slope_5_raw=slope_5_raw,
            slope_10_raw=slope_10_raw,
            slope_5_bps_per_bar=slope_5_raw / ema_5_mean * Decimal(10000),
            slope_10_bps_per_bar=slope_10_raw / ema_10_mean * Decimal(10000),
            macd_dif=dif,
            macd_dea=dea,
            macd_histogram=histogram,
            macd_cross=cross,
            macd_cross_level=cross_level,
            macd_zero_distance_abs=zero_distance_abs,
            macd_zero_distance_bps=zero_distance_abs / bar.close * Decimal(10000),
            volume=bar.volume,
            previous_volume=previous_bar.volume,
            volume_ratio_prev=volume_ratio,
        ),
    )


def _validate_inputs(
    bars: Sequence[CanonicalBar],
    *,
    contract: str,
    segment_start_trading_day: date,
    latest_bar_source: str,
) -> None:
    if not contract.strip():
        raise ValueError("contract must not be empty")
    if not latest_bar_source.strip():
        raise ValueError("latest_bar_source must not be empty")
    if any(bar.trading_day < segment_start_trading_day for bar in bars):
        raise ValueError("bars before segment_start_trading_day are not allowed")
    if any(current.bar_end <= previous.bar_end for previous, current in zip(bars, bars[1:], strict=False)):
        raise ValueError("bar_end must be strictly increasing")


def _point_has_value(point: IndicatorPoint) -> bool:
    return point.ready and point.valid and point.value is not None


def _point_decimal(point: IndicatorPoint) -> Decimal:
    value = point.value
    assert value is not None
    return Decimal(str(value))


def _regression_slope(values: Sequence[Decimal]) -> Decimal:
    n = Decimal(len(values))
    x_mean = Decimal(len(values) - 1) / Decimal(2)
    y_mean = sum(values, Decimal(0)) / n
    numerator = sum(
        (
            (Decimal(index) - x_mean) * (value - y_mean)
            for index, value in enumerate(values)
        ),
        Decimal(0),
    )
    denominator = sum(
        ((Decimal(index) - x_mean) ** 2 for index in range(len(values))),
        Decimal(0),
    )
    return numerator / denominator


def _insufficient() -> SubingFactorResult:
    return SubingFactorResult(
        status=SubingFactorStatus.INSUFFICIENT_DATA,
        snapshot=None,
    )
