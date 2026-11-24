from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.handoff import Handoff, HandoffConfirmation, assess_handoff
from guiyi_quant.lms405.public_conditions import Condition
from lms405_handoff_casebook import report


T = datetime.fromisoformat("2026-10-27T09:00:00+08:00")


def at(minute):
    return T + timedelta(minutes=minute)


def fixture(route, side="SHORT"):
    locked = route in {"RESUME_ORIGINAL", "COUNTER_M_FROM_LOCK"}
    quantity = Decimal(1 if locked else 0)
    request = Handoff(route, Position("JM2701", quantity, quantity), side,
                      "plan-a", "cycle-a", None if route == "RESUME_ORIGINAL" else "next-a", T, at(1))
    supplied = ["POSITION_PATH_CONFIRMED", "SIGNAL"]
    if route.startswith("COUNTER_M"):
        supplied += ["M_CONFIG_PERMITS", "INTERRUPTION"]
    else:
        supplied += ["ORIGINAL_PLAN_VALID"]
    facts = tuple(Condition(name, request.scope, request.before.contract, True,
                            at(3 if name == "SIGNAL" else 2), at(3 if name == "SIGNAL" else 2),
                            "TEST_FIXTURE", "EVENT_TIME") for name in supplied)
    return request, facts


def fixture_approval(request, decided=4, known=4, accepted=True):
    return HandoffConfirmation(request.confirmation_scope("TEST_FIXTURE", at(-1), True), "fixture-1",
                               accepted, at(decided), at(known), "TEST_FIXTURE")


def assess(request, facts, *, cutoff=5, approval=True):
    if approval is True:
        approval = fixture_approval(request)
    return assess_handoff(request, facts, as_of=at(cutoff), source="TEST_FIXTURE",
                          source_available_at=at(-1), version_405=True,
                          approval=approval, allow_test_fixture=True)


@pytest.mark.parametrize("side,original,counter", [("SHORT", "short", "long"), ("LONG", "long", "short")])
@pytest.mark.parametrize("route,action", [("RESUME_ORIGINAL", "UNLOCK"), ("COUNTER_M_FROM_LOCK", "UNLOCK"),
                                         ("COUNTER_M_AFTER_CLEAR", "ENTER"), ("REENTER_ORIGINAL", "REENTER")])
def test_route_handoff_preserves_parent_plan_and_direction(route, action, side, original, counter):
    request, facts = fixture(route, side)
    result = assess(request, facts)
    assert result["status"] == "CONDITIONAL_ACTION"
    leg = counter if route.startswith("COUNTER_M") else original
    assert result["requested_action"] == f"{action}_{leg.upper()}"
    assert result["after"][leg] == "1"
    assert result["after"]["short" if leg == "long" else "long"] == "0"
    assert result["plan_id"] == "plan-a" and result["original_side"] == side
    assert result["parent_cycle_id"] == "cycle-a"
    assert result["hypothetical_active_id"] == ("cycle-a" if route == "RESUME_ORIGINAL" else "next-a")
    assert result["hypothetical_task"] == ("COUNTER_M" if route.startswith("COUNTER_M") else "ORIGINAL_PLAN")
    assert not result["executable"] and result["fill"] is None


def test_counter_m_requires_explicit_config_and_confirmation_after_signal():
    request, facts = fixture("COUNTER_M_FROM_LOCK")
    assert assess(request, facts, cutoff=4)["after"] is None
    for name in ("M_CONFIG_PERMITS", "POSITION_PATH_CONFIRMED"):
        assert assess(request, tuple(f for f in facts if f.name != name))["status"] == "INDETERMINATE"
    assert assess(request, facts, approval=None)["status"] == "INDETERMINATE"
    assert assess(request, facts, approval=fixture_approval(request, accepted=False))["status"] == "NOT_PERMITTED"
    blocked = tuple(replace(f, value=False) if f.name == "M_CONFIG_PERMITS" else f for f in facts)
    assert assess(request, blocked)["status"] == "NOT_PERMITTED"
    assert assess(request, facts, approval=fixture_approval(request, decided=3))["status"] == "INDETERMINATE"
    early_signal = tuple(replace(f, observed_at=at(-1)) if f.name == "SIGNAL" else f for f in facts)
    assert assess(request, early_signal)["status"] == "NOT_PERMITTED"


def test_reading_time_never_supplies_signal_and_scope_cannot_rebind():
    request, facts = fixture("COUNTER_M_FROM_LOCK")
    reviewed = tuple(replace(f, time_kind="RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME")
                     if f.name == "SIGNAL" else f for f in facts)
    assert assess(request, reviewed)["after"] is None
    with pytest.raises(ValueError, match="CONDITION_SCOPE_MISMATCH"):
        assess(replace(request, plan_id="other-plan"), facts)
    with pytest.raises(ValueError, match="HANDOFF_POSITION_MISMATCH"):
        replace(request, route="COUNTER_M_AFTER_CLEAR")
    assert assess(request, facts, cutoff=1)["status"] == "INDETERMINATE"


def test_late_prerequisite_cannot_be_used_for_earlier_confirmed_intent():
    request, facts = fixture("COUNTER_M_FROM_LOCK")
    late = tuple(replace(f, known_at=at(5)) if f.name == "M_CONFIG_PERMITS" else f for f in facts)
    assert assess(request, late, cutoff=5) == assess(
        request, tuple(f for f in facts if f.name != "M_CONFIG_PERMITS"), cutoff=5,
    )
    verdict = assess(request, late, cutoff=6)
    assert verdict["status"] == "NOT_PERMITTED" and verdict["after"] is None
    assert verdict["routes"][0]["checks"]["PRECONDITIONS_BEFORE_CONFIRMATION"] is False
    future_version = assess_handoff(request, facts, as_of=at(5), source="TEST_FIXTURE",
                                    source_available_at=at(5), version_405=False)
    assert future_version["status"] == "INDETERMINATE" and future_version["after"] is None
    assert future_version["sources"] == []


def test_approval_binds_policy_and_fixture_requires_opt_in():
    request, facts = fixture("COUNTER_M_FROM_LOCK")
    approval = fixture_approval(request)
    with pytest.raises(ValueError, match="FIXTURE_CONFIRMATION_DISABLED"):
        assess_handoff(request, facts, as_of=at(5), source="TEST_FIXTURE", source_available_at=at(-1),
                       version_405=True, approval=approval)
    with pytest.raises(ValueError, match="CONFIRMATION_SCOPE_MISMATCH"):
        assess_handoff(request, facts, as_of=at(5), source="different-source", source_available_at=at(-1),
                       version_405=True, approval=approval, allow_test_fixture=True)
    pseudo_approval = replace(facts[0], name="RESEARCH_CONFIRMATION")
    with pytest.raises(ValueError, match="UNEXPECTED_CONDITION"):
        assess(request, facts + (pseudo_approval,), approval=None)
    human = replace(approval, record_kind="HUMAN_RESEARCH_DECISION")
    result = assess_handoff(request, facts, as_of=at(5), source="TEST_FIXTURE", source_available_at=at(-1),
                            version_405=True, approval=human)
    assert result["confirmation_kind"] == "HUMAN_RESEARCH_DECISION"


def test_unrevealed_conflicting_fact_does_not_change_prefix():
    request, facts = fixture("COUNTER_M_FROM_LOCK")
    later = replace(facts[0], known_at=at(5), value=False)
    assert assess(request, facts + (later,)) == assess(request, facts)
    with pytest.raises(ValueError, match="DUPLICATE_CONDITION"):
        assess(request, facts + (later,), cutoff=6)


def test_archived_cases_never_supply_confirmation_or_invent_a_route():
    root = Path(__file__).resolve().parents[4]
    result = report(root / "docs/research/lms405/evidence/plan-handoff-cases.json")
    rows = result["cases"]
    assert {r["contract"][:-4] for r in rows.values()} == {"OI", "JM", "RU", "FG", "SA", "V", "TA", "SH", "I"}
    assert rows["oi-clear-then-m"]["assessment"]["requested_action"] == "ENTER_SHORT"
    assert rows["oi-retain-hedge"]["assessment"]["requested_action"] == "UNLOCK_SHORT"
    assert rows["sh-continuous-m-config-counterexample"]["status"] == "NOT_PERMITTED"
    assert rows["ta-plan-paused"]["assessment"] is None and rows["sa-discontinuous-legs"]["assessment"] is None
    assert all(row["after"] is None for row in rows.values())
    assert all(row["assessment"]["confirmation_id"] is None for row in rows.values() if row["assessment"])
    assert result["author_matches"] is None and result["admitted_author_samples"] == 0
