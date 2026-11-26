from datetime import UTC, datetime, timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_divider_short_candidates import DividerShortPlan, divider_short_events

T = datetime(2026, 10, 20, 1, tzinfo=UTC)
ONE = timedelta(minutes=1)
US = timedelta(microseconds=1)


def test_divider_break_needs_a_contiguous_close_from_inside_the_published_range():
    closes = ((0, 107), (1, 99), (2, 103), (4, 99), (5, 103), (6, 99), (7, 104), (8, 98))
    minutes = [Bar("SH2701", T + (i + 1) * ONE, *[Decimal(close)] * 4, start=T + i * ONE)
               for i, close in closes]
    plan = DividerShortPlan("SH2701", "published", T - ONE, T, T + 11 * ONE, Decimal(100), Decimal(105),
                            "FIRST_FAR_CLOSE")
    series = {1: minutes, 5: []}
    event, = divider_short_events(series, plan, T + 10 * ONE)
    assert event["setup_start"] == T + 5 * ONE
    assert event["at"] == T + 7 * ONE + 9 * US
    assert divider_short_events(series, plan, event["at"]) == []
