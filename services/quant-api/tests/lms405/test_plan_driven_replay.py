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


def test_plan_entry_requires_a_fresh_shape_before_target_and_waits_for_approval(monkeypatch):
    minute = timedelta(minutes=1)
    microsecond = timedelta(microseconds=1)
    prices = ((98, 100, 97, 99), (99, 104, 99, 102), (102, 106, 101, 104),
              (104, 105, 102, 104), (104, 107, 104, 106), (106, 110, 105, 108))
    bars = [Bar("JM2701", START + (i + 1) * minute, *map(Decimal, prices), start=START + i * minute)
            for i, prices in enumerate(prices)]
    monkeypatch.setattr(plan_replay, "read_window", lambda *args: {1: bars})
    seed = Book("JM2701", "entry-test", "LONG", START - minute)
    definition = dict(
        version=plan_replay.MARKET_REQUEST_VERSION, trading_day="2026-10-22", start=START.isoformat(),
        cutoff=(bars[-1].end + 2 * microsecond).isoformat(), seed=json.loads(encoded(asdict(seed))),
        operation="ENTER_TREND", quantity="1", shape_period=1, confirmation_period=1, band=["100", "100"],
        entry_route="BREAK_THEN_SIGNAL", next_reference="110",
        request_expires_at=(START + 8 * minute).isoformat(),
        revision=dict(contract=seed.contract, id="market-entry", source="source-entry",
                      published_at=seed.known_at.isoformat(), known_at=seed.known_at.isoformat(),
                      operations=["ENTER_TREND"]),
    )

    def compile_case(**changes):
        return plan_replay.market_request(session=None, market=None, **(definition | changes))

    report = compile_case()
    row, = report["replay"]["events"]
    assert report["candidate"]["confirmed_at"] == bars[4].end
    assert report["candidate"]["entry_precondition_known_at"] == bars[1].end + microsecond
    assert row["status"] == "INDETERMINATE" and report["replay"]["final"] == asdict(seed)
    cutoff = (bars[4].end + 3 * microsecond).isoformat()
    assert compile_case(cutoff=cutoff)["tape"]["evaluations"] == report["tape"]["evaluations"]
    assert compile_case(next_reference="107")["candidate"] is None
    assert compile_case(next_reference="106")["replay"]["events"] == []
    # The opening minute may block chasing even if its intraminute order is unknown.
    bars[0] = replace(bars[0], high=Decimal(110))
    partial_start = (START + timedelta(seconds=30)).isoformat()
    partial = compile_case(start=partial_start)
    assert partial["entry"]["next_reference_known_at"] == bars[0].end + microsecond
    assert partial["candidate"] is None
    bars[0] = replace(bars[0], high=Decimal(100))

    tape = report["tape"]
    event, = tape["evaluations"]
    proposal_at = datetime.fromisoformat(event["at"])
    event["at"] = (proposal_at + 2 * microsecond).isoformat()
    event["approval"] = dict(scope=row["pending_approval_scope"], id="entry-fixture", accepted=True,
                             decided_at=proposal_at.isoformat(), known_at=(proposal_at + microsecond).isoformat(),
                             record_kind="TEST_FIXTURE")
    approved = replay_input(**tape, allow_test_fixture=True)
    assert approved["final"]["original"] == Decimal(1) and approved["final"]["attempt"] == 1
    event["at"] = report["entry"]["candidate_expires_at"].isoformat()
    later = replay_input(**(tape | {"cutoff": (bars[-1].end + 3 * microsecond).isoformat()}), allow_test_fixture=True)
    assert later["events"][0]["status"] == "EXPIRED" and later["final"] == asdict(seed)

    wait_plan = definition["revision"] | {"operations": []}
    wait = compile_case(entry_route="DO_NOT_CHASE", next_reference=None, revision=wait_plan)
    assert wait["entry"]["status"] == "PLAN_WAIT_NO_CHASE" and wait["tape"]["evaluations"] == []
    with pytest.raises(ValueError, match="REQUEST_SCOPE_INVALID"):
        compile_case(entry_route="DO_NOT_CHASE", next_reference=None)

    reentry = dict(operation="REENTER_TREND", seed=definition["seed"] | {"attempt": 1},
                   revision=definition["revision"] | {"operations": ["REENTER_TREND"]})
    retry = compile_case(**reentry)
    retry_row, = retry["replay"]["events"]
    assert retry_row["unknown"] == ["SCOPED_APPROVAL"]
    assert {f["name"] for f in retry_row["known_facts"]} == {"FRESH_REENTRY_SIGNAL", "PLAN_REENTRY_ALLOWED"}
    assert retry_row["pending_approval_scope"] != row["pending_approval_scope"]
    with pytest.raises(ValueError, match="ENTRY_SCOPE_INVALID"):
        compile_case(**(reentry | {"seed": reentry["seed"] | {"original": "1"}}))
    late_seed = reentry["seed"] | {"known_at": (bars[1].end + microsecond).isoformat()}
    assert compile_case(**(reentry | {"seed": late_seed}))["candidate"] is None


def test_plan_exit_keeps_other_legs_and_requires_explicit_role_and_fresh_evidence(monkeypatch):
    minute = timedelta(minutes=1)
    us = timedelta(microseconds=1)
    prices = ((100, 111, 99, 108), (108, 109, 103, 105), (105, 108, 104, 106),
              (106, 107, 101, 102), (102, 103, 96, 99), (99, 111, 99, 110), (110, 111, 107, 108))
    bars = [Bar("SH2701", START + (i + 1) * minute, *map(Decimal, prices), start=START + i * minute)
            for i, prices in enumerate(prices)]
    monkeypatch.setattr(plan_replay, "read_window", lambda *args: {1: bars})
    seed = Book("SH2701", "exit-test", "LONG", START + minute + us, Decimal(2), Decimal(1), Decimal(1), 1)
    definition = dict(
        version=plan_replay.MARKET_REQUEST_VERSION, trading_day="2026-10-22", start=START.isoformat(),
        cutoff=(bars[-1].end + 2 * us).isoformat(), seed=json.loads(encoded(asdict(seed))),
        revision=dict(contract=seed.contract, id="exit-plan", source="source-exit",
                      published_at=(START - minute).isoformat(), known_at=(START - minute).isoformat(),
                      operations=["CLEAR_TREND", "EXIT_COUNTER_M"]),
        operation="CLEAR_TREND", quantity="3", shape_period=1, confirmation_period=1, band=["110", "110"],
        request_expires_at=(START + 8 * minute).isoformat(), exit_role="DIRECTIONAL_TARGET",
    )

    def compile_case(**changes):
        return plan_replay.market_request(session=None, market=None, **(definition | changes))

    assert compile_case()["exit"]["target_known_at"] == bars[5].end + us
    assert compile_case()["candidate"] is None
    report = compile_case(inherit_observed_target=True)
    assert report["exit"]["target_known_at"] == bars[0].end + us
    assert report["candidate"]["confirmed_at"] == bars[3].end
    row, = report["replay"]["events"]
    assert report["replay"]["final"] == asdict(seed) and row["unknown"] == ["SCOPED_APPROVAL"]
    tape = report["tape"]
    event, = tape["evaluations"]
    at = datetime.fromisoformat(event["at"])
    event["at"] = (at + 2 * us).isoformat()
    event["approval"] = dict(scope=row["pending_approval_scope"], id="exit-fixture", accepted=True,
                             decided_at=at.isoformat(), known_at=(at + us).isoformat(), record_kind="TEST_FIXTURE")
    cleared = replay_input(**tape, allow_test_fixture=True)["final"]
    assert (cleared["original"], cleared["protection"], cleared["counter_m"]) == (0, 0, 1)

    with pytest.raises(ValueError, match="EXIT_ROLE_REQUIRED"):
        compile_case(exit_role="PROTECTION")
    m = compile_case(operation="EXIT_COUNTER_M", quantity="1", seed=json.loads(encoded(cleared)),
                     exit_role="ADVERSE_EXIT", band=["98", "109"])
    assert m["exit"]["managed_side"] == "SHORT"
    assert m["candidate"]["confirmed_at"] == bars[5].end
    assert m["replay"]["events"][0]["unknown"] == ["SCOPED_APPROVAL"]


def test_market_sequence_uses_only_confirmed_books_and_rechecks_the_active_plan(monkeypatch):
    minute, us = timedelta(minutes=1), timedelta(microseconds=1)
    values = ((100, 107, 98, 104), (103, 105, 100, 103), (104, 107, 103, 106), (106, 111, 104, 110))
    bars = [Bar("SH2701", START + (i + 1) * minute, *map(Decimal, prices), start=START + i * minute)
            for i, prices in enumerate(values + values + (values[-1],))]
    monkeypatch.setattr(plan_replay, "read_window", lambda *args: {1: bars})
    seed = Book("SH2701", "sequence-test", "SHORT", START - minute, Decimal(20), attempt=1)
    first = PlanRevision(seed.contract, "protect", START - minute, START - minute, "source-early",
                         frozenset({"PROTECT_EARLY"}))
    second = PlanRevision(seed.contract, "topup", START + 3 * minute + 5 * us, START + 3 * minute + 5 * us,
                          "source-topup", frozenset({"PROTECT_TOPUP"}))
    first_end, last_end = START + 4 * minute, bars[-1].end + 2 * us
    common = dict(trading_day="2026-10-22", shape_period=1, confirmation_period=1)
    steps = [common | dict(id="early", plan_id=first.id, operation="PROTECT_EARLY", quantity="7",
                           start=START.isoformat(), cutoff=first_end.isoformat(),
                           request_expires_at=first_end.isoformat(), band=["109", "110"]),
             common | dict(id="topup", plan_id=second.id, operation="PROTECT_TOPUP", quantity="13",
                           start=first_end.isoformat(), cutoff=last_end.isoformat(),
                           request_expires_at=last_end.isoformat(), band=["105", "107"])]
    plans = json.loads(encoded([plan_replay.revision_record(p) for p in (first, second)]))
    definition = dict(version=plan_replay.MARKET_SEQUENCE_VERSION, seed=json.loads(encoded(asdict(seed))),
                      cutoff=last_end.isoformat(), revisions=plans, steps=steps)

    def run(**changes):
        return plan_replay.market_sequence(session=None, market=None, **(definition | changes))

    def confirm(row, *, accepted=True, delay=1):
        at = row["evaluation"]["at"]
        return dict(scope=row["evaluation"]["pending_approval_scope"], id=f"approval-{row['id']}",
                    accepted=accepted, decided_at=at.isoformat(), known_at=(at + delay * us).isoformat(),
                    record_kind="TEST_FIXTURE")

    baseline = run()
    assert [row["status"] for row in baseline["steps"]] == ["INDETERMINATE", "POSITION_PREREQUISITE_UNMET"]
    first_approval = confirm(baseline["steps"][0])
    with pytest.raises(ValueError, match="FIXTURE_APPROVAL_DISABLED"):
        run(approvals={"early": first_approval})
    left = run(approvals={"early": first_approval}, allow_test_fixture=True)
    assert left["steps"][1]["before"] == left["steps"][0]["after"]
    assert left["final"]["protection"] == 7
    approvals = {"early": first_approval, "topup": confirm(left["steps"][1])}
    complete = run(approvals=approvals, allow_test_fixture=True)
    assert [row["status"] for row in complete["steps"]] == ["CONDITIONAL_ACTION"] * 2
    assert complete["final"]["protection"] == 20
    assert run(cutoff=first_end.isoformat(), approvals=approvals, allow_test_fixture=True)["steps"] == complete["steps"][:1]

    rejected = run(approvals={"early": confirm(baseline["steps"][0], accepted=False)}, allow_test_fixture=True)
    assert [row["status"] for row in rejected["steps"]] == ["REJECTED", "POSITION_PREREQUISITE_UNMET"]
    late = run(approvals={"early": confirm(baseline["steps"][0], delay=6)}, allow_test_fixture=True)
    assert late["steps"][0]["status"] == "PLAN_SUPERSEDED" and late["final"] == asdict(seed)
    stale_topup = confirm(left["steps"][1], delay=1_000_000 * 60)
    expired = run(approvals={"early": first_approval, "topup": stale_topup}, allow_test_fixture=True)
    assert expired["steps"][1]["status"] == "EXPIRED" and expired["final"] == left["final"]
    short_end = first_end - 30 * timedelta(seconds=1)
    shorter_plans = [plans[0] | {"expires_at": short_end.isoformat()}, plans[1]]
    assert run(revisions=shorter_plans)["steps"][0]["cutoff_exclusive"] == short_end


def test_sequence_external_m_evidence_is_scoped_to_the_carried_book():
    seed = Book("JM2701", "m-sequence", "SHORT", START, Decimal(20), Decimal(20), attempt=1)
    rev = plan("m-plan", START - SECOND, ("ROTATE_TO_COUNTER_M", "EXIT_COUNTER_M"))
    def bind(event):
        prefix = f"{plan_replay.EXTERNAL_FIXTURE_PREFIX}{plan_replay.revision_digest(rev)}:"
        facts = tuple(replace(fact, source=prefix + fact.source) for fact in event.facts)
        approval = replace(event.approval, scope=event.request.confirmation_scope(facts))
        return replace(event, facts=facts, approval=approval)

    rotation = bind(proposal(seed, "ROTATE_TO_COUNTER_M", 7, rev.id, START + SECOND))
    _, m_book = replay(seed, (rotation,), (rev,), cutoff=rotation.at + SECOND, allow_test_fixture=True)
    exit_m = bind(proposal(m_book, "EXIT_COUNTER_M", 20, rev.id, rotation.at + 8 * SECOND))

    def step(key, event):
        return dict(id=key, plan_id=rev.id, operation=event.request.operation,
                    quantity=str(event.request.quantity), start=event.at - SECOND, cutoff=event.at + SECOND,
                    request_expires_at=event.request.expires_at,
                    evidence=dict(at=event.at, facts=[asdict(fact) for fact in event.facts]))

    data = json.loads(encoded(dict(version=plan_replay.MARKET_SEQUENCE_VERSION, seed=asdict(seed),
                                   revisions=[plan_replay.revision_record(rev)],
                                   steps=[step("rotate", rotation), step("exit-m", exit_m)],
                                   cutoff=exit_m.at + SECOND)))
    approvals = json.loads(encoded({"rotate": asdict(rotation.approval), "exit-m": asdict(exit_m.approval)}))

    def run(**changes):
        return plan_replay.market_sequence(session=None, market=None, **(data | changes))

    with pytest.raises(ValueError, match="FIXTURE_FACT_DISABLED"):
        run()
    pending = run(allow_test_fixture=True)
    assert [row["status"] for row in pending["steps"]] == ["INDETERMINATE", "POSITION_PREREQUISITE_UNMET"]
    complete = run(approvals=approvals, allow_test_fixture=True)
    assert complete["steps"][0]["after"] == complete["steps"][1]["before"]
    assert complete["steps"][0]["after"]["counter_m"] == 20 and complete["final"]["counter_m"] == 0
    changed = data["seed"] | {"original": "18", "protection": "18"}
    mismatched = run(seed=changed, approvals=approvals, allow_test_fixture=True)
    assert mismatched["steps"][0]["status"] == "EVIDENCE_POSITION_OR_REQUEST_MISMATCH"
    revised = data["revisions"][0] | {"source": "revised-source"}
    stale = run(revisions=[revised], approvals=approvals, allow_test_fixture=True)
    assert stale["steps"][0]["status"] == "EXTERNAL_FACT_PLAN_REVISION_MISMATCH"
    assert stale["final"] == asdict(seed)
    late = approvals | {"rotate": approvals["rotate"] | {"known_at": rotation.at.isoformat()}}
    assert run(approvals=late, allow_test_fixture=True)["final"] == asdict(seed)
    cut = (rotation.at + SECOND).isoformat()
    assert run(cutoff=cut, approvals=approvals, allow_test_fixture=True)["steps"] == complete["steps"][:1]
