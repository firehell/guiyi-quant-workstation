from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_fg_exit_study import fg_window
from lms405_right_side_study import ONE, US, at


def test_reentry_reference_excludes_a_bar_at_its_availability_boundary():
    start = at("2026-09-14T21:00")
    first = Bar("FG2701", start + ONE, *map(Decimal, (929, 930, 925, 925)), start=start)
    second = Bar("FG2701", start + 2 * ONE, *map(Decimal, (925, 926, 923, 924)), start=start + ONE)
    series = {1: [first, second], 5: [], 15: []}

    prefix = fg_window(series, start, second.end + US, "SHORT", after_report=True)
    later = fg_window(series, start, second.end + 2 * US, "SHORT", after_report=True)

    assert prefix["reference_low_925"]["first_range_reaches_direction"] == first.end
    assert prefix["reference_low_925"]["first_close_strict_beyond"] is None
    assert later["reference_low_925"]["first_close_strict_beyond"] == second.end
    assert later["reference_low_925"]["first_same_segment_new_close_cross"] == second.end
    assert later["first_overlap"] is None
    assert later["low_first_at"] == second.end
