from datetime import UTC, datetime, timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_sh_reprotection_replay import NEW_PLAN, admitted_event, next_recovery, opening_average_support

START = datetime(2026, 10, 27, 13, tzinfo=UTC)
ONE = timedelta(minutes=1)
US = timedelta(microseconds=1)


def test_advance_permission_and_touch_policies_require_distinct_evidence():
    signal = {"in_band": False, "pre_touch_arm": True, "available_at": START + ONE + US,
              "touch_known_at": START + 3 * ONE + US, "survives_both_diagnostics": False}
    assert admitted_event(signal, NEW_PLAN, refreshed=False) is None
    assert admitted_event(signal, NEW_PLAN, refreshed=True) == (signal["available_at"], "ADVANCE")
    assert admitted_event(signal, "FIRST_TOUCH", refreshed=False) == (signal["touch_known_at"], "AFTER_FIRST_TOUCH")
    assert admitted_event(signal, "SURVIVING_FIRST_TOUCH", refreshed=True) is None
    assert admitted_event(signal | {"in_band": True}, NEW_PLAN, refreshed=False) == (
        signal["available_at"], "IN_BAND",
    )


def test_conflicting_and_earlier_recovery_shapes_do_not_unlock():
    up = {"direction": "LONG", "shape_start": START + ONE}
    down = {"direction": "SHORT", "shape_start": START + ONE}
    both = [(START + 2 * ONE, [up, down])]
    assert next_recovery(both, START, START + 3 * ONE) is None
    later = [*both, (START + 3 * ONE, [down])]
    assert next_recovery(later, START, START + 3 * ONE) is None
    assert next_recovery(later, START, START + 4 * ONE)["signals"] == [down]


def test_price_support_does_not_use_the_minute_after_the_quote_cutoff():
    def bar(end, price):
        return Bar("SH2701", end, *([Decimal(price)] * 4), start=end - ONE)

    lock = {"at": START + US, "action": "LOCK"}
    tape = [lock]
    matched = {"rows": [{"feasible_checkpoints": [START + ONE, START + 2 * ONE]}]}
    final = {"displayed_legs": {"long": {"quantity": 20, "opening_average": "1492.0"}}}
    bars = [bar(START + ONE, 1492), bar(START + 2 * ONE, 1492), bar(START + 3 * ONE, 1495)]

    a, b = opening_average_support(tape, matched, final, bars, Decimal(1))

    assert not a["whole_minutes_compatible"] and a["overlap_minutes_compatible"]
    assert b["whole_minutes_compatible"]
