from decimal import Decimal
from types import SimpleNamespace

from lms405_first_night_protection import compare_gate
from lms405_right_side_study import ONE, at


def test_gate_partition_preserves_both_sides_of_the_straddling_minute():
    start = at("2026-10-22T21:00")
    minutes = []
    for index, price in enumerate((100, 110, 90), start=1):
        value = Decimal(price)
        minutes.append(SimpleNamespace(bar_end=start + index * ONE, open=value, high=value, low=value, close=value))

    gate = compare_gate(minutes, minutes[0], Decimal(1), 2, range(210, 211))

    assert gate["straddling_minute_allocated_later"]["earlier_count_interval"] == [0, 1]
    assert gate["straddling_minute_allocated_earlier"]["earlier_count_interval"] == [2, 2]
    assert gate["earlier_lots_conservative_interval"] == [0, 2]
    assert gate["wholly_after_gate"]["whole_leg_price_possible"] is False
