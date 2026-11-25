from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_glass_lock_followup import window
from lms405_right_side_study import FIVE, ONE, at
from lms405_sh_lock_lifecycle import signals


def test_between_reports_does_not_use_a_mother_bar_that_crosses_publication():
    def candle(clock, step, prices):
        end = at(f"2026-06-12T{clock}")
        return Bar("FG2609", end, *map(Decimal, prices), start=end - step)

    series = {
        1: [candle("21:26", ONE, (101, 104, 100, 103))],
        5: [candle("21:20", FIVE, (100, 105, 95, 100)),
            candle("21:25", FIVE, (100, 102, 98, 101)),
            candle("21:30", FIVE, (101, 104, 100, 103))],
        15: [],
    }
    start, cut = at("2026-06-12T21:19"), at("2026-06-12T21:31")
    assert signals(series, 5, 5, side="LONG", start=start, cut=cut)[0]["ibar"] is True
    result = window(series, start, cut)
    assert result["candidates"]["5m_to_5m"] == []
    assert result["minute_count"] == 1
