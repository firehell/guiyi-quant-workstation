from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_pvc_recovery_carry import CONTRACT, inspect_day, label_candidate
from lms405_right_side_study import ONE, US, at


def test_pvc_previous_reach_and_current_close_are_independent_of_shape_confirmation():
    start = at("2026-04-28T13:45")
    event = dict(shape_end=start + ONE, shape_minutes=1, modes=["NEAR", "FAR"])
    same_day = dict(first_far_touch=start - 2 * ONE, first_far_close=start - ONE, second_far_close=start)
    conditions = label_candidate(
        event, prior_touch=at("2026-04-22T21:01") + US, prior_close=None, same_day=same_day,
        current_run={"fresh_crossing_known_at": start - ONE}, second_run={"fresh_crossing_known_at": start},
    )
    assert conditions["prior_day_touch_allows_near"] is True
    assert conditions["prior_day_close_allows_near"] is False
    assert conditions["same_day_touch_allows_near"] is True
    assert conditions["new_shape_after_current_first_far_cross"] is True
    assert conditions["new_shape_after_both_far_closes"] is False
    assert conditions["new_shape_after_both_with_current_second_far_cross"] is False

    same_day["second_far_close"] = start - ONE
    after_return = label_candidate(
        event, prior_touch=None, prior_close=None, same_day=same_day,
        current_run={"fresh_crossing_known_at": start - ONE}, second_run={"fresh_crossing_known_at": None},
    )
    assert after_return["new_shape_after_both_far_closes"] is True
    assert after_return["new_shape_after_both_with_current_second_far_cross"] is False


def test_pvc_recovery_window_excludes_far_reach_before_start():
    start = at("2026-04-28T09:01")
    earlier = Bar(CONTRACT, start, *map(Decimal, (5255, 5265, 5250, 5264)), start=start - ONE)
    later = Bar(CONTRACT, start + ONE, *map(Decimal, (5258, 5262, 5252, 5262)), start=start)
    report = inspect_day({1: [earlier, later], 5: [], 15: []}, start=start, cut=later.end + 2 * US,
                         prior_touch=None, prior_close=None)
    assert report["minute_count"] == 1
    assert report["same_trading_day"]["first_far_touch"] == later.end + US
    assert report["same_trading_day"]["first_far_close"] is None
