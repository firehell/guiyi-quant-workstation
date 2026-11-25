from decimal import Decimal
from itertools import combinations, product

from lms405_v_exit_study import displayed_sum, replacement_bounds


def test_display_rounding_keeps_lower_tie_and_excludes_upper_tie():
    assert displayed_sum(Decimal("5078.4"), 40) == (203134, 203137)


def test_replacement_bounds_match_explicit_small_lot_paths():
    quantity = 3
    old_average = Decimal("5.7")
    new_average = Decimal("5.0")
    old_bounds = displayed_sum(old_average, quantity)
    new_bounds = displayed_sum(new_average, quantity)
    old_prices, new_prices = (4, 8), (5, 7)
    paths = set()
    for original in product(range(4, 9), repeat=quantity):
        if not old_bounds[0] <= sum(original) <= old_bounds[1]:
            continue
        for kept in range(quantity + 1):
            for survivors in combinations(original, kept):
                for additions in product(range(5, 8), repeat=quantity - kept):
                    if new_bounds[0] <= sum(survivors + additions) <= new_bounds[1]:
                        paths.add(quantity - kept)

    result = replacement_bounds(
        tuple(map(Decimal, old_prices)), tuple(map(Decimal, new_prices)),
        quantity=quantity, old_average=old_average, new_average=new_average,
    )

    assert result["possible_replaced_lots_within_envelopes"] == sorted(paths) == [1, 2, 3]
