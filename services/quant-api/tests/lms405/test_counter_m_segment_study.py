from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from lms405_breakout_trial_study import price_states
from lms405_counter_m_segment_study import carried_breaks, compare, first_reference, with_opening_cross


START = datetime(2026, 10, 22, 21, tzinfo=timezone(timedelta(hours=8)))
ONE, US = timedelta(minutes=1), timedelta(microseconds=1)


def bar(minute, close, side, *, open_price=None):
    price = Decimal(close if side == "LONG" else 200 - close)
    opened = price if open_price is None else Decimal(open_price if side == "LONG" else 200 - open_price)
    return Bar("JM2701", START + (minute + 1) * ONE, opened, max(opened, price), min(opened, price), price,
               start=START + minute * ONE)


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


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize(("opening", "closing", "origin"), [
    (99, 101, "OPEN_TO_CLOSE_CROSS"),
    (100, 101, "OPEN_TO_CLOSE_CROSS"),
    (101, 102, "OPEN_ALREADY_OUTSIDE"),
    (99, 100, "CLOSE_NOT_OUTSIDE"),
])
def test_opening_cross_classifies_open_and_close_at_completed_minute(side, opening, closing, origin):
    rows = [bar(0, closing, side, open_price=opening)]
    edge = Decimal(100)
    args = dict(side=side, edge=edge, target=None, history_start=START, start=START, session_open=START)
    series = {1: rows, 5: []}
    assert compare(series, cutoff=rows[0].end + US, **args)["opening_minute"] is None
    event = compare(series, cutoff=rows[0].end + 2 * US, **args)["opening_minute"]
    assert (event["origin"], event["known_at"]) == (origin, rows[0].end + US)
    _, crosses = with_opening_cross(rows, price_states(rows, side, edge), side, edge, START)
    assert crosses[rows[0].end] == (rows[0].end if origin == "OPEN_TO_CLOSE_CROSS" else None)


def test_opening_cross_resets_on_recovery_and_gap_without_recreating_at_new_segment():
    rows = [bar(minute, price, "LONG", open_price=opening) for minute, opening, price in (
        (0, 100, 101), (1, 101, 102), (2, 102, 100), (3, 100, 101), (5, 100, 106), (6, 106, 107),
    )]
    edge = Decimal(100)
    opening, crosses = with_opening_cross(rows, price_states(rows, "LONG", edge), "LONG", edge, START)
    assert opening["origin"] == "OPEN_TO_CLOSE_CROSS"
    assert tuple(crosses.values()) == (rows[0].end, rows[0].end, None, rows[3].end, None, None)
    late = rows[4:]
    after_missing_open, crosses = with_opening_cross(late, price_states(late, "LONG", edge), "LONG", edge, START)
    assert after_missing_open is None and tuple(crosses.values()) == (None, None)
    result = compare({1: rows, 5: []}, side="LONG", edge=edge, target=None, history_start=START,
                     start=late[0].start, cutoff=late[-1].end + 2 * US, session_open=START)
    assert result["opening_minute"] is None
