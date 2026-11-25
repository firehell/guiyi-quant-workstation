from datetime import timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_opening_ebar_audit import opening_comparison
from lms405_protection_timeframes import geometry_events
from lms405_right_side_study import at


def test_opening_does_not_use_overnight_bar_as_an_inside_bar_parent():
    day = "2026-05-29"
    opening = at(f"{day}T09:00")

    def bar(start, minutes, values):
        return Bar("OI2609", start + timedelta(minutes=minutes), *map(Decimal, values), start=start)

    series = {
        1: [bar(at("2026-05-28T22:59"), 1, (9, 20, 1, 10)),
            bar(opening, 1, (10, 12, 9, 11)),
            bar(opening + timedelta(minutes=1), 1, (11, 14, 10, 13))],
        5: [bar(opening, 5, (10, 14, 9, 13))],
        15: [bar(opening, 15, (10, 14, 9, 13))],
    }

    shared = geometry_events(series, 1, 1, start=opening, as_of=at(f"{day}T10:15"), side="LONG")
    assert shared[0]["ibar"] is True
    result = opening_comparison(series, day, "LONG")
    assert result["candidates"]["keybar_1m_to_1m"] == []
    assert result["night_close"] == Decimal(10)
