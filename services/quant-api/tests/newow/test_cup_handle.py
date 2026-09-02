from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import pickle

import pytest

from guiyi_quant.newow.cup_handle import (
    CupBarSnapshot,
    CupPivotTrackerState,
    WilderAtrState,
    calculate_cup_handle_series,
    initial_cup_handle_state,
    step_cup_handle,
)
from guiyi_quant.newow.models import (
    CupHandleDirection,
    CupHandleState,
    CupPivot,
    CupPivotKind,
    NewowDailyBar,
    NewowMarkerType,
)
from guiyi_quant.newow.profile import NEWOW_TREND_D1_V1

from .fixtures import (
    bearish_true_cup_handle,
    breakout_then_archived,
    breakout_then_weakened,
    breakout_volume_not_confirmed,
    bullish_true_cup_handle,
    candidate_limit_exceeded,
    competing_ready_and_breakout_candidates,
    cup_too_deep_rejected,
    downtrend_rebound_rejected,
    handle_below_mid_rejected,
    handle_too_deep_rejected,
    handle_too_long_rejected,
    handle_too_short_rejected,
    handle_volume_not_contracting,
    pretrend_not_confirmed,
    ready_and_breakout_same_bar,
    ready_then_expired,
    ready_then_invalidated,
    restored_cup_case,
    rim_gap_rejected,
    rollover_split_candidate,
    shallow_cup_rejected,
    v_bottom_rejected,
    wide_range_rejected,
)


def _bar(index: int, close: int, *, eligible: bool = True) -> NewowDailyBar:
    bar_day = date(2026, 1, 5) + timedelta(days=index)
    close_value = Decimal(close)
    return NewowDailyBar(
        product="rb",
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
        trading_day=bar_day,
        bar_end=datetime.combine(bar_day, datetime.min.time(), tzinfo=UTC),
        open=close_value,
        high=close_value + Decimal("1"),
        low=close_value - Decimal("1"),
        close=close_value,
        volume=100,
        open_interest=200,
        source_identity="fixture:rb:RB2701:1d",
        observation_eligible=eligible,
        completed=True,
    )


def test_confirmed_pivot_is_not_visible_before_its_reversal_bar() -> None:
    """Removing causal confirmation would leak the extreme into an earlier prefix."""

    state = initial_cup_handle_state()
    results = []
    for index, close in enumerate([100] * 14 + [102, 104, 106, 108, 110, 106, 105, 104]):
        result = step_cup_handle(state, _bar(index, close))
        results.append(result)
        state = result.state

    assert all(pivot.kind.value != "HIGH" for pivot in results[18].state.confirmed_pivots)
    high = results[19].state.confirmed_pivots[-1]
    assert high.pivot_at == _bar(18, 110).bar_end
    assert high.confirmed_at == _bar(19, 106).bar_end


def test_wilder_atr14_seed_and_recursive_update_are_exact() -> None:
    """The cup tracker must use the specified Wilder seed and recurrence."""

    bars = tuple(_bar(index, 100 + index) for index in range(14))
    seeded = calculate_cup_handle_series(bars)

    assert all(result.state.atr_state.atr is None for result in seeded[:13])
    assert seeded[-1].state.atr_state.atr == 2.0

    jumped = step_cup_handle(seeded[-1].state, _bar(14, 130))

    assert jumped.state.atr_state.atr == pytest.approx((13 * 2 + 18) / 14)


def _markers(results: tuple[object, ...]) -> list[object]:
    return [marker for result in results for marker in result.markers]  # type: ignore[attr-defined]


def test_true_bullish_fixture_reaches_frozen_ready_then_breakout() -> None:
    """Removing an exact gate or mutating READY facts would corrupt the canonical setup."""

    bars = bullish_true_cup_handle()
    results = calculate_cup_handle_series(bars)
    markers = _markers(results)
    ready_marker = next(
        marker for marker in markers if marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
    )
    breakout_marker = next(
        marker
        for marker in markers
        if marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
    )
    ready_result = next(result for result in results if ready_marker in result.markers)
    breakout_result = next(result for result in results if breakout_marker in result.markers)
    ready = ready_result.active_overlay
    breakout = breakout_result.active_overlay

    assert ready is not None and breakout is not None
    assert ready.direction == CupHandleDirection.BULLISH
    assert ready.state == CupHandleState.READY
    assert breakout.state == CupHandleState.BREAKOUT
    assert (ready.left_rim.pivot_at, ready.bottom.pivot_at, ready.right_rim.pivot_at) == (
        bars[45].bar_end,
        bars[60].bar_end,
        bars[75].bar_end,
    )
    assert ready.handle_extreme is not None
    assert ready.handle_extreme.pivot_at == bars[80].bar_end
    assert ready.pivot_price == Decimal("100")
    assert dict(ready.volume_facts) == {
        "right_leg_median": 120.0,
        "handle_median": 60.0,
        "handle_baseline_median": 120.0,
        "handle_right_ratio": 0.5,
        "handle_baseline_ratio": 0.5,
    }
    assert dict(ready.score_breakdown) == {
        "pretrend": 15.0,
        "cup_geometry": 23.0,
        "u_shape_purity": 18.0,
        "handle_quality": 16.0,
        "volume_structure": 14.0,
    }
    assert ready.score == 86.0
    assert sum(ready.score_breakdown.values()) == ready.score
    assert breakout.candidate_id == ready.candidate_id
    assert breakout.left_rim == ready.left_rim
    assert breakout.bottom == ready.bottom
    assert breakout.right_rim == ready.right_rim
    assert breakout.handle_extreme == ready.handle_extreme
    assert breakout.pivot_price == ready.pivot_price
    assert breakout.confirmed_at == ready.confirmed_at
    assert breakout.score == ready.score
    assert breakout.score_breakdown == ready.score_breakdown
    assert breakout.volume_facts == ready.volume_facts
    assert breakout_marker.related_marker_ids == (ready_marker.marker_id,)
    assert breakout_marker.trigger_facts["state_before"] == "READY"
    assert breakout_marker.trigger_facts["state_after"] == "BREAKOUT"
    assert breakout_marker.trigger_facts["full_score"] == 92.0


def test_bearish_fixture_is_an_exact_directional_mirror() -> None:
    """A one-sided implementation would silently omit the specified bearish risk pattern."""

    bullish = calculate_cup_handle_series(bullish_true_cup_handle())
    bearish = calculate_cup_handle_series(bearish_true_cup_handle())
    bull_overlay = next(
        result.active_overlay
        for result in bullish
        if any(
            marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
            for marker in result.markers
        )
    )
    bear_overlay = next(
        result.active_overlay
        for result in bearish
        if any(
            marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
            for marker in result.markers
        )
    )

    assert bull_overlay is not None and bear_overlay is not None
    assert bull_overlay.direction == CupHandleDirection.BULLISH
    assert bear_overlay.direction == CupHandleDirection.BEARISH
    assert bear_overlay.score == bull_overlay.score
    assert bear_overlay.score_breakdown == bull_overlay.score_breakdown
    assert bear_overlay.left_rim.pivot_index == bull_overlay.left_rim.pivot_index
    assert bear_overlay.bottom.pivot_index == bull_overlay.bottom.pivot_index
    assert bear_overlay.right_rim.pivot_index == bull_overlay.right_rim.pivot_index


def test_ready_and_breakout_same_bar_emit_both_markers_in_order() -> None:
    """Deferring BREAKOUT by one bar would violate the frozen same-bar lifecycle."""

    result = calculate_cup_handle_series(ready_and_breakout_same_bar())[-1]

    assert tuple(marker.marker_type for marker in result.markers) == (
        NewowMarkerType.CUP_HANDLE_READY,
        NewowMarkerType.CUP_HANDLE_BREAKOUT,
    )
    assert result.markers[1].related_marker_ids == (result.markers[0].marker_id,)
    assert result.active_overlay is not None
    assert result.active_overlay.pivot_price == Decimal("100")
    assert result.active_overlay.pivot_price < ready_and_breakout_same_bar()[-1].high


@pytest.mark.parametrize(
    ("case_kwargs", "expected"),
    [
        ({"pretrend": "flat"}, "PRETREND_NOT_CONFIRMED"),
        ({"pretrend": "downtrend_rebound"}, "PRETREND_NOT_CONFIRMED"),
        (
            {"bottom_index": 41, "right_index": 53, "handle_index": 57, "handle_confirmed_index": 60},
            "CUP_DURATION_OUT_OF_RANGE",
        ),
        (
            {"bottom_index": 75, "right_index": 120, "handle_index": 125, "handle_confirmed_index": 128},
            "CUP_DURATION_OUT_OF_RANGE",
        ),
        ({"bottom_price": Decimal("91")}, "CUP_DEPTH_BELOW_10_PERCENT"),
        ({"bottom_price": Decimal("49")}, "CUP_DEPTH_ABOVE_50_PERCENT"),
        ({"atr": 8.0}, "CUP_DEPTH_BELOW_3_ATR"),
        (
            {"right_price": Decimal("94"), "bottom_price": Decimal("75")},
            "RIM_GAP_PERCENT_EXCEEDED",
        ),
        (
            {"right_price": Decimal("98"), "bottom_price": Decimal("78"), "atr": 1.0},
            "RIM_GAP_ATR_EXCEEDED",
        ),
        ({"bottom_span": 1}, "V_BOTTOM_SINGLE_BAR"),
        ({"bottom_index": 36}, "LEG_RATIO_EXTREME"),
        ({"wide_crossings": True}, "MIDLINE_CROSSINGS_EXCEEDED"),
    ],
)
def test_each_body_hard_gate_rejects_without_a_fake_overlay(
    case_kwargs: dict[str, object], expected: str
) -> None:
    """Each body failure must be observable without returning rejected geometry."""

    case = restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    result = step_cup_handle(case.state, case.next_bar)

    assert expected in result.diagnostics
    assert result.active_overlay is None
    assert result.markers == ()


@pytest.mark.parametrize(
    ("case_kwargs", "expected"),
    [
        (
            {"handle_index": 62, "handle_confirmed_index": 64},
            "HANDLE_DURATION_OUT_OF_RANGE",
        ),
        (
            {"handle_index": 70, "handle_confirmed_index": 76},
            "HANDLE_DURATION_OUT_OF_RANGE",
        ),
        ({"handle_price": Decimal("84")}, "HANDLE_DEPTH_EXCEEDED"),
        (
            {"bottom_price": Decimal("70"), "handle_price": Decimal("89")},
            "HANDLE_RETRACE_EXCEEDED",
        ),
        (
            {"bottom_price": Decimal("80"), "handle_price": Decimal("89")},
            "HANDLE_BELOW_CUP_MID",
        ),
        ({"handle_volume": 97}, "HANDLE_VOLUME_NOT_CONTRACTING"),
        ({"right_volume": 0}, "HANDLE_VOLUME_UNAVAILABLE"),
    ],
)
def test_each_handle_and_ready_volume_gate_blocks_promotion(
    case_kwargs: dict[str, object], expected: str
) -> None:
    """An invalid handle may stay FORMING but can never produce a READY fact."""

    case = restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    result = step_cup_handle(case.state, case.next_bar)

    assert expected in result.diagnostics
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY for marker in result.markers
    )
    assert result.active_overlay is None or result.active_overlay.state == CupHandleState.FORMING


@pytest.mark.parametrize(
    "bars_factory",
    [
        pretrend_not_confirmed,
        downtrend_rebound_rejected,
        shallow_cup_rejected,
        cup_too_deep_rejected,
        v_bottom_rejected,
        wide_range_rejected,
        rim_gap_rejected,
        handle_too_short_rejected,
        handle_too_long_rejected,
        handle_too_deep_rejected,
        handle_below_mid_rejected,
        handle_volume_not_contracting,
        rollover_split_candidate,
    ],
)
def test_approved_negative_bar_fixtures_never_emit_ready_or_breakout(
    bars_factory: object,
) -> None:
    """The named fixture matrix protects the user-visible false-positive boundary."""

    results = calculate_cup_handle_series(bars_factory())  # type: ignore[operator]
    marker_types = {marker.marker_type for marker in _markers(results)}

    assert NewowMarkerType.CUP_HANDLE_READY not in marker_types
    assert NewowMarkerType.CUP_HANDLE_BREAKOUT not in marker_types


def test_geometric_breakout_without_volume_stays_ready() -> None:
    """A price-only crossing must remain a research setup, not a confirmed breakout."""

    results = calculate_cup_handle_series(breakout_volume_not_confirmed())

    assert "BREAKOUT_VOLUME_UNCONFIRMED" in results[-1].diagnostics
    assert results[-1].active_overlay is not None
    assert results[-1].active_overlay.state == CupHandleState.READY
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
        for marker in results[-1].markers
    )


def test_candidate_limit_is_bounded_and_fail_closed() -> None:
    """Enumeration must stop before the configured limit can leak a new candidate."""

    case = candidate_limit_exceeded()
    profile = replace(NEWOW_TREND_D1_V1, cup_max_candidate_checks_per_step=1)
    result = step_cup_handle(case.state, case.next_bar, profile=profile)

    assert result.candidate_checks == 1
    assert "CUP_CANDIDATE_LIMIT_EXCEEDED" in result.diagnostics
    assert result.markers == ()

    forming_case = restored_cup_case(handle_volume=97)
    forming = step_cup_handle(forming_case.state, forming_case.next_bar)
    assert forming.state.active_candidate is not None
    assert forming.state.active_candidate.state == CupHandleState.FORMING
    next_day = forming_case.next_bar.trading_day + timedelta(days=1)
    next_bar = replace(
        forming_case.next_bar,
        trading_day=next_day,
        bar_end=datetime.combine(next_day, datetime.min.time(), tzinfo=UTC),
        source_identity="fixture:candidate-limit:preserve",
    )
    preserved = step_cup_handle(forming.state, next_bar, profile=profile)
    assert "CUP_CANDIDATE_LIMIT_EXCEEDED" in preserved.diagnostics
    assert preserved.state.active_candidate == forming.state.active_candidate
    assert preserved.active_overlay == forming.active_overlay


def test_forming_identity_and_first_seen_evolve_into_ready_without_rewrite() -> None:
    """H stays out of candidate identity while a real FORMING setup matures."""

    results = calculate_cup_handle_series(bullish_true_cup_handle())
    forming = [
        result.active_overlay
        for result in results
        if result.active_overlay is not None
        and result.active_overlay.state == CupHandleState.FORMING
    ]
    ready = next(
        result.active_overlay
        for result in results
        if any(
            marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
            for marker in result.markers
        )
    )

    assert ready is not None
    assert len(forming) >= 2
    assert {overlay.candidate_id for overlay in forming} == {ready.candidate_id}
    assert {overlay.first_seen_at for overlay in forming} == {ready.first_seen_at}
    assert all(overlay.handle_extreme is None for overlay in forming)
    assert ready.handle_extreme is not None


def test_same_bar_breakout_outranks_a_higher_scoring_ready_candidate() -> None:
    """Primary selection must classify the current bar before score tie-breaking."""

    case = competing_ready_and_breakout_candidates()
    result = step_cup_handle(case.state, case.next_bar)

    assert tuple(marker.marker_type for marker in result.markers) == (
        NewowMarkerType.CUP_HANDLE_READY,
        NewowMarkerType.CUP_HANDLE_BREAKOUT,
    )
    assert result.active_overlay is not None
    assert result.active_overlay.left_rim.pivot_index == 60
    assert result.active_overlay.right_rim.pivot_index == 90
    quiet = step_cup_handle(
        case.state,
        replace(
            case.next_bar,
            open=Decimal("101"),
            high=Decimal("102"),
            low=Decimal("100"),
            close=Decimal("101"),
            volume=100,
        ),
    )
    assert quiet.active_overlay is not None
    assert quiet.active_overlay.left_rim.pivot_index == 35
    assert quiet.active_overlay.score > result.active_overlay.score


def test_frozen_ready_is_not_replaced_by_a_later_competing_breakout() -> None:
    """Once selected, READY owns the active slot until its own lifecycle terminates."""

    case = competing_ready_and_breakout_candidates()
    quiet_ready_bar = replace(
        case.next_bar,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=100,
    )
    ready = step_cup_handle(case.state, quiet_ready_bar)
    assert ready.state.active_candidate is not None
    assert ready.state.active_candidate.left_rim.pivot_index == 35
    frozen = ready.state.active_candidate
    next_day = quiet_ready_bar.trading_day + timedelta(days=1)
    competing_breakout = replace(
        case.next_bar,
        trading_day=next_day,
        bar_end=datetime.combine(next_day, datetime.min.time(), tzinfo=UTC),
        source_identity="fixture:competing:100",
    )

    result = step_cup_handle(ready.state, competing_breakout)

    assert result.markers == ()
    assert result.state.active_candidate == frozen
    assert result.active_overlay == frozen


def test_zero_frozen_handle_volume_cannot_confirm_a_breakout_ratio() -> None:
    """A zero denominator is unavailable, never an infinite passing ratio."""

    case = restored_cup_case(
        handle_volume=0,
        next_close=Decimal("101"),
        next_volume=180,
    )
    result = step_cup_handle(case.state, case.next_bar)

    assert tuple(marker.marker_type for marker in result.markers) == (
        NewowMarkerType.CUP_HANDLE_READY,
    )
    assert "BREAKOUT_VOLUME_UNCONFIRMED" in result.diagnostics
    assert result.active_overlay is not None
    assert result.active_overlay.state == CupHandleState.READY


def test_handle_upper_half_uses_average_rim_cup_depth() -> None:
    """The upper-half gate is based on cup depth, not only the right leg."""

    case = restored_cup_case(
        left_price=Decimal("110"),
        bottom_price=Decimal("80"),
        right_price=Decimal("90"),
        handle_price=Decimal("87"),
    )
    profile = replace(
        NEWOW_TREND_D1_V1,
        cup_rim_gap_max_pct=0.25,
        cup_rim_gap_max_atr=20.0,
    )
    result = step_cup_handle(case.state, case.next_bar, profile=profile)

    assert "HANDLE_BELOW_CUP_MID" in result.diagnostics
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
        for marker in result.markers
    )


@pytest.mark.parametrize(
    "case_kwargs",
    [
        {"bottom_price": Decimal("90"), "handle_price": Decimal("97")},
        {
            "bottom_index": 47,
            "right_index": 64,
            "handle_index": 69,
            "handle_confirmed_index": 72,
            "bottom_price": Decimal("50"),
            "handle_price": Decimal("85"),
        },
        {"atr": 20 / 3},
        {
            "left_price": Decimal("102.5"),
            "right_price": Decimal("97.5"),
            "bottom_price": Decimal("75"),
            "handle_price": Decimal("90"),
            "atr": 10 / 3,
        },
    ],
)
def test_cup_geometry_hard_boundaries_are_inclusive(
    case_kwargs: dict[str, object],
) -> None:
    """Exact 10%, 50%, 3 ATR, 5%, and 1.5 ATR values must remain admissible."""

    case = restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    result = step_cup_handle(case.state, case.next_bar)

    assert not {
        "CUP_DEPTH_BELOW_10_PERCENT",
        "CUP_DEPTH_ABOVE_50_PERCENT",
        "CUP_DEPTH_BELOW_3_ATR",
        "RIM_GAP_PERCENT_EXCEEDED",
        "RIM_GAP_ATR_EXCEEDED",
    }.intersection(result.diagnostics)
    assert result.active_overlay is not None


@pytest.mark.parametrize(
    "case_kwargs",
    [
        {"handle_index": 63, "handle_confirmed_index": 65},
        {"handle_index": 70, "handle_confirmed_index": 75},
        {
            "bottom_index": 47,
            "right_index": 64,
            "handle_index": 69,
            "handle_confirmed_index": 72,
            "bottom_price": Decimal("50"),
            "handle_price": Decimal("85"),
        },
        {"bottom_price": Decimal("70"), "handle_price": Decimal("90")},
        {"right_volume": 100, "handle_volume": 80},
        {
            "bottom_index": 50,
            "bottom_price": Decimal("70"),
            "right_volume": 120,
            "baseline_volume": 80,
            "handle_volume": 90,
        },
    ],
)
def test_handle_and_contraction_hard_boundaries_are_inclusive(
    case_kwargs: dict[str, object],
) -> None:
    """Exact 5/15 bars, 15%, one-third, 0.80, and 0.90 must permit READY."""

    case = restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    result = step_cup_handle(case.state, case.next_bar)

    assert result.active_overlay is not None
    assert result.active_overlay.state == CupHandleState.READY
    assert tuple(marker.marker_type for marker in result.markers) == (
        NewowMarkerType.CUP_HANDLE_READY,
    )


def test_forming_score_exactly_45_is_admitted_and_46_rejects() -> None:
    """Restoring the obsolete 65-point FORMING threshold would erase valid bodies."""

    case = restored_cup_case(
        pretrend="weak",
        atr=6.0,
        bottom_index=50,
        bottom_span=3,
    )
    at_boundary = step_cup_handle(case.state, case.next_bar)
    above_boundary = step_cup_handle(
        case.state,
        case.next_bar,
        profile=replace(NEWOW_TREND_D1_V1, cup_forming_min_body_score=46),
    )

    assert at_boundary.active_overlay is not None
    assert at_boundary.active_overlay.state == CupHandleState.FORMING
    assert at_boundary.active_overlay.score == 45.0
    assert above_boundary.active_overlay is None
    assert "CUP_FORMING_SCORE_INSUFFICIENT" in above_boundary.diagnostics


def test_ready_score_exactly_80_is_admitted_and_81_stays_forming() -> None:
    """READY admission is inclusive at the frozen 80-point boundary."""

    case = restored_cup_case(right_volume=100, handle_volume=78)
    at_boundary = step_cup_handle(case.state, case.next_bar)
    above_boundary = step_cup_handle(
        case.state,
        case.next_bar,
        profile=replace(NEWOW_TREND_D1_V1, cup_ready_min_score=81),
    )

    assert at_boundary.active_overlay is not None
    assert at_boundary.active_overlay.state == CupHandleState.READY
    assert at_boundary.active_overlay.score == 80.0
    assert above_boundary.active_overlay is not None
    assert above_boundary.active_overlay.state == CupHandleState.FORMING
    assert "CUP_READY_SCORE_INSUFFICIENT" in above_boundary.diagnostics


def test_breakout_full_score_exactly_85_is_admitted() -> None:
    """The full-score comparison must include the six breakout-volume points exactly once."""

    case = restored_cup_case(
        pretrend="weak",
        atr=6.0,
        next_close=Decimal("101"),
        next_volume=180,
    )
    profile = replace(NEWOW_TREND_D1_V1, cup_ready_min_score=79)
    result = step_cup_handle(case.state, case.next_bar, profile=profile)

    assert result.active_overlay is not None
    assert result.active_overlay.score == 79.0
    assert tuple(marker.marker_type for marker in result.markers) == (
        NewowMarkerType.CUP_HANDLE_READY,
        NewowMarkerType.CUP_HANDLE_BREAKOUT,
    )
    assert result.markers[-1].trigger_facts["full_score"] == 85.0


def test_breakout_volume_boundaries_1_20_and_1_50_are_inclusive() -> None:
    """Exact breakout volume ratios must not be lost to a strict comparison."""

    volume20_case = restored_cup_case(next_close=Decimal("101"), next_volume=144)
    volume20_result = step_cup_handle(volume20_case.state, volume20_case.next_bar)
    volume20_marker = volume20_result.markers[-1]
    assert volume20_marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
    assert volume20_marker.trigger_facts["breakout_volume20_ratio"] == 1.2

    handle_case = restored_cup_case()
    ready_result = step_cup_handle(handle_case.state, handle_case.next_bar)
    state = ready_result.state
    last_bar = handle_case.next_bar
    for offset in range(1, 20):
        bar_day = last_bar.trading_day + timedelta(days=offset)
        quiet_bar = replace(
            last_bar,
            trading_day=bar_day,
            bar_end=datetime.combine(bar_day, datetime.min.time(), tzinfo=UTC),
            open=Decimal("98"),
            high=Decimal("99"),
            low=Decimal("97"),
            close=Decimal("98"),
            volume=40,
            source_identity=f"fixture:quiet:{offset}",
        )
        state = step_cup_handle(state, quiet_bar).state
    breakout_day = last_bar.trading_day + timedelta(days=20)
    breakout_bar = replace(
        last_bar,
        trading_day=breakout_day,
        bar_end=datetime.combine(breakout_day, datetime.min.time(), tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=90,
        source_identity="fixture:handle-boundary",
    )
    handle_result = step_cup_handle(state, breakout_bar)
    handle_marker = handle_result.markers[-1]

    assert handle_marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
    assert handle_marker.trigger_facts["breakout_handle_volume_ratio"] == 1.5


def test_unconfirmed_crossing_requires_a_reset_before_later_promotion() -> None:
    """Staying above P after a low-volume crossing must never become BREAKOUT later."""

    bars = list(breakout_volume_not_confirmed())
    prior = bars[-1]

    def next_bar(offset: int, close: str, volume: int) -> NewowDailyBar:
        bar_day = prior.trading_day + timedelta(days=offset)
        value = Decimal(close)
        return replace(
            prior,
            trading_day=bar_day,
            bar_end=datetime.combine(bar_day, datetime.min.time(), tzinfo=UTC),
            open=value,
            high=value + Decimal("1"),
            low=value - Decimal("1"),
            close=value,
            volume=volume,
            source_identity=f"fixture:rearm:{offset}",
        )

    bars.extend(
        (
            next_bar(1, "102", 180),
            next_bar(2, "99", 100),
            next_bar(3, "102", 180),
        )
    )
    results = calculate_cup_handle_series(tuple(bars))

    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
        for marker in results[-3].markers
    )
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
        for marker in results[-2].markers
    )
    assert tuple(marker.marker_type for marker in results[-1].markers) == (
        NewowMarkerType.CUP_HANDLE_BREAKOUT,
    )


def test_breakout_weakened_invalidated_relations_and_frozen_facts() -> None:
    """Lifecycle transitions must relate immutable milestones without rewriting READY facts."""

    bars = list(breakout_then_weakened())
    weak_results = calculate_cup_handle_series(tuple(bars))
    weak_result = weak_results[-1]
    ready_marker, breakout_marker, weakened_marker = _markers(weak_results)
    ready_overlay = next(
        result.active_overlay
        for result in weak_results
        if ready_marker in result.markers
    )
    assert ready_overlay is not None and weak_result.active_overlay is not None
    assert weak_result.active_overlay.state == CupHandleState.WEAKENED
    assert weak_result.active_overlay.score == ready_overlay.score
    assert weak_result.active_overlay.score_breakdown == ready_overlay.score_breakdown
    assert weak_result.active_overlay.volume_facts == ready_overlay.volume_facts
    assert weakened_marker.related_marker_ids == (
        ready_marker.marker_id,
        breakout_marker.marker_id,
    )
    assert weakened_marker.trigger_facts["state_before"] == "BREAKOUT"

    prior = bars[-1]
    day = prior.trading_day + timedelta(days=1)
    invalid_bar = replace(
        prior,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=Decimal("92"),
        high=Decimal("93"),
        low=Decimal("91"),
        close=Decimal("92"),
        source_identity="fixture:weak-invalid",
    )
    invalid_result = step_cup_handle(weak_result.state, invalid_bar)
    invalidated = invalid_result.markers[-1]

    assert invalid_result.active_overlay is not None
    assert invalid_result.active_overlay.state == CupHandleState.INVALIDATED
    assert invalid_result.state.active_candidate is None
    assert invalidated.related_marker_ids == (
        ready_marker.marker_id,
        breakout_marker.marker_id,
        weakened_marker.marker_id,
    )
    assert invalidated.trigger_facts["state_before"] == "WEAKENED"


def test_ready_invalidates_directly_and_terminal_candidate_cannot_rebirth() -> None:
    """A broken H ends the L/B/R identity; another H cannot resurrect it."""

    bars = list(ready_then_invalidated())
    results = calculate_cup_handle_series(tuple(bars))
    terminal = results[-1]
    ready_marker, invalidated_marker = _markers(results)
    candidate_id = invalidated_marker.trigger_facts["candidate_id"]

    assert terminal.active_overlay is not None
    assert terminal.active_overlay.state == CupHandleState.INVALIDATED
    assert terminal.state.active_candidate is None
    assert invalidated_marker.related_marker_ids == (ready_marker.marker_id,)
    assert invalidated_marker.trigger_facts["state_before"] == "READY"
    assert candidate_id in terminal.state.recent_terminal_candidate_ids

    state = terminal.state
    prior = bars[-1]
    later_markers = []
    for offset in range(1, 8):
        day = prior.trading_day + timedelta(days=offset)
        later = replace(
            prior,
            trading_day=day,
            bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            source_identity=f"fixture:no-rebirth:{offset}",
        )
        result = step_cup_handle(state, later)
        later_markers.extend(result.markers)
        state = result.state
    assert all(
        marker.trigger_facts["candidate_id"] != candidate_id for marker in later_markers
    )


def test_ready_expires_on_twentieth_bar_and_clears_active_state() -> None:
    """Expiry must use the READY bar, emit once at 20, and terminate the candidate."""

    results = calculate_cup_handle_series(ready_then_expired())
    ready_index = next(
        index
        for index, result in enumerate(results)
        if any(
            marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
            for marker in result.markers
        )
    )
    expired_index = next(
        index
        for index, result in enumerate(results)
        if any(
            marker.marker_type == NewowMarkerType.CUP_HANDLE_EXPIRED
            for marker in result.markers
        )
    )
    expired_result = results[expired_index]
    ready_marker, expired_marker = _markers(results)

    assert expired_index - ready_index == 20
    assert expired_result.active_overlay is not None
    assert expired_result.active_overlay.state == CupHandleState.EXPIRED
    assert expired_result.state.active_candidate is None
    assert expired_marker.related_marker_ids == (ready_marker.marker_id,)
    assert all(
        marker.marker_type != NewowMarkerType.CUP_HANDLE_EXPIRED
        for result in results[expired_index + 1 :]
        for marker in result.markers
    )


def test_breakout_archives_silently_after_twenty_unchanged_bars() -> None:
    """A stable breakout must leave bounded active state without inventing a marker."""

    results = calculate_cup_handle_series(breakout_then_archived())
    breakout_index = next(
        index
        for index, result in enumerate(results)
        if any(
            marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
            for marker in result.markers
        )
    )
    archive_index = breakout_index + 20

    assert results[archive_index - 1].state.active_candidate is not None
    assert results[archive_index].state.active_candidate is None
    assert results[archive_index].active_overlay is None
    assert results[archive_index].markers == ()


def test_candidate_and_marker_ids_and_marker_facts_are_deterministic() -> None:
    """Replaying the same prefix must produce byte-stable identities and causal facts."""

    bars = bullish_true_cup_handle()
    first = calculate_cup_handle_series(bars)
    second = calculate_cup_handle_series(bars)
    first_markers = _markers(first)
    second_markers = _markers(second)
    ready = next(
        result.active_overlay
        for result in first
        if any(
            marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
            for marker in result.markers
        )
    )
    assert ready is not None
    expected_candidate_id = sha256(
        "|".join(
            (
                "newow_trend_v1",
                "newow_cup_handle_v1",
                "RB2701",
                "rb:RB2701:2026-01-01",
                "BULLISH",
                ready.left_rim.pivot_at.isoformat(),
                ready.bottom.pivot_at.isoformat(),
                ready.right_rim.pivot_at.isoformat(),
            )
        ).encode()
    ).hexdigest()

    assert ready.candidate_id == expected_candidate_id
    assert [marker.marker_id for marker in first_markers] == [
        marker.marker_id for marker in second_markers
    ]
    for marker in first_markers:
        assert marker.marker_id == sha256(
            f"{expected_candidate_id}|{marker.marker_type.value}|{marker.bar_end.isoformat()}".encode()
        ).hexdigest()
        assert {
            "candidate_id",
            "direction",
            "state_before",
            "state_after",
            "left_rim",
            "bottom",
            "right_rim",
            "handle_extreme",
            "pivot_price",
            "score",
            "score_breakdown",
            "volume_facts",
            "formula_version",
        }.issubset(marker.trigger_facts)


def test_pivots_alternate_and_confirmed_facts_never_move_with_future_bars() -> None:
    """A confirmed pivot is an immutable causal fact, not a repainting extreme."""

    bars = bullish_true_cup_handle()
    prefix = calculate_cup_handle_series(bars[:79])
    confirmed = prefix[-1].state.confirmed_pivots
    future = calculate_cup_handle_series(bars + tuple(
        replace(
            bars[-1],
            trading_day=bars[-1].trading_day + timedelta(days=offset),
            bar_end=datetime.combine(
                bars[-1].trading_day + timedelta(days=offset),
                datetime.min.time(),
                tzinfo=UTC,
            ),
            open=Decimal("150") + offset,
            high=Decimal("151") + offset,
            low=Decimal("149") + offset,
            close=Decimal("150") + offset,
            source_identity=f"fixture:future-pivot:{offset}",
        )
        for offset in range(1, 5)
    ))

    assert future[78].state.confirmed_pivots == confirmed
    assert all(
        left.kind != right.kind
        for left, right in zip(
            future[-1].state.confirmed_pivots,
            future[-1].state.confirmed_pivots[1:],
        )
    )


def test_initial_pivot_tie_break_is_stable_and_high_first() -> None:
    """Equal normalized reversal distances and timestamps must deterministically choose HIGH."""

    extreme_bar = replace(
        _bar(0, 100),
        high=Decimal("115"),
        low=Decimal("85"),
    )
    extreme = CupBarSnapshot(extreme_bar, eligible_index=0, atr=10.0)
    state = replace(
        initial_cup_handle_state(),
        atr_state=WilderAtrState(
            count=14,
            atr=10.0,
            previous_close=Decimal("100"),
        ),
        pivot_tracker=CupPivotTrackerState(
            leg="SEEK_DIRECTION",
            extreme_high=extreme,
            extreme_low=extreme,
            eligible_index=9,
        ),
        eligible_bars=(extreme,),
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
        eligible_started=True,
    )

    result = step_cup_handle(state, _bar(10, 100))

    assert result.state.confirmed_pivots[-1].kind == CupPivotKind.HIGH
    assert result.state.confirmed_pivots[-1].pivot_at == extreme_bar.bar_end


def test_equal_price_handle_pivots_choose_the_later_pivot() -> None:
    """Equal normalized H prices use the spec's later-pivot tie-break."""

    case = restored_cup_case(handle_index=64, handle_confirmed_index=66)
    snapshots = list(case.state.eligible_bars)
    prior = snapshots[-1].bar
    appended: list[CupBarSnapshot] = []
    for index, close in enumerate((98, 97, 96, 95, 96, 97, 99), start=67):
        day = prior.trading_day + timedelta(days=index - 66)
        value = Decimal(close)
        appended_bar = replace(
            prior,
            trading_day=day,
            bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            open=value,
            high=Decimal("120") if index == 67 else value + Decimal("1"),
            low=Decimal("94") if index == 70 else value - Decimal("1"),
            close=value,
            volume=60,
            source_identity=f"fixture:tied-handle:{index}",
        )
        appended.append(CupBarSnapshot(appended_bar, index, 2.0))
    snapshots.extend(appended)

    high = CupPivot(
        CupPivotKind.HIGH,
        Decimal("120"),
        snapshots[67].bar.bar_end,
        snapshots[69].bar.bar_end,
        67,
        69,
        2.0,
    )
    later_low = CupPivot(
        CupPivotKind.LOW,
        Decimal("94"),
        snapshots[70].bar.bar_end,
        snapshots[73].bar.bar_end,
        70,
        73,
        2.0,
    )
    state = replace(
        case.state,
        atr_state=replace(
            case.state.atr_state,
            count=74,
            atr=2.0,
            previous_close=snapshots[-1].bar.close,
        ),
        pivot_tracker=replace(case.state.pivot_tracker, eligible_index=73),
        eligible_bars=tuple(snapshots),
        confirmed_pivots=case.state.confirmed_pivots + (high, later_low),
    )
    day = prior.trading_day + timedelta(days=8)
    next_bar = replace(
        prior,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        source_identity="fixture:tied-handle:74",
    )

    result = step_cup_handle(state, next_bar)

    assert result.active_overlay is not None
    assert result.active_overlay.handle_extreme is not None
    assert result.active_overlay.handle_extreme.pivot_index == 70


def test_ineligible_bars_warm_atr_but_never_enter_geometry() -> None:
    """Pre-rank1 bars may seed ATR, never eligible indexes, pivots, or volume windows."""

    warmup = tuple(replace(_bar(index, 100), observation_eligible=False) for index in range(14))
    pattern = tuple(
        replace(
            bar,
            trading_day=bar.trading_day + timedelta(days=14),
            bar_end=bar.bar_end + timedelta(days=14),
            source_identity=f"fixture:warmed:{index}",
        )
        for index, bar in enumerate(bullish_true_cup_handle())
    )
    results = calculate_cup_handle_series(warmup + pattern)

    assert all(result.state.eligible_bars == () for result in results[:14])
    assert results[13].state.atr_state.atr is not None
    ready = next(
        result.active_overlay
        for result in results
        if any(
            marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
            for marker in result.markers
        )
    )
    assert ready is not None
    assert ready.left_rim.pivot_index == 45
    assert ready.bottom.pivot_index == 60
    assert ready.right_rim.pivot_index == 75


def test_rollover_resets_atr_pivots_candidate_and_emits_no_terminal_marker() -> None:
    """A physical-segment boundary is identity reset, not pattern invalidation."""

    bars = bullish_true_cup_handle()
    prefix = calculate_cup_handle_series(bars[:83])
    assert prefix[-1].state.active_candidate is not None
    prior = bars[82]
    rollover = replace(
        prior,
        physical_contract="RB2705",
        segment_id="rb:RB2705:2026-05-01",
        trading_day=prior.trading_day + timedelta(days=1),
        bar_end=prior.bar_end + timedelta(days=1),
        source_identity="fixture:rollover",
    )
    result = step_cup_handle(prefix[-1].state, rollover)

    assert result.diagnostics == ("CUP_ROLLOVER_RESET", "CUP_ATR_UNAVAILABLE")
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state.atr_state.count == 1
    assert result.state.eligible_bars == ()
    assert result.state.confirmed_pivots == ()
    assert result.state.recent_terminal_candidate_ids == ()


def test_full_prefix_batch_incremental_restore_and_future_tail_parity() -> None:
    """All historical and resumed paths must produce identical immutable step facts."""

    bars = bullish_true_cup_handle()
    full = calculate_cup_handle_series(bars)
    state = initial_cup_handle_state()
    incremental = []
    for bar in bars:
        result = step_cup_handle(state, bar)
        incremental.append(result)
        state = result.state
    assert tuple(incremental) == full
    for cut in (1, 13, 46, 61, 76, 83, 85):
        assert calculate_cup_handle_series(bars[:cut]) == full[:cut]

    for cut in (20, 50, 82, 84):
        state = initial_cup_handle_state()
        for bar in bars[:cut]:
            state = step_cup_handle(state, bar).state
        restored = pickle.loads(pickle.dumps(state))
        resumed = []
        for bar in bars[cut:]:
            result = step_cup_handle(restored, bar)
            resumed.append(result)
            restored = result.state
        assert tuple(resumed) == full[cut:]

    prefix_length = 80
    mutated_tail = tuple(
        replace(
            bar,
            open=bar.open + Decimal("25"),
            high=bar.high + Decimal("25"),
            low=bar.low + Decimal("25"),
            close=bar.close + Decimal("25"),
            volume=bar.volume + 500,
            source_identity=f"fixture:mutated:{index}",
        )
        for index, bar in enumerate(bars[prefix_length:], start=prefix_length)
    )
    assert calculate_cup_handle_series(bars[:prefix_length] + mutated_tail)[:prefix_length] == full[:prefix_length]


def test_corrupt_restored_state_fails_closed_instead_of_continuing() -> None:
    """Non-alternating restored pivots must reset rather than create a candidate."""

    case = restored_cup_case()
    duplicate_high = CupPivot(
        kind=CupPivotKind.HIGH,
        price=Decimal("101"),
        pivot_at=case.state.confirmed_pivots[-1].pivot_at,
        confirmed_at=case.state.confirmed_pivots[-1].confirmed_at,
        pivot_index=case.state.confirmed_pivots[-1].pivot_index,
        confirmed_index=case.state.confirmed_pivots[-1].confirmed_index,
        atr_at_pivot=2.0,
    )
    malformed = replace(
        case.state,
        confirmed_pivots=case.state.confirmed_pivots[:1] + (duplicate_high,),
    )

    result = step_cup_handle(malformed, case.next_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def test_state_collections_and_absolute_indexes_remain_bounded() -> None:
    """A long segment cannot grow history, pivots, or terminal IDs without bound."""

    bars = tuple(
        _bar(index, 100 + (6 if (index // 4) % 2 else -6)) for index in range(280)
    )
    result = calculate_cup_handle_series(bars)[-1]

    assert len(result.state.eligible_bars) == 220
    assert result.state.eligible_bars[-1].eligible_index == 279
    assert result.state.eligible_bars[0].eligible_index == 60
    assert len(result.state.confirmed_pivots) <= 32
    assert len(result.state.recent_terminal_candidate_ids) <= 32


def test_expiry_still_occurs_when_twentieth_bar_is_an_unconfirmed_crossing() -> None:
    """A price-only crossing on the deadline is still not a legal breakout."""

    case = restored_cup_case()
    ready = step_cup_handle(case.state, case.next_bar)
    state = ready.state
    prior = case.next_bar
    for offset in range(1, 20):
        day = prior.trading_day + timedelta(days=offset)
        quiet = replace(
            prior,
            trading_day=day,
            bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            open=Decimal("98"),
            high=Decimal("99"),
            low=Decimal("97"),
            close=Decimal("98"),
            volume=40,
            source_identity=f"fixture:expiry-cross:{offset}",
        )
        state = step_cup_handle(state, quiet).state
    deadline = prior.trading_day + timedelta(days=20)
    low_volume_cross = replace(
        prior,
        trading_day=deadline,
        bar_end=datetime.combine(deadline, datetime.min.time(), tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=1,
        source_identity="fixture:expiry-low-volume-cross",
    )

    result = step_cup_handle(state, low_volume_cross)

    assert "BREAKOUT_VOLUME_UNCONFIRMED" in result.diagnostics
    assert tuple(marker.marker_type for marker in result.markers) == (
        NewowMarkerType.CUP_HANDLE_EXPIRED,
    )
    assert result.state.active_candidate is None


@pytest.mark.parametrize(
    "case_kwargs",
    [
        {
            "bottom_index": 42,
            "right_index": 54,
            "handle_index": 59,
            "handle_confirmed_index": 62,
        },
        {
            "bottom_index": 75,
            "right_index": 119,
            "handle_index": 124,
            "handle_confirmed_index": 127,
        },
    ],
)
def test_cup_duration_25_and_90_bar_boundaries_are_inclusive(
    case_kwargs: dict[str, object],
) -> None:
    """The two exact duration endpoints are valid cup bodies."""

    case = restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    result = step_cup_handle(case.state, case.next_bar)

    assert result.active_overlay is not None
    assert (
        result.active_overlay.right_rim.pivot_index
        - result.active_overlay.left_rim.pivot_index
        + 1
    ) in {25, 90}


@pytest.mark.parametrize(
    ("case_kwargs", "expected"),
    [
        (
            {"pretrend": "rising", "atr": 6.0},
            {
                "pretrend": 12.0,
                "cup_geometry": 21.0,
                "u_shape_purity": 18.0,
                "handle_quality": 16.0,
                "volume_structure": 14.0,
            },
        ),
        (
            {"bottom_span": 3},
            {
                "pretrend": 15.0,
                "cup_geometry": 23.0,
                "u_shape_purity": 16.0,
                "handle_quality": 16.0,
                "volume_structure": 14.0,
            },
        ),
        (
            {"midline_crossings": 4},
            {
                "pretrend": 15.0,
                "cup_geometry": 23.0,
                "u_shape_purity": 14.0,
                "handle_quality": 16.0,
                "volume_structure": 14.0,
            },
        ),
        (
            {"right_volume": 100, "handle_volume": 70},
            {
                "pretrend": 15.0,
                "cup_geometry": 23.0,
                "u_shape_purity": 18.0,
                "handle_quality": 16.0,
                "volume_structure": 12.0,
            },
        ),
    ],
)
def test_discrete_ready_score_buckets_are_exact(
    case_kwargs: dict[str, object], expected: dict[str, float]
) -> None:
    """Each documented score bucket contributes only its fixed discrete points."""

    case = restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    result = step_cup_handle(case.state, case.next_bar)

    assert result.active_overlay is not None
    assert result.active_overlay.state == CupHandleState.READY
    assert dict(result.active_overlay.score_breakdown) == expected
    assert result.active_overlay.score == sum(expected.values())


@pytest.mark.parametrize(
    ("case_kwargs", "expected_handle_score"),
    [
        ({"handle_index": 63, "handle_confirmed_index": 65}, 14.0),
        ({"bottom_price": Decimal("70"), "handle_price": Decimal("94")}, 20.0),
        ({"bottom_price": Decimal("70"), "handle_price": Decimal("92")}, 18.0),
        ({"bottom_price": Decimal("60"), "handle_price": Decimal("90")}, 16.0),
        (
            {
                "bottom_index": 47,
                "right_index": 64,
                "handle_index": 69,
                "handle_confirmed_index": 72,
                "bottom_price": Decimal("50"),
                "handle_price": Decimal("85"),
            },
            12.0,
        ),
    ],
)
def test_discrete_handle_quality_score_buckets_are_exact(
    case_kwargs: dict[str, object], expected_handle_score: float
) -> None:
    """Length, depth, retrace, and upper-half points follow the frozen table."""

    case = restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    result = step_cup_handle(case.state, case.next_bar)

    assert result.active_overlay is not None
    assert result.active_overlay.state == CupHandleState.READY
    assert result.active_overlay.score_breakdown["handle_quality"] == expected_handle_score
