from itertools import product

import pytest
from lms405_portfolio_retention_prices import feasible_retention


@pytest.mark.parametrize("same_day,today_count", [(True, 3), (False, 1), (False, None)])
def test_retention_bounds_match_integer_tick_envelope_enumeration(same_day, today_count):
    old_prices, interim_prices, today_prices = range(8, 12), range(7, 10), range(10, 13)
    before, after = 2, 3
    old_sums, new_sums = range(17, 21), range(27, 33)
    expected = []
    for retained in range(min(before, after) + 1):
        additions = after - retained
        middle = 0 if same_day or today_count is None else additions - today_count
        if middle < 0:
            continue
        fill_ranges = [interim_prices] * middle + [today_prices] * (additions - middle)
        if any(sum(old) in old_sums and sum(old[:retained]) + sum(added) in new_sums
               for old in product(old_prices, repeat=before) for added in product(*fill_ranges)):
            expected.append(retained)
    assert feasible_retention(
        before, {"quantity": after, "today_quantity": today_count}, [0, min(before, after)], old_sums, new_sums,
        (8, 11), (7, 9), (10, 12), same_day=same_day,
    ) == expected


def test_two_displayed_averages_can_require_partial_replacement():
    assert feasible_retention(
        2, {"quantity": 2, "today_quantity": None}, [0, 2],
        range(200, 201), range(202, 203), (90, 110), None, (110, 110), same_day=True,
    ) == [1]


def test_old_replacement_cannot_use_only_next_trading_day_prices():
    assert feasible_retention(
        3, {"quantity": 3, "today_quantity": 1}, [0, 2],
        range(300, 301), range(300, 301), (100, 100), None, (100, 100), same_day=False,
    ) == [2]
