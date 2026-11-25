from datetime import UTC, datetime, timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_first_night_confirmation_clocks import price_envelope

MINUTE = timedelta(minutes=1)
MICROSECOND = timedelta(microseconds=1)
T0 = datetime(2026, 10, 22, 13, tzinfo=UTC)


def bar(offset, price):
    start = T0 + offset * MINUTE
    value = Decimal(price)
    return Bar("FG2701", start + MINUTE, value, value, value, value, start=start)


def test_confirming_minute_and_overlap_are_kept_distinct():
    minutes = [bar(0, "825"), bar(1, "828"), bar(2, "830")]
    event = {"available_at": minutes[0].end + MICROSECOND}
    result = price_envelope(minutes, event, Decimal(1), 2, range(1656, 1657), minutes[-1].end)
    assert result["minimum_lots_outside_later_minutes"] == {"overlap_allowed": 0, "fully_after": 1}


def test_price_infeasibility_does_not_change_candidate_visibility():
    minutes = [bar(0, "825"), bar(1, "828")]
    event = {"available_at": minutes[0].end + MICROSECOND}
    result = price_envelope(minutes, event, Decimal(1), 2, range(1660, 1661), minutes[-1].end)
    assert not result["whole_leg_price_possible_in_prefix"]
    assert result["first_candidate_known_before_quote_end"]
    assert result["minimum_lots_outside_later_minutes"] is None
