from itertools import product

import pytest

from lms405_oi_report_scope import retained_origins


@pytest.mark.parametrize("later_prices", [(100, 101), None])
def test_origin_bounds_reuse_the_same_retained_opening_prices(later_prices):
    phases = ((98, 101), None, (104, 106))
    original_average_sum = range(304, 306)
    later_average_sum = range(305, 307)
    original_prices = [(phase, price) for phase, bounds in enumerate(phases) if bounds is not None
                       for price in range(bounds[0], bounds[1] + 1)]
    new_prices = range(later_prices[0], later_prices[1] + 1) if later_prices is not None else ()
    expected = set()
    for batch in product(original_prices, repeat=3):
        if sum(price for _, price in batch) not in original_average_sum:
            continue
        for keep in product((False, True), repeat=3):
            still_open = [row for row, survives in zip(batch, keep, strict=True) if survives]
            closed = [row for row, survives in zip(batch, keep, strict=True) if not survives]
            old_ticks = sum(price for _, price in still_open)
            if any(old_ticks + sum(new) in later_average_sum for new in product(new_prices, repeat=len(closed))):
                expected.add(tuple(tuple(sum(phase == k for phase, _ in bucket) for k in range(3))
                                   for bucket in (still_open, closed)))
    assert expected
    assert set(retained_origins(3, phases, later_prices, original_average_sum, later_average_sum)) == expected
