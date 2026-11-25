from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_glass_soda_august_wait import lowest_return
from lms405_right_side_study import ONE, at


def test_opening_below_reference_does_not_create_a_new_crossing():
    edge = Decimal(870)

    def minute(start, close):
        price = Decimal(close)
        return Bar("FG2609", start + ONE, price, price, price, price, start=start)

    night = at("2026-08-03T21:00")
    day = at("2026-08-04T09:00")
    rows = [minute(night, 869), minute(night + ONE, 870),
            minute(night + 2 * ONE, 880), minute(day, 869), minute(day + ONE, 869),
            minute(day + 2 * ONE, 870), minute(day + 3 * ONE, 869), minute(day + 4 * ONE, 871)]
    result = lowest_return(rows, edge)
    assert result["first_strict_close_below_end"] == night + ONE
    assert result["first_strict_return_above_end"] == night + 3 * ONE
    assert result["first_new_contiguous_cross_below_end"] == day + 4 * ONE
    assert result["first_return_above_after_new_cross_end"] == day + 5 * ONE
    assert result["strict_close_below_count"] == 4
    assert result["longest_consecutive_minutes_closed_below"] == 2
