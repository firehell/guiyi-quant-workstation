from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.portfolio_tasks import REQUIRED, Book, Intent
from guiyi_quant.lms405.public_conditions import Condition
from lms405_plan_driven_replay import Evaluation, PlanRevision, replay

START = datetime(2026, 10, 22, 12, tzinfo=UTC)
SECOND = timedelta(seconds=1)


def plan(identity, when, operations):
    return PlanRevision("JM2701", identity, when, when, f"fixture:{identity}", frozenset(operations))


def proposal(book, operation, quantity, identity, observed_at):
    at = observed_at + 4 * SECOND
    request = Intent(book, operation, Decimal(quantity), identity, at + SECOND)
    facts = tuple(Condition(name, request.scope, book.contract, True, observed_at, observed_at + SECOND,
                            "TEST_FIXTURE", "EVENT_TIME") for name in REQUIRED[operation])
    approval = HandoffConfirmation(request.confirmation_scope(facts), f"fixture:{operation}", True,
                                   at - 2 * SECOND, at - SECOND, "TEST_FIXTURE")
    return Evaluation(at, request, facts, approval)


def test_ordered_plan_replay_waits_then_advances_only_current_roles():
    seed = Book("JM2701", "test-continuous", "SHORT", START)
    original = plan("original", START, REQUIRED)
    revisions = [original]
    steps = []
    expected_positions = [(20, 0, 0), (20, 7, 0), (20, 20, 0), (20, 20, 5), (20, 0, 5), (0, 0, 5), (0, 0, 0)]
    operations = (("ENTER_TREND", 20), ("PROTECT_EARLY", 7), ("PROTECT_TOPUP", 13),
                  ("ENTER_COUNTER_M", 5), ("RECOVER_ORIGINAL", 20), ("CLEAR_TREND", 20), ("EXIT_COUNTER_M", 5))
    book = seed
    for (operation, quantity), expected in zip(operations, expected_positions, strict=True):
        step = proposal(book, operation, quantity, original.id, book.known_at + SECOND)
        steps.append(step)
        _, book = replay(seed, steps, revisions, cutoff=step.at + SECOND, allow_test_fixture=True)
        assert (book.original, book.protection, book.counter_m) == expected
    pause = plan("pause", book.known_at + SECOND, ())
    resumed = plan("resumed", pause.known_at + 8 * SECOND, ("REENTER_TREND",))
    revisions += [pause, resumed]
    waiting = proposal(book, "REENTER_TREND", 20, pause.id, pause.known_at + SECOND)
    stale = proposal(book, "REENTER_TREND", 20, resumed.id, resumed.known_at - SECOND)
    fresh = proposal(book, "REENTER_TREND", 20, resumed.id, resumed.known_at + 5 * SECOND)
    steps += [waiting, stale, fresh]
    rows, terminal = replay(seed, steps, revisions, cutoff=fresh.at + SECOND, allow_test_fixture=True)
    assert [row["status"] for row in rows[-3:]] == [
        "PLAN_DOES_NOT_ALLOW_ACTION", "CONDITION_NOT_NEW_UNDER_PLAN", "CONDITIONAL_ACTION",
    ]
    assert terminal.attempt == 2 and terminal.original == 20
    for event in steps:
        prefix, _ = replay(seed, steps, revisions, cutoff=event.at, allow_test_fixture=True)
        assert prefix == [row for row in rows if row["at"] < event.at]
    public, terminal = replay(seed, tuple(replace(e, facts=(), approval=None) for e in steps),
                              revisions, cutoff=fresh.at + SECOND)
    assert terminal == seed and not any(row["changed"] for row in public)


def test_replaced_plan_blocks_its_approval_but_pause_does_not_clear_old_book():
    seed = Book("JM2701", "test-pause", "SHORT", START, Decimal(20), attempt=1)
    original = plan("original", START, ("CLEAR_TREND",))
    exit_step = proposal(seed, "CLEAR_TREND", 20, original.id, START + SECOND)
    pause = plan("pause", exit_step.at - SECOND, ())
    rows, terminal = replay(seed, (exit_step,), (original, pause), cutoff=exit_step.at + SECOND,
                            allow_test_fixture=True)
    assert rows[0]["status"] == "PLAN_SUPERSEDED" and terminal == seed
    with pytest.raises(ValueError, match="AUTHORITY_ROUTE_MISMATCH"):
        replace(exit_step, uses_public_plan=False)
    independent = Intent(seed, "CLEAR_TREND", Decimal(20), "INDEPENDENT:research-risk", exit_step.request.expires_at)
    evidence_only = Evaluation(exit_step.at, independent, uses_public_plan=False)
    rows, terminal = replay(seed, (evidence_only,), (original, pause), cutoff=exit_step.at + SECOND)
    assert rows[0]["status"] == "INDETERMINATE" and terminal == seed


def test_expired_plan_and_late_revision_cannot_revive_an_approval():
    seed = Book("JM2701", "test-expiry", "SHORT", START, Decimal(20), attempt=1)
    step = proposal(seed, "PROTECT_REGULAR", 20, "active", START + SECOND)
    older = plan("older", START - SECOND, ("PROTECT_REGULAR",))
    active = replace(plan("active", START, ("PROTECT_REGULAR",)), expires_at=step.at)
    later = plan("new", step.at, ("PROTECT_REGULAR",))
    with pytest.raises(ValueError, match="AUTHORITY_ROUTE_MISMATCH"):
        replace(step, uses_public_plan=False)
    rows, terminal = replay(seed, (step,), (older, active, later), cutoff=step.at + SECOND, allow_test_fixture=True)
    assert rows[0]["status"] == "PLAN_EXPIRED" and terminal == seed
    assert rows[0]["current_plan_id"] == "active" and rows[0]["approval"] == step.approval
