from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from lms405_fresh_reprotection import annotated_geometry, leg_envelope
from lms405_right_side_study import US, at


def bar(start, end, prices):
    return Bar("FG2701", at(f"2026-10-23T{end}"), *map(Decimal, prices), start=at(f"2026-10-23T{start}"))


@pytest.mark.parametrize("mother_start,mother_end,pinbar,survives", [
    ("10:10", "10:15", False, False),
    ("10:25", "10:30", False, True),
    ("10:10", "10:15", True, True),
])
def test_reopening_can_reset_inside_bar_without_resetting_independent_pinbar(mother_start, mother_end, pinbar, survives):
    mother = bar(mother_start, mother_end, (829, 835, 820, 829))
    shape = bar("10:30", "10:35", (826, 827, 822, 827) if pinbar else (825, 830, 824, 829))
    same_close = bar("10:35", "10:36", (828, 833, 826, 832))
    series = {1: [same_close], 5: [mother, shape], 15: []}
    assert annotated_geometry(series, shape.start, same_close.end + US)["5m_to_1m"] == []
    (event,) = annotated_geometry(series, shape.start, same_close.end + 2 * US)["5m_to_1m"]
    assert event["ibar"] is True
    assert event["survives_resetting_ibar_at_session_gap"] is survives


def test_wholly_later_price_window_does_not_reuse_overlapping_minute():
    overlapping = bar("10:33", "10:34", (827, 829, 826, 828))
    later = bar("10:34", "10:35", (831, 833, 830, 832))
    leg = {"quantity": 20, "opening_average": "828.8"}
    bound = leg_envelope([overlapping, later], overlapping.start, later.end + 2 * US, leg, Decimal(1))
    assert bound["overlap_allowed"]["whole_leg_price_compatible"] is True
    assert bound["strictly_whole_after_known"]["whole_leg_price_compatible"] is False
    assert bound["strictly_whole_after_known"]["minimum_outside_later_window"] == 6
