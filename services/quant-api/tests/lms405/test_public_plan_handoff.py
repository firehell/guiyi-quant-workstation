from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Action, Position, Zone
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.public_plan_handoff import PlanAction, Publication, assess_plan_action


CONTRACT = "TA2701"
ZERO = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
STEP = timedelta(minutes=1)


def plan(revision, minute, *, withheld=False, contract=CONTRACT, expires=None, received=None):
    published_at = ZERO + minute * STEP
    known_at = published_at if received is None else ZERO + received * STEP
    zone = None if withheld else Zone(revision, contract, Decimal(100), Decimal(110), known_at, revision, expires)
    return Publication(revision, contract, published_at, known_at, revision, zone)


def facts(request, minute, *, reading=False):
    observed = ZERO + minute * STEP
    trigger = Condition("TRIGGER", request.scope, CONTRACT, True, observed, observed + STEP,
                        "TEST_FIXTURE", "RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME" if reading else "EVENT_TIME")
    return trigger, HandoffConfirmation(request.confirmation_scope(trigger), "TEST_FIXTURE", True,
                                       observed + 2 * STEP, observed + 3 * STEP, "TEST_FIXTURE")


def assess(request, revisions, evidence, minute):
    trigger, approval = (*evidence, None, None)[:2]
    return assess_plan_action(request, revisions, as_of=ZERO + minute * STEP, trigger=trigger, approval=approval,
                              allow_test_fixture=True)


def test_pause_supersedes_prior_range_strictly_and_other_contract_does_not_leak():
    original, pause = plan("old", 0), plan("paused", 6, withheld=True)
    another = plan("different", 3, contract="TA2609")
    request = PlanAction(Position(CONTRACT), "flat", ZERO, Action("ENTER_LONG", Decimal(1)), original)
    revisions, evidence = (original, pause, another), facts(request, 1)
    assert assess(request, revisions, evidence, 6) == assess(request, (original,), evidence, 6)
    assert assess(request, revisions, evidence, 6)["after"] == {"long": "1", "short": "0"}
    after = assess(request, revisions, evidence, 7)
    assert after["status"] == "NOT_PERMITTED" and after["after"] is None


@pytest.mark.parametrize("kind,quantity,projection", [
    ("LOCK", 34, {"long": "34", "short": "34"}),
    ("EXIT_LONG", 5, {"long": "29", "short": "0"}),
    ("EXIT_LONG", 34, {"long": "0", "short": "0"}),
])
def test_old_position_action_requires_separate_permission_while_zone_is_withheld(kind, quantity, projection):
    request = PlanAction(Position(CONTRACT, long=Decimal(34)), "old-position", ZERO, Action(kind, Decimal(quantity)))
    revisions, evidence = (plan("paused", 0, withheld=True),), facts(request, 1)
    assert assess(request, revisions, evidence[:1], 5)["after"] is None
    assert assess(request, revisions, evidence, 4)["after"] is None
    result = assess(request, revisions, evidence, 5)
    assert result["after"] == projection
    assert result["sources"] == ["TEST_FIXTURE"]


def test_republished_zone_needs_a_fresh_signal_and_approval():
    revisions = (plan("paused", 0, withheld=True), plan("new", 6))
    request = PlanAction(Position(CONTRACT), "new-flat", ZERO, Action("REENTER_LONG", Decimal(1)), revisions[-1])
    assert assess(request, revisions, (), 6)["observed_publication_state"] == "WITHHELD"
    assert assess(request, revisions, (), 7)["status"] == "INDETERMINATE"
    assert assess(request, revisions, facts(request, 5), 11)["status"] == "NOT_PERMITTED"
    assert assess(request, revisions, facts(request, 7), 10)["after"] is None
    assert assess(request, revisions, facts(request, 7), 11)["after"] == {"long": "1", "short": "0"}
    assert assess(request, revisions, facts(request, 7, reading=True), 11)["after"] is None


def test_current_plan_expiry_or_conflict_never_reuses_the_earlier_range():
    revisions = (plan("original", 0), plan("branch", 7, expires=ZERO + 9 * STEP))
    request = PlanAction(Position(CONTRACT), "flat", ZERO, Action("ENTER_LONG", Decimal(1)), revisions[0])
    assert assess(request, revisions, facts(request, 1), 9)["observed_publication_state"] == "EXPIRED"
    assert assess(request, revisions, facts(request, 1), 9)["after"] is None
    competing = (*revisions, plan("other", 7, withheld=True))
    assert assess(request, competing, facts(request, 1), 8)["observed_publication_state"] == "CONFLICT_AT_SAME_TIME"
    assert assess(request, competing, facts(request, 1), 8)["after"] is None


def test_permission_cannot_move_to_another_position_snapshot_or_action():
    old = PlanAction(Position(CONTRACT, long=Decimal(34)), "old", ZERO, Action("LOCK", Decimal(34)))
    newer = PlanAction(old.position, "newer", ZERO + STEP, Action("EXIT_LONG", Decimal(34)))
    with pytest.raises(ValueError, match="PUBLIC_PLAN_FACT_SCOPE_MISMATCH"):
        assess(newer, (plan("paused", 0, withheld=True),), facts(old, 1), 5)


def test_independent_entry_requires_explicit_route_and_its_own_evidence():
    seed = Position(CONTRACT)
    opening = Action("ENTER_LONG", Decimal(1))
    revisions = (plan("paused", 0, withheld=True),)
    with pytest.raises(ValueError, match="PUBLIC_PLAN_EXPLICIT_ROUTE_REQUIRED"):
        PlanAction(seed, "flat", ZERO, opening)
    request = PlanAction(seed, "flat", ZERO, opening, independent_entry=True)
    assert assess(request, revisions, (), 5)["after"] is None
    assert assess(request, revisions, facts(request, 1), 5)["after"] == {"long": "1", "short": "0"}


def test_old_plan_discovered_late_cannot_displace_a_newer_pause():
    old, pause = plan("old", 0, received=8), plan("pause", 6, withheld=True)
    request = PlanAction(Position(CONTRACT), "flat", ZERO, Action("ENTER_LONG", Decimal(1)), old)
    assert assess(request, (old,), facts(request, 9), 13)["after"] == {"long": "1", "short": "0"}
    blocked = assess(request, (pause, old), facts(request, 9), 13)
    assert blocked["status"] == "NOT_PERMITTED"
    assert blocked["observed_publication_revision"] == pause.revision


def test_replacing_zone_or_signal_cannot_reuse_approval():
    original = plan("original", 0)
    revised = replace(original, zone=replace(original.zone, upper=Decimal(120)))
    request = PlanAction(Position(CONTRACT), "flat", ZERO, Action("ENTER_LONG", Decimal(1)), original)
    trigger, approval = facts(request, 1)
    assert assess(request, (revised,), (trigger, approval), 5)["after"] is None
    replaced_signal = replace(trigger, source="TEST_FIXTURE_OTHER_SIGNAL")
    with pytest.raises(ValueError, match="CONFIRMATION_SCOPE_MISMATCH"):
        assess(request, (original,), (replaced_signal, approval), 5)
    with pytest.raises(ValueError, match="FIXTURE_CONFIRMATION_DISABLED"):
        assess_plan_action(request, (original,), trigger=trigger, approval=approval, as_of=ZERO + 5 * STEP)
