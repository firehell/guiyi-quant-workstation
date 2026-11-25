from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_protection_lot_timing import displayed_tick_totals
from lms405_pta_pause_carry import lot_survival
from lms405_right_side_study import ONE, at


def test_same_average_requires_retention_until_a_cheaper_replacement_window():
    def bar(clock, low, high):
        end = at(f"2026-10-26T{clock}")
        lo, hi = Decimal(low), Decimal(high)
        return Bar("TA2701", end, lo, hi, lo, hi, start=end - ONE)

    low, earlier, morning, later = [bar(clock, lo, hi) for clock, lo, hi in (
        ("09:01", 99, 100), ("09:02", 103, 103), ("09:03", 103, 103), ("09:04", 99, 103),
    )]
    tick, lots = Decimal(1), 4
    args = dict(tick=tick, lots=lots, totals=displayed_tick_totals(Decimal("100.0"), lots, tick))
    fixed = lot_survival([low, earlier, morning, later], [earlier.end], [morning.end], **args)
    assert fixed["minimum_retained_across_pairs"] == 3
    assert fixed["maximum_replaced_across_pairs"] == 1
    assert fixed["complete_close_then_rebuild_price_compatible"] is False
    assert fixed["unchanged_possible_for_every_pair"] is True
    flexible = lot_survival([low, earlier, morning, later], [earlier.end], [morning.end, later.end], **args)
    assert flexible["minimum_retained_across_pairs"] == 0
    assert flexible["complete_close_then_rebuild_price_compatible"] is True
