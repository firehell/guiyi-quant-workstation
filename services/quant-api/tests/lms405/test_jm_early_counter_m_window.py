from datetime import datetime, timedelta, timezone
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_jm_early_counter_m_window import assess


def test_early_counter_m_checks_new_lots_without_using_gate_or_quote_minutes():
    start = datetime(2026, 10, 23, 9, tzinfo=timezone(timedelta(hours=8)))
    minute = timedelta(minutes=1)
    prices = (110, 101, 101, 110, 110, 110, 130)
    bars = []
    for index, value in enumerate(prices):
        price = Decimal(value)
        bar_start = start + index * minute
        bars.append(Bar("JM2701", bar_start + minute, price, price, price, price, start=bar_start))
    result = assess(bars, early_quote=start + 4 * minute, close_quote=start + 7 * minute,
                    old_ticks=(100, 100), gate=start + timedelta(microseconds=1), tick=Decimal(1), lots=2,
                    old_total=range(200, 201), end_total=range(220, 221))
    assert result["early_price_ticks"] == (101, 101)
    assert result["late_price_ticks"] == (110, 110)
    assert result["full_replacement_before_early_possible"] is False
    assert result["flat_at_early_then_full_new_leg_possible"] is True
    assert result["feasible_allocations"] == [[0, 0, 2]]
