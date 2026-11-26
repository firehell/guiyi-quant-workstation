from datetime import UTC, datetime, timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_protection_quantity_stages import compatible_allocations, quantity_result

START = datetime(2026, 10, 22, 13, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
US = timedelta(microseconds=1)


def test_allocates_all_three_phases_against_one_opening_price_sum():
    amounts = compatible_allocations(4, range(22, 23), ((4, 4), (5, 5), (7, 7)))
    assert amounts == [(0, 3, 1), (2, 0, 2)]
    assert compatible_allocations(4, range(28, 29), (None, None, (7, 7))) == [(0, 0, 4)]
    assert compatible_allocations(4, range(27, 28), (None, None, (7, 7))) == []


def test_overlap_can_be_allocated_but_strict_phase_excludes_boundary_minutes():
    bars = [
        Bar("FG2701", START + i * MINUTE, *([Decimal(price)] * 4), start=START + (i - 1) * MINUTE)
        for i, price in enumerate((7, 8, 10, 12, 99), 1)
    ]
    known = bars[1].end + US
    quote = bars[3].end
    wide = quantity_result(bars, bars[0], known, quote, Decimal(1), 2, range(18, 19), overlap=True)
    strict = quantity_result(bars, bars[0], known, quote, Decimal(1), 2, range(18, 19), overlap=False)
    assert wide["tick_bounds_before_touch_middle_after_confirmation"] == ((7, 7), (7, 10), (10, 12))
    assert strict["tick_bounds_before_touch_middle_after_confirmation"] == (None, (8, 8), (12, 12))
    assert wide["minimum_before_confirmation"] == 1
    assert wide["whole_after_touch"] and not wide["whole_after_confirmation"]
    assert strict["minimum_before_confirmation"] is None
