from dataclasses import FrozenInstanceError, replace
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
    failures = ["SHALLOW_CUP"]
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
        hard_failures=failures,  # type: ignore[arg-type]
        diagnostics=(),
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
    failures.append("V_BOTTOM")
    markers.clear()

    assert marker.related_marker_ids == ("related-1",)
    assert overlay.hard_failures == ("SHALLOW_CUP",)
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


def test_escape_marker_contract_codes_are_spec_stable() -> None:
    assert NewowMarkerType.ESCAPE_D1.value == "NEWOW_ESCAPE_D1"
    assert NewowMarkerType.ESCAPE_D2.value == "NEWOW_ESCAPE_D2"
    assert NewowMarkerType.ESCAPE_D3.value == "NEWOW_ESCAPE_D3"
