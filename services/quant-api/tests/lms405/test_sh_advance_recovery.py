from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import ONE, US, at
from lms405_sh_advance_recovery import next_prices


def test_post_lock_level_progress_separates_touch_close_and_bar_availability():
    start = at("2026-10-27T21:25")

    def bar(end, low, close, step=ONE, *, high=1491):
        return Bar("SH2701", end, Decimal(high), Decimal(high), Decimal(low), Decimal(close), start=end - step)

    minutes = [
        bar(start + ONE, 1489, 1489),
        bar(start + 2 * ONE, 1489, 1489, high=1489),
        bar(start + 3 * ONE, 1490, 1490),
    ]
    fives = [bar(start + 5 * ONE, 1489, 1489, 5 * ONE), bar(start + 10 * ONE, 1489, 1489, 5 * ONE)]
    result = next_prices({1: minutes, 5: fives}, Decimal(1490), start + 2 * US, start + 10 * ONE + US)
    assert result == {
        "first_directional_reach_minute": start + 2 * ONE,
        "first_range_contains_level_minute": start + 3 * ONE,
        "first_strict_minute_close": start + 2 * ONE,
        "first_strict_five_minute_close": None,
    }
