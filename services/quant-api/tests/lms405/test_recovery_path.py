from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar, Zone
from guiyi_quant.lms405.recovery_path import RecoveryPlan, advance_recovery

T = datetime(2026, 9, 10, 13, tzinfo=UTC)
M = timedelta(minutes=1)
US = timedelta(microseconds=1)


def zone(id_, lower, upper, *, known=T - US):
    return Zone(id_, "OI2701", Decimal(lower), Decimal(upper), known, "study")


def minute(index, high, low, close):
    end = T + index * M
    return Bar("OI2701", end, Decimal(close), Decimal(high), Decimal(low), Decimal(close), start=end - M)


def test_same_bar_target_cannot_enable_recovery_until_next_minute():
    plan = RecoveryPlan("LONG", zone("recover", 100, 102), (zone("first", 105, 107),))
    one = advance_recovery(plan, minute(1, 104, 100, 103))
    two = advance_recovery(plan, minute(2, 107, 103, 105), one)
    three = advance_recovery(plan, minute(3, 106, 102, 104), two)
    assert two.price_recovery_candidate and two.target_seen_at == (T + 2 * M + US,)
    assert not two.first_target_and_recovery_candidate
    assert three.first_target_and_recovery_candidate and three.all_targets_and_recovery_candidate


def test_gap_and_equal_close_reset_recovery_without_resetting_targets():
    plan = RecoveryPlan("SHORT", zone("recover", 104, 105), (zone("first", 100, 101), zone("second", 95, 96)))
    one = advance_recovery(plan, minute(1, 105, 100, 103))
    two = advance_recovery(plan, minute(2, 104, 99, 103), one)
    gap = advance_recovery(plan, minute(4, 104, 94, 103), two)
    resumed = advance_recovery(plan, minute(5, 105, 102, 103), gap)
    equal = advance_recovery(plan, minute(6, 106, 103, 104), resumed)
    assert two.first_target_and_recovery_candidate and not two.all_targets_and_recovery_candidate
    assert gap.consecutive_recovery_closes == 1 and not gap.price_recovery_candidate
    assert resumed.all_targets_and_recovery_candidate
    assert equal.consecutive_recovery_closes == 0 and equal.previously_known_targets == ("first", "second")


def test_plan_visibility_and_scope_are_strict():
    plan = RecoveryPlan("LONG", zone("recover", 100, 102, known=T), (zone("first", 105, 107, known=T),))
    assert advance_recovery(plan, minute(1, 107, 99, 103)) is None
    current = advance_recovery(plan, minute(2, 105, 100, 102))
    assert current.target_seen_at == (None,) and not current.price_recovery_candidate
    with pytest.raises(ValueError, match="SCOPE_OR_ORDER"):
        advance_recovery(replace(plan, side="SHORT"), minute(3, 105, 100, 103), current)
    with pytest.raises(ValueError, match="SCOPE_OR_ORDER"):
        advance_recovery(plan, minute(2, 105, 100, 102), current)
    with pytest.raises(ValueError, match="COMPLETED_CONTRACT_MINUTE"):
        advance_recovery(plan, replace(minute(3, 104, 100, 103), contract="OI2609"), current)


def test_plan_expires_at_observation_availability_and_cannot_carry_to_revision():
    expiry = T + 2 * M + US
    recovery = replace(zone("recover", 100, 102), expires_at=expiry)
    target = replace(zone("first", 105, 107), expires_at=expiry)
    plan = RecoveryPlan("LONG", recovery, (target,))
    first = advance_recovery(plan, minute(1, 108, 100, 104))
    assert first.target_seen_at == (T + M + US,)
    assert advance_recovery(plan, minute(2, 108, 106, 107), first) is None
    next_plan = RecoveryPlan("LONG", replace(recovery, known_at=T + M, expires_at=None),
                             (replace(target, known_at=T + M, expires_at=None),))
    with pytest.raises(ValueError, match="SCOPE_OR_ORDER"):
        advance_recovery(next_plan, minute(3, 106, 100, 104), first)
    fresh = advance_recovery(next_plan, minute(3, 106, 100, 104))
    assert fresh.target_seen_at == (None,) and fresh.consecutive_recovery_closes == 1
