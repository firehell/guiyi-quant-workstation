from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from guiyi_quant.newow.models import (
    CupHandleState,
    NewowDailyBar,
    TrendBandState,
)
from guiyi_quant.newow.profile import NEWOW_TREND_D1_V1


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


def test_enum_values_are_stable() -> None:
    """Payload consumers rely on the documented enum values."""

    assert TrendBandState.YELLOW.value == "YELLOW"
    assert TrendBandState.BLUE.value == "BLUE"
    assert CupHandleState.READY.value == "READY"
