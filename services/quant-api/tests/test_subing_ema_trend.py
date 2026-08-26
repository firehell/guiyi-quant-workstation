from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from guiyi_quant.indicators import ema_series

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    ResolvedContractSegment,
)
from app.market_data.subing_ema_trend import (
    SubingEmaTrendStatus,
    calculate_subing_ema_trend,
    calculate_subing_ema_trend_series,
    calculate_subing_ema_trend_stitched,
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


def _pre_refactor_golden_bars(
    frequency: BarFrequency,
) -> tuple[CanonicalBar, ...]:
    start = datetime(2026, 8, 3, 1, tzinfo=UTC)
    step = 5 if frequency is BarFrequency.M5 else 15
    closes = (
        [
            Decimal("100.125")
            + Decimal(index) * Decimal("0.73")
            + Decimal(index % 4) * Decimal("0.11")
            for index in range(48)
        ]
        if frequency is BarFrequency.M5
        else [
            Decimal("250.875")
            - Decimal(index) * Decimal("0.61")
            + Decimal(index % 5) * Decimal("0.07")
            for index in range(48)
        ]
    )
    return tuple(
        CanonicalBar(
            bar_end=start + timedelta(minutes=step * index),
            trading_day=date(2026, 8, 3),
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


def _stitched_bars() -> tuple[CanonicalBar, ...]:
    start_day = date(2026, 7, 23)
    closes = tuple(
        [Decimal("3100") + Decimal(index) for index in range(20)]
        + [Decimal("3500") + Decimal(index) for index in range(10)]
    )
    return tuple(
        CanonicalBar(
            bar_end=datetime.combine(
                start_day + timedelta(days=index),
                datetime.min.time(),
                UTC,
            )
            + timedelta(hours=15),
            trading_day=start_day + timedelta(days=index),
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


_STITCHED_SEGMENTS = (
    ResolvedContractSegment("RB2605", date(2026, 7, 23), date(2026, 8, 11)),
    ResolvedContractSegment("RB2610", date(2026, 8, 12), date(2026, 8, 31)),
)


def _calculate_stitched(
    bars: tuple[CanonicalBar, ...],
    *,
    current_contract: str = "RB2610",
    current_segment_start_trading_day: date = date(2026, 8, 12),
    segments: tuple[ResolvedContractSegment, ...] = _STITCHED_SEGMENTS,
):
    return calculate_subing_ema_trend_stitched(
        bars,
        timeframe=BarFrequency.D1,
        current_contract=current_contract,
        current_segment_start_trading_day=current_segment_start_trading_day,
        resolved_contract_segments=segments,
    )


def _regression_slope(values: tuple[Decimal, ...]) -> Decimal:
    x_mean = Decimal(len(values) - 1) / Decimal(2)
    y_mean = sum(values, Decimal(0)) / Decimal(len(values))
    return sum(
        (
            (Decimal(index) - x_mean) * (value - y_mean)
            for index, value in enumerate(values)
        ),
        Decimal(0),
    ) / sum(
        ((Decimal(index) - x_mean) ** 2 for index in range(len(values))),
        Decimal(0),
    )


def test_stitched_trend_uses_raw_cross_roll_closes_and_records_lineage() -> None:
    """Catches smoothing/resetting the rollover or mislabeling warm-up lineage."""
    bars = _stitched_bars()
    raw_ema = ema_series(
        [float(bar.close) for bar in bars],
        21,
        bar_ends=[bar.bar_end.isoformat() for bar in bars],
        seed_policy="sma_window",
        indicator_code="ema21",
    )
    ema_values = tuple(
        Decimal(str(point.value))
        for point in raw_ema.points[-10:]
        if point.value is not None
    )

    result = _calculate_stitched(bars)

    assert result.status is SubingEmaTrendStatus.READY
    assert result.snapshot is not None
    snapshot = result.snapshot
    assert len(ema_values) == 10
    assert snapshot.ema21 == ema_values[-1]
    expected_slope_5 = _regression_slope(ema_values[-5:])
    expected_slope_10 = _regression_slope(ema_values)
    assert snapshot.slope_5_raw == expected_slope_5
    assert snapshot.slope_10_raw == expected_slope_10
    assert snapshot.slope_5_bps_per_bar == (
        expected_slope_5
        / (sum(ema_values[-5:], Decimal(0)) / Decimal(5))
        * Decimal(10000)
    )
    assert snapshot.slope_10_bps_per_bar == (
        expected_slope_10
        / (sum(ema_values, Decimal(0)) / Decimal(10))
        * Decimal(10000)
    )
    assert snapshot.contract == "RB2610"
    assert snapshot.current_segment_start_trading_day == date(2026, 8, 12)
    assert snapshot.warmup_start_trading_day == bars[0].trading_day
    assert snapshot.warmup_bar_count == 30
    assert snapshot.warmup_segment_count == 2
    assert snapshot.history_mode == "rank1_stitched_raw"


def test_stitched_trend_requires_all_thirty_raw_bars() -> None:
    """Catches treating 29 EMA warm-up bars as ready."""
    bars = _stitched_bars()

    insufficient = _calculate_stitched(bars[:-1])
    ready = _calculate_stitched(bars)

    assert insufficient.status is SubingEmaTrendStatus.INSUFFICIENT_DATA
    assert insufficient.snapshot is None
    assert ready.status is SubingEmaTrendStatus.READY
    assert ready.snapshot is not None


def test_stitched_trend_rejects_empty_current_contract() -> None:
    with pytest.raises(ValueError, match="current_contract must not be empty"):
        _calculate_stitched(_stitched_bars(), current_contract="   ")


def test_stitched_trend_rejects_non_increasing_bar_end() -> None:
    bars = list(_stitched_bars())
    bars[20] = replace(bars[20], bar_end=bars[19].bar_end)

    with pytest.raises(ValueError, match="bar_end must be strictly increasing"):
        _calculate_stitched(tuple(bars))


@pytest.mark.parametrize(
    "segments",
    (
        (
            ResolvedContractSegment(
                "RB2605", date(2026, 7, 23), date(2026, 8, 10)
            ),
            _STITCHED_SEGMENTS[1],
        ),
        (
            ResolvedContractSegment(
                "RB2605", date(2026, 7, 23), date(2026, 8, 12)
            ),
            _STITCHED_SEGMENTS[1],
        ),
    ),
)
def test_stitched_trend_requires_every_bar_covered_exactly_once(
    segments: tuple[ResolvedContractSegment, ...],
) -> None:
    """Catches accepting a map gap or overlap inside the EMA input window."""
    with pytest.raises(
        ValueError,
        match="bars must be covered exactly once by resolved_contract_segments",
    ):
        _calculate_stitched(_stitched_bars(), segments=segments)


def test_stitched_trend_requires_current_segment_lineage_to_own_latest_bar() -> None:
    segments = (
        ResolvedContractSegment(
            "RB2605", date(2026, 7, 23), date(2026, 8, 12)
        ),
        ResolvedContractSegment(
            "RB2610", date(2026, 8, 13), date(2026, 8, 31)
        ),
    )

    with pytest.raises(
        ValueError,
        match="current segment must contain latest trading day",
    ):
        _calculate_stitched(_stitched_bars(), segments=segments)


def test_stitched_trend_requires_latest_owner_to_equal_current_contract() -> None:
    segments = (
        _STITCHED_SEGMENTS[0],
        ResolvedContractSegment(
            "RB2701", date(2026, 8, 12), date(2026, 8, 31)
        ),
    )

    with pytest.raises(
        ValueError,
        match="latest segment owner must equal current_contract",
    ):
        _calculate_stitched(_stitched_bars(), segments=segments)


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


def test_segment_local_v1_rejects_bar_before_segment_start() -> None:
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


@pytest.mark.parametrize(
    ("frequency", "expected"),
    [
        (
            BarFrequency.M5,
            (
                Decimal("127.31271"),
                PriceSide.ABOVE,
                Decimal("0.7301415"),
                Decimal("0.7302731818181818181818181818"),
                Decimal("58.02041428197590688771069916"),
                Decimal("58.88562894977286565845070983"),
            ),
        ),
        (
            BarFrequency.M15,
            (
                Decimal("228.438223"),
                PriceSide.BELOW,
                Decimal("-0.6133585"),
                Decimal("-0.6107582969696969696969696970"),
                Decimal("-26.70672491294420647077695257"),
                Decimal("-26.41810766206838140590736725"),
            ),
        ),
    ],
)
def test_m5_m15_factor_and_trend_match_pre_refactor_golden_values(
    frequency: BarFrequency,
    expected: tuple[Decimal, PriceSide, Decimal, Decimal, Decimal, Decimal],
) -> None:
    """Catches 5m/15m EMA facts drifting from the pre-seam implementation."""
    bars = _pre_refactor_golden_bars(frequency)
    factor = calculate_subing_factor(
        bars,
        timeframe=frequency,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )
    trend = calculate_subing_ema_trend(
        bars,
        timeframe=frequency,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
    )

    assert factor.status is SubingFactorStatus.READY
    assert factor.snapshot is not None
    assert trend.status is SubingEmaTrendStatus.READY
    assert trend.snapshot is not None
    assert (
        factor.snapshot.ema21,
        factor.snapshot.price_side,
        factor.snapshot.slope_5_raw,
        factor.snapshot.slope_10_raw,
        factor.snapshot.slope_5_bps_per_bar,
        factor.snapshot.slope_10_bps_per_bar,
    ) == expected
    assert (
        trend.snapshot.ema21,
        trend.snapshot.price_side,
        trend.snapshot.slope_5_raw,
        trend.snapshot.slope_10_raw,
        trend.snapshot.slope_5_bps_per_bar,
        trend.snapshot.slope_10_bps_per_bar,
    ) == expected
