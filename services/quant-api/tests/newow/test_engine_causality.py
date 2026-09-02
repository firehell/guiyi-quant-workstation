from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import pickle

import pytest

from guiyi_quant.newow.cup_handle import (
    calculate_cup_handle_series,
    initial_cup_handle_state,
    step_cup_handle,
)
from guiyi_quant.newow.engine import (
    NewowTrendD1Engine,
    _receipt,
    calculate_newow_trend_frames,
)
from guiyi_quant.newow.escape_d123 import (
    EscapeState,
    calculate_escape_series,
    initial_escape_state,
    step_escape_d123,
)
from guiyi_quant.newow.models import NewowDailyBar, NewowMarkerType, TrendBandState
from guiyi_quant.newow.trend_band import (
    calculate_trend_band,
    initial_trend_band_state,
    step_trend_band,
)

from .fixtures import (
    bearish_true_cup_handle,
    breakout_then_weakened,
    breakout_volume_not_confirmed,
    bullish_true_cup_handle,
    downtrend_rebound_rejected,
    ready_and_breakout_same_bar,
    ready_then_expired,
    ready_then_invalidated,
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


_MARKER_FAMILY = {
    NewowMarkerType.BUILD: (0, 0),
    NewowMarkerType.CLEAR: (0, 1),
    NewowMarkerType.ESCAPE_D1: (1, 0),
    NewowMarkerType.ESCAPE_D2: (1, 1),
    NewowMarkerType.ESCAPE_D3: (1, 2),
    NewowMarkerType.CUP_HANDLE_READY: (2, 0),
    NewowMarkerType.CUP_HANDLE_BREAKOUT: (2, 1),
    NewowMarkerType.CUP_HANDLE_WEAKENED: (2, 2),
    NewowMarkerType.CUP_HANDLE_INVALIDATED: (2, 3),
    NewowMarkerType.CUP_HANDLE_EXPIRED: (2, 4),
}


def _expected_markers(trend_marker, escape_markers, cup_markers):
    source = (() if trend_marker is None else (trend_marker,)) + escape_markers + cup_markers
    return tuple(
        sorted(
            source,
            key=lambda marker: (
                _MARKER_FAMILY[marker.marker_type],
                marker.marker_type.value,
                marker.marker_id,
            ),
        )
    )


def _assert_real_kernel_parity(bars: tuple[NewowDailyBar, ...]):
    """Compare every Engine frame/state with a parallel run of the real kernels."""

    engine = NewowTrendD1Engine.initial()
    trend_state = initial_trend_band_state()
    escape_state = initial_escape_state()
    cup_state = initial_cup_handle_state()
    prior_identity = None
    frames = []
    steps = []
    for bar in bars:
        identity = (bar.physical_contract, bar.segment_id)
        rollover = prior_identity is not None and identity != prior_identity
        if rollover:
            trend_state = initial_trend_band_state()
            escape_state = initial_escape_state()
            cup_state = initial_cup_handle_state()
        trend = step_trend_band(trend_state, bar)
        escape = step_escape_d123(escape_state, bar)
        cup = step_cup_handle(cup_state, bar)
        step = engine.step(bar)

        assert step.frame.bar is bar
        assert step.frame.trend_band == trend.point
        assert step.frame.cup_handle == cup.active_overlay
        assert step.frame.diagnostics == cup.diagnostics
        assert step.state.trend_band_state == trend.state
        assert step.state.escape_state == escape.state
        assert step.state.cup_handle_state == cup.state
        assert step.state.last_bar_end == bar.bar_end
        assert step.state.last_trading_day == bar.trading_day
        assert step.state.physical_contract == bar.physical_contract
        assert step.state.segment_id == bar.segment_id
        assert step.state.eligibility_started == (
            cup_state.eligible_started or bar.observation_eligible
        )
        assert step.state.escape_state.previous_rsv9 == escape.rsv9
        assert step.state.escape_state.previous_var4 == escape.var4
        if escape.ma120 is not None:
            assert step.state.escape_state.ma120_values[-1] == escape.ma120
        expected = () if rollover else _expected_markers(
            trend.marker, escape.markers, cup.markers
        )
        assert step.frame.markers == expected
        assert [marker.trigger_facts for marker in step.frame.markers] == [
            marker.trigger_facts for marker in expected
        ]
        assert [_MARKER_FAMILY[marker.marker_type] for marker in step.frame.markers] == sorted(
            _MARKER_FAMILY[marker.marker_type] for marker in step.frame.markers
        )

        trend_state, escape_state, cup_state = trend.state, escape.state, cup.state
        prior_identity = identity
        frames.append(step.frame)
        steps.append(step)
    return tuple(frames), tuple(steps)


def _escape_state_for(
    *,
    previous_var4: float,
    closes: tuple[float, ...] = (100.0,) * 119 + (120.0,),
    prior_closes: tuple[float, ...] = (100.0,) * 9,
    highs: tuple[float, ...] = (120.0,) * 120,
    lows: tuple[float, ...] = (100.0,) * 120,
) -> EscapeState:
    """Build an internally authenticated 120-bar D123 state for Engine integration."""

    ma_source = prior_closes + closes
    ma_values = tuple(
        sum(ma_source[index : index + 120]) / 120.0 for index in range(10)
    )
    denominator = max(highs[-9:]) - min(lows[-9:])
    previous_rsv9 = (
        100.0
        if denominator == 0.0
        else 100.0 * (closes[-1] - min(lows[-9:])) / denominator
    )
    return EscapeState(
        closes=closes,
        highs=highs,
        lows=lows,
        ma120_values=ma_values,
        previous_rsv9=previous_rsv9,
        previous_var4=previous_var4,
        history_count=120,
        ma120_prior_closes=prior_closes,
        prior_var4=(3.0 * previous_var4 - previous_rsv9) / 2.0,
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
    )


def _d3_escape_state_and_bar() -> tuple[EscapeState, NewowDailyBar]:
    normalized_slope = -0.001
    base = 200.0
    spread = 1.0
    daily_change = normalized_slope * base / (1.0 - 69.5 * normalized_slope)
    history = tuple(base + daily_change * index for index in range(130))
    state = _escape_state_for(
        previous_var4=91.0,
        closes=history[9:129],
        prior_closes=history[:9],
        highs=tuple(value + spread for value in history[9:129]),
        lows=tuple(value - spread for value in history[9:129]),
    )
    close = Decimal(str(history[129]))
    return state, replace(
        _bar(120, int(close)),
        open=close,
        high=close + Decimal(str(spread)),
        low=close - Decimal(str(spread)),
        close=close,
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

    with pytest.raises(ValueError) as duplicate:
        engine.step(first)
    assert duplicate.value.args == ("NEWOW_BAR_DUPLICATE",)
    with pytest.raises(ValueError) as out_of_order:
        engine.step(replace(first, bar_end=first.bar_end - timedelta(days=1), trading_day=first.trading_day - timedelta(days=1)))
    assert out_of_order.value.args == ("NEWOW_BAR_OUT_OF_ORDER",)
    with pytest.raises(ValueError) as trading_day:
        engine.step(replace(first, bar_end=first.bar_end + timedelta(days=1)))
    assert trading_day.value.args == ("NEWOW_TRADING_DAY_OUT_OF_ORDER",)
    with pytest.raises(ValueError) as eligibility:
        engine.step(_bar(1, 101, eligible=False))
    assert eligibility.value.args == ("NEWOW_OBSERVATION_ELIGIBILITY_REGRESSION",)


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


def test_restore_rejects_valid_trend_state_from_an_older_cut() -> None:
    """A valid five-bar trend window must not be combined with 20-bar peer states."""

    bars = bullish_true_cup_handle()
    current = _run_incremental(bars[:20])[-1].state
    older_trend = _run_incremental(bars[:5])[-1].state.trend_band_state
    restored = NewowTrendD1Engine(
        state=replace(current, trend_band_state=older_trend)
    )

    result = restored.step(bars[20])

    assert result.frame.trend_band.state is TrendBandState.UNAVAILABLE
    assert result.frame.markers == ()
    assert result.frame.diagnostics == ("NEWOW_ENGINE_STATE_INVALID",)
    assert result.state == NewowTrendD1Engine.initial().state


def test_restore_rejects_saturated_trend_state_from_an_older_cut() -> None:
    """A 25-bar saturated trend window cannot stand in for the 30-bar processing cut."""

    bars = bullish_true_cup_handle()
    current = _run_incremental(bars[:30])[-1].state
    older_trend = _run_incremental(bars[:25])[-1].state.trend_band_state
    restored = NewowTrendD1Engine(
        state=replace(current, trend_band_state=older_trend)
    )

    result = restored.step(bars[30])

    assert result.frame.trend_band.state is TrendBandState.UNAVAILABLE
    assert result.frame.markers == ()
    assert result.frame.diagnostics == ("NEWOW_ENGINE_STATE_INVALID",)
    assert result.state == NewowTrendD1Engine.initial().state


def test_restore_rejects_stale_engine_watermark_before_duplicate_replay() -> None:
    """A forged old watermark must not permit replay of a bar already in all substates."""

    bars = bullish_true_cup_handle()
    current = _run_incremental(bars[:20])[-1].state
    restored = NewowTrendD1Engine(
        state=replace(
            current,
            last_bar_end=bars[10].bar_end,
            last_trading_day=bars[10].trading_day,
        )
    )

    result = restored.step(bars[19])

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
        restored = NewowTrendD1Engine(state=pickle.loads(pickle.dumps(state)))
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


def test_real_kernel_harness_matches_all_fields_across_bull_bear_negative_and_rollover() -> None:
    """The Engine must not drift from any real Kernel on positive or negative paths."""

    for bars in (
        bullish_true_cup_handle(),
        bearish_true_cup_handle(),
        downtrend_rebound_rejected(),
        rollover_split_candidate(),
    ):
        frames, steps = _assert_real_kernel_parity(bars)
        assert frames == calculate_newow_trend_frames(bars)
        assert tuple(step.frame for step in _run_incremental(bars)) == frames
        assert tuple(
            tuple(marker.marker_id for marker in frame.markers) for frame in frames
        ) == tuple(
            tuple(marker.marker_id for marker in frame.markers)
            for frame in calculate_newow_trend_frames(bars)
        )
        assert steps[-1].state == _run_incremental(bars)[-1].state


def test_every_prefix_and_genuine_serialized_restore_cut_matches_full_run() -> None:
    """Every completed prefix and shared-cut pickle restore must reproduce the full suffix."""

    bars = bullish_true_cup_handle()
    full, _ = _assert_real_kernel_parity(bars)
    for cut in range(1, len(bars) + 1):
        assert calculate_newow_trend_frames(bars[:cut]) == full[:cut]
    for cut in (1, 14, 20, 45, len(bars) - 1):
        state = _run_incremental(bars[:cut])[-1].state
        restored = NewowTrendD1Engine(state=pickle.loads(pickle.dumps(state)))
        assert tuple(restored.step(bar).frame for bar in bars[cut:]) == full[cut:]


@pytest.mark.parametrize(
    ("bars", "terminal_type"),
    (
        (breakout_then_weakened(), NewowMarkerType.CUP_HANDLE_WEAKENED),
        (ready_then_invalidated(), NewowMarkerType.CUP_HANDLE_INVALIDATED),
        (ready_then_expired(), NewowMarkerType.CUP_HANDLE_EXPIRED),
    ),
)
def test_engine_orders_all_real_cup_terminal_markers(
    bars: tuple[NewowDailyBar, ...], terminal_type: NewowMarkerType
) -> None:
    """Terminal cup facts remain real Kernel facts and preserve family ordering in Engine frames."""

    frames, _ = _assert_real_kernel_parity(bars)
    emitted = [
        marker.marker_type for frame in frames for marker in frame.markers
    ]

    assert NewowMarkerType.CUP_HANDLE_READY in emitted
    assert terminal_type in emitted
    for frame in frames:
        assert [_MARKER_FAMILY[marker.marker_type] for marker in frame.markers] == sorted(
            _MARKER_FAMILY[marker.marker_type] for marker in frame.markers
        )


def test_cup_diagnostic_coexists_with_valid_slice_a_frame() -> None:
    """A rejected cup breakout must not erase an otherwise valid trend-band/D123 result."""

    frames, _ = _assert_real_kernel_parity(breakout_volume_not_confirmed())
    frame = next(
        item for item in frames if "BREAKOUT_VOLUME_UNCONFIRMED" in item.diagnostics
    )

    assert frame.trend_band.state is not TrendBandState.UNAVAILABLE
    assert frame.bar.completed is True


def test_real_kernel_family_coverage_keeps_d123_facts_and_cup_lifecycle_ordered() -> None:
    """Every Engine marker family is exercised by real Kernel output, never a mock marker."""

    seeded_bars = tuple(_bar(index, 100) for index in range(120))
    seed = _run_incremental(seeded_bars)[-1].state
    d3_state, d3_bar = _d3_escape_state_and_bar()
    cases = (
        (
            _escape_state_for(previous_var4=96.0),
            replace(_bar(120, 131), high=Decimal("140"), low=Decimal("100")),
            NewowMarkerType.ESCAPE_D1,
        ),
        (
            _escape_state_for(previous_var4=94.0),
            replace(_bar(120, 105), high=Decimal("120"), low=Decimal("100")),
            NewowMarkerType.ESCAPE_D2,
        ),
        (d3_state, d3_bar, NewowMarkerType.ESCAPE_D3),
    )
    observed = set()
    for escape_state, bar, marker_type in cases:
        direct = step_escape_d123(escape_state, bar)
        engine_state = replace(
            seed,
            escape_state=escape_state,
            escape_receipt=_receipt(
                "escape",
                escape_state,
                seed.last_bar_end,
                seed.last_trading_day,
                seed.physical_contract,
                seed.segment_id,
            ),
        )
        result = NewowTrendD1Engine(
            state=engine_state
        ).step(bar)
        engine_escape = tuple(
            marker
            for marker in result.frame.markers
            if marker.marker_type in {
                NewowMarkerType.ESCAPE_D1,
                NewowMarkerType.ESCAPE_D2,
                NewowMarkerType.ESCAPE_D3,
            }
        )

        assert result.state.escape_state == direct.state
        assert engine_escape == direct.markers
        assert engine_escape[0].marker_type is marker_type
        assert engine_escape[0].trigger_facts == direct.markers[0].trigger_facts
        observed.add(marker_type)

    for bars in (
        bearish_true_cup_handle(),
        breakout_then_weakened(),
        ready_then_invalidated(),
        ready_then_expired(),
    ):
        frames, _ = _assert_real_kernel_parity(bars)
        observed.update(
            marker.marker_type for frame in frames for marker in frame.markers
        )

    assert observed.issuperset(
        {
            NewowMarkerType.BUILD,
            NewowMarkerType.CLEAR,
            NewowMarkerType.ESCAPE_D1,
            NewowMarkerType.ESCAPE_D2,
            NewowMarkerType.ESCAPE_D3,
            NewowMarkerType.CUP_HANDLE_READY,
            NewowMarkerType.CUP_HANDLE_BREAKOUT,
            NewowMarkerType.CUP_HANDLE_WEAKENED,
            NewowMarkerType.CUP_HANDLE_INVALIDATED,
            NewowMarkerType.CUP_HANDLE_EXPIRED,
        }
    )
