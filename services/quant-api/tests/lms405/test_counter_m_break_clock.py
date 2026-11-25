from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_counter_m_break_clock import check_prefixes
from lms405_right_side_study import ONE, US, at


def test_counter_m_requires_a_new_shape_and_does_not_carry_old_gate_across_return():
    start = at("2025-12-22T09:00")
    prices = ((99, 103, 98, 101), (101, 104, 99, 100), (100, 104, 99, 102), (102, 103, 101, 102),
              (102, 106, 101, 105), (105, 106, 99, 100), (100, 105, 99, 102), (102, 104, 101, 103),
              (103, 106, 102, 105))
    minutes = [Bar("OI2605", start + i * ONE, *map(Decimal, row), start=start + (i - 1) * ONE)
               for i, row in enumerate(prices, 1)]
    five = Bar("OI2605", start + 5 * ONE, *map(Decimal, (99, 106, 98, 105)), start=start)
    series = {1: minutes, 5: [five], 15: []}
    report = check_prefixes(series, side="LONG", edge=Decimal(100), start=start, cut=minutes[-1].end + 2 * US)
    gate1 = report["gates"]["1m"]["groups"]["1m_to_1m"]
    gate5 = report["gates"]["5m"]["groups"]["1m_to_1m"]
    assert gate1["still_beyond"]["confirmed_at"] == five.end
    assert gate1["gate_in_active_run"] is None  # Shape starts when renewed break closes.
    assert gate5["still_beyond"]["confirmed_at"] == minutes[-1].end
    assert gate5["still_beyond"]["active_minute_run_start"] == minutes[6].end
    assert gate5["gate_in_active_run"] is None  # 5m gate is before the most recent return to edge.
    assert report["prefix_checks"] > 5
