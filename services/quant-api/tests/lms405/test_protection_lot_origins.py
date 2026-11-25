from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_protection_lot_origins import allocations, phase_prices
from lms405_right_side_study import ONE, at


def test_joint_origin_counts_respect_both_displayed_sums():
    inputs = (2, (10, 14), [(8, 8), (12, 12), (15, 15)], range(24, 25), range(27, 28))
    assert allocations(*inputs) == [(0, 0, 1, 1), (1, 0, 0, 1)]
    assert allocations(*inputs, require_no_retention=True) == [(0, 0, 1, 1)]
    assert allocations(2, None, [None, None, (14, 14)], None, range(27, 28)) == []


def test_price_buckets_use_each_minute_once_and_keep_overlap_separate():
    start = at("2026-10-23T10:33")
    minutes = [Bar("FG2701", start + i * ONE, *(Decimal(826 + i),) * 4,
                   start=start + (i - 1) * ONE) for i in range(1, 5)]
    gates = (start + ONE, start + 2 * ONE)
    assert phase_prices(minutes, gates, "EVENT_MINUTE_ALLOWED_AFTER", Decimal(1)) == [
        None, (827, 827), (828, 830),
    ]
    assert phase_prices(minutes, gates, "ONLY_COMPLETE_MINUTES_AFTER", Decimal(1)) == [
        (827, 828), (829, 829), (830, 830),
    ]
