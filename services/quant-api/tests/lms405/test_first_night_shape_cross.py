from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_first_night_shape_cross import breaches, price_bounds
from lms405_protection_lot_timing import displayed_tick_totals
from lms405_right_side_study import FIVE, ONE, US, at


def candle(start, step, prices):
    return Bar("SH2701", start + step, *map(Decimal, prices), start=start)


def test_wick_only_breach_is_known_after_child_completion_without_waiting_for_next_parent():
    start = at("2026-10-22T21:00")
    shape_end = start + 2 * FIVE
    mother = candle(start, FIVE, (110, 119, 100, 110))
    inside = candle(start + FIVE, FIVE, (110, 114, 105, 110))
    equal = candle(shape_end, ONE, (110, 114, 108, 113))
    through = candle(shape_end + ONE, ONE, (113, 115, 112, 114))
    assert breaches([mother, inside], [equal, through], start, through.end + US) == []
    (observed,) = breaches([mother, inside], [equal, through], start, through.end + 2 * US)
    assert observed["boundary"] == equal.high == through.close
    assert observed["breach_end"] == through.end
    assert observed["actual_cross_at"] is None
    assert observed["within_minute_upward_cross_proven"]
    assert breaches([mother, inside], [through], start, through.end + 2 * US) == []


def test_price_bounds_can_require_lots_after_breach_and_in_quote_minute():
    start = at("2026-10-22T21:00")
    rows = [candle(start + i * ONE, ONE, prices) for i, prices in enumerate((
        (100, 100, 100, 100), (100, 101, 100, 100), (102, 104, 102, 102), (103, 112, 103, 109),
    ))]
    result = price_bounds(
        rows, {"breach_end": rows[1].end, "observation_known_at": rows[1].end + US,
               "shape_ohlc": tuple(map(Decimal, (104, 105, 103, 104)))},
        rows[-1].end, tick=Decimal(1), lots=10, totals=displayed_tick_totals(Decimal("105.0"), 10, Decimal(1)),
    )
    assert result["minimum_lots_before_breach_minute"] == 0
    assert result["minimum_lots_after_breach_minute"] == 4
    assert result["minimum_lots_in_quote_minute"] == 2
    assert result["first_later_close_below_shape_low"] == rows[2].end
    assert result["minimum_lots_after_invalidation_minute"] == 2
