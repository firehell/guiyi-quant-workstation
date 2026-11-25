from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from lms405_resonance_cases import scope_path, shared_directions


START = datetime.fromisoformat("2026-04-23T09:00:00+08:00")


def bar(minute, low, high, close):
    low, high, close = map(Decimal, (low, high, close))
    return SimpleNamespace(bar_end=START + timedelta(minutes=minute), open=close, high=high, low=low, close=close)


def test_level_touch_and_close_remain_distinct():
    bars = [bar(1, 9, 10, 9), bar(2, 9, 12, 11), bar(3, 8, 12, 12), bar(4, 11, 13, 13)]
    result = scope_path(bars, {"zone": (Decimal(10), Decimal(12))})
    levels = result["levels"]["zone"]
    assert levels["first_contact"]["end"] == "2026-04-23T09:01+08:00"
    assert levels["first_close_above"]["end"] == "2026-04-23T09:04+08:00"
    assert result["first_low"]["end"] == "2026-04-23T09:03+08:00"


def test_comovement_uses_overlapping_minutes_and_excludes_session_breaks():
    a = [bar(1, 8, 10, 9), bar(2, 9, 12, 11), bar(3, 9, 12, 11), bar(40, 6, 7, 7), bar(41, 6, 8, 8)]
    b = [bar(1, 18, 20, 19), bar(2, 19, 22, 21), bar(3, 20, 22, 20), bar(40, 29, 31, 31), bar(41, 29, 31, 30)]
    assert shared_directions(a, b) == {
        "overlapping_contiguous_moves": 3, "both_nonzero": 2,
        "same_direction": 1, "opposite_direction": 1, "flat_on_at_least_one": 1,
    }
