from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json

import pytest

import lms405_plan_driven_replay as plan_replay
from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.portfolio_tasks import REQUIRED, Book, Intent
from guiyi_quant.lms405.public_conditions import Condition
from lms405_plan_driven_replay import INPUT_VERSION, Evaluation, PlanRevision, first_early_candidate, replay, replay_input
from lms_near405_replay import encoded

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


def test_early_protection_does_not_read_future_or_same_minute_contact():
    minute = timedelta(minutes=1)
    us = timedelta(microseconds=1)
    candles = []
    for i, prices in enumerate(((100, 107, 98, 104), (103, 105, 100, 103), (104, 107, 103, 106),
                                (106, 111, 104, 110))):
        start = START + i * minute
        candles.append(Bar("SH2701", start + minute, *map(Decimal, prices), start=start))
    band = Decimal(109), Decimal(110)
    known = candles[2].end + us
    assert first_early_candidate({1: candles}, start=START, cutoff=known, band=band) is None
    early = first_early_candidate({1: candles}, start=START, cutoff=known + us, band=band)
    later = first_early_candidate({1: candles}, start=START, cutoff=candles[-1].end + 2 * us, band=band)
    assert early == later and early["pre_touch_arm"] and early["segment_first_touch"] is None
    same_minute = candles[:2] + [replace(candles[2], high=Decimal(109))]
    assert first_early_candidate({1: same_minute}, start=START, cutoff=known + us, band=band) is None


def test_json_tape_waits_for_exact_approval_and_requires_fixture_opt_in():
    seed = Book("JM2701", "test-input", "SHORT", START)
    current = plan("current", START, ("ENTER_TREND",))
    event = proposal(seed, "ENTER_TREND", 20, current.id, START + SECOND)
    request = event.request
    tape = json.loads(encoded(dict(
        version=INPUT_VERSION, cutoff=event.at + SECOND, seed=asdict(seed),
        revisions=[asdict(current) | {"operations": ["ENTER_TREND"]}],
        evaluations=[asdict(request) | dict(at=event.at, facts=[asdict(f) for f in event.facts])],
    )))
    with pytest.raises(ValueError, match="FIXTURE_FACT_DISABLED"):
        replay_input(**tape)
    pending = replay_input(**tape, allow_test_fixture=True)
    assert pending["final"] == asdict(seed)
    assert pending["events"][0]["pending_approval_scope"] == event.approval.scope
    tape["evaluations"][0]["approval"] = json.loads(encoded(asdict(event.approval)))
    assert replay_input(**tape, allow_test_fixture=True)["final"]["original"] == Decimal(20)
    cutoff = tape | {"cutoff": event.at.isoformat()}
    assert replay_input(**cutoff)["events"] == []
    with pytest.raises(ValueError, match="DECIMAL_STRING_REQUIRED"):
        replay_input(**(tape | {"seed": tape["seed"] | {"original": 0}}))
    with pytest.raises(ValueError, match="OPERATION_LIST_REQUIRED"):
        replay_input(**(tape | {"revisions": [tape["revisions"][0] | {"operations": {"ENTER_TREND": False}}]}))
    approval_only = tape | {"revisions": [], "evaluations": [tape["evaluations"][0] | {"facts": []}]}
    with pytest.raises(ValueError, match="FIXTURE_APPROVAL_DISABLED"):
        replay_input(**approval_only)


def test_market_request_roundtrip_binds_declared_plan_and_preserves_prefix(monkeypatch):
    minute = timedelta(minutes=1)
    seed = Book("SH2701", "market-test", "SHORT", START - minute, Decimal(20), attempt=1)
    prices = ((100, 107, 98, 104), (103, 105, 100, 103), (104, 107, 103, 106), (106, 111, 104, 110))
    candles = [Bar(seed.contract, START + (i + 1) * minute, *map(Decimal, prices), start=START + i * minute)
               for i, prices in enumerate(prices)]
    monkeypatch.setattr(plan_replay, "read_window", lambda *args: {1: candles})
    definition = dict(
        version=plan_replay.MARKET_REQUEST_VERSION, trading_day="2026-10-22", start=START.isoformat(),
        cutoff=(candles[-1].end + timedelta(microseconds=2)).isoformat(), seed=json.loads(encoded(asdict(seed))),
        operation="PROTECT_EARLY", quantity="20", shape_period=1, confirmation_period=1, band=["109", "110"],
        request_expires_at=(START + 8 * minute).isoformat(),
        revision=dict(contract=seed.contract, id="market-plan", source="source-a",
                      published_at=seed.known_at.isoformat(), known_at=seed.known_at.isoformat(),
                      operations=["PROTECT_EARLY"]),
    )
    def compile_case(**changes):
        return plan_replay.market_request(session=None, market=None, **(definition | changes))

    report = compile_case()
    row, = report["replay"]["events"]
    assert row["status"] == "INDETERMINATE"
    scope = row["pending_approval_scope"]
    assert report["replay"]["final"] == asdict(seed)
    cut = (candles[2].end + timedelta(microseconds=3)).isoformat()
    assert compile_case(cutoff=cut)["replay"]["events"][0]["pending_approval_scope"] == scope
    altered = definition["revision"] | {"source": "source-b"}
    assert compile_case(revision=altered)["replay"]["events"][0]["pending_approval_scope"] != scope
    tape = report["tape"]
    event = tape["evaluations"][0]
    at = datetime.fromisoformat(event["at"])
    event["at"] = (at + 2 * timedelta(microseconds=1)).isoformat()
    event["approval"] = dict(scope=scope, id="test-approval", accepted=True, decided_at=at.isoformat(),
                             known_at=(at + timedelta(microseconds=1)).isoformat(), record_kind="TEST_FIXTURE")
    assert replay_input(**tape, allow_test_fixture=True)["final"]["protection"] == Decimal(20)
    changed_tape = tape | {"revisions": [altered]}
    assert replay_input(**changed_tape, allow_test_fixture=True)["events"][0]["status"] == (
        "MARKET_FACT_PLAN_REVISION_MISMATCH"
    )
    with pytest.raises(ValueError, match="BAND_ARRAY_REQUIRED"):
        compile_case(band={"109": False, "110": False})
