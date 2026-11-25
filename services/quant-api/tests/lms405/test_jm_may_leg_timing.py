from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_jm_may_leg_timing import CONTRACT, LONG_AVERAGE, LOTS, TICK, forecast_bound
from lms405_protection_lot_timing import displayed_tick_totals
from lms405_right_side_study import ONE, at


def test_rounded_average_separates_first_overlapping_minute_from_full_later_minutes():
    boundary = at("2026-05-20T13:52")
    earlier = Decimal("1196.5")
    overlapping = Decimal("1205.5")
    later = Decimal("1211")
    prices = (earlier, overlapping, later)
    bars = [
        Bar(CONTRACT, boundary + i * ONE, price, price, price, price, start=boundary + (i - 1) * ONE)
        for i, price in enumerate(prices)
    ]
    totals = displayed_tick_totals(LONG_AVERAGE, LOTS, TICK)
    assert list(totals) == [48240]
    generous = forecast_bound(bars, boundary, totals, include_overlap=True)
    strict = forecast_bound(bars, boundary, totals, include_overlap=False)
    assert generous["all_lots_possible_after"] is True
    assert generous["first_post_window_minute_end"] == "2026-05-20T13:53+08:00"
    assert strict["first_post_window_minute_end"] == "2026-05-20T13:54+08:00"
    assert strict["prior_lots_min"] == 7
    assert strict["all_lots_possible_after"] is False
