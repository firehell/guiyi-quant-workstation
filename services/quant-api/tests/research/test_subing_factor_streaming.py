from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_research import (
    calculate_subing_factor_series,
    initial_subing_factor_state,
    step_subing_factor,
)


def _factor_bars(timeframe: BarFrequency) -> tuple[CanonicalBar, ...]:
    minutes = 5 if timeframe is BarFrequency.M5 else 15
    start = datetime(2026, 8, 3, 1, tzinfo=UTC)
    return tuple(
        CanonicalBar(
            bar_end=start + timedelta(minutes=minutes * index),
            trading_day=date(2026, 8, 3),
            open=close,
            high=close + Decimal("1.25"),
            low=close - Decimal("1.5"),
            close=close,
            volume=Decimal("100") + Decimal((index * 17) % 43),
            turnover=None,
            open_interest=None,
        )
        for index in range(52)
        for close in (
            Decimal("180.125")
            + Decimal(index) * Decimal("0.37")
            + Decimal((index * 7) % 11) * Decimal("0.09"),
        )
    )


def _stream_factor_results(
    bars: tuple[CanonicalBar, ...],
    *,
    timeframe: BarFrequency,
):
    state = initial_subing_factor_state(
        timeframe=timeframe,
        contract="JM2601",
        segment_start_trading_day=date(2026, 8, 1),
        latest_bar_source="canonical",
    )
    results = []
    for bar in bars:
        state, result = step_subing_factor(state, bar)
        results.append(result)
        assert len(state.trend.ema_points) <= 10
        assert len(state.macd.fast.seed_values) <= state.macd.fast.period
        assert len(state.macd.slow.seed_values) <= state.macd.slow.period
        assert len(state.macd.signal.seed_values) <= state.macd.signal.period
    return tuple(results)


@pytest.mark.parametrize("timeframe", (BarFrequency.M5, BarFrequency.M15))
def test_factor_stream_matches_batch_for_every_prefix(
    timeframe: BarFrequency,
) -> None:
    """Catches streaming warm-up, cross, volume, or identity parity drift."""
    bars = _factor_bars(timeframe)

    for prefix in range(1, len(bars) + 1):
        batch = calculate_subing_factor_series(
            bars[:prefix],
            timeframe=timeframe,
            contract="JM2601",
            segment_start_trading_day=date(2026, 8, 1),
            latest_bar_source="canonical",
        )
        stream = _stream_factor_results(bars[:prefix], timeframe=timeframe)
        assert stream == batch


@pytest.mark.parametrize("timeframe", (BarFrequency.M5, BarFrequency.M15))
def test_factor_stream_append_is_prefix_invariant(timeframe: BarFrequency) -> None:
    """Catches one appended future Bar changing any prior Factor result."""
    bars = _factor_bars(timeframe)

    original = _stream_factor_results(bars[:-1], timeframe=timeframe)
    appended = _stream_factor_results(bars, timeframe=timeframe)

    assert appended[:-1] == original


def test_factor_stream_rejects_duplicate_or_reversed_watermark() -> None:
    """Catches a stale Bar mutating the current physical-segment state."""
    bars = _factor_bars(BarFrequency.M5)
    state = initial_subing_factor_state(
        timeframe=BarFrequency.M5,
        contract="JM2601",
        segment_start_trading_day=date(2026, 8, 1),
        latest_bar_source="canonical",
    )
    state, _ = step_subing_factor(state, bars[0])

    with pytest.raises(ValueError, match="bar_end must be strictly increasing"):
        step_subing_factor(state, bars[0])


def test_factor_stream_rejects_cross_segment_nested_state() -> None:
    """Catches an outer Factor identity reusing another segment's trend state."""
    bars = _factor_bars(BarFrequency.M5)
    state = initial_subing_factor_state(
        timeframe=BarFrequency.M5,
        contract="JM2601",
        segment_start_trading_day=date(2026, 8, 1),
        latest_bar_source="canonical",
    )
    mismatched = replace(state, contract="RB2601")

    with pytest.raises(ValueError, match="SUBING_FACTOR_STATE_IDENTITY_MISMATCH"):
        step_subing_factor(mismatched, bars[0])
