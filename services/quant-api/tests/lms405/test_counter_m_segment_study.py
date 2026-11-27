from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from lms405_breakout_trial_study import price_states
from lms405_counter_m_segment_study import carried_breaks, first_reference


START = datetime(2026, 10, 22, 21, tzinfo=timezone(timedelta(hours=8)))
ONE, US = timedelta(minutes=1), timedelta(microseconds=1)


def bar(minute, close, side):
    price = Decimal(close if side == "LONG" else 200 - close)
    return Bar("JM2701", START + (minute + 1) * ONE, price, price, price, price, start=START + minute * ONE)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_carry_survives_gap_but_resets_on_equal_close_and_requires_new_cross(side):
    rows = [bar(minute, price, side) for minute, price in (
        (0, 100), (1, 101), (5, 103), (6, 100), (10, 104), (11, 100), (12, 102),
    )]
    paths = price_states(rows, side, Decimal(100))
    carried = carried_breaks(paths)
    assert paths[rows[2].end]["active_cross_at"] is None
    assert carried[rows[2].end] == rows[1].end
    assert carried[rows[3].end] is None
    assert carried[rows[4].end] is None
    assert carried[rows[-1].end] == rows[-1].end


def test_night_reference_can_block_even_when_current_window_never_reaches_target():
    rows = [bar(0, 110, "LONG"), bar(5, 105, "LONG")]
    target = Decimal(110)
    assert first_reference(rows, START, rows[0].end + US, target, "LONG") is None
    assert first_reference(rows, START, rows[0].end + 2 * US, target, "LONG") == rows[0].end + US
    assert first_reference(rows, rows[1].start, rows[1].end + 2 * US, target, "LONG") is None
    assert first_reference(rows, START, rows[1].end + 2 * US, None, "LONG") is None
    partial_start = START + US
    cutoff = rows[0].end + 2 * US
    assert first_reference(rows, partial_start, cutoff, target, "LONG") is None
    assert first_reference(rows, partial_start, cutoff, target, "LONG", overlap_can_block=True) == rows[0].end + US
