from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import at
from lms405_sh_recovery_exposure import price_path


def test_short_reference_path_distinguishes_wick_equal_close_and_break():
    def minute(start, end, high, low, close):
        return Bar("SH2701", at(f"2026-10-27T{end}"), *map(Decimal, (1490, high, low, close)),
                   start=at(f"2026-10-27T{start}"))

    wick = minute("14:09", "14:10", 1494, 1488, 1491)
    equal = minute("14:10", "14:11", 1496, 1489, 1493)
    broken = minute("14:11", "14:12", 1495, 1487, 1494)
    levels = {"old_level": Decimal(1493), "already_below_market": Decimal(1480)}
    assert price_path([], Decimal(1490), levels) is None
    report = price_path([wick, equal, broken], Decimal(1490), levels)
    assert report["max_short_adverse_points"] == Decimal(6)
    assert report["max_short_favorable_points"] == Decimal(3)
    assert report["max_rebound_from_earlier_minute_low"] == dict(
        points=Decimal(8), low_bar_end=wick.end, high_bar_end=equal.end,
    )
    assert report["upper_level_observations"]["old_level"] == dict(
        first_high_at_or_above_end=wick.end, first_range_contains_end=wick.end,
        first_close_at_or_above_end=equal.end, first_strict_close_end=broken.end,
    )
    assert report["upper_level_observations"]["already_below_market"]["first_range_contains_end"] is None
