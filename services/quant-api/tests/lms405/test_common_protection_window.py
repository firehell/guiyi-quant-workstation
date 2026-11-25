from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from lms405_common_protection_window import classify_leg, enclosed_averages, summary


START = datetime.fromisoformat("2026-10-22T21:00:00+08:00")


def bar(n, low, high):
    return SimpleNamespace(bar_end=START + timedelta(minutes=n), low=Decimal(low), high=Decimal(high))


def test_same_minute_and_common_interval_have_distinct_requirements():
    a = [bar(1, 10, 12), bar(2, 13, 14), bar(3, 15, 16)]
    b = [bar(1, 20, 21), bar(2, 22, 23), bar(3, 24, 25)]
    windows = enclosed_averages({"A": a, "B": b}, {"A": Decimal(11), "B": Decimal(24)})
    result = summary(windows)
    assert result["counts_at_fixed_width"]["1"] == 0
    assert result["minimum_minutes"] == 3
    assert result["first_minimum_window"] == {
        "start": "2026-10-22T21:00+08:00", "last_bar_end": "2026-10-22T21:03+08:00",
    }
    assert not enclosed_averages({"A": a, "B": b}, {"A": Decimal(11), "B": Decimal(26)})
    with pytest.raises(ValueError, match="COMMON_WINDOW_MINUTE_IDENTITY_MISMATCH"):
        enclosed_averages({"A": a, "B": b[1:]}, {"A": Decimal(11), "B": Decimal(24)})


def test_missing_or_changed_leg_remains_a_display_observation():
    initial = dict(quantity=20, opening_average="1720.0")
    assert classify_leg(initial, None) == "UNLISTED_UNKNOWN"
    assert classify_leg(initial, initial | {"opening_average": None}) == "VISIBLE_FIELDS_INCOMPLETE"
    assert classify_leg(initial, initial | {"opening_average": "1720"}) == "SAME_VISIBLE_QUANTITY_AND_OPENING_AVERAGE"
    assert classify_leg(initial, initial | {"opening_average": "1721"}) == "VISIBLE_FIELDS_CHANGED"
