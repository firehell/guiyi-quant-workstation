from decimal import Decimal
from types import SimpleNamespace

from lms405_protection_lot_timing import displayed_tick_totals
from lms405_right_side_study import ONE, at
from lms405_rubber_leg_transition import displayed_mark, position_change


def test_rubber_rounded_opening_and_float_identify_tick_price():
    assert displayed_mark(Decimal("19674.8"), Decimal("115.3"), Decimal("23050"),
                          lots=20, tick=Decimal("5"), multiplier=Decimal("10")) == (
        Decimal("19674.75"), Decimal("19790"),
    )


def test_rubber_replacement_bounds_allow_pre_m_prices_without_assuming_full_reversal():
    first = at("2026-10-22T22:09")
    bar_ranges = [("19270", "19630"), ("19540", "19775"), ("19780", "19850")]
    bars = [
        SimpleNamespace(bar_end=first + n * ONE, low=Decimal(low), high=Decimal(high))
        for n, (low, high) in enumerate(bar_ranges)
    ]
    tick, lots = Decimal("5"), 20
    bounds = position_change(
        bars, bars[0].bar_end, bars[-1].bar_end, bars[-1].bar_end, tick=tick, lots=lots,
        old_totals=displayed_tick_totals(Decimal("19505.0"), lots, tick),
        new_totals=displayed_tick_totals(Decimal("19674.8"), lots, tick),
    )
    assert bounds["minimum_replaced_lots"] == 6
    assert bounds["minimum_lots_originating_before_m"] == 5
    assert bounds["all_new_before_m_possible"]
