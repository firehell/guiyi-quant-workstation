from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_ema_trend import (
    SubingEmaTrendStatus,
    calculate_subing_ema_trend,
    calculate_subing_ema_trend_series,
)
from app.market_data.subing_research import (
    PriceSide,
    SubingFactorStatus,
    calculate_subing_factor,
)


def _bars_from_closes(closes: list[Decimal]) -> tuple[CanonicalBar, ...]:
    start = datetime(2026, 8, 3, 1, tzinfo=UTC)
    return tuple(
        CanonicalBar(
            bar_end=start + timedelta(hours=index),
            trading_day=date(2026, 8, 3) + timedelta(days=index // 8),
            open=close,
            high=close + Decimal("1"),
            low=close - Decimal("1"),
            close=close,
            volume=Decimal("100") + Decimal(index),
            turnover=None,
            open_interest=None,
        )
        for index, close in enumerate(closes)
    )


def _calculate(bars: tuple[CanonicalBar, ...]):
    return calculate_subing_ema_trend(
        bars,
        timeframe=BarFrequency.H1,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
    )


def test_rising_ema_trend_is_ready_above_with_positive_slopes() -> None:
    """Catches reversed price-side or slope direction on a rising series."""
    bars = _bars_from_closes(
        [Decimal("100") + Decimal(index) for index in range(40)]
    )

    result = _calculate(bars)

    assert result.status is SubingEmaTrendStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.price_side is PriceSide.ABOVE
    assert result.snapshot.slope_5_bps_per_bar > 0
    assert result.snapshot.slope_10_bps_per_bar > 0


def test_descending_ema_trend_is_ready_below_with_negative_slopes() -> None:
    """Catches reversed price-side or slope direction on a falling series."""
    bars = _bars_from_closes(
        [Decimal("200") - Decimal(index) for index in range(40)]
    )

    result = _calculate(bars)

    assert result.status is SubingEmaTrendStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.price_side is PriceSide.BELOW
    assert result.snapshot.slope_5_bps_per_bar < 0
    assert result.snapshot.slope_10_bps_per_bar < 0


def test_flat_ema_trend_is_equal_with_exact_zero_slopes() -> None:
    """Catches treating a flat EMA as directional or introducing slope noise."""
    bars = _bars_from_closes([Decimal("100") for _ in range(40)])

    result = _calculate(bars)

    assert result.status is SubingEmaTrendStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.price_side is PriceSide.EQUAL
    assert result.snapshot.slope_5_raw == Decimal(0)
    assert result.snapshot.slope_10_raw == Decimal(0)
    assert result.snapshot.slope_5_bps_per_bar == Decimal(0)
    assert result.snapshot.slope_10_bps_per_bar == Decimal(0)


def test_series_stays_insufficient_until_ten_ready_ema_points_exist() -> None:
    """Catches exposing trend facts before the EMA21 plus 10-point warm-up."""
    bars = _bars_from_closes(
        [Decimal("100") + Decimal(index) for index in range(30)]
    )

    series = calculate_subing_ema_trend_series(
        bars,
        timeframe=BarFrequency.H1,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
    )

    assert len(series) == 30
    assert all(
        result.status is SubingEmaTrendStatus.INSUFFICIENT_DATA
        for result in series[:-1]
    )
    assert series[-1].status is SubingEmaTrendStatus.READY


def test_empty_contract_is_rejected() -> None:
    """Catches accepting an unidentifiable contract segment."""
    bars = _bars_from_closes([Decimal("100") for _ in range(40)])

    with pytest.raises(ValueError, match="contract must not be empty"):
        calculate_subing_ema_trend(
            bars,
            timeframe=BarFrequency.H1,
            contract="   ",
            segment_start_trading_day=bars[0].trading_day,
        )


def test_non_increasing_bar_end_is_rejected() -> None:
    """Catches regression windows built from duplicate or reversed bar order."""
    bars = list(_bars_from_closes([Decimal("100") for _ in range(40)]))
    bars[20] = replace(bars[20], bar_end=bars[19].bar_end)

    with pytest.raises(ValueError, match="bar_end must be strictly increasing"):
        calculate_subing_ema_trend(
            bars,
            timeframe=BarFrequency.H1,
            contract="JM2609",
            segment_start_trading_day=bars[0].trading_day,
        )


def test_bar_before_segment_start_is_rejected() -> None:
    """Catches trend leakage from a prior dominant-contract segment."""
    bars = _bars_from_closes([Decimal("100") for _ in range(40)])

    with pytest.raises(
        ValueError,
        match="bars before segment_start_trading_day are not allowed",
    ):
        calculate_subing_ema_trend(
            bars,
            timeframe=BarFrequency.H1,
            contract="JM2609",
            segment_start_trading_day=bars[0].trading_day + timedelta(days=1),
        )


def test_existing_factor_and_frequency_neutral_trend_have_exact_ema_parity() -> None:
    """Catches any EMA, price-side, slope, or normalization semantic drift."""
    bars = _bars_from_closes(
        [Decimal("100") + Decimal(index) for index in range(48)]
    )

    factor = calculate_subing_factor(
        bars,
        timeframe=BarFrequency.H1,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )
    trend = _calculate(bars)

    assert factor.status is SubingFactorStatus.READY
    assert factor.snapshot is not None
    assert trend.status is SubingEmaTrendStatus.READY
    assert trend.snapshot is not None
    assert factor.snapshot.ema21 == trend.snapshot.ema21
    assert factor.snapshot.price_side is trend.snapshot.price_side
    assert factor.snapshot.slope_5_raw == trend.snapshot.slope_5_raw
    assert factor.snapshot.slope_10_raw == trend.snapshot.slope_10_raw
    assert (
        factor.snapshot.slope_5_bps_per_bar
        == trend.snapshot.slope_5_bps_per_bar
    )
    assert (
        factor.snapshot.slope_10_bps_per_bar
        == trend.snapshot.slope_10_bps_per_bar
    )
