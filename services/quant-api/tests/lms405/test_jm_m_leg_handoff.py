from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_jm_m_leg_handoff import formation
from lms405_right_side_study import ONE, at
from lms405_rubber_m_replacements import first_gates


START = at("2026-10-23T21:00")


def minute(index, high, low, close):
    return Bar("JM2701", START + index * ONE, Decimal(close), Decimal(high), Decimal(low), Decimal(close),
               start=START + (index - 1) * ONE)


def test_short_gate_uses_high_edge_first_and_distinguishes_touch_from_close():
    minutes = [minute(1, 110, 105, 105), minute(2, 108, 101, 104), minute(3, 106, 99, 100)]
    bands = {"divider": (Decimal(100), Decimal(105))}
    gates = first_gates({1: minutes, 5: [], 15: []}, START, START + 4 * ONE, bands=bands, side="SHORT")
    assert gates["divider_near_touch"]["end"] == START + ONE
    assert gates["divider_near_strict_close"]["end"] == START + 2 * ONE
    assert gates["divider_far_touch"]["end"] == START + 3 * ONE
    assert gates["divider_far_strict_close"]["end"] is None


def test_formation_distinguishes_capture_before_gate_and_overlapping_minute():
    minutes = [minute(1, 100, 100, 100), minute(2, 105, 105, 105), minute(3, 110, 110, 110)]
    captures = [row.end for row in minutes]
    event = captures[1]
    result = list(formation(minutes, captures, event, boundary="ONLY_COMPLETE_MINUTES_AFTER",
                            tick=Decimal(1), lots=2, totals=range(200, 201)).values())
    assert result[0]["status"] == "GATE_NOT_OBSERVED_BY_QUOTE"
    assert result[1]["status"] == "QUOTE_MINUTE_EQUALS_GATE"
    assert result[2]["min_outside_later_bucket"] == 2
