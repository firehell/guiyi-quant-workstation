from lms405_exit_position_scope import leg, scenario
from lms405_right_side_study import at


def test_missing_leg_and_complete_scope_hypothesis_stay_distinct():
    pvc, support = "V2701/long", "I2701/short"
    tables = {
        "old": {pvc: leg(40, 0, "5045"), support: leg(16, 0, "682.50")},
        "gap": {support: leg(16, 0, "682.5")},
        "new": {pvc: leg(40, 40, "5117")},
    }
    anchors = {"old": [at("2026-10-26T10:01")], "gap": [at("2026-10-26T11:30")],
               "new": [at("2026-10-26T21:10")]}
    result = scenario(tables, anchors, key=pvc, before="old", gap="gap", after="new")

    assert result["observed_gap"] is result["exact_close_lots"] is result["account_scope_verified"] is None
    assert result["shared_unchanged_quantity_and_open_average"] == [support]
    hypothesis = result["same_scope_hypothesis"]
    assert hypothesis["missing_leg_quantity"] == 0
    assert hypothesis["minimum_prior_lots_closed"] == hypothesis["minimum_later_lots_reopened"] == 40
    assert hypothesis["ordered_quote_bounds_verified"]
    assert hypothesis["ordered_reopen_quote_bounds_verified"]

    anchors["gap"] = []
    unordered = scenario(tables, anchors, key=pvc, before="old", gap="gap", after="new")["same_scope_hypothesis"]
    assert unordered["earliest_before_quote"] is unordered["latest_gap_quote"] is None
    assert not unordered["ordered_quote_bounds_verified"]
