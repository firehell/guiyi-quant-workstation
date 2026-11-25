from lms405_pta_pause_scopes import NO_NEW_PLAN, REFERENCE_ONLY, SHORT_PAUSE, assess_snapshot
from lms405_right_side_study import US, at


def test_short_pause_only_blocks_short_participation_of_bound_version_after_disclosure():
    known = at("2026-06-18T17:13")
    scope = dict(known_at=known, source="june-disclosure")
    before = assess_snapshot("TA2609", "5.0", SHORT_PAUSE, as_of=known - US, **scope)
    equal = assess_snapshot("TA2609", "5.0", SHORT_PAUSE, as_of=known, **scope)
    named = assess_snapshot("TA2609", "5.0", SHORT_PAUSE, as_of=known + US, **scope)
    unknown_identity = assess_snapshot("TA2609", "4.0.5", SHORT_PAUSE, as_of=known + US, **scope)
    retrial = "reenter_short_under_separate_permission"
    assert before == equal
    assert all(row["status"] == "INDETERMINATE" and row["sources"] == [] for row in equal.values())
    assert all(row["sources"] == ["june-disclosure"] for row in named.values())
    assert named[retrial]["failed"] == ["short_participation_unpaused"]
    assert named["open_short_under_separate_permission"]["failed"] == ["short_participation_unpaused"]
    assert unknown_identity[retrial]["status"] == "INDETERMINATE"
    assert named["exit_existing_short"]["status"] == named["open_long_under_separate_permission"]["status"] == "INDETERMINATE"
    assert all(row["after"] is None for results in (equal, named, unknown_identity) for row in results.values())


def test_public_plan_absence_blocks_only_routes_that_require_the_new_public_plan():
    known = at("2026-10-23T19:29")
    scope = dict(known_at=known, as_of=known + US, source="public-disclosure")
    no_plan = assess_snapshot("TA2701", "4.0.5", NO_NEW_PLAN, **scope)
    reference = assess_snapshot("TA2701", "4.0.5", REFERENCE_ONLY, **scope)
    assert no_plan["open_long_with_new_public_plan"]["failed"] == ["public_new_plan_available"]
    assert no_plan["open_short_with_new_public_plan"]["failed"] == ["public_new_plan_available"]
    for name in ("protect_existing_long", "exit_existing_long", "reenter_short_under_separate_permission",
                 "open_short_under_separate_permission"):
        assert no_plan[name]["status"] == "INDETERMINATE"
    assert all(row["status"] == "INDETERMINATE" and row["after"] is None for row in reference.values())
