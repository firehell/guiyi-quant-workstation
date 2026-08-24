from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from guiyi_quant.indicators import IndicatorPoint, ema_series

from .domain import BarFrequency, CanonicalBar


class SubingEmaTrendStatus(StrEnum):
    READY = "ready"
    INSUFFICIENT_DATA = "insufficient_data"


class PriceSide(StrEnum):
    ABOVE = "above"
    BELOW = "below"
    EQUAL = "equal"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SubingEmaTrendSnapshot:
    timeframe: BarFrequency
    bar_end: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    close: Decimal
    ema21: Decimal
    price_side: PriceSide
    slope_5_raw: Decimal
    slope_10_raw: Decimal
    slope_5_bps_per_bar: Decimal
    slope_10_bps_per_bar: Decimal


@dataclass(frozen=True, slots=True)
class SubingEmaTrendResult:
    status: SubingEmaTrendStatus
    snapshot: SubingEmaTrendSnapshot | None


def calculate_subing_ema_trend_series(
    bars: Sequence[CanonicalBar],
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
) -> tuple[SubingEmaTrendResult, ...]:
    """Calculate aligned, segment-local EMA21 trend observations."""

    _validate_inputs(
        bars,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
    )
    if not bars:
        return ()

    ema = ema_series(
        [float(bar.close) for bar in bars],
        21,
        bar_ends=[bar.bar_end.isoformat() for bar in bars],
        seed_policy="sma_window",
        indicator_code="ema21",
    )
    return tuple(
        _result_at(
            bars,
            index=index,
            timeframe=timeframe,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            ema_points=ema.points,
        )
        for index in range(len(bars))
    )


def calculate_subing_ema_trend(
    bars: Sequence[CanonicalBar],
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
) -> SubingEmaTrendResult:
    """Return the latest aligned EMA21 trend result."""

    results = calculate_subing_ema_trend_series(
        bars,
        timeframe=timeframe,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
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
    ema_points: Sequence[IndicatorPoint],
) -> SubingEmaTrendResult:
    if index < 9:
        return _insufficient()

    ema_window = ema_points[index - 9 : index + 1]
    if len(ema_window) != 10 or not all(
        _point_has_value(point) for point in ema_window
    ):
        return _insufficient()

    ema_values = tuple(_point_decimal(point) for point in ema_window)
    ema21 = ema_values[-1]
    slope_5_raw = _regression_slope(ema_values[-5:])
    slope_10_raw = _regression_slope(ema_values)
    ema_5_mean = sum(ema_values[-5:], Decimal(0)) / Decimal(5)
    ema_10_mean = sum(ema_values, Decimal(0)) / Decimal(10)
    if ema_5_mean == 0 or ema_10_mean == 0:
        return _insufficient()

    bar = bars[index]
    if bar.close > ema21:
        price_side = PriceSide.ABOVE
    elif bar.close < ema21:
        price_side = PriceSide.BELOW
    else:
        price_side = PriceSide.EQUAL

    return SubingEmaTrendResult(
        status=SubingEmaTrendStatus.READY,
        snapshot=SubingEmaTrendSnapshot(
            timeframe=timeframe,
            bar_end=bar.bar_end,
            trading_day=bar.trading_day,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            close=bar.close,
            ema21=ema21,
            price_side=price_side,
            slope_5_raw=slope_5_raw,
            slope_10_raw=slope_10_raw,
            slope_5_bps_per_bar=slope_5_raw / ema_5_mean * Decimal(10000),
            slope_10_bps_per_bar=slope_10_raw / ema_10_mean * Decimal(10000),
        ),
    )


def _validate_inputs(
    bars: Sequence[CanonicalBar],
    *,
    contract: str,
    segment_start_trading_day: date,
) -> None:
    if not contract.strip():
        raise ValueError("contract must not be empty")
    if any(bar.trading_day < segment_start_trading_day for bar in bars):
        raise ValueError("bars before segment_start_trading_day are not allowed")
    if any(
        current.bar_end <= previous.bar_end
        for previous, current in zip(bars, bars[1:], strict=False)
    ):
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


def _insufficient() -> SubingEmaTrendResult:
    return SubingEmaTrendResult(
        status=SubingEmaTrendStatus.INSUFFICIENT_DATA,
        snapshot=None,
    )
