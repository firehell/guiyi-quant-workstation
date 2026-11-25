from decimal import Decimal
from types import SimpleNamespace

from lms405_protection_handoff_study import conditional_average_window, price_window
from lms405_right_side_study import ONE, at


def bar(end, low, high, close):
    time = at(f"2026-10-26T22:{end:02d}")
    return SimpleNamespace(start=time - ONE, end=time, low=Decimal(low), high=Decimal(high),
                           close=Decimal(close))


def test_average_check_excludes_ambiguous_boundary_and_photo_minute():
    bars = [
        bar(25, 1498, 1502, 1499),
        bar(26, 1487, 1500, 1492),
        bar(27, 1488, 1490, 1490),
        bar(28, 1491, 1493, 1491),
        bar(29, 1485, 1505, 1492),
    ]
    result = conditional_average_window(bars, at("2026-10-26T22:25"),
                                        at("2026-10-26T22:29"), Decimal("1490.1"))
    assert result["compatible"]
    assert result["price_envelope"] == (Decimal("1488"), Decimal("1493"))
    assert result["minutes_containing_mean"] == []


def test_target_and_protection_windows_keep_their_own_price_direction():
    bars = [bar(1, 1497, 1500, 1497), bar(3, 1491, 1497, 1494), bar(4, 1494, 1497, 1495)]
    levels = {"same_price": "1498 1498"}
    old = price_window(bars, "2026-10-26T22:00", "2026-10-26T22:02", "SHORT", levels)
    new = price_window(bars, "2026-10-26T22:02", "2026-10-26T22:05", "LONG", levels)
    assert old["levels"]["same_price"]["first_strict_close_beyond_far"] == "2026-10-26T22:01+08:00"
    assert new["levels"]["same_price"]["first_near_reach"] is None
