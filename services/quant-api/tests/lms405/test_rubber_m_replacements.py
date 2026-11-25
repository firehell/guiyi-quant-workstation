from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import ONE, at
from lms405_rubber_m_replacements import compare_gate


START = at("2026-10-23T13:30")


def prices(*levels):
    return [Bar("RU2701", START + i * ONE, *(Decimal(level) for _ in range(4)),
                start=START + (i - 1) * ONE) for i, level in enumerate(levels, 1)]


def compare(bars, quote_pairs, gate, boundary):
    return compare_gate(bars, quote_pairs, gate, boundary=boundary, tick=Decimal(1), lots=2,
                        old_totals=range(200, 201), new_totals=range(220, 221))


def test_same_minute_prices_do_not_prove_post_confirmation_replacement():
    old, event, after = (START + i * ONE for i in (1, 2, 4))
    pairs = [(old, event), (old, after)]
    bars = prices(100, 120, 110, 100)
    generous = compare(bars, pairs, event, "EVENT_MINUTE_ALLOWED_AFTER")
    strict = compare(bars, pairs, event, "ONLY_COMPLETE_MINUTES_AFTER")
    assert generous["equal_minute_pairs"] == strict["equal_minute_pairs"] == 1
    assert generous["pairs_all_replacement_after_possible"] == 2
    assert generous["pairs_all_ending_lots_new_after_possible"] == 1
    assert strict["pairs_all_replacement_after_possible"] == 0
    assert strict["minimum_new_earlier_or_overlapping"] == 1


def test_gate_after_visible_quote_is_excluded():
    baseline = START + ONE
    photo = START + 2 * ONE
    result = compare(prices(100, 120, 130), [(baseline, photo)], START + 3 * ONE,
                     "EVENT_MINUTE_ALLOWED_AFTER")
    assert result["eligible_pairs"] == 0
    assert result["minimum_new_earlier_or_overlapping"] is None
    assert next(iter(result["pair_details"].values())) == {"status": "GATE_AFTER_QUOTE_MINUTE"}
