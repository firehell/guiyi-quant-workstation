from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_oi_leg_intent import CONTRACT, START, quote_relation, standing_long
from lms405_right_side_study import ONE, US


def test_completed_price_event_at_quote_minute_start_cannot_pass_strict_before():
    quote_end = START + 4 * ONE
    assert quote_relation(quote_end - ONE - US, quote_end) == "BEFORE_QUOTE_MINUTE"
    assert quote_relation(quote_end - ONE, quote_end) == "WITHIN_QUOTE_MINUTE"
    assert quote_relation(quote_end, quote_end) == "AT_OR_AFTER_QUOTE_END"
    assert quote_relation(None, quote_end) == "EVENT_UNAVAILABLE"


def test_standing_long_needs_two_completed_closes_before_shape_in_current_run():
    values = ((101, 103, 100, 102), (102, 104, 101, 103), (103, 107, 102, 104),
              (104, 106, 103, 105), (105, 109, 104, 108))
    bars = [Bar(CONTRACT, START + (i + 1) * ONE, *map(Decimal, prices), start=START + i * ONE)
            for i, prices in enumerate(values)]
    cutoff = bars[-1].end + 2 * US
    intact = standing_long({1: bars, 5: [], 15: []}, bars, 100, START, cutoff)
    event, = intact["fresh_long_in_same_run"]["1m_to_1m"]
    assert event["event"]["confirmed_at"] == bars[-1].end
    assert event["two_closes_known_at"] == bars[1].end + US
    after_gap = bars[:1] + bars[2:]
    reset = standing_long({1: after_gap, 5: [], 15: []}, after_gap, 100, START, cutoff)
    assert reset["fresh_long_in_same_run"]["1m_to_1m"] == []
