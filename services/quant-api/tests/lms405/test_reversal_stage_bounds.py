from decimal import Decimal
from types import SimpleNamespace

from lms405_reversal_stage_bounds import assess_window
from lms405_right_side_study import ONE, at


def test_price_after_capture_does_not_enter_displayed_leg_bounds():
    start = at("2026-10-23T09:00")
    prices = [("824", "826", "826"), ("826", "830", "830"), ("829", "831", "831"),
              ("833", "838", "837"), ("834", "842", "840")]
    bars = [
        SimpleNamespace(bar_end=start + n * ONE, low=Decimal(low), high=Decimal(high), close=Decimal(close))
        for n, (low, high, close) in enumerate(prices, start=1)
    ]
    window = assess_window(bars, start, start + 4 * ONE, (829, 836), (842, 844),
                           tick=Decimal("1"), lots=20, average=Decimal("828.8"))
    gates = window["gates"]
    assert gates["protection_first_overlap"]["lot_bounds"]["entire_leg_possible_after"]
    assert gates["close_above_protection_near"]["lot_bounds"]["minimum_earlier_lots"] == 1
    assert gates["close_above_protection_near"]["only_full_minutes_after_close"]["minimum_earlier_lots"] == 10
    assert not gates["m_near_reached"]["seen_by_capture"]
    assert gates["m_near_reached"]["lot_bounds"]["minimum_earlier_lots"] == 20
    assert gates["m_near_reached"]["lot_bounds"]["after_bounds_ticks"] is None
