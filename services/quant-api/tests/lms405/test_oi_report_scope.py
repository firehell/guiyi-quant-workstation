from decimal import Decimal
from types import SimpleNamespace

import pytest

from lms405_oi_report_scope import opening_contribution
from lms405_right_side_study import ONE, at


def test_same_minute_contribution_bound_excludes_future_prices():
    quote = at("2026-10-26T22:04")
    event = SimpleNamespace(bar_end=at("2026-10-26T21:06"), low=Decimal(10283), high=Decimal(10296))
    previous = SimpleNamespace(bar_end=event.bar_end - ONE, low=Decimal(10330), high=Decimal(10346))
    future = SimpleNamespace(bar_end=quote + ONE, low=Decimal(10390), high=Decimal(10400))

    case = opening_contribution([previous, event, future], event, quote, lots=40, average=Decimal("10340.0"))
    assert case["compatible_event_minute_lots"] == [0, 1, 2, 3, 4]
    assert case["minimum_elsewhere"] == 36
    assert case["earlier_tick_bounds"] == (10330, 10346)
    assert case["later_tick_bounds"] is None
    assert case["minimum_before_event_minute"] == 36
    assert case["minimum_after_event_minute"] == 0
    with pytest.raises(ValueError, match="OI_REPORT_AFTER_QUOTE_WINDOW"):
        opening_contribution([previous, event], event, previous.bar_end, lots=40, average=Decimal("10340.0"))


def test_joint_windows_require_later_prices_even_when_same_minute_is_unused():
    event = SimpleNamespace(bar_end=at("2026-10-26T21:06"), low=Decimal(10283), high=Decimal(10296))
    earlier = SimpleNamespace(bar_end=event.bar_end - ONE, low=Decimal(10290), high=Decimal(10328))
    later = SimpleNamespace(bar_end=event.bar_end + ONE, low=Decimal(10261), high=Decimal(10346))

    case = opening_contribution([earlier, event, later], event, later.bar_end, lots=40, average=Decimal("10340.0"))
    assert case["compatible_event_minute_lots"] == [0, 1, 2, 3, 4]
    assert case["minimum_after_event_minute"] == 27
    assert case["minimum_before_event_minute"] == 0
