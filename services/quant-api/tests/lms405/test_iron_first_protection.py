from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_iron_first_protection import by_knowledge, fixed_quote_span, support
from lms405_protection_lot_timing import displayed_tick_totals
from lms405_right_side_study import ONE, US, at


def test_open_quote_cannot_use_the_completed_first_minute_to_authorize_itself():
    start = at("2026-10-22T21:00")
    first = Bar("I2701", start + ONE, *map(Decimal, ("669", "670", "667", "667")), start=start)
    second = Bar("I2701", first.end + ONE, *map(Decimal, ("669", "671", "668", "670")), start=first.end)
    tick, lots = Decimal("0.5"), 16
    totals = displayed_tick_totals(Decimal("668.75"), lots, tick)
    args = dict(tick=tick, lots=lots, totals=totals)

    by_open = {first.end, second.end}
    assert not support([first, second], first.end, by_open, include_quote=False, **args)["entire_leg_allowed"]
    assert support([first, second], first.end, by_open, include_quote=True, **args)["entire_leg_allowed"]
    known = first.end + US
    assert by_knowledge([first, second], known, overlapping=False) == set()
    assert by_knowledge([first, second], known, overlapping=True) == {second.end}
    assert not support([first, second], first.end, {second.end}, include_quote=True, **args)["entire_leg_allowed"]


def test_quote_span_can_use_other_rows_before_and_after_the_fixed_anchor():
    start = at("2026-10-22T21:00")
    others = [[start + i * ONE for i in offsets] for offsets in ((1, 8), (5, 9), (8,))]
    assert fixed_quote_span(start + ONE, others) == 7
    assert fixed_quote_span(start + 6 * ONE, others) == 3
    assert fixed_quote_span(start + 8 * ONE, others) == 1
