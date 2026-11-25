from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_fg_sa_leg_handoff import night_or_morning
from lms405_right_side_study import ONE, at


def minute(end, low, high):
    end = at(end)
    return Bar("SA2701", end, Decimal(low), Decimal(high), Decimal(low), Decimal(high), start=end - ONE)


def test_night_or_morning_stops_at_quote_and_keeps_sides_distinct():
    night = minute("2026-10-22T22:13", 95, 95)
    morning = minute("2026-10-23T09:01", 105, 105)
    later = minute("2026-10-23T09:02", 100, 100)
    result = night_or_morning((night, morning, later), (night.end,), (morning.end, later.end), morning.start,
                              tick=Decimal(1), lots=2, totals=range(200, 201))[night.end.isoformat()]
    assert result[morning.end.isoformat()] == {
        "minimum_night_lots": 1, "maximum_night_lots": 1,
        "whole_leg_can_form_in_night": False, "whole_leg_can_form_in_morning": False,
    }
    assert result[later.end.isoformat()]["whole_leg_can_form_in_morning"] is True
