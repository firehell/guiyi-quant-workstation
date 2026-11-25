from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import ONE, at
from lms405_strong_side_transition_audit import persistence_after_target


def test_completed_target_does_not_trigger_on_its_own_bar_or_carry_run_across_break():
    bars = []
    for clock, low in (("09:01", 98), ("09:02", 90), ("09:03", 98), ("10:31", 98)):
        end = at(f"2026-10-27T{clock}")
        bars.append(Bar("I2701", end, Decimal(98), Decimal(99), Decimal(low), Decimal(98), start=end - ONE))

    edge, target = Decimal(100), Decimal(90)
    prefix = persistence_after_target(bars[:2], edge, target)
    assert prefix["target_first_reached_at"] == bars[1].end
    assert prefix["first_qualified_at"] is None
    assert persistence_after_target(bars[:3], edge, target)["qualified_at_end"] is True

    whole = persistence_after_target(bars, edge, target)
    assert whole["first_qualified_at"] == bars[2].end
    assert whole["qualified_at_end"] is False
