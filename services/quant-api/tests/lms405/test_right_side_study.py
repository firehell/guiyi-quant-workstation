from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from lms405_right_side_study import ordered_closes, retest_path


T = datetime.fromisoformat("2026-10-27T09:00:00+08:00")


def bar(minute, low, high, close):
    return SimpleNamespace(bar_end=T + timedelta(minutes=minute), low=Decimal(low),
                           high=Decimal(high), close=Decimal(close))


def test_close_sequence_needs_separate_revealed_bars():
    bars = [bar(1, 90, 105, 91), bar(2, 90, 96, 94), bar(3, 89, 97, 90)]
    result = ordered_closes(bars, ("100", "95", "91"), "SHORT")
    assert [row["at"] for row in result] == [b.bar_end.isoformat() for b in bars]
    assert ordered_closes(bars[:1], ("100", "95", "91"), "SHORT") == [
        result[0], dict(level=Decimal(95), at=None, close=None),
    ]


def test_retest_rejects_same_bar_orders_and_restarts_at_gap_or_full_invalidation():
    first = bar(1, 98, 100, 99)
    contact = bar(2, 97, 100, 98)
    next_close = bar(3, 97, 99, 98)
    assert retest_path([first, contact], Decimal(100), Decimal(102), "SHORT") == (first, contact, None)
    assert retest_path([first, contact, next_close], Decimal(100), Decimal(102), "SHORT") == (first, contact, next_close)
    for restart in (bar(3, 100, 104, 103), bar(7, 99, 101, 101)):
        ending = bar(int((restart.bar_end - T).total_seconds() / 60) + 1, 97, 99, 98)
        assert retest_path([first, contact, restart, ending], Decimal(100), Decimal(102), "SHORT") == (ending, None, None)
