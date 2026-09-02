from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from guiyi_quant.newow.models import (
    NewowDailyBar,
    NewowMarkerType,
    TrendBandState,
    TrendTransition,
)
from guiyi_quant.newow.profile import NEWOW_TREND_D1_V1
from guiyi_quant.newow.trend_band import (
    TrendBandStateValue,
    calculate_trend_band,
    initial_trend_band_state,
    step_trend_band,
)


def make_bar(
    index: int,
    close: str | int | float,
    *,
    eligible: bool = True,
    physical_contract: str = "RB2701",
    segment_id: str = "rb:RB2701:2026-01-01",
) -> NewowDailyBar:
    close_decimal = Decimal(str(close))
    trading_day = date(2026, 1, 1) + timedelta(days=index)
    return NewowDailyBar(
        product="rb",
        physical_contract=physical_contract,
        segment_id=segment_id,
        trading_day=trading_day,
        bar_end=datetime.combine(trading_day, datetime.min.time(), tzinfo=UTC),
        open=close_decimal - Decimal("1"),
        high=close_decimal + Decimal("2"),
        low=close_decimal - Decimal("3"),
        close=close_decimal,
        volume=100 + index,
        open_interest=None,
        source_identity="fixture:rb:RB2701:1d",
        observation_eligible=eligible,
        completed=True,
    )


def fixture_bars(*, eligibility_start: int = 0) -> tuple[NewowDailyBar, ...]:
    closes = tuple(range(130, 100, -1)) + tuple(range(100, 141)) + tuple(range(140, 99, -1))
    return tuple(
        make_bar(index, close, eligible=index >= eligibility_start)
        for index, close in enumerate(closes)
    )


def manual_typical(bar: NewowDailyBar) -> float:
    return (
        3.0 * float(bar.close)
        + float(bar.open)
        + float(bar.high)
        + float(bar.low)
    ) / 6.0


def manual_values(bars: tuple[NewowDailyBar, ...]) -> tuple[list[float | None], list[float | None]]:
    typicals = [manual_typical(bar) for bar in bars]
    b_values: list[float | None] = []
    for index in range(len(typicals)):
        window = typicals[index - 19 : index + 1]
        b_values.append(
            None if len(window) < 20 else sum((offset + 1) * value for offset, value in enumerate(window)) / 210.0
        )
    c_values: list[float | None] = []
    for index in range(len(b_values)):
        window = b_values[index - 4 : index + 1]
        c_values.append(None if len(window) < 5 or any(value is None for value in window) else sum(window) / 5.0)  # type: ignore[arg-type]
    return b_values, c_values


def run_steps(bars: tuple[NewowDailyBar, ...]):
    state = initial_trend_band_state()
    results = []
    for bar in bars:
        result = step_trend_band(state, bar)
        results.append(result)
        state = result.state
    return tuple(results)


def test_formula_warmup_weights_and_equality_state_are_exact() -> None:
    bars = fixture_bars()[:30]
    points = calculate_trend_band(bars)
    expected_b, expected_c = manual_values(bars)

    assert [point.b_value for point in points] == expected_b
    assert [point.c_value for point in points] == expected_c
    assert all(point.b_value is None for point in points[:19])
    assert points[19].b_value is not None
    assert all(point.c_value is None for point in points[:23])
    assert points[23].c_value is not None

    equal_bars = tuple(make_bar(index, 100) for index in range(24))
    equal_point = calculate_trend_band(equal_bars)[-1]
    assert equal_point.b_value == equal_point.c_value
    assert equal_point.state is TrendBandState.YELLOW


def test_typical_price_uses_frozen_profile_close_weight() -> None:
    """A profile close-weight change must flow through the one formula authority."""

    profile = replace(NEWOW_TREND_D1_V1, typical_price_close_weight=1.0)
    bars = tuple(make_bar(index, 100 + index) for index in range(20))
    point = calculate_trend_band(bars, profile=profile)[-1]
    typicals = [
        (
            float(bar.close)
            + float(bar.open)
            + float(bar.high)
            + float(bar.low)
        )
        / 4.0
        for bar in bars
    ]
    expected = sum((index + 1) * value for index, value in enumerate(typicals)) / 210.0

    assert point.b_value == pytest.approx(expected)


def test_transitions_emit_one_build_and_one_clear_with_reference_change_copy() -> None:
    results = run_steps(fixture_bars())
    markers = tuple(result.marker for result in results if result.marker is not None)
    transitions = tuple(result.point.transition for result in results if result.point.transition is not None)

    assert transitions == (TrendTransition.BUILD, TrendTransition.CLEAR)
    assert [marker.marker_type for marker in markers] == [NewowMarkerType.BUILD, NewowMarkerType.CLEAR]
    assert markers[1].trigger_facts["reference_basis"] == "signal_close"
    assert "策略信号参考变化" in markers[1].label
    assert "非真实成交" in markers[1].label
    assert "未计手续费、滑点、涨跌停和换月" in markers[1].label

    clear_after_build = markers[1]
    assert clear_after_build.trigger_facts["reference_basis"] == "signal_close"
    assert clear_after_build.trigger_facts["reference_change_pct"] == pytest.approx(
        (float(clear_after_build.price) / float(markers[0].price) - 1.0) * 100.0
    )
    assert clear_after_build.related_marker_ids == (markers[0].marker_id,)


def test_transition_marker_facts_freeze_state_before_and_after() -> None:
    results = run_steps(fixture_bars())
    markers = tuple(result.marker for result in results if result.marker is not None)

    assert markers[0].trigger_facts["state_before"] == TrendBandState.BLUE.value
    assert markers[0].trigger_facts["state_after"] == TrendBandState.YELLOW.value
    assert markers[1].trigger_facts["state_before"] == TrendBandState.YELLOW.value
    assert markers[1].trigger_facts["state_after"] == TrendBandState.BLUE.value


def test_transition_marker_id_is_deterministic_and_hold_empty_do_not_duplicate() -> None:
    bars = fixture_bars()
    results = run_steps(bars)
    markers = tuple(result.marker for result in results if result.marker is not None)

    assert len(markers) == 2
    for marker in markers:
        expected = sha256(
            "|".join(("newow_trend_v1", NEWOW_TREND_D1_V1.trend_band_formula, "RB2701", marker.marker_type.value, marker.bar_end.isoformat())).encode()
        ).hexdigest()
        assert marker.marker_id == expected
    assert all(result.marker is None for result in results if result.point.transition is None)


def test_pre_rank1_warmup_emits_no_marker_and_first_eligible_transition_uses_warmed_state() -> None:
    baseline = run_steps(fixture_bars())
    build_index = next(index for index, result in enumerate(baseline) if result.point.transition is TrendTransition.BUILD)
    results = run_steps(fixture_bars(eligibility_start=build_index))

    assert all(result.marker is None for result in results[:build_index])
    assert results[build_index].point.transition is TrendTransition.BUILD
    assert results[build_index].marker is not None


def test_prefix_and_step_serialized_state_parity() -> None:
    bars = fixture_bars()
    full = calculate_trend_band(bars)
    for length in range(1, len(bars) + 1):
        assert calculate_trend_band(bars[:length]) == full[:length]

    continuous = run_steps(bars)
    state = initial_trend_band_state()
    for bar in bars[:-10]:
        state = step_trend_band(state, bar).state
    restored = TrendBandStateValue(**asdict(state))
    resumed = []
    for bar in bars[-10:]:
        result = step_trend_band(restored, bar)
        resumed.append(result)
        restored = result.state
    assert tuple(resumed) == continuous[-10:]


def test_future_tail_mutation_cannot_change_existing_prefix_outputs() -> None:
    bars = fixture_bars()
    prefix_length = 70
    mutated_tail = tuple(
        make_bar(index, bar.close + Decimal("1000"))
        for index, bar in enumerate(bars[prefix_length:], start=prefix_length)
    )

    assert calculate_trend_band(bars[:prefix_length]) == calculate_trend_band(
        bars[:prefix_length] + mutated_tail
    )[:prefix_length]


@pytest.mark.parametrize(
    ("physical_contract", "segment_id"),
    [
        ("RB2705", "rb:RB2705:2026-03-01"),
        ("RB2701", "rb:RB2701:2026-03-01"),
    ],
)
def test_rollover_resets_bound_state_without_cross_segment_transition_or_marker(
    physical_contract: str, segment_id: str
) -> None:
    warmed = run_steps(fixture_bars()[:60])
    prior_state = warmed[-1].state
    rollover = make_bar(
        60,
        200,
        physical_contract=physical_contract,
        segment_id=segment_id,
    )

    result = step_trend_band(prior_state, rollover)

    assert result.point.state is TrendBandState.UNAVAILABLE
    assert result.point.b_value is None
    assert result.point.c_value is None
    assert result.point.transition is None
    assert result.marker is None
    assert result.state.physical_contract == physical_contract
    assert result.state.segment_id == segment_id
    assert result.state.weighted_window == (manual_typical(rollover),)
    assert result.state.signal_window == ()
    assert result.state.previous_state is None
    assert result.state.last_build_close is None
    assert result.state.last_build_marker_id is None


def test_suppressed_build_cannot_later_produce_formal_clear() -> None:
    baseline = run_steps(fixture_bars())
    build_index = next(
        index for index, result in enumerate(baseline) if result.point.transition is TrendTransition.BUILD
    )
    clear_index = next(
        index
        for index, result in enumerate(baseline)
        if result.point.transition is TrendTransition.CLEAR
    )
    bars = fixture_bars(eligibility_start=clear_index)
    results = run_steps(bars)

    assert results[build_index].point.state is TrendBandState.YELLOW
    assert results[build_index].marker is None
    assert results[clear_index].point.state is TrendBandState.BLUE
    assert results[clear_index].point.transition is None
    assert results[clear_index].marker is None
    assert all(result.marker is None for result in results[: clear_index + 1])


@pytest.mark.parametrize("invalid_reference", [Decimal("0"), Decimal("NaN"), Decimal("Infinity")])
def test_invalid_build_reference_fails_closed_without_clear(invalid_reference: Decimal) -> None:
    state = TrendBandStateValue(
        weighted_window=(200.0,) * 20,
        signal_window=(200.0,) * 4,
        previous_state=TrendBandState.YELLOW,
        last_build_close=invalid_reference,
        last_build_marker_id="build-marker",
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
    )

    result = step_trend_band(state, make_bar(0, 100))

    assert result.point.state is TrendBandState.UNAVAILABLE
    assert result.point.transition is None
    assert result.marker is None
    assert result.state == initial_trend_band_state()


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_prior_state_fails_closed_without_transition_or_marker(invalid: float) -> None:
    state = replace(initial_trend_band_state(), weighted_window=(invalid,) * 20)
    result = step_trend_band(state, make_bar(0, 100))

    assert result.point.state is TrendBandState.UNAVAILABLE
    assert result.point.transition is None
    assert result.marker is None
    assert result.state == initial_trend_band_state()


def test_restored_trend_history_requires_complete_physical_identity() -> None:
    """Identity-free restored windows must not calculate or emit a transition."""

    valid = run_steps(fixture_bars()[:60])[-1].state
    malformed = replace(valid, physical_contract=None, segment_id=None)

    result = step_trend_band(malformed, make_bar(60, 200))

    assert result.point.state is TrendBandState.UNAVAILABLE
    assert result.point.transition is None
    assert result.marker is None
    assert result.state == initial_trend_band_state()


@pytest.mark.parametrize(
    "malformed",
    [
        TrendBandStateValue(
            weighted_window=(100.0,),
            signal_window=(100.0,),
            previous_state=None,
            physical_contract="RB2701",
            segment_id="rb:RB2701:2026-01-01",
        ),
        TrendBandStateValue(
            weighted_window=(100.0,) * 20,
            signal_window=(100.0,),
            previous_state=TrendBandState.YELLOW,
            physical_contract="RB2701",
            segment_id="rb:RB2701:2026-01-01",
        ),
        TrendBandStateValue(
            weighted_window=(100.0,) * 20,
            signal_window=(100.0,) * 5,
            previous_state=TrendBandState.YELLOW,
            last_build_close=Decimal("100"),
            last_build_marker_id=None,
            physical_contract="RB2701",
            segment_id="rb:RB2701:2026-01-01",
        ),
    ],
)
def test_structurally_incoherent_restored_trend_state_fails_closed(
    malformed: TrendBandStateValue,
) -> None:
    """Impossible warm-up stages or half-built marker facts cannot be resumed."""

    result = step_trend_band(malformed, make_bar(60, 100))

    assert result.point.state is TrendBandState.UNAVAILABLE
    assert result.point.transition is None
    assert result.marker is None
    assert result.state == initial_trend_band_state()
