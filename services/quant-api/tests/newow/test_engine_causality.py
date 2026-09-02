from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow.cup_handle import calculate_cup_handle_series
from guiyi_quant.newow.engine import (
    NewowTrendD1Engine,
    NewowTrendD1EngineState,
    calculate_newow_trend_frames,
)
from guiyi_quant.newow.escape_d123 import calculate_escape_series
from guiyi_quant.newow.models import NewowDailyBar, NewowMarkerType, TrendBandState
from guiyi_quant.newow.trend_band import calculate_trend_band

from .fixtures import (
    bullish_true_cup_handle,
    ready_and_breakout_same_bar,
    rollover_split_candidate,
)


def _run_incremental(bars: tuple[NewowDailyBar, ...]) -> tuple:
    engine = NewowTrendD1Engine.initial()
    return tuple(engine.step(bar) for bar in bars)


def _bar(index: int, close: int, *, eligible: bool = True) -> NewowDailyBar:
    day = date(2026, 1, 5) + timedelta(days=index)
    price = Decimal(close)
    return NewowDailyBar(
        product="rb",
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=100,
        open_interest=200,
        source_identity=f"engine:{index}",
        observation_eligible=eligible,
        completed=True,
    )


def test_engine_preserves_slice_a_and_cup_same_bar_results() -> None:
    """Replacing a kernel result or its input bar would break exact frame parity."""

    bars = ready_and_breakout_same_bar()
    steps = _run_incremental(bars)
    trend = calculate_trend_band(bars)
    escape = calculate_escape_series(bars)
    cup = calculate_cup_handle_series(bars)

    assert tuple(step.frame.trend_band for step in steps) == trend
    assert tuple(step.frame.cup_handle for step in steps) == tuple(
        result.active_overlay for result in cup
    )
    assert all(step.frame.bar is bar for step, bar in zip(steps, bars, strict=True))
    assert all(
        step.frame.trend_band.bar_end == bar.bar_end
        for step, bar in zip(steps, bars, strict=True)
    )
    assert steps[-1].frame.markers[-2:] == cup[-1].markers
    assert {marker.marker_type for marker in steps[-1].frame.markers}.issuperset(
        {marker.marker_type for marker in escape[-1].markers}
    )


def test_engine_uses_fixed_marker_family_order_including_same_bar_cup_milestones() -> None:
    """Sorting only by global marker priority would put D1/D2/D3 ahead of BUILD/CLEAR."""

    frame = _run_incremental(ready_and_breakout_same_bar())[-1].frame
    cup_types = [
        marker.marker_type
        for marker in frame.markers
        if marker.marker_type
        in {
            NewowMarkerType.CUP_HANDLE_READY,
            NewowMarkerType.CUP_HANDLE_BREAKOUT,
            NewowMarkerType.CUP_HANDLE_WEAKENED,
            NewowMarkerType.CUP_HANDLE_INVALIDATED,
            NewowMarkerType.CUP_HANDLE_EXPIRED,
        }
    ]

    assert cup_types == [
        NewowMarkerType.CUP_HANDLE_READY,
        NewowMarkerType.CUP_HANDLE_BREAKOUT,
    ]
    family = {
        NewowMarkerType.BUILD: 1,
        NewowMarkerType.CLEAR: 1,
        NewowMarkerType.ESCAPE_D1: 2,
        NewowMarkerType.ESCAPE_D2: 2,
        NewowMarkerType.ESCAPE_D3: 2,
        NewowMarkerType.CUP_HANDLE_READY: 3,
        NewowMarkerType.CUP_HANDLE_BREAKOUT: 3,
        NewowMarkerType.CUP_HANDLE_WEAKENED: 3,
        NewowMarkerType.CUP_HANDLE_INVALIDATED: 3,
        NewowMarkerType.CUP_HANDLE_EXPIRED: 3,
    }
    assert [family[marker.marker_type] for marker in frame.markers] == sorted(
        family[marker.marker_type] for marker in frame.markers
    )


def test_rollover_resets_all_substates_and_suppresses_current_bar_markers() -> None:
    """Keeping any prior state across a contract segment can create a false cross-contract signal."""

    bars = rollover_split_candidate()
    steps = _run_incremental(bars)
    rollover_index = next(
        index
        for index, bar in enumerate(bars)
        if index > 0 and bar.physical_contract != bars[index - 1].physical_contract
    )
    step = steps[rollover_index]

    assert step.frame.rollover_started is True
    assert step.frame.markers == ()
    assert step.state.trend_band_state.weighted_window == (
        float(bars[rollover_index].close),
    )
    assert step.state.escape_state.history_count == 1
    assert step.state.cup_handle_state.atr_state.count == 1
    assert step.state.cup_handle_state.confirmed_pivots == ()


def test_engine_rejects_duplicate_out_of_order_trading_day_and_eligibility_regression() -> None:
    """Accepting replayed or regressed observations makes the state non-causal."""

    engine = NewowTrendD1Engine.initial()
    first = _bar(0, 100, eligible=True)
    engine.step(first)

    with pytest.raises(ValueError, match="NEWOW_BAR_DUPLICATE"):
        engine.step(first)
    with pytest.raises(ValueError, match="NEWOW_BAR_OUT_OF_ORDER"):
        engine.step(replace(first, bar_end=first.bar_end - timedelta(days=1), trading_day=first.trading_day - timedelta(days=1)))
    with pytest.raises(ValueError, match="NEWOW_TRADING_DAY_OUT_OF_ORDER"):
        engine.step(replace(first, bar_end=first.bar_end + timedelta(days=1)))
    with pytest.raises(ValueError, match="NEWOW_OBSERVATION_ELIGIBILITY_REGRESSION"):
        engine.step(_bar(1, 101, eligible=False))


def test_false_to_true_is_allowed_but_false_bars_only_warm_cup_atr() -> None:
    """Letting ineligible bars enter cup geometry would manufacture observations before rank-1 eligibility."""

    bars = tuple(_bar(index, 100 + index, eligible=index >= 14) for index in range(16))
    steps = _run_incremental(bars)

    assert all(step.state.cup_handle_state.eligible_bars == () for step in steps[:14])
    assert steps[13].state.cup_handle_state.atr_state.count == 14
    assert steps[14].state.cup_handle_state.eligible_bars[0].eligible_index == 0
    assert steps[14].state.eligibility_started is True


def test_invalid_restored_substate_fails_closed_to_initial_state() -> None:
    """Continuing from one malformed substate can mix incompatible historical identities."""

    prior = _run_incremental(bullish_true_cup_handle()[:20])[-1].state
    malformed_states = (
        replace(
            prior,
            trend_band_state=replace(
                prior.trend_band_state, weighted_window=(float("nan"),)
            ),
        ),
        replace(prior, escape_state=replace(prior.escape_state, history_count=0)),
        replace(
            prior,
            cup_handle_state=replace(
                prior.cup_handle_state,
                atr_state=replace(prior.cup_handle_state.atr_state, count=-1),
            ),
        ),
        replace(
            prior,
            physical_contract="RB2705",
            segment_id="rb:RB2705:2026-05-01",
        ),
    )

    for malformed in malformed_states:
        engine = NewowTrendD1Engine(state=malformed)
        result = engine.step(bullish_true_cup_handle()[20])

        assert result.frame.trend_band.state is TrendBandState.UNAVAILABLE
        assert result.frame.markers == ()
        assert result.frame.diagnostics == ("NEWOW_ENGINE_STATE_INVALID",)
        assert result.state == NewowTrendD1Engine.initial().state


def test_batch_incremental_prefix_restore_and_future_tail_are_invariant() -> None:
    """Recomputing history or restoring at a cut point must not change a completed prefix."""

    bars = bullish_true_cup_handle()
    full = calculate_newow_trend_frames(bars)
    incremental = tuple(result.frame for result in _run_incremental(bars))

    assert incremental == full
    for cut in (1, 14, 45, len(bars) - 1):
        assert calculate_newow_trend_frames(bars[:cut]) == full[:cut]
        state = _run_incremental(bars[:cut])[-1].state
        restored_state = NewowTrendD1EngineState(
            trend_band_state=state.trend_band_state,
            escape_state=state.escape_state,
            cup_handle_state=state.cup_handle_state,
            physical_contract=state.physical_contract,
            segment_id=state.segment_id,
            last_bar_end=state.last_bar_end,
            last_trading_day=state.last_trading_day,
            eligibility_started=state.eligibility_started,
        )
        restored = NewowTrendD1Engine(state=restored_state)
        resumed = tuple(restored.step(bar).frame for bar in bars[cut:])
        assert resumed == full[cut:]

    mutated_tail = tuple(
        replace(
            bar,
            close=bar.close + Decimal("20"),
            high=bar.high + Decimal("20"),
            low=bar.low + Decimal("20"),
            open=bar.open + Decimal("20"),
        )
        for bar in bars[40:]
    )
    assert calculate_newow_trend_frames(bars[:40] + mutated_tail)[:40] == full[:40]
