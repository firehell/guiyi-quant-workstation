from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, latest_whole_leg_start
from lms405_right_side_study import at


def test_displayed_tick_totals_use_precision_of_each_source():
    assert list(displayed_tick_totals(Decimal("663.34"), 16, Decimal("0.5"))) == [21227]
    assert list(displayed_tick_totals(Decimal("1490.1"), 20, Decimal("1"))) == [29801, 29802]


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
