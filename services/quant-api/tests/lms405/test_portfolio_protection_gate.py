from dataclasses import replace
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from lms405_portfolio_protection_gate import advance_due, price_admission
from lms405_right_side_study import ONE, US, at


START = at("2026-07-10T09:00")
BAND = ProtectionBandUpdate("SA2609", "fixture", "PROTECTION", START - ONE, START - ONE,
                            "FIXTURE", "SHORT", Decimal(1079), Decimal(1087))


def minute(n, price):
    end = START + n * ONE
    price = Decimal(price)
    return Bar("SA2609", end, price, price, price, price, start=end - ONE)


def signal(n, close):
    return dict(shape_end=START + (n - 5) * ONE, available_at=START + n * ONE + US, close=Decimal(close))


def test_opening_beyond_is_a_directional_reach_without_range_contact():
    bars = [minute(n, 1089) for n in range(1, 12)]
    result = price_admission(bars, BAND, signal(11, 1089))
    assert result["status"] == "REACH_WITHOUT_RANGE_CONTACT"
    assert result["loose_due_at"] == bars[0].end + US
    assert result["ordinary_due_at"] is None


def test_contact_on_confirmation_minute_cannot_be_used_earlier():
    bars = [minute(n, 1088) for n in range(1, 11)]
    bars.append(minute(11, 1087))
    assert price_admission(bars, BAND, signal(11, 1087))["ordinary_due_at"] is None
    assert price_admission(bars, BAND, signal(12, 1087))["ordinary_due_at"] == bars[-1].end + US


def test_shared_edge_preserves_protection_scope_and_session_boundary():
    old_contact = minute(1, 1087)
    new_segment = [minute(n, 1089) for n in range(20, 31)]
    assert price_admission([old_contact, *new_segment], BAND, signal(30, 1089))["first_contact_at"] is None
    new_segment[1] = minute(21, 1087)
    at_shared_edge = price_admission(new_segment, BAND, signal(30, 1087))
    assert at_shared_edge["ordinary_due_at"] == new_segment[1].end + US
    strict_m_side = price_admission(new_segment, BAND, signal(30, 1088))
    assert strict_m_side["ordinary_due_at"] is None


def test_contact_before_current_position_cannot_support_its_protection():
    bars = [minute(1, 1087), *[minute(n, 1088) for n in range(2, 12)]]
    result = price_admission(bars, BAND, signal(12, 1087), position_since=bars[0].end + US)
    assert result["first_contact_at"] is None
    assert result["ordinary_due_at"] is None


def test_advance_requires_explicit_plan_and_a_complete_confirming_bar_before_the_zone():
    authorized = replace(BAND, contract="FG2701", revision="A5356884629782554")
    bar = replace(minute(20, 1078), contract="FG2701")
    before = {"status": "NO_PRIOR_DIRECTIONAL_REACH"}
    assert advance_due(bar, authorized, before) == bar.end
    assert advance_due(bar, replace(authorized, revision="unknown"), before) is None
    assert advance_due(replace(bar, high=Decimal(1079)), authorized, before) is None
    assert advance_due(bar, authorized, {"status": "REACH_WITHOUT_RANGE_CONTACT"}) is None


def test_advance_rejects_a_foreign_confirmation_bar():
    authorized = replace(BAND, contract="FG2701", revision="A5356884629782554")
    with pytest.raises(ValueError, match="PROTECTION_ADVANCE_CONFIRMATION_BAR_MISMATCH"):
        advance_due(minute(20, 1078), authorized, {"status": "NO_PRIOR_DIRECTIONAL_REACH"})
