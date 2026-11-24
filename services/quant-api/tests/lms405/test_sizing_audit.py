from decimal import Decimal

import pytest

from lms405_sizing_audit import common_target, normalized_leg, sizing_report


def test_opening_notional_and_one_tick_use_distinct_price_bases():
    leg = normalized_leg({"quantity": 20, "opening_average": "19470"}, {
        "multiplier": Decimal(10), "tick": Decimal(5),
    })
    assert leg["opening_notional"] == Decimal(3894000)
    assert leg["tick_cny"] == Decimal(1000)
    with pytest.raises(ValueError, match="DISPLAYED_QUANTITY_REQUIRED"):
        normalized_leg({"quantity": None, "opening_average": "19470"}, {})


def test_rounding_envelopes_allow_either_visible_leg_and_both_half_lot_endpoints():
    positions = {
        "A": {"long": {"quantity": 2, "unit": Decimal(10)}, "short": {"quantity": 2, "unit": Decimal(11)}},
        "B": {"long": {"quantity": 3, "unit": Decimal(11)}},
    }
    equal = common_target(positions, "unit")
    assert equal["required_minimum"] == equal["allowed_maximum"] == Decimal("27.5")
    assert equal["common_target_possible_with_envelopes"] is True
    positions["B"]["long"]["unit"] = Decimal(12)
    rejected = common_target(positions, "unit")
    assert rejected["common_target_possible_with_envelopes"] is False
    assert (rejected["minimum_contract"], rejected["maximum_contract"]) == ("B", "A")


def test_mixed_tables_cannot_create_repeated_size_evidence():
    specs = {
        "RU2701": {"multiplier": Decimal(10), "tick": Decimal(5)},
        "V2701": {"multiplier": Decimal(5), "tick": Decimal(1)},
    }
    table = {
        "source": "test-source", "table": "图2", "system": "4.0.5", "binding": "SYSTEM_COVER",
        "published_at": "2026-10-22T22:10:00+08:00", "source_url": "test", "image": {},
        "contracts": {
            "RU2701": {"legs": {"short": {"quantity": 20, "opening_average": "19470"}}},
            "V2701": {"legs": {"long": {"quantity": 40, "opening_average": "5078.4"}}},
        },
    }
    mixed = table | {"source": "test-mixed", "binding": "SYSTEM_POST_MIXED_ROWS"}
    report = sizing_report({"tables": [table, mixed]}, specs)
    assert len(report["displays"]) == 1
    assert report["by_contract"]["RU2701"]["stable_lots_across_visible_tables"] is None
    assert report["by_contract"]["FG2701"]["opening_notional_range"] is None
    assert report["account_equity"] is report["account_margin"] is report["original_sizing_formula"] is None
