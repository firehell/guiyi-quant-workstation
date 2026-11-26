from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_iron_midday_protection import low_price_counts, phase_prices
from lms405_protection_lot_timing import displayed_tick_totals
from lms405_right_side_study import ONE, at


def bar(start, low, high):
    low, high = Decimal(low), Decimal(high)
    return Bar("I2701", start + ONE, low, high, low, high, start=start)


def test_alternatives_keep_each_origin_possible_and_enforce_total_in_joint_allocation():
    start, morning, split = (at(clock) for clock in (
        "2026-10-26T21:00", "2026-10-27T09:00", "2026-10-27T10:14",
    ))
    tick, lots = Decimal(1), 3
    totals = displayed_tick_totals(Decimal("105.0"), lots, tick)
    rows = [bar(start, 100, 106), bar(morning, 102, 105), bar(split, 104, 111)]
    result = phase_prices(rows, split=split, trading_open=morning, tick=tick, lots=lots, totals=totals)
    assert result["compatible_single_phase"] == [True, True, True]
    assert all(sum(counts) == lots for counts in result["feasible_counts"])
    assert result["post_morning_lots"] == [0, 1, 2, 3]


def test_band_floor_can_force_a_majority_of_lots_to_lower_prices():
    start = at("2026-10-27T11:00")
    tick, lots = Decimal("0.5"), 16
    totals = displayed_tick_totals(Decimal("663.34"), lots, tick)
    rows = [bar(start, 660, "673.5"), bar(start + ONE, "664.5", 667)]
    assert min(low_price_counts(rows, Decimal(667), tick=tick, lots=lots, totals=totals)) == 9
    assert min(low_price_counts(rows, Decimal("664.5"), tick=tick, lots=lots, totals=totals)) == 5
