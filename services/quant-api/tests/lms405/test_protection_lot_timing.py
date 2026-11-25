from datetime import timedelta
from decimal import Decimal
from itertools import product
from types import SimpleNamespace

from lms405_oi_leg_intent import lot_bound
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, latest_whole_leg_start
from lms405_right_side_study import ONE, US, at
from lms405_sh_protection_replacement import compatible_counts


def test_displayed_tick_totals_use_precision_of_each_source():
    assert list(displayed_tick_totals(Decimal("663.34"), 16, Decimal("0.5"))) == [21227]
    assert list(displayed_tick_totals(Decimal("1490.1"), 20, Decimal("1"))) == [29801, 29802]
    assert list(displayed_tick_totals(Decimal("10224.0"), 40, Decimal("1"))) == [408958, 408959, 408960, 408961]


def test_envelopes_require_some_lots_before_disputed_confirmation():
    totals = range(404, 405)
    assert earlier_lot_counts((98, 100), (103, 105), 4, totals) == [2, 3]
    assert earlier_lot_counts((98, 100), None, 4, totals) == []
    assert earlier_lot_counts((98, 105), None, 4, totals) == [4]
    assert earlier_lot_counts(None, (98, 105), 4, totals) == [0]


def test_latest_whole_leg_start_combines_disjoint_minutes_as_an_optimistic_bound():
    end = at("2026-10-27T11:30")
    bars = [
        SimpleNamespace(bar_end=end - timedelta(minutes=1), low=Decimal("98"), high=Decimal("100")),
        SimpleNamespace(bar_end=end, low=Decimal("103"), high=Decimal("105")),
    ]
    assert latest_whole_leg_start(bars, Decimal("1"), 4, range(404, 405)) == "2026-10-27T11:28+08:00"
    assert latest_whole_leg_start(bars[1:], Decimal("1"), 4, range(404, 405)) is None


def test_retained_lot_joint_bounds_match_exhaustive_small_tick_ranges():
    lots, old, afternoon, night = 3, (98, 101), (97, 99), (103, 104)
    old_total, new_total = range(298, 300), range(302, 304)
    compatible = set()
    for before in product(range(old[0], old[1] + 1), repeat=lots):
        if sum(before) not in old_total:
            continue
        for retained in range(lots + 1):
            for day_lots in range(lots - retained + 1):
                night_lots = lots - retained - day_lots
                for day in product(range(afternoon[0], afternoon[1] + 1), repeat=day_lots):
                    for evening in product(range(night[0], night[1] + 1), repeat=night_lots):
                        if sum(before[:retained] + day + evening) in new_total:
                            compatible.add((retained, day_lots, night_lots))
    observed = compatible_counts(lots, old_total, new_total, old, afternoon, night)
    assert observed == [list(row) for row in sorted(compatible)]
    assert compatible_counts(lots, old_total, new_total, old, None, night) == [
        list(row) for row in sorted(compatible) if row[1] == 0
    ]


def test_gate_comparison_exposes_the_effect_of_the_minute_straddling_availability():
    gate_end = at("2026-10-27T21:01")
    bars = [SimpleNamespace(start=gate_end + (index - 1) * ONE, end=gate_end + index * ONE,
                           low=Decimal(price), high=Decimal(price))
            for index, price in enumerate((98, 102, 110))]
    args = dict(lots=2, tick=Decimal(1), totals=range(200, 201))
    optimistic = lot_bound(bars, gate_end, **args)
    strict = lot_bound(bars, gate_end + US, **args)
    assert optimistic["minimum_prior_lots"] == 1
    assert strict["minimum_prior_lots"] == 2
    assert strict["first_later_completed_minute_end"] == "2026-10-27T21:03+08:00"
