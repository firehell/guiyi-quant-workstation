from decimal import Decimal
from types import SimpleNamespace

from lms405_fg_sa_case import at
from lms405_session_carry_study import SHORT_DAY, wait_windows


def test_intraminute_contact_and_completed_close_use_different_price_windows():
    rows = [SimpleNamespace(bar_end=at(f"26T21:0{idx}"), trading_day=SHORT_DAY,
                            low=Decimal(low), high=Decimal(high), close=Decimal(close))
            for idx, low, high, close in ((1, 833, 835, 833), (2, 830, 834, 831), (3, 830, 831, 831))]
    result = wait_windows(rows, rows, (Decimal(828), Decimal(832)), "832")
    touch, close = result["night_touch"], result["night_close_below_upper"]
    assert touch["bar_end"] == close["bar_end"] == "2026-10-26T21:02+08:00"
    assert touch["price"]["range"] == ["830", "834"]
    assert touch["price"]["average_range_compatible"]
    assert close["price"]["range"] == ["830", "831"]
    assert not close["price"]["average_range_compatible"]
    assert result["night_close_below_lower"] is None
