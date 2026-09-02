from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from math import nextafter
import pickle
from typing import Mapping

import pytest

from guiyi_quant.newow.cup_handle import (
    CupBarSnapshot,
    CupPivotTrackerState,
    WilderAtrState,
    _body_facts,
    _pretrend_score,
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
    RestoredCupCase,
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


def test_zero_wilder_seed_is_unavailable_without_invalidating_restored_state() -> None:
    """Fourteen flat bars are a valid ATR seed, but cannot support geometry."""

    flat_bars = tuple(
        replace(
            _bar(index, 100),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            source_identity=f"fixture:flat-atr:{index}",
        )
        for index in range(15)
    )

    seeded = calculate_cup_handle_series(flat_bars[:14])[-1]
    resumed = step_cup_handle(seeded.state, flat_bars[14])

    assert seeded.diagnostics == ("CUP_ATR_UNAVAILABLE",)
    assert seeded.state.atr_state.atr == 0.0
    assert seeded.state.eligible_bars == ()
    assert seeded.state.confirmed_pivots == ()
    assert seeded.active_overlay is None
    assert resumed.diagnostics == ("CUP_ATR_UNAVAILABLE",)
    assert "NEWOW_CUP_STATE_INVALID" not in resumed.diagnostics
    assert resumed.state.atr_state.atr == 0.0
    assert resumed.state.eligible_bars == ()
    assert resumed.state.confirmed_pivots == ()
    assert resumed.active_overlay is None


@pytest.mark.parametrize("huge", (Decimal("1e1000"), Decimal("1e1000000")))
def test_nonfinite_current_atr_is_unavailable_without_geometry(huge: Decimal) -> None:
    """A finite Decimal range that overflows float ATR cannot enter a pivot."""

    flat_bars = tuple(
        replace(
            _bar(index, 100),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            source_identity=f"fixture:finite-atr-warmup:{index}",
        )
        for index in range(13)
    )
    state = calculate_cup_handle_series(flat_bars)[-1].state
    overflow_bar = replace(
        _bar(13, 100),
        open=huge,
        high=huge,
        low=huge,
        close=huge,
        source_identity="fixture:finite-decimal-float-overflow",
    )

    result = step_cup_handle(state, overflow_bar)

    assert result.diagnostics == ("CUP_ATR_UNAVAILABLE",)
    assert result.state.eligible_bars == ()
    assert result.state.confirmed_pivots == ()
    assert result.active_overlay is None

    continued = step_cup_handle(
        result.state,
        replace(
            _bar(14, 100),
            source_identity="fixture:finite-decimal-float-overflow:continued",
        ),
    )

    assert continued.diagnostics == ("CUP_ATR_UNAVAILABLE",)
    assert "NEWOW_CUP_STATE_INVALID" not in continued.diagnostics
    assert continued.state.physical_contract == overflow_bar.physical_contract
    assert continued.state.segment_id == overflow_bar.segment_id
    assert continued.state.eligible_started is True
    assert continued.state.atr_state.atr is None
    assert continued.state.atr_state.tr_total == 0.0
    assert continued.state.pivot_tracker.eligible_index == 14
    assert continued.state.eligible_bars == ()
    assert continued.state.confirmed_pivots == ()
    assert continued.active_overlay is None


def test_same_bar_confirmed_pivot_state_remains_valid_on_the_next_step() -> None:
    """Rejecting confirmed_index == pivot_index drops a legal tracker transition."""

    warmup = tuple(
        replace(
            _bar(index, 100, eligible=False),
            source_identity=f"fixture:same-bar-pivot:warmup:{index}",
        )
        for index in range(14)
    )
    state = calculate_cup_handle_series(warmup)[-1].state
    eligible_ohlc = (
        (99, 100, 80),
        (102, 103, 101),
        (104, 105, 103),
        (106, 107, 105),
        (100, 120, 99),
    )
    result = None
    for offset, (close, high, low) in enumerate(eligible_ohlc, start=14):
        result = step_cup_handle(
            state,
            replace(
                _bar(offset, close),
                high=Decimal(high),
                low=Decimal(low),
                source_identity=f"fixture:same-bar-pivot:{offset}",
            ),
        )
        state = result.state

    assert result is not None
    same_bar_high = result.state.confirmed_pivots[-1]
    assert same_bar_high.kind == CupPivotKind.HIGH
    assert same_bar_high.confirmed_index == same_bar_high.pivot_index

    resumed = step_cup_handle(
        result.state,
        replace(
            _bar(19, 101),
            source_identity="fixture:same-bar-pivot:19",
        ),
    )

    assert "NEWOW_CUP_STATE_INVALID" not in resumed.diagnostics
    assert resumed.state.confirmed_pivots[-1] == same_bar_high


@pytest.mark.parametrize(
    "changes",
    (
        {"count": True},
        {"count": 14.5},
        {"count": 13, "tr_total": 0.0, "atr": 2.0},
        {"count": 14, "tr_total": 28.0, "atr": None},
        {"count": 14, "tr_total": 27.0, "atr": 2.0},
        {"count": 14, "tr_total": 28.0, "atr": nextafter(2.0, float("inf"))},
        {"count": 15, "tr_total": 28.0, "atr": 2.0},
        {
            "count": 0,
            "tr_total": 0.0,
            "atr": None,
            "previous_close": Decimal("100"),
        },
        {
            "count": 1,
            "tr_total": 2.0,
            "atr": None,
            "previous_close": None,
        },
    ),
)
def test_restored_atr_rejects_impossible_initial_seed_and_recursive_phases(
    changes: dict[str, object],
) -> None:
    """Malformed ATR phase state must fail closed instead of silently reseeding."""

    warmup = tuple(
        replace(_bar(index, 100, eligible=False), source_identity=f"atr:{index}")
        for index in range(14)
    )
    seeded = calculate_cup_handle_series(warmup)[-1].state
    malformed = replace(
        seeded,
        atr_state=replace(seeded.atr_state, **changes),
    )

    result = step_cup_handle(
        malformed,
        replace(_bar(14, 100, eligible=False), source_identity="atr:next"),
    )

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.state == initial_cup_handle_state()


@pytest.mark.parametrize("phase", ("warmup", "zero"))
def test_restored_unavailable_atr_phase_cannot_retain_mature_geometry(
    phase: str,
) -> None:
    """A locally valid ATR warm-up phase cannot coexist with a frozen READY setup."""

    case = restored_cup_case()
    ready = step_cup_handle(case.state, case.next_bar)
    assert ready.state.active_candidate is not None
    atr_state = (
        WilderAtrState(
            count=1,
            tr_total=2.0,
            atr=None,
            previous_close=case.next_bar.close,
        )
        if phase == "warmup"
        else replace(ready.state.atr_state, tr_total=0.0, atr=0.0)
    )
    malformed = replace(ready.state, atr_state=atr_state)
    next_day = case.next_bar.trading_day + timedelta(days=1)
    next_bar = replace(
        case.next_bar,
        trading_day=next_day,
        bar_end=datetime.combine(next_day, datetime.min.time(), tzinfo=UTC),
        source_identity="fixture:atr-phase-rollback",
    )

    result = step_cup_handle(malformed, next_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def _markers(results: tuple[object, ...]) -> list[object]:
    return [marker for result in results for marker in result.markers]  # type: ignore[attr-defined]


def _with_exact_pivot_snapshot_prices(case: RestoredCupCase) -> RestoredCupCase:
    """Keep sub-context Decimal pivot prices observable in restored snapshots."""

    snapshots = list(case.state.eligible_bars)
    for pivot in case.state.confirmed_pivots[:3]:
        snapshot = snapshots[pivot.pivot_index]
        bar = (
            replace(snapshot.bar, high=pivot.price)
            if pivot.kind == CupPivotKind.HIGH
            else replace(snapshot.bar, low=pivot.price)
        )
        snapshots[pivot.pivot_index] = replace(snapshot, bar=bar)
    return replace(
        case,
        state=replace(case.state, eligible_bars=tuple(snapshots)),
    )


def _with_even_atr_values(
    snapshots: tuple[CupBarSnapshot, ...],
    *,
    start: int,
    end: int,
    lower: float,
    upper: float,
) -> tuple[CupBarSnapshot, ...]:
    """Replace one even-sized ATR window without changing its Bar facts."""

    count = end - start + 1
    assert count > 0 and count % 2 == 0
    values = [lower] * (count // 2) + [upper] * (count // 2)
    changed = list(snapshots)
    for index, atr in zip(range(start, end + 1), values, strict=True):
        changed[index] = replace(changed[index], atr=atr)
    return tuple(changed)


def _even_atr_body_facts(
    *,
    left_price: Decimal = Decimal("100"),
    bottom_price: Decimal,
    right_price: Decimal = Decimal("100"),
    lower_atr: float = 10.0,
    upper_atr: float = 10.000000000000002,
    profile=NEWOW_TREND_D1_V1,
) -> tuple[object | None, tuple[str, ...]]:
    case = restored_cup_case(
        left_index=30,
        bottom_index=44,
        right_index=59,
        handle_index=64,
        handle_confirmed_index=67,
        left_price=left_price,
        bottom_price=bottom_price,
        right_price=right_price,
    )
    snapshots = _with_even_atr_values(
        case.state.eligible_bars,
        start=30,
        end=59,
        lower=lower_atr,
        upper=upper_atr,
    )
    by_index = {snapshot.eligible_index: snapshot for snapshot in snapshots}
    left, bottom, right = case.state.confirmed_pivots[:3]
    return _body_facts(
        CupHandleDirection.BULLISH,
        left,
        bottom,
        right,
        by_index,
        profile,
    )


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

    bullish_bars = bullish_true_cup_handle()
    bearish_bars = bearish_true_cup_handle()
    bullish = calculate_cup_handle_series(bullish_bars)
    bearish = calculate_cup_handle_series(bearish_bars)
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
    assert [
        result.active_overlay.state if result.active_overlay is not None else None
        for result in bearish
    ] == [
        result.active_overlay.state if result.active_overlay is not None else None
        for result in bullish
    ]

    for bull_anchor, bear_anchor in zip(
        (
            bull_overlay.left_rim,
            bull_overlay.bottom,
            bull_overlay.right_rim,
            bull_overlay.handle_extreme,
        ),
        (
            bear_overlay.left_rim,
            bear_overlay.bottom,
            bear_overlay.right_rim,
            bear_overlay.handle_extreme,
        ),
        strict=True,
    ):
        assert bull_anchor is not None and bear_anchor is not None
        assert bull_anchor.kind != bear_anchor.kind
        assert bull_anchor.price + bear_anchor.price == Decimal("200")
        assert (
            bull_anchor.pivot_at,
            bull_anchor.confirmed_at,
            bull_anchor.pivot_index,
            bull_anchor.confirmed_index,
            bull_anchor.atr_at_pivot,
        ) == (
            bear_anchor.pivot_at,
            bear_anchor.confirmed_at,
            bear_anchor.pivot_index,
            bear_anchor.confirmed_index,
            bear_anchor.atr_at_pivot,
        )
    assert bull_overlay.pivot_price is not None and bear_overlay.pivot_price is not None
    assert bull_overlay.pivot_price + bear_overlay.pivot_price == Decimal("200")

    bull_markers = _markers(bullish)
    bear_markers = _markers(bearish)
    assert [marker.marker_type for marker in bear_markers] == [
        marker.marker_type for marker in bull_markers
    ]
    assert [marker.bar_end for marker in bear_markers] == [
        marker.bar_end for marker in bull_markers
    ]
    marker_id_mirror = {
        bull.marker_id: bear.marker_id
        for bull, bear in zip(bull_markers, bear_markers, strict=True)
    }
    for bull, bear in zip(bull_markers, bear_markers, strict=True):
        assert bull.price + bear.price == Decimal("200")
        assert bear.related_marker_ids == tuple(
            marker_id_mirror[marker_id] for marker_id in bull.related_marker_ids
        )
        assert bear.trigger_facts["direction"] == "BEARISH"
        assert bull.trigger_facts["direction"] == "BULLISH"
        for key in (
            "state_before",
            "state_after",
            "score",
            "score_breakdown",
            "volume_facts",
            "formula_version",
            "full_score",
            "breakout_volume20_median",
            "breakout_volume20_ratio",
            "breakout_handle_volume_ratio",
        ):
            if key in bull.trigger_facts or key in bear.trigger_facts:
                assert bear.trigger_facts[key] == bull.trigger_facts[key]
        for key in ("left_rim", "bottom", "right_rim", "handle_extreme"):
            bull_facts = bull.trigger_facts[key]
            bear_facts = bear.trigger_facts[key]
            assert isinstance(bull_facts, Mapping)
            assert isinstance(bear_facts, Mapping)
            assert bull_facts["kind"] != bear_facts["kind"]
            assert Decimal(str(bull_facts["price"])) + Decimal(
                str(bear_facts["price"])
            ) == Decimal("200")
            for fact_key in (
                "pivot_at",
                "confirmed_at",
                "pivot_index",
                "confirmed_index",
                "atr_at_pivot",
            ):
                assert bull_facts[fact_key] == bear_facts[fact_key]
        assert Decimal(str(bull.trigger_facts["pivot_price"])) + Decimal(
            str(bear.trigger_facts["pivot_price"])
        ) == Decimal("200")

    state = initial_cup_handle_state()
    incremental = []
    for bar in bearish_bars:
        result = step_cup_handle(state, bar)
        incremental.append(result)
        state = result.state
    assert tuple(incremental) == bearish
    for cut in (46, 61, 76, 83, 85):
        assert calculate_cup_handle_series(bearish_bars[:cut]) == bearish[:cut]
    cut = 84
    restored = pickle.loads(pickle.dumps(bearish[cut - 1].state))
    resumed = []
    for bar in bearish_bars[cut:]:
        result = step_cup_handle(restored, bar)
        resumed.append(result)
        restored = result.state
    assert tuple(resumed) == bearish[cut:]


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


def test_single_bar_v_bottom_can_form_but_never_become_ready() -> None:
    """A one-Bar bottom scores zero for span and remains FORMING-only."""

    case = restored_cup_case(bottom_span=1)
    result = step_cup_handle(case.state, case.next_bar)

    assert "V_BOTTOM_SINGLE_BAR" in result.diagnostics
    assert result.active_overlay is not None
    assert result.active_overlay.state == CupHandleState.FORMING
    assert result.active_overlay.score_breakdown["u_shape_purity"] == 10.0
    assert result.active_overlay.score == 48.0
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
        for marker in result.markers
    )


@pytest.mark.parametrize(
    ("case_kwargs", "expected"),
    [
        (
            {"handle_index": 63, "handle_confirmed_index": 64},
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
    ("bars_factory", "expected_diagnostic"),
    [
        (pretrend_not_confirmed, "PRETREND_NOT_CONFIRMED"),
        (downtrend_rebound_rejected, "PRETREND_NOT_CONFIRMED"),
        (shallow_cup_rejected, "CUP_DEPTH_BELOW_10_PERCENT"),
        (cup_too_deep_rejected, "CUP_DEPTH_ABOVE_50_PERCENT"),
        (v_bottom_rejected, "V_BOTTOM_SINGLE_BAR"),
        (wide_range_rejected, "MIDLINE_CROSSINGS_EXCEEDED"),
        (rim_gap_rejected, "RIM_GAP_PERCENT_EXCEEDED"),
        (handle_too_short_rejected, "HANDLE_DURATION_OUT_OF_RANGE"),
        (handle_too_long_rejected, "HANDLE_DURATION_OUT_OF_RANGE"),
        (handle_too_deep_rejected, "HANDLE_DEPTH_EXCEEDED"),
        (handle_below_mid_rejected, "HANDLE_BELOW_CUP_MID"),
        (handle_volume_not_contracting, "HANDLE_VOLUME_NOT_CONTRACTING"),
        (rollover_split_candidate, "CUP_ROLLOVER_RESET"),
    ],
)
def test_approved_negative_bar_fixtures_never_emit_ready_or_breakout(
    bars_factory: object, expected_diagnostic: str
) -> None:
    """Each named causal fixture must actually execute its documented Gate."""

    results = calculate_cup_handle_series(bars_factory())  # type: ignore[operator]
    marker_types = {marker.marker_type for marker in _markers(results)}
    diagnostics = {diagnostic for result in results for diagnostic in result.diagnostics}

    assert expected_diagnostic in diagnostics
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
        {"bottom_price": Decimal("82"), "atr": 6.0},
        {
            "left_price": Decimal("101.5"),
            "right_price": Decimal("98.5"),
            "bottom_price": Decimal("78"),
            "handle_price": Decimal("94"),
            "atr": 2.0,
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
    ("case_kwargs", "expected_diagnostic"),
    (
        (
            {
                "bottom_price": Decimal("90.000000000000001"),
                "handle_price": Decimal("97"),
            },
            "CUP_DEPTH_BELOW_10_PERCENT",
        ),
        (
            {
                "bottom_price": Decimal("49.999999999999999"),
                "handle_price": Decimal("94"),
            },
            "CUP_DEPTH_ABOVE_50_PERCENT",
        ),
    ),
)
def test_decimal_depth_just_outside_hard_limits_never_emits_ready(
    case_kwargs: dict[str, object],
    expected_diagnostic: str,
) -> None:
    """Float rounding must not admit a depth infinitesimally outside an exact gate."""

    case = restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    result = step_cup_handle(case.state, case.next_bar)

    assert expected_diagnostic in result.diagnostics
    assert result.active_overlay is None
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
        for marker in result.markers
    )


def test_decimal_depth_beyond_context_precision_stays_below_ten_percent() -> None:
    """Default Decimal division precision must not round a shallow cup into READY."""

    case = restored_cup_case(
        left_price=Decimal("100"),
        bottom_price=Decimal("90." + "0" * 27 + "1"),
        right_price=Decimal("100"),
        handle_price=Decimal("97"),
    )
    snapshots = list(case.state.eligible_bars)
    bottom = case.state.confirmed_pivots[1]
    snapshots[bottom.pivot_index] = replace(
        snapshots[bottom.pivot_index],
        bar=replace(snapshots[bottom.pivot_index].bar, low=bottom.price),
    )
    case = replace(case, state=replace(case.state, eligible_bars=tuple(snapshots)))

    result = step_cup_handle(case.state, case.next_bar)

    assert "CUP_DEPTH_BELOW_10_PERCENT" in result.diagnostics
    assert result.active_overlay is None
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
        for marker in result.markers
    )


@pytest.mark.parametrize(
    ("case_kwargs", "rounded_failure"),
    (
        (
            {
                "left_price": Decimal("101"),
                "right_price": Decimal("101"),
                "bottom_price": Decimal("90.9"),
                "handle_price": Decimal("98"),
            },
            "CUP_DEPTH_BELOW_10_PERCENT",
        ),
        (
            {
                "left_price": Decimal("90.34515"),
                "right_price": Decimal("90.25485"),
                "bottom_price": Decimal("45.15"),
                "handle_price": Decimal("82"),
            },
            "CUP_DEPTH_ABOVE_50_PERCENT",
        ),
        (
            {
                "left_price": Decimal("103.525"),
                "right_price": Decimal("98.475"),
                "bottom_price": Decimal("75"),
                "handle_price": Decimal("94"),
                "atr": 4.0,
            },
            "RIM_GAP_PERCENT_EXCEEDED",
        ),
        (
            {
                "left_price": Decimal("100.15"),
                "right_price": Decimal("99.85"),
                "bottom_price": Decimal("80"),
                "handle_price": Decimal("94"),
                "atr": 0.2,
            },
            "RIM_GAP_ATR_EXCEEDED",
        ),
        (
            {
                "left_price": Decimal("800"),
                "right_price": Decimal("800"),
                "bottom_price": Decimal("719.199999999999998"),
                "handle_price": Decimal("780"),
                "atr": 26.933333333333334,
            },
            "CUP_DEPTH_BELOW_3_ATR",
        ),
    ),
)
def test_decimal_exact_geometry_boundaries_survive_float_cancellation(
    case_kwargs: dict[str, object],
    rounded_failure: str,
) -> None:
    """An exactly inclusive price or ATR boundary must not fail after cancellation."""

    case = restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    result = step_cup_handle(case.state, case.next_bar)

    assert rounded_failure not in result.diagnostics
    assert result.active_overlay is not None


def test_even_atr_median_rejects_depth_below_three_exact_atr() -> None:
    """A rounded-down float median must not admit a sub-3-ATR cup body."""

    facts, diagnostics = _even_atr_body_facts(
        bottom_price=Decimal("69.9999999999999985"),
    )

    assert facts is None
    assert "CUP_DEPTH_BELOW_3_ATR" in diagnostics


def test_even_atr_median_keeps_depth_below_four_in_lower_score_bucket() -> None:
    """The exact even median keeps a sub-4-ATR body out of the five-point bucket."""

    facts, diagnostics = _even_atr_body_facts(
        bottom_price=Decimal("59.999999999999998"),
    )

    assert diagnostics == ()
    assert facts is not None
    assert facts.breakdown["cup_geometry"] == 17.0


def test_even_atr_median_keeps_rim_gap_inside_one_point_five_atr() -> None:
    """A rounded-down float median must not reject an exact legal rim gap."""

    facts, diagnostics = _even_atr_body_facts(
        left_price=Decimal("107.5000000000000005"),
        bottom_price=Decimal("60"),
        right_price=Decimal("92.4999999999999995"),
        profile=replace(NEWOW_TREND_D1_V1, cup_rim_gap_max_pct=1.0),
    )

    assert "RIM_GAP_ATR_EXCEEDED" not in diagnostics
    assert facts is not None


def test_even_atr_median_keeps_rim_gap_in_zero_point_seven_five_bucket() -> None:
    """The exact even median preserves the inclusive 0.75-ATR rim score."""

    facts, diagnostics = _even_atr_body_facts(
        left_price=Decimal("100.375000000000000025"),
        bottom_price=Decimal("65"),
        right_price=Decimal("99.624999999999999975"),
        lower_atr=1.0,
        upper_atr=1.0000000000000002,
        profile=replace(NEWOW_TREND_D1_V1, cup_rim_gap_max_pct=1.0),
    )

    assert diagnostics == ()
    assert facts is not None
    assert facts.breakdown["cup_geometry"] == 23.0


def test_finite_large_even_atr_median_does_not_overflow() -> None:
    """Two finite large middle values remain a finite exact median."""

    facts, diagnostics = _even_atr_body_facts(
        bottom_price=Decimal("60"),
        lower_atr=1e308,
        upper_atr=1e308,
    )

    assert facts is None
    assert "CUP_DEPTH_BELOW_3_ATR" in diagnostics
    assert "CUP_ATR_UNAVAILABLE" not in diagnostics


@pytest.mark.parametrize(
    ("start_close", "left_price", "expected_score"),
    (
        (Decimal("96"), Decimal("100.00000000000000015"), None),
        (Decimal("94"), Decimal("100.0000000000000002"), 10.0),
    ),
)
def test_even_atr_median_preserves_pretrend_four_atr_and_strength_buckets(
    start_close: Decimal,
    left_price: Decimal,
    expected_score: float | None,
) -> None:
    """Pretrend uses the same exact median for its 4-ATR gate and 1.5 bucket."""

    case = restored_cup_case()
    snapshots = list(
        _with_even_atr_values(
            case.state.eligible_bars,
            start=1,
            end=30,
            lower=1.0,
            upper=1.0000000000000002,
        )
    )
    final_close = left_price - Decimal("1")
    for offset, index in enumerate(range(1, 31)):
        close = start_close + (final_close - start_close) * Decimal(offset) / Decimal(29)
        snapshots[index] = replace(
            snapshots[index],
            bar=replace(
                snapshots[index].bar,
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
            ),
        )
    left = replace(case.state.confirmed_pivots[0], price=left_price)
    score = _pretrend_score(
        CupHandleDirection.BULLISH,
        left,
        {snapshot.eligible_index: snapshot for snapshot in snapshots},
        replace(
            NEWOW_TREND_D1_V1,
            cup_pretrend_min_bars=29,
            cup_pretrend_max_bars=29,
        ),
    )

    assert score == expected_score


def test_pretrend_move_below_four_atr_is_rejected_before_float_rounding() -> None:
    """A sub-float epsilon below the four-ATR hard gate must remain a failure."""

    almost_100 = Decimal("99." + "9" * 28)
    case = _with_exact_pivot_snapshot_prices(
        restored_cup_case(
            left_price=almost_100,
            right_price=almost_100,
            handle_price=Decimal("94"),
            atr=1.0,
            pretrend="flat",
        )
    )

    result = step_cup_handle(case.state, case.next_bar)

    assert "PRETREND_NOT_CONFIRMED" in result.diagnostics
    assert result.active_overlay is None
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
        for marker in result.markers
    )


def test_pretrend_strength_below_one_point_five_stays_in_lower_bucket() -> None:
    """A sub-float epsilon below 1.5 strength earns ten, not twelve, points."""

    almost_102 = Decimal("101." + "9" * 28)
    case = _with_exact_pivot_snapshot_prices(
        restored_cup_case(
            left_price=almost_102,
            right_price=almost_102,
            handle_price=Decimal("95"),
            atr=1.0,
            pretrend="flat",
        )
    )

    result = step_cup_handle(case.state, case.next_bar)

    assert result.active_overlay is not None
    assert result.active_overlay.score_breakdown["pretrend"] == 10.0


def test_cup_depth_below_three_atr_is_rejected_before_float_rounding() -> None:
    """A sub-float epsilon below the three-ATR hard gate must remain a failure."""

    case = _with_exact_pivot_snapshot_prices(
        restored_cup_case(
            bottom_price=Decimal("70." + "0" * 27 + "1"),
            atr=10.0,
        )
    )

    result = step_cup_handle(case.state, case.next_bar)

    assert "CUP_DEPTH_BELOW_3_ATR" in result.diagnostics
    assert result.active_overlay is None
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
        for marker in result.markers
    )


def test_cup_depth_below_four_atr_stays_in_lower_score_bucket() -> None:
    """A sub-float epsilon below four ATR earns three, not five, points."""

    case = _with_exact_pivot_snapshot_prices(
        restored_cup_case(
            bottom_price=Decimal("60." + "0" * 27 + "1"),
            handle_price=Decimal("94"),
            atr=10.0,
        )
    )

    result = step_cup_handle(case.state, case.next_bar)

    assert result.active_overlay is not None
    assert result.active_overlay.score_breakdown["cup_geometry"] == 17.0


def test_rim_gap_above_one_point_five_atr_is_rejected_before_float_rounding() -> None:
    """A sub-float epsilon above the 1.5-ATR hard gate must remain a failure."""

    case = _with_exact_pivot_snapshot_prices(
        restored_cup_case(
            right_price=Decimal("98.4" + "9" * 27),
            bottom_price=Decimal("78"),
            handle_price=Decimal("94"),
            atr=1.0,
        )
    )

    result = step_cup_handle(case.state, case.next_bar)

    assert "RIM_GAP_ATR_EXCEEDED" in result.diagnostics
    assert result.active_overlay is None
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
        for marker in result.markers
    )


def test_rim_gap_above_zero_point_seven_five_atr_stays_in_lower_bucket() -> None:
    """A sub-float epsilon above 0.75 ATR earns five, not seven, points."""

    case = _with_exact_pivot_snapshot_prices(
        restored_cup_case(
            right_price=Decimal("98.4" + "9" * 27),
            bottom_price=Decimal("78"),
            handle_price=Decimal("94"),
            atr=2.0,
        )
    )

    result = step_cup_handle(case.state, case.next_bar)

    assert result.active_overlay is not None
    assert result.active_overlay.score_breakdown["cup_geometry"] == 21.0


@pytest.mark.parametrize(
    ("case_kwargs", "score_key", "expected_score"),
    (
        (
            {
                "left_price": Decimal("100"),
                "right_price": Decimal("100"),
                "handle_price": Decimal("94"),
                "atr": 1.0,
                "pretrend": "flat",
            },
            "pretrend",
            10.0,
        ),
        (
            {
                "left_price": Decimal("102"),
                "right_price": Decimal("102"),
                "handle_price": Decimal("95"),
                "atr": 1.0,
                "pretrend": "flat",
            },
            "pretrend",
            12.0,
        ),
        (
            {
                "bottom_price": Decimal("60"),
                "handle_price": Decimal("94"),
                "atr": 10.0,
            },
            "cup_geometry",
            19.0,
        ),
        (
            {
                "right_price": Decimal("98.5"),
                "bottom_price": Decimal("78"),
                "handle_price": Decimal("94"),
                "atr": 2.0,
            },
            "cup_geometry",
            23.0,
        ),
    ),
)
def test_exact_atr_thresholds_enter_their_inclusive_score_bucket(
    case_kwargs: dict[str, object],
    score_key: str,
    expected_score: float,
) -> None:
    """Exact 4/1.5/4/0.75 ATR boundaries stay on their inclusive side."""

    case = _with_exact_pivot_snapshot_prices(
        restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    )

    result = step_cup_handle(case.state, case.next_bar)

    assert result.active_overlay is not None
    assert result.active_overlay.score_breakdown[score_key] == expected_score


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


@pytest.mark.parametrize(
    "case_kwargs",
    (
        {
            "right_volume": 5 * 9_007_199_254_740_999,
            "baseline_volume": 5 * 9_007_199_254_740_999,
            "handle_volume": 4 * 9_007_199_254_740_999,
        },
        {
            "bottom_index": 50,
            "bottom_price": Decimal("70"),
            "right_volume": 13 * 1_125_899_906_832_627,
            "baseline_volume": 7 * 1_125_899_906_832_627,
            "handle_volume": 9 * 1_125_899_906_832_627,
        },
    ),
)
def test_large_integer_volume_boundaries_are_exactly_inclusive(
    case_kwargs: dict[str, object],
) -> None:
    """Integer ratios at exact 0.80/0.90 remain admissible above 2**53."""

    case = restored_cup_case(**case_kwargs)  # type: ignore[arg-type]
    result = step_cup_handle(case.state, case.next_bar)

    assert result.active_overlay is not None
    assert result.active_overlay.state == CupHandleState.READY
    assert tuple(marker.marker_type for marker in result.markers) == (
        NewowMarkerType.CUP_HANDLE_READY,
    )
    assert all(
        type(value) is float for value in result.active_overlay.volume_facts.values()
    )
    next_day = case.next_bar.trading_day + timedelta(days=1)
    continued = step_cup_handle(
        result.state,
        replace(
            case.next_bar,
            trading_day=next_day,
            bar_end=datetime.combine(next_day, datetime.min.time(), tzinfo=UTC),
            source_identity="fixture:large-volume-boundary:continued",
        ),
    )
    assert "NEWOW_CUP_STATE_INVALID" not in continued.diagnostics


@pytest.mark.parametrize(
    ("denominator", "handle_volume"),
    (
        (10 * 2**53, 8 * 2**53 + 1),
        (10**28 + 1, 8 * 10**27 + 1),
    ),
)
def test_large_integer_volume_one_unit_above_limit_never_emits_ready(
    denominator: int,
    handle_volume: int,
) -> None:
    """Float rounding must not admit a handle ratio one integer above 0.80."""

    case = restored_cup_case(
        bottom_index=50,
        bottom_price=Decimal("70"),
        right_volume=denominator,
        baseline_volume=denominator,
        handle_volume=handle_volume,
    )
    result = step_cup_handle(case.state, case.next_bar)

    assert "HANDLE_VOLUME_NOT_CONTRACTING" in result.diagnostics
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
        for marker in result.markers
    )


def test_unrepresentable_legal_volume_is_unavailable_without_exception() -> None:
    """A legal integer volume outside finite float range must fail closed."""

    huge = 10**1000
    case = restored_cup_case(
        right_volume=huge,
        baseline_volume=huge,
        handle_volume=huge // 2,
    )
    result = step_cup_handle(case.state, case.next_bar)

    assert "HANDLE_VOLUME_UNAVAILABLE" in result.diagnostics
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
        for marker in result.markers
    )
    next_day = case.next_bar.trading_day + timedelta(days=1)
    continued = step_cup_handle(
        result.state,
        replace(
            case.next_bar,
            trading_day=next_day,
            bar_end=datetime.combine(next_day, datetime.min.time(), tzinfo=UTC),
            volume=100,
            source_identity="fixture:unrepresentable-volume:continued",
        ),
    )
    assert "NEWOW_CUP_STATE_INVALID" not in continued.diagnostics
    assert not any(
        marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
        for marker in continued.markers
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


def test_long_lived_weakened_state_survives_bounded_history_rollover() -> None:
    """Authentic WEAKENED state remains valid after its BREAKOUT Bar ages out."""

    bars = breakout_then_weakened()
    state = calculate_cup_handle_series(bars)[-1].state
    prior = bars[-1]
    diagnostics: list[str] = []
    for offset in range(1, 231):
        day = prior.trading_day + timedelta(days=offset)
        bar = replace(
            prior,
            trading_day=day,
            bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            source_identity=f"fixture:long-weakened:{offset}",
        )
        result = step_cup_handle(state, bar)
        diagnostics.extend(result.diagnostics)
        state = result.state

    assert "NEWOW_CUP_STATE_INVALID" not in diagnostics
    assert state.active_candidate is not None
    assert state.active_candidate.state == CupHandleState.WEAKENED


def test_long_lived_weakened_retains_an_immutable_typed_ready_witness() -> None:
    """Aged READY facts need one bounded authority after source Bars are evicted."""

    bars = breakout_then_weakened()
    state = calculate_cup_handle_series(bars)[-1].state
    prior = bars[-1]
    for offset in range(1, 231):
        day = prior.trading_day + timedelta(days=offset)
        state = step_cup_handle(
            state,
            replace(
                prior,
                trading_day=day,
                bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                source_identity=f"fixture:ready-witness:{offset}",
            ),
        ).state

    active = state.active_candidate
    witness = getattr(state, "ready_witness", None)
    assert active is not None and active.state == CupHandleState.WEAKENED
    assert witness is not None
    assert witness.candidate_id == active.candidate_id
    assert witness.left_rim == active.left_rim
    assert witness.bottom == active.bottom
    assert witness.right_rim == active.right_rim
    assert witness.handle_extreme == active.handle_extreme
    assert witness.pivot_price == active.pivot_price
    assert witness.confirmed_at == active.confirmed_at
    assert witness.score == active.score
    assert dict(witness.score_breakdown) == dict(active.score_breakdown)
    assert dict(witness.volume_facts) == dict(active.volume_facts)
    assert witness.formula_version == active.formula_version
    with pytest.raises(FrozenInstanceError):
        witness.score = active.score + 1  # type: ignore[misc]


@pytest.mark.parametrize("field_name", ("score_breakdown", "volume_facts"))
def test_restored_ready_witness_rejects_mutable_fact_containers(
    field_name: str,
) -> None:
    """Frozen state cannot admit a list through an unchecked reconstructed field."""

    bars = breakout_then_weakened()
    state = calculate_cup_handle_series(bars)[-1].state
    witness = state.ready_witness
    assert witness is not None
    malformed_witness = replace(
        witness,
        **{field_name: list(getattr(witness, field_name))},
    )
    malformed = replace(state, ready_witness=malformed_witness)
    day = bars[-1].trading_day + timedelta(days=1)

    result = step_cup_handle(
        malformed,
        replace(
            bars[-1],
            trading_day=day,
            bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            source_identity=f"fixture:mutable-ready-witness:{field_name}",
        ),
    )

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.state == initial_cup_handle_state()


@pytest.mark.parametrize("corruption", ("pivot", "score", "volume"))
def test_aged_weakened_ready_facts_cannot_be_edited_after_source_eviction(
    corruption: str,
) -> None:
    """P, score, and volume facts must stay bound to the frozen READY witness."""

    bars = breakout_then_weakened()
    state = calculate_cup_handle_series(bars)[-1].state
    prior = bars[-1]
    last_bar = prior
    for offset in range(1, 231):
        day = prior.trading_day + timedelta(days=offset)
        last_bar = replace(
            prior,
            trading_day=day,
            bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            source_identity=f"fixture:ready-witness-corrupt:{offset}",
        )
        state = step_cup_handle(state, last_bar).state

    active = state.active_candidate
    assert active is not None and active.pivot_price is not None
    if corruption == "pivot":
        changed = replace(active, pivot_price=active.pivot_price + Decimal("1"))
    elif corruption == "score":
        breakdown = dict(active.score_breakdown)
        breakdown["pretrend"] = 12.0
        changed = replace(
            active,
            score=sum(breakdown.values()),
            score_breakdown=breakdown,
        )
    else:
        volumes = dict(active.volume_facts)
        for key in (
            "right_leg_median",
            "handle_median",
            "handle_baseline_median",
        ):
            volumes[key] = float(volumes[key]) * 2
        changed = replace(active, volume_facts=volumes)
    malformed = replace(state, active_candidate=changed)
    day = last_bar.trading_day + timedelta(days=1)

    result = step_cup_handle(
        malformed,
        replace(
            last_bar,
            trading_day=day,
            bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            source_identity=f"fixture:ready-witness-corrupt:{corruption}",
        ),
    )

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.state == initial_cup_handle_state()


def test_aged_weakened_state_rejects_a_shape_only_breakout_hash() -> None:
    """A 64-hex impostor cannot become a relation after its source Bar ages out."""

    bars = breakout_then_weakened()
    results = calculate_cup_handle_series(bars)
    breakout = next(
        marker
        for marker in _markers(results)
        if marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
    )
    state = results[-1].state
    prior = bars[-1]
    last_bar = prior
    for offset in range(1, 231):
        day = prior.trading_day + timedelta(days=offset)
        last_bar = replace(
            prior,
            trading_day=day,
            bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            source_identity=f"fixture:aged-weakened:{offset}",
        )
        state = step_cup_handle(state, last_bar).state

    assert state.active_candidate is not None
    assert state.active_candidate.state == CupHandleState.WEAKENED
    assert breakout.bar_end < state.eligible_bars[0].bar.bar_end
    facts = list(state.emitted_milestone_facts)
    facts[1] = replace(facts[1], marker_id="a" * 64)
    malformed = replace(
        state,
        emitted_milestones=(
            state.emitted_milestones[0],
            "a" * 64,
            state.emitted_milestones[2],
        ),
        emitted_milestone_facts=tuple(facts),
    )
    day = last_bar.trading_day + timedelta(days=1)
    next_bar = replace(
        last_bar,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        source_identity="fixture:aged-weakened:corrupt",
    )

    result = step_cup_handle(malformed, next_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def test_weakened_state_preserves_bounded_typed_milestone_facts() -> None:
    """The bounded state keeps enough immutable facts to authenticate old IDs."""

    bars = breakout_then_weakened()
    results = calculate_cup_handle_series(bars)
    state = results[-1].state
    markers = _markers(results)

    facts = state.emitted_milestone_facts
    assert len(facts) == 3
    assert tuple(fact.marker_id for fact in facts) == tuple(
        marker.marker_id for marker in markers
    )
    assert tuple(fact.marker_type for fact in facts) == (
        NewowMarkerType.CUP_HANDLE_READY,
        NewowMarkerType.CUP_HANDLE_BREAKOUT,
        NewowMarkerType.CUP_HANDLE_WEAKENED,
    )
    assert tuple(fact.bar_end for fact in facts) == tuple(
        marker.bar_end for marker in markers
    )
    by_time = {snapshot.bar.bar_end: snapshot for snapshot in state.eligible_bars}
    assert tuple(fact.eligible_index for fact in facts) == tuple(
        by_time[marker.bar_end].eligible_index for marker in markers
    )
    assert tuple(fact.source_identity for fact in facts) == tuple(
        by_time[marker.bar_end].bar.source_identity for marker in markers
    )


@pytest.mark.parametrize("corruption", ["eligible_index", "source_identity"])
def test_aged_milestone_fact_authenticates_its_original_bar_identity(
    corruption: str,
) -> None:
    """Aged milestone provenance cannot be changed independently of its proof."""

    bars = breakout_then_weakened()
    state = calculate_cup_handle_series(bars)[-1].state
    prior = bars[-1]
    last_bar = prior
    for offset in range(1, 231):
        day = prior.trading_day + timedelta(days=offset)
        last_bar = replace(
            prior,
            trading_day=day,
            bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            source_identity=f"fixture:aged-proof:{offset}",
        )
        state = step_cup_handle(state, last_bar).state

    facts = list(state.emitted_milestone_facts)
    breakout_fact = facts[1]
    facts[1] = (
        replace(breakout_fact, eligible_index=breakout_fact.eligible_index - 1)
        if corruption == "eligible_index"
        else replace(
            breakout_fact,
            source_identity=f"{breakout_fact.source_identity}:forged",
        )
    )
    malformed = replace(state, emitted_milestone_facts=tuple(facts))
    day = last_bar.trading_day + timedelta(days=1)
    next_bar = replace(
        last_bar,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        source_identity=f"fixture:aged-proof:corrupt:{corruption}",
    )

    result = step_cup_handle(malformed, next_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


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


def test_restored_tracker_rejects_an_active_extreme_from_the_previous_leg() -> None:
    """An UP leg cannot reuse a retained high from before its LOW confirmation."""

    bars = bullish_true_cup_handle()
    state = calculate_cup_handle_series(bars[:64])[-1].state
    tracker = state.pivot_tracker
    assert tracker.leg == "UP_LEG"
    assert tracker.last_pivot is not None
    assert tracker.last_pivot.kind == CupPivotKind.LOW
    by_index = {
        snapshot.eligible_index: snapshot for snapshot in state.eligible_bars
    }
    earlier_leg_extreme = by_index[tracker.last_pivot.pivot_index]
    assert earlier_leg_extreme.eligible_index < tracker.last_pivot.confirmed_index
    malformed = replace(
        state,
        pivot_tracker=replace(tracker, extreme_high=earlier_leg_extreme),
    )

    result = step_cup_handle(malformed, bars[64])

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.state == initial_cup_handle_state()


@pytest.mark.parametrize(
    ("pivot_position", "exact_close", "bar_high", "bar_low"),
    (
        (0, Decimal("98." + "0" * 27 + "1"), Decimal("99"), Decimal("97")),
        (1, Decimal("81." + "9" * 28), Decimal("83"), Decimal("81")),
    ),
)
def test_restored_pivot_reversal_below_threshold_is_rejected_exactly(
    pivot_position: int,
    exact_close: Decimal,
    bar_high: Decimal,
    bar_low: Decimal,
) -> None:
    """Decimal subtraction must not round a sub-threshold reversal up to two."""

    case = restored_cup_case()
    snapshots = list(case.state.eligible_bars)
    pivots = list(case.state.confirmed_pivots)
    pivot = pivots[pivot_position]
    snapshots[pivot.pivot_index] = replace(
        snapshots[pivot.pivot_index],
        atr=1.6,
    )
    confirmed = snapshots[pivot.confirmed_index]
    snapshots[pivot.confirmed_index] = replace(
        confirmed,
        bar=replace(
            confirmed.bar,
            open=exact_close,
            high=bar_high,
            low=bar_low,
            close=exact_close,
        ),
    )
    pivots[pivot_position] = replace(pivot, atr_at_pivot=1.6)
    malformed = replace(
        case.state,
        eligible_bars=tuple(snapshots),
        confirmed_pivots=tuple(pivots),
    )

    result = step_cup_handle(malformed, case.next_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def test_initial_pivot_tie_break_is_stable_and_high_first() -> None:
    """Equal normalized reversal distances and timestamps must deterministically choose HIGH."""

    extreme_bar = replace(
        _bar(0, 100),
        high=Decimal("115"),
        low=Decimal("85"),
    )
    extreme = CupBarSnapshot(extreme_bar, eligible_index=0, atr=10.0)
    history = (extreme,) + tuple(
        CupBarSnapshot(_bar(index, 100), eligible_index=index, atr=10.0)
        for index in range(1, 10)
    )
    state = replace(
        initial_cup_handle_state(),
        atr_state=WilderAtrState(
            count=15,
            atr=10.0,
            previous_close=Decimal("100"),
        ),
        pivot_tracker=CupPivotTrackerState(
            leg="SEEK_DIRECTION",
            extreme_high=extreme,
            extreme_low=extreme,
            eligible_index=9,
        ),
        eligible_bars=history,
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
        pivot_tracker=CupPivotTrackerState(
            leg="UP_LEG",
            extreme_high=snapshots[73],
            extreme_low=snapshots[70],
            last_pivot=later_low,
            eligible_index=73,
        ),
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


def test_malformed_restored_scalar_type_fails_closed_without_raising() -> None:
    """A damaged scalar field is an invalid state, not an internal exception."""

    case = restored_cup_case()
    malformed = replace(
        case.state,
        atr_state=replace(case.state.atr_state, count="bad"),  # type: ignore[arg-type]
    )

    result = step_cup_handle(malformed, case.next_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


@pytest.mark.parametrize(
    "corruption",
    ("duplicate_bar_end", "duplicate_trading_day", "eligible_not_bool"),
)
def test_restored_retained_bars_require_strict_causal_observable_facts(
    corruption: str,
) -> None:
    """Retained geometry cannot contain duplicate time or non-bool eligibility."""

    bars = bullish_true_cup_handle()
    state = calculate_cup_handle_series(bars[:30])[-1].state
    retained = list(state.eligible_bars)
    previous = retained[4]
    current = retained[5]
    if corruption == "duplicate_bar_end":
        changed_bar = replace(current.bar, bar_end=previous.bar.bar_end)
    elif corruption == "duplicate_trading_day":
        changed_bar = replace(current.bar, trading_day=previous.bar.trading_day)
    else:
        changed_bar = replace(current.bar, observation_eligible=1)  # type: ignore[arg-type]
    retained[5] = replace(current, bar=changed_bar)
    malformed = replace(state, eligible_bars=tuple(retained))

    result = step_cup_handle(malformed, bars[30])

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def test_restored_retained_window_rejects_negative_absolute_index() -> None:
    """A reconstructed retained window cannot restart its absolute index below zero."""

    state = calculate_cup_handle_series(tuple(_bar(index, 100) for index in range(14)))[
        -1
    ].state
    original = state.eligible_bars[0]
    shifted = replace(original, eligible_index=-1)
    malformed = replace(
        state,
        eligible_bars=(shifted,),
        pivot_tracker=replace(
            state.pivot_tracker,
            extreme_high=shifted,
            extreme_low=shifted,
            eligible_index=-1,
        ),
        eligible_started=False,
    )

    result = step_cup_handle(malformed, _bar(14, 100))

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def test_restored_atr_previous_close_matches_latest_retained_bar() -> None:
    """The next true range must start from the last observable retained close."""

    bars = bullish_true_cup_handle()
    state = calculate_cup_handle_series(bars[:30])[-1].state
    assert state.atr_state.previous_close is not None
    malformed = replace(
        state,
        atr_state=replace(
            state.atr_state,
            previous_close=state.atr_state.previous_close + Decimal("7"),
        ),
    )

    result = step_cup_handle(malformed, bars[30])

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


@pytest.mark.parametrize(
    "corruption",
    (
        "zero_atr",
        "nonfinite_atr",
        "ineligible",
        "foreign_identity",
        "future_time",
        "negative_index",
        "float_index",
    ),
)
def test_restored_out_of_window_tracker_extreme_requires_observable_facts(
    corruption: str,
) -> None:
    """An aged live extreme still carries validated ATR, identity, time, and index facts."""

    bars = tuple(_bar(index, 100) for index in range(251))
    state = calculate_cup_handle_series(bars[:250])[-1].state
    tracker = state.pivot_tracker
    extreme = tracker.extreme_high
    assert tracker.leg == "SEEK_DIRECTION"
    assert extreme is not None
    assert extreme.eligible_index < state.eligible_bars[0].eligible_index
    if corruption == "zero_atr":
        changed = replace(extreme, atr=0.0)
    elif corruption == "nonfinite_atr":
        changed = replace(extreme, atr=float("nan"))
    elif corruption == "ineligible":
        changed = replace(
            extreme,
            bar=replace(extreme.bar, observation_eligible=False),
        )
    elif corruption == "foreign_identity":
        changed = replace(
            extreme,
            bar=replace(
                extreme.bar,
                physical_contract="JM2701",
                segment_id="jm:JM2701:2026-01-01",
            ),
        )
    elif corruption == "future_time":
        future_day = date(2030, 1, 1)
        changed = replace(
            extreme,
            bar=replace(
                extreme.bar,
                trading_day=future_day,
                bar_end=datetime.combine(future_day, datetime.min.time(), tzinfo=UTC),
            ),
        )
    elif corruption == "negative_index":
        changed = replace(extreme, eligible_index=-999)
    else:
        changed = replace(extreme, eligible_index=float(extreme.eligible_index))  # type: ignore[arg-type]
    malformed = replace(
        state,
        pivot_tracker=replace(tracker, extreme_high=changed),
    )

    result = step_cup_handle(malformed, bars[250])

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


@pytest.mark.parametrize(
    "corruption",
    ("plain_kind", "future_confirmed_at", "same_index_different_time"),
)
def test_restored_aged_pivot_keeps_typed_and_causal_facts(
    corruption: str,
) -> None:
    """Eviction from the 220-Bar window cannot erase a confirmed Pivot's causal bounds."""

    bars = bullish_true_cup_handle()
    state = calculate_cup_handle_series(bars)[-1].state
    prior = bars[-1]
    last_bar = prior
    for offset in range(1, 231):
        day = prior.trading_day + timedelta(days=offset)
        last_bar = replace(
            prior,
            trading_day=day,
            bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            source_identity=f"fixture:aged-pivot:{offset}",
        )
        state = step_cup_handle(state, last_bar).state

    aged = state.confirmed_pivots[0]
    assert aged.pivot_index < state.eligible_bars[0].eligible_index
    malformed_pivot = object.__new__(CupPivot)
    values = {
        "kind": aged.kind,
        "price": aged.price,
        "pivot_at": aged.pivot_at,
        "confirmed_at": aged.confirmed_at,
        "pivot_index": aged.pivot_index,
        "confirmed_index": aged.confirmed_index,
        "atr_at_pivot": aged.atr_at_pivot,
    }
    if corruption == "plain_kind":
        values["kind"] = "HIGH"
    elif corruption == "future_confirmed_at":
        values["confirmed_at"] = last_bar.bar_end + timedelta(days=1)
    else:
        values["confirmed_index"] = aged.pivot_index
        values["confirmed_at"] = aged.pivot_at + timedelta(hours=1)
    for name, value in values.items():
        object.__setattr__(malformed_pivot, name, value)
    malformed = replace(
        state,
        confirmed_pivots=(malformed_pivot,) + state.confirmed_pivots[1:],
    )
    next_day = last_bar.trading_day + timedelta(days=1)
    next_bar = replace(
        last_bar,
        trading_day=next_day,
        bar_end=datetime.combine(next_day, datetime.min.time(), tzinfo=UTC),
        source_identity=f"fixture:aged-pivot:{corruption}:next",
    )

    result = step_cup_handle(malformed, next_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def test_nan_handle_volume_in_restored_ready_state_cannot_break_out() -> None:
    """A non-finite frozen volume fact must reset before lifecycle evaluation."""

    case = restored_cup_case()
    ready = step_cup_handle(case.state, case.next_bar)
    assert ready.state.active_candidate is not None
    volume_facts = dict(ready.state.active_candidate.volume_facts)
    volume_facts["handle_median"] = float("nan")
    malformed = replace(
        ready.state,
        active_candidate=replace(
            ready.state.active_candidate,
            volume_facts=volume_facts,
        ),
    )
    day = case.next_bar.trading_day + timedelta(days=1)
    breakout_bar = replace(
        case.next_bar,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=180,
        source_identity="fixture:invalid-restored-volume",
    )

    result = step_cup_handle(malformed, breakout_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


@pytest.mark.parametrize(
    "lifecycle",
    [CupHandleState.READY, CupHandleState.BREAKOUT, CupHandleState.WEAKENED],
)
@pytest.mark.parametrize("corruption", ["breakdown", "volume"])
def test_each_frozen_lifecycle_state_validates_exact_facts_on_restore(
    lifecycle: CupHandleState, corruption: str
) -> None:
    """READY-derived states share the same exact frozen-fact restore contract."""

    bars = (
        breakout_then_weakened()
        if lifecycle == CupHandleState.WEAKENED
        else bullish_true_cup_handle()
    )
    states = calculate_cup_handle_series(bars)
    restored = next(
        result.state
        for result in reversed(states)
        if result.state.active_candidate is not None
        and result.state.active_candidate.state == lifecycle
    )
    active = restored.active_candidate
    assert active is not None
    if corruption == "breakdown":
        breakdown = dict(active.score_breakdown)
        breakdown.pop("volume_structure")
        active = replace(active, score_breakdown=breakdown)
    else:
        volume_facts = dict(active.volume_facts)
        volume_facts["handle_median"] = float("nan")
        active = replace(active, volume_facts=volume_facts)
    malformed = replace(restored, active_candidate=active)
    prior = restored.eligible_bars[-1].bar
    day = prior.trading_day + timedelta(days=1)
    next_bar = replace(
        prior,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=Decimal("99"),
        high=Decimal("100"),
        low=Decimal("98"),
        close=Decimal("99"),
        volume=100,
        source_identity=f"fixture:invalid-{lifecycle.value.lower()}-{corruption}",
    )

    result = step_cup_handle(malformed, next_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def test_bogus_restored_ready_marker_cannot_become_a_breakout_relation() -> None:
    """Relations may reference only the deterministic READY milestone identity."""

    case = restored_cup_case()
    ready = step_cup_handle(case.state, case.next_bar)
    malformed = replace(ready.state, emitted_milestones=("bogus-ready-marker",))
    day = case.next_bar.trading_day + timedelta(days=1)
    breakout_bar = replace(
        case.next_bar,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101"),
        volume=180,
        source_identity="fixture:invalid-restored-marker",
    )

    result = step_cup_handle(malformed, breakout_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def test_restored_weakened_state_requires_the_actual_breakout_marker_id() -> None:
    """A hash for a non-breakout Bar is not an authentic BREAKOUT milestone."""

    bars = breakout_then_weakened()
    weak = calculate_cup_handle_series(bars)[-1]
    active = weak.state.active_candidate
    assert active is not None
    assert active.state == CupHandleState.WEAKENED
    fake_breakout_id = sha256(
        (
            f"{active.candidate_id}|{NewowMarkerType.CUP_HANDLE_BREAKOUT.value}|"
            f"{active.confirmed_at.isoformat()}"
        ).encode()
    ).hexdigest()
    malformed = replace(
        weak.state,
        emitted_milestones=(
            weak.state.emitted_milestones[0],
            fake_breakout_id,
            weak.state.emitted_milestones[2],
        ),
    )
    prior = bars[-1]
    day = prior.trading_day + timedelta(days=1)
    next_bar = replace(
        prior,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        source_identity="fixture:invalid-restored-breakout-id",
    )

    result = step_cup_handle(malformed, next_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def test_restored_weakened_milestone_requires_a_real_weakening_bar() -> None:
    """A deterministic ID is insufficient when its Bar did not satisfy WEAKENED."""

    bars = breakout_then_weakened()
    results = calculate_cup_handle_series(bars)
    weak = results[-1]
    active = weak.state.active_candidate
    assert active is not None
    breakout = next(
        marker
        for marker in _markers(results)
        if marker.marker_type == NewowMarkerType.CUP_HANDLE_BREAKOUT
    )
    fake_weakened_id = sha256(
        (
            f"{active.candidate_id}|{NewowMarkerType.CUP_HANDLE_WEAKENED.value}|"
            f"{breakout.bar_end.isoformat()}"
        ).encode()
    ).hexdigest()
    malformed = replace(
        weak.state,
        active_candidate=replace(active, state_changed_at=breakout.bar_end),
        emitted_milestones=(
            weak.state.emitted_milestones[0],
            weak.state.emitted_milestones[1],
            fake_weakened_id,
        ),
    )
    prior = bars[-1]
    day = prior.trading_day + timedelta(days=1)
    next_bar = replace(
        prior,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        source_identity="fixture:invalid-restored-weakened-id",
    )

    result = step_cup_handle(malformed, next_bar)

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


def test_plausible_but_wrong_restored_breakdown_fails_closed() -> None:
    """Valid-looking component values must still match the retained causal Bars."""

    bars = bullish_true_cup_handle()
    results = calculate_cup_handle_series(bars)
    ready_index = next(
        index
        for index, result in enumerate(results)
        if any(
            marker.marker_type == NewowMarkerType.CUP_HANDLE_READY
            for marker in result.markers
        )
    )
    ready_state = results[ready_index].state
    active = ready_state.active_candidate
    assert active is not None
    breakdown = dict(active.score_breakdown)
    breakdown["pretrend"] = 12.0
    breakdown["cup_geometry"] = 25.0
    malformed = replace(
        ready_state,
        active_candidate=replace(
            active,
            score=sum(breakdown.values()),
            score_breakdown=breakdown,
        ),
    )

    result = step_cup_handle(malformed, bars[ready_index + 1])

    assert result.diagnostics == ("NEWOW_CUP_STATE_INVALID",)
    assert result.markers == ()
    assert result.active_overlay is None
    assert result.state == initial_cup_handle_state()


@pytest.mark.parametrize(
    "corruption",
    [
        "breakdown_missing_key",
        "breakdown_extra_key",
        "breakdown_non_discrete",
        "score_mismatch",
        "score_tiny_mismatch",
        "volume_missing_key",
        "volume_ratio_mismatch",
        "volume_ratio_tiny_mismatch",
        "candidate_id_mismatch",
        "candidate_first_seen_before_anchor",
        "anchor_not_in_tracker_history",
        "anchor_confirmation_mismatch",
        "tracker_last_pivot_mismatch",
        "tracker_extreme_mismatch",
        "state_milestone_count_mismatch",
    ],
)
def test_each_restored_ready_state_invariant_fails_closed(corruption: str) -> None:
    """Every persisted READY invariant is checked before consuming the next Bar."""

    case = restored_cup_case()
    ready = step_cup_handle(case.state, case.next_bar)
    active = ready.state.active_candidate
    assert active is not None
    malformed = ready.state

    if corruption.startswith("breakdown_"):
        breakdown = dict(active.score_breakdown)
        if corruption == "breakdown_missing_key":
            breakdown.pop("handle_quality")
        elif corruption == "breakdown_extra_key":
            breakdown["other"] = 0.0
        else:
            breakdown["pretrend"] = 11.0
            breakdown["cup_geometry"] -= 1.0
        malformed = replace(
            malformed,
            active_candidate=replace(active, score_breakdown=breakdown),
        )
    elif corruption in {"score_mismatch", "score_tiny_mismatch"}:
        malformed = replace(
            malformed,
            active_candidate=replace(
                active,
                score=active.score
                + (5e-13 if corruption == "score_tiny_mismatch" else 1.0),
            ),
        )
    elif corruption.startswith("volume_"):
        volume_facts = dict(active.volume_facts)
        if corruption == "volume_missing_key":
            volume_facts.pop("handle_baseline_ratio")
        elif corruption == "volume_ratio_mismatch":
            volume_facts["handle_right_ratio"] = 0.1
        else:
            volume_facts["handle_right_ratio"] += 5e-13
        malformed = replace(
            malformed,
            active_candidate=replace(active, volume_facts=volume_facts),
        )
    elif corruption == "candidate_id_mismatch":
        malformed = replace(
            malformed,
            active_candidate=replace(active, candidate_id="bogus-candidate"),
        )
    elif corruption == "candidate_first_seen_before_anchor":
        malformed = replace(
            malformed,
            active_candidate=replace(
                active,
                first_seen_at=active.left_rim.pivot_at,
            ),
        )
    elif corruption == "anchor_not_in_tracker_history":
        pivots = list(malformed.confirmed_pivots)
        pivots[2] = replace(pivots[2], price=pivots[2].price + Decimal("1"))
        malformed = replace(malformed, confirmed_pivots=tuple(pivots))
    elif corruption == "anchor_confirmation_mismatch":
        right = replace(
            active.right_rim,
            confirmed_at=active.right_rim.confirmed_at + timedelta(hours=1),
        )
        pivots = tuple(
            right if pivot == active.right_rim else pivot
            for pivot in malformed.confirmed_pivots
        )
        malformed = replace(
            malformed,
            confirmed_pivots=pivots,
            active_candidate=replace(active, right_rim=right),
        )
    elif corruption == "tracker_last_pivot_mismatch":
        malformed = replace(
            malformed,
            pivot_tracker=replace(
                malformed.pivot_tracker,
                leg="DOWN_LEG",
                last_pivot=malformed.confirmed_pivots[-2],
            ),
        )
    elif corruption == "tracker_extreme_mismatch":
        extreme = malformed.pivot_tracker.extreme_high
        assert extreme is not None
        malformed = replace(
            malformed,
            pivot_tracker=replace(
                malformed.pivot_tracker,
                extreme_high=replace(extreme, atr=extreme.atr + 1.0),
            ),
        )
    else:
        malformed = replace(
            malformed,
            active_candidate=replace(
                active,
                state=CupHandleState.BREAKOUT,
                state_changed_at=case.next_bar.bar_end + timedelta(days=1),
            ),
        )

    day = case.next_bar.trading_day + timedelta(days=1)
    next_bar = replace(
        case.next_bar,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        source_identity=f"fixture:restored-invariant:{corruption}",
    )
    result = step_cup_handle(malformed, next_bar)

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
