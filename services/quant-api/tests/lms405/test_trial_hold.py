from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.trial_hold import TrialHold, assess_trial_hold


T = datetime.fromisoformat("2026-10-27T10:00:00+08:00")


def at(minute):
    return T + timedelta(minutes=minute)


def inputs(position):
    request = TrialHold(position, "plan-a", "trial-a", T, at(-1), at(3), True)
    facts = tuple(Condition(name, request.scope, position.contract, True, at(minute), at(minute),
                            "TEST_FIXTURE", "EVENT_TIME")
                  for name, minute in (("TRIAL_SUCCEEDED", 1), ("TREND_CONFIRMED", 2), ("SAME_TRIAL_STILL_OPEN", 3)))
    return request, facts


def assess(request, facts, *, as_of):
    return assess_trial_hold(request, facts, as_of=as_of, allow_test_fixture=True)


@pytest.mark.parametrize("long,short", [(20, 0), (0, 20)])
def test_holding_preserves_trial_and_quantities_without_order(long, short):
    request, facts = inputs(Position("JM2701", Decimal(long), Decimal(short)))
    answer = assess(request, facts, as_of=at(4))
    assert answer["status"] == "CONDITIONAL_ROLE_CHANGE"
    assert answer["after"] == dict(role="TREND_HOLD", trial_id="trial-a", snapshot_at=at(3).isoformat(),
                                   position=dict(contract="JM2701", long=Decimal(long), short=Decimal(short)))
    assert answer["requested_action"] is None and answer["fill"] is None and not answer["executable"]


def test_unrevealed_or_non_event_evidence_does_not_establish_role():
    request, facts = inputs(Position("JM2701", Decimal(20)))
    prefix = assess(request, facts[:2], as_of=at(3))
    assert assess(request, facts, as_of=at(3)) == prefix
    assert prefix["status"] == "INDETERMINATE"
    reviewed = replace(facts[-1], time_kind="RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME")
    assert assess(request, (*facts[:2], reviewed), as_of=at(4))["after"] is None
    equal = replace(facts[1], observed_at=at(3), known_at=at(3))
    assert assess(request, (facts[0], equal, facts[2]), as_of=at(4))["status"] == "INDETERMINATE"
    stale = replace(facts[-1], observed_at=at(1))
    assert assess(request, (*facts[:2], stale), as_of=at(4))["status"] == "NOT_PERMITTED"
    closed = replace(facts[-1], value=False)
    assert assess(request, (*facts[:2], closed), as_of=at(4))["status"] == "NOT_PERMITTED"


def test_late_confirmation_or_old_snapshot_cannot_relabel_current_position():
    request, facts = inputs(Position("JM2701", Decimal(20)))
    late = replace(facts[0], known_at=at(8))
    assert assess(request, (late, *facts[1:]), as_of=at(10))["status"] == "NOT_PERMITTED"
    later_snapshot = replace(request, snapshot_at=at(9))
    rescoped = tuple(replace(fact, case_id=later_snapshot.scope) for fact in facts)
    assert assess(later_snapshot, rescoped, as_of=at(10))["status"] == "NOT_PERMITTED"
    historical = assess(request, facts, as_of=at(10))
    assert historical["after"]["snapshot_at"] == at(3).isoformat()
    for source in ("TEST_FIXTURE", "TEST_FIXTURE:price-bare"):
        relabeled = tuple(replace(fact, source=source) for fact in facts)
        with pytest.raises(ValueError, match="FIXTURE_CONFIRMATION_DISABLED"):
            assess_trial_hold(request, relabeled, as_of=at(4))


def test_flat_or_locked_positions_and_unrelated_trials_cannot_inherit():
    request, facts = inputs(Position("JM2701", Decimal(20)))
    for position in (Position("JM2701"), Position("JM2701", Decimal(20), Decimal(20))):
        with pytest.raises(ValueError, match="SINGLE_TRIAL_LEG_REQUIRED"):
            replace(request, position=position)
    with pytest.raises(ValueError, match="TRIAL_HOLD_CONDITION_SCOPE_MISMATCH"):
        assess(replace(request, trial_id="trial-b"), facts, as_of=at(4))
    with pytest.raises(ValueError, match="TRIAL_HOLD_CONDITION_SCOPE_MISMATCH"):
        assess(request, (replace(facts[0], contract="SH2701"),), as_of=at(4))
    unknown = replace(request, version_405=None)
    scoped = tuple(replace(fact, case_id=unknown.scope) for fact in facts)
    assert assess(unknown, scoped, as_of=at(4))["status"] == "INDETERMINATE"
