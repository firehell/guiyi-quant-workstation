from lms405_fg_sa_case import at
from lms405_jm_exit_attribution import retained_exit_boundaries


def test_removing_the_price_boundary_leaves_independent_fixed_plan_exits():
    checks = {reason: at(f"27T{time}") for reason, time in (
        ("RISK_INVALID", "09:45"), ("REGIME_INVALID", "09:50"),
        ("PLAN_EXPIRED", "10:40"), ("RANGE_TARGET", "11:30"),
    )}
    rows = retained_exit_boundaries(checks)
    assert [row["first_reason"] for row in rows] == list(checks)
    assert [row["available_at"] for row in rows] == list(checks.values())
    assert rows[1]["omit_only_for_diagnosis"] == ("RISK_INVALID",)
