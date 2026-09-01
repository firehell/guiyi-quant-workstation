from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow.escape_d123 import (
    EscapeState,
    calculate_escape_series,
    initial_escape_state,
    step_escape_d123,
)
from guiyi_quant.newow.models import NewowDailyBar, NewowMarkerType
from guiyi_quant.newow.profile import NEWOW_TREND_D1_V1


def make_bar(
    index: int,
    close: int | float,
    *,
    high: int | float | None = None,
    low: int | float | None = None,
    eligible: bool = True,
    physical_contract: str = "RB2701",
    segment_id: str = "rb:RB2701:2026-01-01",
) -> NewowDailyBar:
    close_value = Decimal(str(close))
    high_value = Decimal(str(high if high is not None else close + 1))
    low_value = Decimal(str(low if low is not None else close - 1))
    day = date(2026, 1, 1) + timedelta(days=index)
    return NewowDailyBar(
        product="rb", physical_contract=physical_contract, segment_id=segment_id,
        trading_day=day, bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=close_value, high=high_value, low=low_value, close=close_value,
        volume=100, open_interest=None, source_identity="fixture:rb:1d",
        observation_eligible=eligible, completed=True,
    )


def run_steps(bars: tuple[NewowDailyBar, ...]):
    state = initial_escape_state()
    results = []
    for bar in bars:
        result = step_escape_d123(state, bar)
        results.append(result)
        state = result.state
    return tuple(results)


def state_for(
    *, previous_var4: float, ma120: tuple[float, ...] = (100.0,) * 10,
    highs: tuple[float, ...] = (120.0,) * 120, lows: tuple[float, ...] = (100.0,) * 120,
) -> EscapeState:
    return EscapeState(
        closes=(100.0,) * 120,
        highs=highs,
        lows=lows,
        ma120_values=ma120,
        previous_rsv9=100.0,
        previous_var4=previous_var4,
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
    )


def marker(result, marker_type: NewowMarkerType):
    matches = [item for item in result.markers if item.marker_type is marker_type]
    assert len(matches) == 1
    return matches[0]


def test_rsv9_normal_and_zero_span_reuses_previous_then_50() -> None:
    normal = run_steps(tuple(make_bar(index, 100 + index, high=102 + index, low=98 + index) for index in range(9)))[-1]
    assert normal.rsv9 == pytest.approx(100.0 * (108.0 - 98.0) / (110.0 - 98.0))
    first_flat = step_escape_d123(initial_escape_state(), make_bar(0, 100, high=100, low=100))
    second_flat = step_escape_d123(first_flat.state, make_bar(1, 100, high=100, low=100))
    assert first_flat.rsv9 == 50.0
    assert second_flat.rsv9 == 50.0


def test_var4_uses_exact_sma_cn_recursion() -> None:
    bars = (make_bar(0, 100, high=100, low=100), make_bar(1, 110, high=110, low=100), make_bar(2, 100, high=110, low=100))
    results = run_steps(bars)
    assert results[0].var4 == 50.0
    assert results[1].var4 == pytest.approx((100.0 + 2.0 * 50.0) / 3.0)
    assert results[2].var4 == pytest.approx((0.0 + 2.0 * results[1].var4) / 3.0)


def test_d1_requires_cross_below_95_and_30_percent_above_ma120() -> None:
    result = step_escape_d123(state_for(previous_var4=96.0), make_bar(120, 131, high=140, low=100))
    item = marker(result, NewowMarkerType.ESCAPE_D1)
    assert item.label == "★S逃命"
    assert item.trigger_facts["var4_cross_level"] == 95
    assert item.trigger_facts["ma120_deviation"] >= 0.30


def test_d2_requires_amplitude_and_flat_ma120() -> None:
    result = step_escape_d123(state_for(previous_var4=94.0), make_bar(120, 105, high=120, low=100))
    item = marker(result, NewowMarkerType.ESCAPE_D2)
    assert item.label == "★S逃"
    assert item.trigger_facts["amplitude30"] > 0.10
    assert abs(item.trigger_facts["ma120_slope10"]) <= 0.0005


def test_d3_requires_below_falling_ma120_and_cross_below_90() -> None:
    result = step_escape_d123(
        state_for(previous_var4=91.0, ma120=tuple(110.0 - value for value in range(10))),
        make_bar(120, 80, high=100, low=80),
    )
    item = marker(result, NewowMarkerType.ESCAPE_D3)
    assert item.label == "★S跑"
    assert item.trigger_facts["close_below_ma120"] is True
    assert item.trigger_facts["ma120_slope10"] < -0.0005


def test_strict_negative_thresholds_and_no_duplicate_cross() -> None:
    d1_boundary = step_escape_d123(state_for(previous_var4=96.0), make_bar(120, 130, high=140, low=100))
    d2_amplitude = step_escape_d123(
        state_for(previous_var4=94.0, highs=(100.0,) * 120), make_bar(120, 105, high=110, low=100)
    )
    d2_last_ma = (11900.0 + 105.0) / 120.0
    d2_slope = step_escape_d123(
        state_for(previous_var4=94.0, ma120=ma_history_ending_at(d2_last_ma, d2_last_ma * 0.0005001)),
        make_bar(120, 105, high=120, low=100),
    )
    d3_last_ma = (11900.0 + 80.0) / 120.0
    d3_slope = step_escape_d123(
        state_for(previous_var4=91.0, ma120=ma_history_ending_at(d3_last_ma, -d3_last_ma * 0.0005)),
        make_bar(120, 80, high=100, low=80),
    )
    already_below = step_escape_d123(state_for(previous_var4=92.0), make_bar(120, 105, high=120, low=100))
    assert NewowMarkerType.ESCAPE_D1 not in marker_types(d1_boundary)
    assert marker_types(d2_amplitude) == ()
    assert marker_types(d2_slope) == ()
    assert marker_types(d3_slope) == ()
    assert marker_types(already_below) == ()
    assert d2_slope.ma120_slope10 == pytest.approx(0.0005001)
    assert d3_slope.ma120_slope10 == pytest.approx(-0.0005)


def marker_types(result) -> tuple[NewowMarkerType, ...]:
    return tuple(item.marker_type for item in result.markers)


def ma_history_ending_at(last: float, slope: float) -> tuple[float, ...]:
    """Nine prior values that become the specified OLS slope after ``last``."""
    return tuple(last - slope * (9 - index) for index in range(9))


def test_same_bar_retains_hits_with_d1_d2_d3_priority_metadata() -> None:
    result = step_escape_d123(state_for(previous_var4=96.0), make_bar(120, 131, high=140, low=100))
    assert marker_types(result) == (NewowMarkerType.ESCAPE_D1, NewowMarkerType.ESCAPE_D2)
    assert [item.priority for item in result.markers] == sorted((item.priority for item in result.markers), reverse=True)


def test_warmup_eligibility_reset_and_bounded_state() -> None:
    no_output = run_steps(tuple(make_bar(index, 100 + index % 3) for index in range(119)))[-1]
    suppressed = step_escape_d123(state_for(previous_var4=96.0), make_bar(120, 130, high=140, low=100, eligible=False))
    reset = step_escape_d123(suppressed.state, make_bar(121, 100, physical_contract="RB2705", segment_id="rb:RB2705:2026-06-01"))
    assert marker_types(no_output) == ()
    assert marker_types(suppressed) == ()
    assert marker_types(reset) == ()
    assert reset.state.closes == (100.0,)
    assert len(run_steps(tuple(make_bar(index, 100 + index % 5) for index in range(180)))[-1].state.closes) == 120


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_invalid_state_and_empty_window_fail_closed(invalid: float) -> None:
    corrupt = replace(state_for(previous_var4=96.0), closes=(invalid,) * 120)
    malformed = EscapeState((), (), (), (), None, None)
    bar = make_bar(120, 131, high=140, low=100)
    assert marker_types(step_escape_d123(corrupt, bar)) == ()
    assert marker_types(step_escape_d123(malformed, bar)) == ()


def test_prefix_tail_batch_incremental_and_serialization_parity() -> None:
    bars = tuple(make_bar(index, 100 + (index % 17)) for index in range(145))
    full = calculate_escape_series(bars)
    assert calculate_escape_series(bars[:130]) == full[:130]
    mutated_tail = tuple(make_bar(index, 300 + index) for index in range(130, 145))
    assert calculate_escape_series(bars[:130]) == calculate_escape_series(bars[:130] + mutated_tail)[:130]
    results = run_steps(bars)
    state = initial_escape_state()
    for bar in bars[:-10]:
        state = step_escape_d123(state, bar).state
    restored = EscapeState(**asdict(state))
    resumed = []
    for bar in bars[-10:]:
        result = step_escape_d123(restored, bar)
        resumed.append(result)
        restored = result.state
    assert tuple(resumed) == results[-10:]


def test_marker_identity_is_deterministic_and_formula_sensitive() -> None:
    bar = make_bar(120, 131, high=140, low=100)
    old = marker(step_escape_d123(state_for(previous_var4=96.0), bar), NewowMarkerType.ESCAPE_D1)
    alternate = replace(NEWOW_TREND_D1_V1, escape_formula="newow_escape_d123_v2")
    new = marker(step_escape_d123(state_for(previous_var4=96.0), bar, profile=alternate), NewowMarkerType.ESCAPE_D1)
    assert old.marker_id != new.marker_id
    assert old.marker_id == marker(step_escape_d123(state_for(previous_var4=96.0), bar), NewowMarkerType.ESCAPE_D1).marker_id
