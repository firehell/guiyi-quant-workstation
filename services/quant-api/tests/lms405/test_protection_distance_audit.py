from datetime import datetime
from decimal import Decimal

import pytest

from lms405_protection_distance_audit import band_distance, included_target, row_for_band


def test_profit_protection_and_already_touched_regions_are_not_adverse_budget_inputs():
    locked_gain = band_distance(Decimal("682.5"), ("667", "671"), 16, Decimal(100))
    assert locked_gain["signed_short_leg_cost"] == [Decimal(-24800), Decimal(-18400)]
    assert locked_gain["target_envelope"] is None
    partially_crossed = band_distance(Decimal("835"), ("829", "836"), 20, Decimal(20))
    assert partially_crossed["signed_short_leg_cost"] == [Decimal(-2400), Decimal(400)]
    assert partially_crossed["relation"] == "REFERENCE_IN_OR_ON_BAND"
    assert partially_crossed["target_envelope"] is None


def test_common_target_only_uses_comparable_protection_information():
    iron = band_distance(Decimal("666.5"), ("667", "671"), 16, Decimal(100))
    rubber = band_distance(Decimal("19390"), ("19530", "19680"), 20, Decimal(10))
    rows = {
        "iron": iron | {"comparison_status": "RESEARCH_COMPARABLE"},
        "rubber": rubber | {"comparison_status": "RESEARCH_COMPARABLE"},
        "stale": {"comparison_status": "EARLIER_BAND_EFFECTIVITY_UNKNOWN"},
        "mismatch": {"comparison_status": "QUOTE_ANCHOR_NOT_VERIFIED"},
    }
    assert included_target(rows) == {
        "contracts": ["iron", "rubber"], "required_minimum": Decimal(27300),
        "allowed_maximum": Decimal(7425), "common_budget_possible": False,
    }
    del rows["rubber"]
    assert included_target(rows)["common_budget_possible"] is None


def test_band_published_in_quote_anchor_minute_cannot_enter_comparison():
    band = {"source": "plan", "band": ["667", "671"]}
    at = datetime.fromisoformat("2026-10-27T11:30:00+08:00")
    with pytest.raises(ValueError, match="PROTECTION_BAND_NOT_PRIOR_TO_REFERENCE"):
        row_for_band({}, "I2701", band, Decimal("666.5"), {}, {"plan": {"published_at": at.isoformat()}}, at)
