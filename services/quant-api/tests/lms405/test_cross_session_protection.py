from dataclasses import replace
from decimal import Decimal

from lms405_cross_session_protection import compare, leg, transition
from lms405_right_side_study import ONE, US, at


def test_old_and_new_protection_with_equal_size_have_different_trading_day_identity():
    start = at("2026-10-27T21:00")
    last = start + 2 * ONE
    seed = {"long": leg(2, 2, "100"), "short": leg(2, 0, "120")}
    visible = {"long": leg(2, 2, "100"), "short": leg(2, 0, "120")}
    release = transition("SH2701", "UNLOCK_SHORT", 2, start - ONE, "release")
    lock = transition("SH2701", "LOCK", 2, start + ONE, "lock")
    retained, = compare("SH2701", "long", seed, start, visible, [last], [], {})["checks"]
    assert retained["model"]["long"] == {"quantity": Decimal(2), "today_quantity": Decimal(0)}
    assert retained["fields"]["long"] == {"quantity": True, "today": False, "opening_average": True}
    before, after = compare("SH2701", "long", seed, start, visible, [lock.effective_at, last],
                            [release, lock], {last: True})["checks"]
    assert before["model"]["long"]["quantity"] == 0
    assert before["status"] == "INCOMPATIBLE"
    assert after["status"] == "COMPATIBLE_UNDER_ASSUMPTIONS"
    assert after["model"]["long"]["today_quantity"] == 2


def test_unlisted_leg_cannot_distinguish_release_from_carry():
    start = at("2026-10-27T21:00")
    seed = {"long": leg(2, None, "100"), "short": leg(2, 0, "120")}
    only_short = {"short": seed["short"]}
    release = transition("I2701", "UNLOCK_SHORT", 2, start + US, "release")
    for events in ([], [release]):
        result, = compare("I2701", "long", seed, start, only_short, [start + ONE], events, {})["checks"]
        assert result["status"] == "INDETERMINATE"
        assert result["fields"]["long"] == {"quantity": None, "today": None, "opening_average": None}
    confirmed_zero = only_short | {"long": leg(0, 0)}
    for events, status in (([], "INCOMPATIBLE"), ([release], "COMPATIBLE_UNDER_ASSUMPTIONS")):
        result, = compare("I2701", "long", seed, start, confirmed_zero, [start + ONE], events, {})["checks"]
        assert result["status"] == status


def test_late_disclosure_cannot_relabel_the_unchanged_seed_as_today():
    start = at("2026-10-27T21:00")
    seed = {"long": leg(2, 2, "100"), "short": leg(2, 0, "120")}
    after = start + 2 * ONE
    lock = transition("SH2701", "LOCK", 2, start + ONE, "late")
    late = replace(lock, known_at=lock.effective_at)
    result, = compare("SH2701", "long", seed, start, seed, [after], [late], {after: True})["checks"]
    assert result["model"]["long"]["today_quantity"] == 0
    assert result["status"] == "INCOMPATIBLE"
