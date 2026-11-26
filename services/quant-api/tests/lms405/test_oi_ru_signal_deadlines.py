from datetime import datetime, timezone
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_oi_ru_signal_deadlines import both_ready, combine_support, gate_check, minimum_outside_band
from lms405_right_side_study import ONE, US


START = datetime(2026, 10, 27, 13, tzinfo=timezone.utc)


def one_minute(offset, low, high):
    start = START + offset * ONE
    return Bar("RU2701", start + ONE, *map(Decimal, (low, high, low, high)), start=start)


def test_shared_clock_requires_both_candidates_and_respects_later_knowledge():
    rows = [one_minute(0, 100, 100), one_minute(1, 100, 100), one_minute(2, 110, 110)]
    price = dict(tick=Decimal(1), lots=2, totals=range(200, 201))
    early, late = START + US, START + ONE + US
    assert both_ready(early, late) == late
    assert both_ready(early, None) is None
    assert gate_check(rows, early, **price)["price_compatible"] is True
    delayed = gate_check(rows, both_ready(early, late), **price)
    assert delayed["price_compatible"] is False
    assert delayed["minimum_lots_outside_strict_minutes"] == 2
    assert gate_check(rows, None, **price)["candidate_ready_at_boundary"] is False
    assert combine_support((True, None)) is None
    assert combine_support((False, None)) is False


def test_minimum_outside_reference_uses_display_sum_and_does_not_assume_ticks_in_gap():
    rows = [one_minute(0, 95, 95), one_minute(1, 110, 110)]
    params = dict(band=(Decimal(95), Decimal(105)), tick=Decimal(1), lots=2)
    assert minimum_outside_band(rows, side="ABOVE", totals=range(205, 206), **params) == 1
    assert minimum_outside_band(rows, side="ABOVE", totals=range(206, 207), **params) is None
    assert minimum_outside_band(rows, side="BELOW", totals=range(205, 206), **params) == 0
