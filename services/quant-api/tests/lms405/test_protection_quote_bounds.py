from datetime import datetime, timedelta, timezone
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_protection_quote_bounds import gate_price_support


def test_quote_prefix_cannot_reuse_permission_bar_as_later_price():
    end = datetime(2026, 10, 27, 13, 29, tzinfo=timezone.utc)
    minute = timedelta(minutes=1)
    bar = Bar("SH2701", end, Decimal(1487), Decimal(1505), Decimal(1487), Decimal(1494), start=end - minute)
    overlap = Bar("SH2701", end + minute, Decimal(1494), Decimal(1500), Decimal(1488), Decimal(1492), start=end)
    args = dict(tick=Decimal(1), lots=20, totals=range(29839, 29841))
    permission = end + timedelta(microseconds=3)

    same_minute = gate_price_support([bar], permission, **args)
    assert all(row == {"whole_leg_possible": False, "minimum_earlier_or_overlapping_lots": 20}
               for row in same_minute.values())

    following = gate_price_support([bar, overlap], permission, **args)
    assert following["including_minute_overlapping_permission"]["whole_leg_possible"]
    assert not following["only_complete_minutes_after_permission"]["whole_leg_possible"]
