from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from guiyi_quant.newow.models import (
    CupHandleDirection,
    CupHandleState,
    CupPivot,
    CupPivotKind,
    NewowCupHandleOverlay,
    NewowDailyBar,
    NewowMainMarker,
    NewowMarkerType,
    NewowTrendBandPoint,
    NewowTrendFrame,
    TrendBandState,
)
from guiyi_quant.newow.profile import NEWOW_TREND_D1_V1


_INTEGER_PROFILE_FIELDS = (
    "trend_weight_period",
    "trend_signal_period",
    "var4_lookback",
    "var4_smoothing_n",
    "var4_smoothing_m",
    "ma120_period",
    "ma120_slope_window",
    "cup_min_leg_bars",
    "cup_history_limit",
    "cup_max_confirmed_pivots",
    "cup_max_candidate_checks_per_step",
    "cup_atr_period",
    "cup_pretrend_min_bars",
    "cup_pretrend_max_bars",
    "cup_min_bars",
    "cup_max_bars",
    "cup_bottom_span_ready_min",
    "cup_midline_crossings_soft_max",
    "cup_midline_crossings_hard_max",
    "cup_handle_min_bars",
    "cup_handle_max_bars",
    "cup_forming_min_body_score",
    "cup_ready_min_score",
    "cup_breakout_min_score",
    "cup_ready_expiry_bars",
    "cup_post_breakout_archive_bars",
    "cup_recent_terminal_ids_limit",
)

_BOOL_RELATION_COMPANIONS: dict[str, dict[str, int]] = {
    "cup_pretrend_max_bars": {"cup_pretrend_min_bars": 1},
    "cup_max_bars": {"cup_min_bars": 1},
    "cup_midline_crossings_hard_max": {"cup_midline_crossings_soft_max": 1},
    "cup_handle_max_bars": {"cup_handle_min_bars": 1},
}


def valid_bar_kwargs() -> dict[str, object]:
    return {
        "product": "rb",
        "physical_contract": "RB2701",
        "segment_id": "rb:RB2701:2026-01-01",
        "trading_day": date(2026, 1, 5),
        "bar_end": datetime(2026, 1, 5, 7, tzinfo=UTC),
        "open": Decimal("3500"),
        "high": Decimal("3520"),
        "low": Decimal("3480"),
        "close": Decimal("3510"),
        "volume": 100,
        "open_interest": 200,
        "source_identity": "fixture:rb:RB2701:1d",
        "observation_eligible": True,
        "completed": True,
    }


def test_newow_profile_is_exact_and_immutable() -> None:
    """A changed V1 formula identity or mutable profile is a versioning bug."""

    profile = NEWOW_TREND_D1_V1

    assert profile.profile_id == "newow_trend_d1_v1"
    assert profile.frequency == "1d"
    assert profile.trend_band_formula == "newow_trend_band_cleanroom_v1"
    assert profile.escape_formula == "newow_escape_d123_v1"
    assert profile.cup_handle_formula == "newow_cup_handle_v1"
    with pytest.raises(FrozenInstanceError):
        profile.frequency = "60m"  # type: ignore[misc]


def test_cup_profile_and_pivot_contract_reject_invalid_values() -> None:
    """Invalid cup thresholds or a non-causal pivot would admit non-reproducible setups."""

    profile = NEWOW_TREND_D1_V1
    assert profile.cup_atr_period == 14
    assert profile.cup_pretrend_min_bars == 20
    assert profile.cup_pretrend_max_bars == 60
    assert profile.cup_depth_min_pct == 0.10
    assert profile.cup_depth_hard_max_pct == 0.50
    assert profile.cup_handle_min_bars == 5
    assert profile.cup_handle_max_bars == 15
    assert profile.cup_breakout_volume20_min_ratio == 1.20
    assert profile.cup_ready_expiry_bars == 20
    with pytest.raises(ValueError, match="NEWOW_PROFILE_INVALID"):
        replace(profile, cup_depth_min_pct=float("nan"))

    pivot_at = datetime(2026, 1, 5, 7, tzinfo=UTC)
    with pytest.raises(ValueError, match="NEWOW_CUP_PIVOT_INVALID"):
        CupPivot(
            kind=CupPivotKind.HIGH,
            price=Decimal("100"),
            pivot_at=pivot_at,
            confirmed_at=pivot_at,
            pivot_index=3,
            confirmed_index=2,
            atr_at_pivot=1.0,
        )


def test_cup_pivot_is_immutable_and_rejects_every_invalid_field_class() -> None:
    """Pivot facts must remain positive, finite, ordered, and immutable."""

    pivot_at = datetime(2026, 1, 5, 7, tzinfo=UTC)
    pivot = CupPivot(
        CupPivotKind.HIGH,
        Decimal("100"),
        pivot_at,
        pivot_at,
        3,
        3,
        2.0,
    )
    with pytest.raises(FrozenInstanceError):
        pivot.price = Decimal("101")  # type: ignore[misc]
    for changes in (
        {"price": Decimal("0")},
        {"atr_at_pivot": float("nan")},
        {"pivot_index": -1},
    ):
        with pytest.raises(ValueError, match="NEWOW_CUP_PIVOT_INVALID"):
            replace(pivot, **changes)


def test_cup_profile_freezes_every_slice_b_formula_value() -> None:
    """Changing any clean-room threshold without a new formula version is a versioning bug."""

    profile = NEWOW_TREND_D1_V1

    assert {
        "cup_atr_period": profile.cup_atr_period,
        "cup_pretrend_min_bars": profile.cup_pretrend_min_bars,
        "cup_pretrend_max_bars": profile.cup_pretrend_max_bars,
        "cup_pretrend_min_return": profile.cup_pretrend_min_return,
        "cup_pretrend_min_move_atr": profile.cup_pretrend_min_move_atr,
        "cup_min_bars": profile.cup_min_bars,
        "cup_max_bars": profile.cup_max_bars,
        "cup_depth_min_pct": profile.cup_depth_min_pct,
        "cup_depth_preferred_max_pct": profile.cup_depth_preferred_max_pct,
        "cup_depth_hard_max_pct": profile.cup_depth_hard_max_pct,
        "cup_depth_min_atr": profile.cup_depth_min_atr,
        "cup_rim_gap_max_pct": profile.cup_rim_gap_max_pct,
        "cup_rim_gap_max_atr": profile.cup_rim_gap_max_atr,
        "cup_bottom_zone_ratio": profile.cup_bottom_zone_ratio,
        "cup_bottom_span_ready_min": profile.cup_bottom_span_ready_min,
        "cup_leg_ratio_soft_min": profile.cup_leg_ratio_soft_min,
        "cup_leg_ratio_soft_max": profile.cup_leg_ratio_soft_max,
        "cup_leg_ratio_hard_min": profile.cup_leg_ratio_hard_min,
        "cup_leg_ratio_hard_max": profile.cup_leg_ratio_hard_max,
        "cup_midline_crossings_soft_max": profile.cup_midline_crossings_soft_max,
        "cup_midline_crossings_hard_max": profile.cup_midline_crossings_hard_max,
        "cup_handle_min_bars": profile.cup_handle_min_bars,
        "cup_handle_max_bars": profile.cup_handle_max_bars,
        "cup_handle_depth_max_pct": profile.cup_handle_depth_max_pct,
        "cup_handle_retrace_max_ratio": profile.cup_handle_retrace_max_ratio,
        "cup_handle_upper_half_ratio": profile.cup_handle_upper_half_ratio,
        "cup_handle_right_volume_max_ratio": profile.cup_handle_right_volume_max_ratio,
        "cup_handle_baseline_volume_max_ratio": profile.cup_handle_baseline_volume_max_ratio,
        "cup_breakout_buffer_atr": profile.cup_breakout_buffer_atr,
        "cup_breakout_volume20_min_ratio": profile.cup_breakout_volume20_min_ratio,
        "cup_breakout_handle_volume_min_ratio": profile.cup_breakout_handle_volume_min_ratio,
        "cup_forming_min_body_score": profile.cup_forming_min_body_score,
        "cup_ready_min_score": profile.cup_ready_min_score,
        "cup_breakout_min_score": profile.cup_breakout_min_score,
        "cup_ready_expiry_bars": profile.cup_ready_expiry_bars,
        "cup_post_breakout_archive_bars": profile.cup_post_breakout_archive_bars,
        "cup_recent_terminal_ids_limit": profile.cup_recent_terminal_ids_limit,
    } == {
        "cup_atr_period": 14,
        "cup_pretrend_min_bars": 20,
        "cup_pretrend_max_bars": 60,
        "cup_pretrend_min_return": 0.10,
        "cup_pretrend_min_move_atr": 4.0,
        "cup_min_bars": 25,
        "cup_max_bars": 90,
        "cup_depth_min_pct": 0.10,
        "cup_depth_preferred_max_pct": 0.35,
        "cup_depth_hard_max_pct": 0.50,
        "cup_depth_min_atr": 3.0,
        "cup_rim_gap_max_pct": 0.05,
        "cup_rim_gap_max_atr": 1.50,
        "cup_bottom_zone_ratio": 0.25,
        "cup_bottom_span_ready_min": 3,
        "cup_leg_ratio_soft_min": 0.50,
        "cup_leg_ratio_soft_max": 2.00,
        "cup_leg_ratio_hard_min": 1 / 3,
        "cup_leg_ratio_hard_max": 3.00,
        "cup_midline_crossings_soft_max": 3,
        "cup_midline_crossings_hard_max": 5,
        "cup_handle_min_bars": 5,
        "cup_handle_max_bars": 15,
        "cup_handle_depth_max_pct": 0.15,
        "cup_handle_retrace_max_ratio": 1 / 3,
        "cup_handle_upper_half_ratio": 0.50,
        "cup_handle_right_volume_max_ratio": 0.80,
        "cup_handle_baseline_volume_max_ratio": 0.90,
        "cup_breakout_buffer_atr": 0.10,
        "cup_breakout_volume20_min_ratio": 1.20,
        "cup_breakout_handle_volume_min_ratio": 1.50,
        "cup_forming_min_body_score": 45,
        "cup_ready_min_score": 80,
        "cup_breakout_min_score": 85,
        "cup_ready_expiry_bars": 20,
        "cup_post_breakout_archive_bars": 20,
        "cup_recent_terminal_ids_limit": 32,
    }
    assert {
        "cup_reversal_atr": profile.cup_reversal_atr,
        "cup_min_leg_bars": profile.cup_min_leg_bars,
        "cup_history_limit": profile.cup_history_limit,
        "cup_max_confirmed_pivots": profile.cup_max_confirmed_pivots,
        "cup_max_candidate_checks_per_step": profile.cup_max_candidate_checks_per_step,
    } == {
        "cup_reversal_atr": 1.25,
        "cup_min_leg_bars": 3,
        "cup_history_limit": 220,
        "cup_max_confirmed_pivots": 32,
        "cup_max_candidate_checks_per_step": 256,
    }


@pytest.mark.parametrize(
    ("changes"),
    [
        {"cup_pretrend_min_bars": 61},
        {"cup_depth_preferred_max_pct": 0.09},
        {"cup_leg_ratio_hard_min": 0.6},
        {"cup_midline_crossings_soft_max": 6},
        {"cup_handle_upper_half_ratio": 1.1},
        {"cup_handle_right_volume_max_ratio": 1.1},
        {"cup_breakout_buffer_atr": -0.1},
        {"cup_forming_min_body_score": 61},
        {"cup_ready_min_score": 95},
        {"cup_breakout_min_score": 101},
        {"cup_max_candidate_checks_per_step": 0},
    ],
)
def test_cup_profile_rejects_invalid_window_ratio_and_score_combinations(
    changes: dict[str, object],
) -> None:
    """Malformed parameters must fail before they can change candidate admission."""

    with pytest.raises(ValueError, match="NEWOW_PROFILE_INVALID"):
        replace(NEWOW_TREND_D1_V1, **changes)


def test_integer_profile_field_matrix_covers_every_declared_int() -> None:
    """A new integer control cannot silently escape strict construction checks."""

    assert tuple(
        field.name
        for field in fields(type(NEWOW_TREND_D1_V1))
        if field.type is int
    ) == _INTEGER_PROFILE_FIELDS


@pytest.mark.parametrize("field_name", _INTEGER_PROFILE_FIELDS)
def test_every_integer_profile_field_rejects_bool(field_name: str) -> None:
    """Python bool is numerically int-like but is never a valid window or cap."""

    changes: dict[str, object] = dict(
        _BOOL_RELATION_COMPANIONS.get(field_name, {})
    )
    changes[field_name] = True

    with pytest.raises(ValueError, match="NEWOW_PROFILE_INVALID"):
        replace(NEWOW_TREND_D1_V1, **changes)


@pytest.mark.parametrize("field_name", _INTEGER_PROFILE_FIELDS)
def test_every_integer_profile_field_rejects_fractional_value(
    field_name: str,
) -> None:
    """A numerically plausible fraction must not enter an integer state dimension."""

    fractional = float(getattr(NEWOW_TREND_D1_V1, field_name)) + 0.5

    with pytest.raises(ValueError, match="NEWOW_PROFILE_INVALID"):
        replace(NEWOW_TREND_D1_V1, **{field_name: fractional})


def test_cup_overlay_rejects_hard_failures_and_incomplete_ready_state() -> None:
    """Rejected geometry cannot masquerade as an active overlay or READY fact."""

    pivot_at = datetime(2026, 1, 5, 7, tzinfo=UTC)
    left = CupPivot(
        CupPivotKind.HIGH,
        Decimal("100"),
        pivot_at,
        pivot_at,
        20,
        23,
        2.0,
    )
    bottom = CupPivot(
        CupPivotKind.LOW,
        Decimal("80"),
        pivot_at,
        pivot_at,
        35,
        38,
        2.0,
    )
    right = CupPivot(
        CupPivotKind.HIGH,
        Decimal("100"),
        pivot_at,
        pivot_at,
        50,
        53,
        2.0,
    )
    base = {
        "candidate_id": "candidate-1",
        "direction": CupHandleDirection.BULLISH,
        "left_rim": left,
        "bottom": bottom,
        "right_rim": right,
        "handle_start_at": pivot_at,
        "handle_extreme": None,
        "pivot_price": None,
        "pivot_frozen_at": None,
        "confirmed_at": pivot_at,
        "first_seen_at": pivot_at,
        "state_changed_at": pivot_at,
        "score": 50.0,
        "score_breakdown": {
            "pretrend": 15.0,
            "cup_geometry": 20.0,
            "u_shape_purity": 15.0,
            "handle_quality": 0.0,
            "volume_structure": 0.0,
        },
        "formula_version": "newow_cup_handle_v1",
    }

    with pytest.raises(ValueError, match="NEWOW_CUP_OVERLAY_INVALID"):
        NewowCupHandleOverlay(
            state=CupHandleState.FORMING,
            hard_failures=("V_BOTTOM_SINGLE_BAR",),
            **base,
        )
    with pytest.raises(ValueError, match="NEWOW_CUP_OVERLAY_INVALID"):
        NewowCupHandleOverlay(state=CupHandleState.READY, **base)
    with pytest.raises(ValueError, match="NEWOW_CUP_OVERLAY_INVALID"):
        NewowCupHandleOverlay(state=CupHandleState.NONE, **base)
    with pytest.raises(ValueError, match="NEWOW_CUP_OVERLAY_INVALID"):
        NewowCupHandleOverlay(
            state=CupHandleState.FORMING,
            direction=CupHandleDirection.BEARISH,
            **{key: value for key, value in base.items() if key != "direction"},
        )
    with pytest.raises(ValueError, match="NEWOW_CUP_OVERLAY_INVALID"):
        NewowCupHandleOverlay(
            state=CupHandleState.FORMING,
            bottom=replace(bottom, pivot_index=51, confirmed_index=54),
            **{key: value for key, value in base.items() if key != "bottom"},
        )

    wrong_handle = CupPivot(
        CupPivotKind.HIGH,
        Decimal("95"),
        pivot_at,
        pivot_at,
        55,
        58,
        2.0,
    )
    with pytest.raises(ValueError, match="NEWOW_CUP_OVERLAY_INVALID"):
        NewowCupHandleOverlay(
            state=CupHandleState.READY,
            handle_extreme=wrong_handle,
            pivot_price=Decimal("99"),
            pivot_frozen_at=pivot_at,
            **{
                key: value
                for key, value in base.items()
                if key not in {"handle_extreme", "pivot_price", "pivot_frozen_at"}
            },
        )


def test_marker_trigger_facts_are_deeply_frozen() -> None:
    """Mutating caller-owned nested facts must not rewrite an emitted marker."""

    breakdown = {"pretrend": 15.0}
    facts: dict[str, object] = {"score_breakdown": breakdown, "anchors": ["L", "B"]}
    marker = NewowMainMarker(
        marker_id="marker-1",
        marker_type=NewowMarkerType.CUP_HANDLE_READY,
        bar_end=datetime(2026, 1, 5, 7, tzinfo=UTC),
        price=Decimal("100"),
        label="CUP_HANDLE_READY",
        color_token="cup_handle",
        priority=100,
        related_marker_ids=(),
        trigger_facts=facts,
        formula_version="newow_cup_handle_v1",
    )

    breakdown["pretrend"] = 0.0
    facts["anchors"] = []

    assert marker.trigger_facts["score_breakdown"] == {"pretrend": 15.0}
    assert marker.trigger_facts["anchors"] == ("L", "B")


def test_newow_daily_bar_requires_completed_d1_and_valid_ohlc() -> None:
    """An incomplete D1 bar must not enter the formal Newow calculation path."""

    with pytest.raises(ValueError, match="NEWOW_BAR_NOT_COMPLETED"):
        NewowDailyBar(
            product="rb",
            physical_contract="RB2701",
            segment_id="rb:RB2701:2026-01-01",
            trading_day=date(2026, 1, 5),
            bar_end=datetime(2026, 1, 5, 7, tzinfo=UTC),
            open=Decimal("3500"),
            high=Decimal("3520"),
            low=Decimal("3480"),
            close=Decimal("3510"),
            volume=100,
            open_interest=200,
            source_identity="fixture:rb:RB2701:1d",
            observation_eligible=True,
            completed=False,
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("series_kind", "continuous", "NEWOW_BAR_INVALID_SERIES_KIND"),
        ("frequency", "60m", "NEWOW_BAR_INVALID_FREQUENCY"),
    ],
)
def test_newow_daily_bar_requires_actual_dominant_completed_d1_identity(
    field: str, value: str, error: str
) -> None:
    """A non-actual-dominant or non-D1 input is outside the frozen V1 contract."""

    with pytest.raises(ValueError, match=error):
        NewowDailyBar(**(valid_bar_kwargs() | {field: value}))  # type: ignore[arg-type]


def test_newow_daily_bar_keeps_upstream_rank1_eligibility_flag() -> None:
    """The core preserves, but cannot independently derive, rank-1 eligibility."""

    bar = NewowDailyBar(
        product="rb",
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
        trading_day=date(2026, 1, 5),
        bar_end=datetime(2026, 1, 5, 7, tzinfo=UTC),
        open=Decimal("3500"),
        high=Decimal("3520"),
        low=Decimal("3480"),
        close=Decimal("3510"),
        volume=100,
        open_interest=200,
        source_identity="fixture:rb:RB2701:1d",
        observation_eligible=False,
        completed=True,
    )

    assert bar.observation_eligible is False


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("open", 3500, "NEWOW_BAR_PRICE_MUST_BE_DECIMAL"),
        ("bar_end", datetime(2026, 1, 5, 7), "NEWOW_BAR_NAIVE_TIMESTAMP"),
        ("product", "RB", "NEWOW_BAR_INVALID_PRODUCT"),
        ("physical_contract", "rb2701", "NEWOW_BAR_INVALID_PHYSICAL_CONTRACT"),
        ("source_identity", "", "NEWOW_BAR_EMPTY_IDENTITY"),
    ],
)
def test_newow_daily_bar_rejects_invalid_contract_input(
    field: str, value: object, error: str
) -> None:
    """Malformed market identities, timestamps, and prices cannot enter the core."""

    with pytest.raises(ValueError, match=error):
        NewowDailyBar(**(valid_bar_kwargs() | {field: value}))  # type: ignore[arg-type]


def test_immutable_output_sequences_copy_caller_lists() -> None:
    """Frozen output contracts cannot retain a caller's mutable lists."""

    related = ["related-1"]
    diagnostics = ["FORMING_OBSERVED"]
    marker = NewowMainMarker(
        marker_id="marker-1",
        marker_type=NewowMarkerType.BUILD,
        bar_end=datetime(2026, 1, 5, 7, tzinfo=UTC),
        price=Decimal("3510"),
        label="建仓",
        color_token="yellow",
        priority=1,
        related_marker_ids=related,  # type: ignore[arg-type]
    )
    pivot_at = datetime(2026, 1, 5, 7, tzinfo=UTC)
    pivot = CupPivot(
        kind=CupPivotKind.HIGH,
        price=Decimal("3510"),
        pivot_at=pivot_at,
        confirmed_at=pivot_at,
        pivot_index=0,
        confirmed_index=0,
        atr_at_pivot=1.0,
    )
    overlay = NewowCupHandleOverlay(
        candidate_id="candidate-1",
        direction=CupHandleDirection.BULLISH,
        state=CupHandleState.FORMING,
        left_rim=pivot,
        bottom=CupPivot(
            kind=CupPivotKind.LOW,
            price=Decimal("3480"),
            pivot_at=pivot_at,
            confirmed_at=pivot_at,
            pivot_index=1,
            confirmed_index=1,
            atr_at_pivot=1.0,
        ),
        right_rim=CupPivot(
            kind=CupPivotKind.HIGH,
            price=Decimal("3510"),
            pivot_at=pivot_at,
            confirmed_at=pivot_at,
            pivot_index=2,
            confirmed_index=2,
            atr_at_pivot=1.0,
        ),
        handle_start_at=pivot_at,
        handle_extreme=None,
        pivot_price=None,
        pivot_frozen_at=None,
        confirmed_at=pivot_at,
        first_seen_at=pivot_at,
        state_changed_at=pivot_at,
        score=45.0,
        score_breakdown={
            "pretrend": 15.0,
            "cup_geometry": 20.0,
            "u_shape_purity": 10.0,
            "handle_quality": 0.0,
            "volume_structure": 0.0,
        },
        hard_failures=(),
        diagnostics=diagnostics,  # type: ignore[arg-type]
        formula_version="newow_cup_handle_v1",
    )
    markers = [marker]
    frame = NewowTrendFrame(
        bar=NewowDailyBar(
            product="rb",
            physical_contract="RB2701",
            segment_id="rb:RB2701:2026-01-01",
            trading_day=date(2026, 1, 5),
            bar_end=datetime(2026, 1, 5, 7, tzinfo=UTC),
            open=Decimal("3500"),
            high=Decimal("3520"),
            low=Decimal("3480"),
            close=Decimal("3510"),
            volume=100,
            open_interest=200,
            source_identity="fixture:rb:RB2701:1d",
            observation_eligible=True,
            completed=True,
        ),
        trend_band=NewowTrendBandPoint(
            bar_end=datetime(2026, 1, 5, 7, tzinfo=UTC),
            b_value=None,
            c_value=None,
            state=TrendBandState.UNAVAILABLE,
            state_before=None,
        ),
        markers=markers,  # type: ignore[arg-type]
        cup_handle=overlay,
    )

    related.append("related-2")
    diagnostics.append("LATER_DIAGNOSTIC")
    markers.clear()

    assert marker.related_marker_ids == ("related-1",)
    assert overlay.hard_failures == ()
    assert overlay.diagnostics == ("FORMING_OBSERVED",)
    assert frame.markers == (marker,)


def test_newow_daily_bar_rejects_invalid_ohlc_envelope() -> None:
    """An OHLC envelope with close above high is invalid market input."""

    with pytest.raises(ValueError, match="NEWOW_BAR_INVALID_OHLC"):
        NewowDailyBar(
            product="rb",
            physical_contract="RB2701",
            segment_id="rb:RB2701:2026-01-01",
            trading_day=date(2026, 1, 5),
            bar_end=datetime(2026, 1, 5, 7, tzinfo=UTC),
            open=Decimal("3500"),
            high=Decimal("3520"),
            low=Decimal("3480"),
            close=Decimal("3530"),
            volume=100,
            open_interest=None,
            source_identity="fixture:rb:RB2701:1d",
            observation_eligible=True,
            completed=True,
        )


@pytest.mark.parametrize("price", [Decimal("0"), Decimal("-1")])
def test_newow_daily_bar_rejects_nonpositive_ohlc_prices(price: Decimal) -> None:
    """Zero or negative market prices must fail closed before any formula runs."""

    with pytest.raises(ValueError, match="NEWOW_BAR_NONPOSITIVE_PRICE"):
        NewowDailyBar(
            **(
                valid_bar_kwargs()
                | {"open": price, "high": price, "low": price, "close": price}
            )
        )  # type: ignore[arg-type]


def test_enum_values_are_stable() -> None:
    """Payload consumers rely on the documented enum values."""

    assert TrendBandState.YELLOW.value == "YELLOW"
    assert TrendBandState.BLUE.value == "BLUE"
    assert CupHandleState.READY.value == "READY"
    assert NewowMarkerType.CUP_HANDLE_EXPIRED.value == "CUP_HANDLE_EXPIRED"


def test_escape_marker_contract_codes_are_spec_stable() -> None:
    assert NewowMarkerType.ESCAPE_D1.value == "NEWOW_ESCAPE_D1"
    assert NewowMarkerType.ESCAPE_D2.value == "NEWOW_ESCAPE_D2"
    assert NewowMarkerType.ESCAPE_D3.value == "NEWOW_ESCAPE_D3"
