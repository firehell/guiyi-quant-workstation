import pytest

from lms405_position_continuity import ALLOWED, EXCLUDED, UNKNOWN, continuity, protect_only


def leg(quantity, today, average):
    return {"quantity": quantity, "today_quantity": today, "opening_average": average}


@pytest.mark.parametrize(
    ("earlier", "later", "same_day", "bounds", "full_replacement"),
    (
        (leg(20, 0, "1720"), leg(20, 0, "1720.0"), True, [20, 20], EXCLUDED),
        (leg(20, 0, "850"), leg(20, 0, "856"), True, None, EXCLUDED),
        (leg(10, 8, "100"), leg(10, 7, "100"), True, None, EXCLUDED),
        (leg(20, 0, "945"), leg(20, 20, "944"), True, [0, 0], ALLOWED),
        (leg(40, 40, "5078.4"), leg(40, 0, "5078.4"), False, [0, 40], ALLOWED),
        (leg(40, 0, "5045"), leg(40, 40, "5117"), False, [0, 0], ALLOWED),
    ),
)
def test_retained_quantity_respects_age_and_cost_evidence(earlier, later, same_day, bounds, full_replacement):
    result = continuity(earlier, later, same_day=same_day)

    assert result["bounds"] == bounds
    assert result["inconsistent_same_scope"] == (bounds is None)
    assert result["full_replacement"] == full_replacement


def test_price_evidence_caps_retained_lots_without_inferring_full_replacement():
    result = continuity(leg(40, 40, "5117"), leg(40, 40, "5078.4"),
                        same_day=True, minimum_price_replacements=14)

    assert result["bounds"] == [0, 26]
    assert result["minimum_new_lots"] == 14
    assert result["unchanged"] == EXCLUDED
    assert result["full_replacement"] == ALLOWED


def test_exact_prior_session_close_changes_older_lot_lower_bound():
    earlier, later = leg(40, 40, "5078.4"), leg(40, 0, "5078.4")

    assert continuity(earlier, later, same_day=False)["bounds"] == [0, 40]
    bounded = continuity(earlier, later, same_day=False, at_prior_session_close=True)
    assert bounded["bounds"] == [40, 40]
    assert bounded["full_replacement"] == EXCLUDED

    conflicting = continuity(leg(40, 40, "10330"), leg(40, 0, "10337"),
                             same_day=False, at_prior_session_close=True)
    assert conflicting["bounds"] is None
    assert conflicting["inconsistent_same_scope"] is True


def test_missing_opposite_cannot_prove_protection_was_removed():
    earlier = leg(20, 0, "1720")
    retained = continuity(earlier, earlier, same_day=True)
    missing = continuity(leg(20, 20, "1490.1"), {}, same_day=True)
    sides = {"long": missing, "short": retained}

    assert missing["bounds"] is None
    assert protect_only("short", sides, {"short": earlier}) == UNKNOWN
    assert protect_only("short", sides, {"short": earlier, "long": leg(20, 20, "1490.1")}) == EXCLUDED
