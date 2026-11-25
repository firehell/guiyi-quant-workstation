from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from lms405_pta_pause_entry import gap_gates, retention_bounds
from lms405_right_side_study import ONE, at


START = at("2026-10-23T21:00")


def minute(index, *prices):
    end = START + index * ONE
    return Bar("TA2701", end, *map(Decimal, prices), start=end - ONE)


def test_filling_gap_and_reclaiming_open_are_distinct_completed_times():
    bars = [minute(1, 108, 110, 98, 104), minute(2, 104, 109, 102, 108), minute(3, 108, 112, 106, 110)]
    gap = gap_gates(bars, Decimal(100))
    assert gap["touch_prior_close"] == bars[0].end
    assert gap["later_strict_close_above_open"] == bars[2].end


@pytest.mark.parametrize("old_low,maximum", [(100, 0), (90, 1)])
def test_same_reported_average_bounds_replacement_without_proving_retention(old_low, maximum):
    bars = [minute(1, 100, 100, old_low, 100), minute(2, 110, 110, 110, 110), minute(3, 110, 110, 110, 110)]
    result = retention_bounds(bars, [bars[1].end], [bars[2].end], tick=Decimal(1), lots=2, totals=range(200, 201))
    assert list(result.values()) == [dict(min_retained=2 - maximum, max_replaced=maximum, unchanged_possible=True)]
