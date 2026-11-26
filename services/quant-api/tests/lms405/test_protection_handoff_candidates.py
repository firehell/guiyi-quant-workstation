from datetime import UTC, datetime, timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_protection_handoff_candidates import HandoffPlan, handoff_events

T = datetime(2026, 10, 26, 13, tzinfo=UTC)
ONE = timedelta(minutes=1)
US = timedelta(microseconds=1)


def test_recovery_shape_uses_current_break_after_price_recaptures_far_edge():
    raw = ((101, 102, 98, 99), (99, 103, 98, 102), (102, 103, 97, 99),
           (99, 100, 97, 98), (98, "99.5", 98, 99), (99, "99.5", 95, 96))
    minutes = [Bar("RU2701", T + (i + 1) * ONE, *map(Decimal, prices), start=T + i * ONE)
               for i, prices in enumerate(raw)]
    plan = HandoffPlan("RU2701", "old", "recovery", T - ONE, T, Decimal(100), "new", T + 10 * ONE,
                       T + 12 * ONE, "FAR_CLOSE_THEN_SHAPE")
    recoveries, replacements = handoff_events({1: minutes, 5: []}, (), plan, T + 7 * ONE)
    assert not replacements
    event, = recoveries
    assert event["first_break_start"] == T + 2 * ONE
    assert event["first_break_known_at"] == T + 3 * ONE + US
    assert event["at"] == T + 6 * ONE + 6 * US
    assert handoff_events({1: minutes, 5: []}, (), plan, event["at"]) == ([], [])
