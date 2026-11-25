from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_first_night_early_protection import after_price_paths, minimum_outside_directional_near, touched
from lms405_protection_lot_timing import displayed_tick_totals
from lms405_right_side_study import ONE, at


def test_intraminute_touch_and_completed_touch_have_different_price_envelopes():
    start = at("2026-10-22T21:00")
    bars = [Bar("FG2701", start + (i + 1) * ONE, *map(Decimal, prices), start=start + i * ONE)
            for i, prices in enumerate(((827, 829, 827, 828), (829, 830, 829, 830), (829, 832, 829, 831)))]
    tick = Decimal(1)
    totals = displayed_tick_totals(Decimal("828.0"), 20, tick)
    gate = touched(bars, (Decimal(829), Decimal(836)))
    assert gate == bars[0]
    outcome = after_price_paths(bars, gate, tick=tick, lots=20, totals=totals)
    assert outcome["minimum_before_touch_minute"] == 0
    assert outcome["after_completed_touch_minute"] == {"overlap_allowed": 10, "fully_after": 10}
    same_minute = after_price_paths(bars[:1], gate, tick=tick, lots=20, totals=totals)
    assert same_minute["quote_and_touch_share_minute"]
    assert same_minute["after_completed_touch_minute"] is None
    assert minimum_outside_directional_near(bars, Decimal(829), tick=tick, lots=20, totals=totals) == 10


def test_an_unseen_touch_is_unknown_at_earlier_quote():
    start = at("2026-10-22T21:00")
    price = Decimal(828)
    early = Bar("FG2701", start + ONE, price, price, price, price, start=start)
    price = Decimal(829)
    later = Bar("FG2701", start + 2 * ONE, price, price, price, price, start=early.end)
    totals = displayed_tick_totals(Decimal("828.0"), 20, Decimal(1))
    assert after_price_paths([early], later, tick=Decimal(1), lots=20, totals=totals) is None
