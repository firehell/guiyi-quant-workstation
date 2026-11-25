from decimal import Decimal

import pytest

from lms405_sizing_audit import common_target, compare_visible_quantities, normalized_leg, sizing_report


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


def test_cross_month_rescale_uses_only_observed_rows_and_all_later_quantities():
    october = {
        "OI2701": {"displayed_quantities": [40]},
        "SH2701": {"displayed_quantities": [20]},
        "TA2701": {"displayed_quantities": [34]},
    }
    august = {"OI2609": 40, "SH2609": 16, "JM2609": 20}
    report = compare_visible_quantities(october, august)
    assert report["no_comparable_august_row"] == ["TA"]
    assert report["lower_scale_by_contract"]["SH2701"] == Decimal("1.21875")
    assert report["upper_scale_by_contract"]["OI2701"] == Decimal("1.0125")
    assert report["fixed_lots_all_displayed_possible"] is False
    assert report["common_quantity_scale_possible"] is False
    assert report["account_and_strategy_continuity"] is None

    october["SH2701"]["displayed_quantities"] = [16, 20]
    mixed_sizes = compare_visible_quantities(october, august)
    assert mixed_sizes["comparable"]["SH"]["same_lots_observed"] is False
    assert mixed_sizes["common_quantity_scale_possible"] is False
    assert compare_visible_quantities(october, {})["common_quantity_scale_possible"] is None
