"""Replay attributed LMS research proposals against the plan known at each evaluation."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import argparse

from guiyi_quant.lms405 import physical_contract, timestamp
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.portfolio_tasks import REQUIRED, Book, Intent, assess
from guiyi_quant.lms405.public_conditions import Condition
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US
from lms_near405_replay import encoded

VERSION = "lms405-plan-driven-replay-v1"
INDEPENDENT_PREFIX = "INDEPENDENT:"
INDEPENDENT_MANAGEMENT = frozenset({"CLEAR_TREND", "EXIT_COUNTER_M"})


@dataclass(frozen=True)
class PlanRevision:
    contract: str
    id: str
    published_at: datetime
    known_at: datetime
    source: str
    operations: frozenset[str]
    expires_at: datetime | None = None

    def __post_init__(self):
        physical_contract(self.contract)
        timestamp(self.published_at)
        timestamp(self.known_at)
        if (not isinstance(self.id, str) or not self.id.strip() or not isinstance(self.source, str)
                or not self.source.strip() or self.id.startswith(INDEPENDENT_PREFIX)
                or self.published_at > self.known_at
                or not isinstance(self.operations, frozenset) or not self.operations <= REQUIRED.keys()):
            raise ValueError("PLAN_REPLAY_INVALID_REVISION")
        if self.expires_at is not None:
            timestamp(self.expires_at)
            if self.expires_at <= self.known_at:
                raise ValueError("PLAN_REPLAY_INVALID_EXPIRY")


@dataclass(frozen=True)
class Evaluation:
    at: datetime
    request: Intent
    facts: tuple[Condition, ...] = ()
    approval: HandoffConfirmation | None = None
    uses_public_plan: bool = True

    def __post_init__(self):
        timestamp(self.at)
        if type(self.uses_public_plan) is not bool or not isinstance(self.request, Intent):
            raise ValueError("PLAN_REPLAY_ROUTE_REQUIRED")
        if self.request.plan_id.startswith(INDEPENDENT_PREFIX) == self.uses_public_plan:
            raise ValueError("PLAN_REPLAY_AUTHORITY_ROUTE_MISMATCH")


def current_plan(contract, revisions, as_of):
    known = [row for row in revisions if row.contract == contract and row.known_at < as_of]
    if not known:
        return None, "PLAN_NOT_AVAILABLE"
    if len(set(known)) != len({row.id for row in known}):
        return None, "PLAN_REVISION_CONFLICT"
    latest = max(row.published_at for row in known)
    choices = {row for row in known if row.published_at == latest}
    if len(choices) != 1:
        return None, "PLAN_REVISION_CONFLICT"
    (current,) = choices
    if current.expires_at is not None and as_of >= current.expires_at:
        return current, "PLAN_EXPIRED"
    return current, None


def evaluate(book, event, revisions, allow_test_fixture):
    plan, unavailable = current_plan(book.contract, revisions, event.at)
    request = event.request
    status = None
    if event.uses_public_plan:
        if unavailable:
            status = unavailable
        elif request.plan_id != plan.id:
            status = "PLAN_SUPERSEDED"
        elif request.operation not in plan.operations:
            status = "PLAN_DOES_NOT_ALLOW_ACTION"
        elif any(fact.known_at < event.at and fact.observed_at <= plan.known_at for fact in event.facts):
            status = "CONDITION_NOT_NEW_UNDER_PLAN"
    elif request.operation not in INDEPENDENT_MANAGEMENT:
        status = "INDEPENDENT_ACTION_UNSUPPORTED"
    if status:
        result = dict(status=status, after=None, unknown=[], executable=False)
    else:
        result = assess(book, request, event.facts, as_of=event.at, approval=event.approval,
                        allow_test_fixture=allow_test_fixture)
    after = result["after"] or book
    approval = event.approval if event.approval and event.approval.known_at < event.at else None
    return after, dict(
        at=event.at, contract=book.contract, episode=book.episode, operation=request.operation,
        plan_id=request.plan_id, current_plan_id=plan.id if plan else None, uses_public_plan=event.uses_public_plan,
        current_plan_source=plan.source if plan else None,
        current_plan_known_at=plan.known_at if plan else None, request_scope=request.scope, approval=approval,
        known_facts=tuple(fact for fact in event.facts if fact.known_at < event.at),
        before=book, after=after, changed=after != book, status=result["status"], unknown=result["unknown"],
    )


def replay(seed: Book, evaluations, revisions, *, cutoff, allow_test_fixture=False):
    """Run a single episode using only events and revisions strictly before each clock."""
    timestamp(cutoff)
    if type(allow_test_fixture) is not bool:
        raise ValueError("PLAN_REPLAY_BOOLEAN_FIXTURE_MODE_REQUIRED")
    if seed.known_at >= cutoff:
        return [], None
    ready = sorted((row for row in evaluations if row.at < cutoff), key=lambda row: row.at)
    if (any((row.request.before.contract, row.request.before.episode, row.request.before.direction)
            != (seed.contract, seed.episode, seed.direction) or row.at <= seed.known_at for row in ready)
            or len({row.at for row in ready}) != len(ready)):
        raise ValueError("PLAN_REPLAY_EVALUATION_SCOPE_OR_TIME_CONFLICT")
    revisions = tuple(row for row in revisions if row.contract == seed.contract and row.known_at < cutoff)
    book, rows = seed, []
    for event in ready:
        book, row = evaluate(book, event, revisions, allow_test_fixture)
        rows.append(row)
    return rows, book


def report_rows(rows):
    return [row | dict(
        before=asdict(row["before"]), after=asdict(row["after"]),
        approval=asdict(row["approval"]) if row["approval"] is not None else None,
        known_facts=[asdict(fact) for fact in row["known_facts"]],
    ) for row in rows]


def sh_oct27_case():
    """Use frozen signal candidates and explicit test approvals for the first linked case."""
    path = Path("output/lms405-sh-cycle-permissions-20261126/final-a.json")
    digest = "f69045985afb4b72644c450627ba269eb35c3153361d6138964ffe8c022920a6"
    report = verified_json(path, digest)
    scenario = report["scenarios"]["old_near_5m_to_1m:both_immediate"]
    plan_ids = ("A5358325972992140", "A5358686695981271")
    position_id = "WRoAkcEppg"
    index = input_sources()
    sources = {key: load_source(index, key) for key in (*plan_ids, position_id)}
    if any(source != report["sources"][key] for key, source in sources.items()):
        raise ValueError("PLAN_REPLAY_SH_SOURCES_CHANGED")
    contract = report["contract"]
    known_at = datetime.fromisoformat(sources[position_id]["published_at"]) + ONE
    seed = Book(contract, f"{position_id}:CONDITIONAL", "SHORT", known_at,
                Decimal(20), Decimal(20), attempt=1)
    revisions, evaluations = [], []
    before = seed
    for source_id, operation, candidate_name, shape_period in zip(
        plan_ids, ("RECOVER_ORIGINAL", "PROTECT_EARLY"), ("recovery_candidate", "protection_candidate"),
        (5, 1), strict=True,
    ):
        source = sources[source_id]
        published = datetime.fromisoformat(source["published_at"])
        revisions.append(PlanRevision(contract, source_id, published, published + ONE,
                                      source["source_url"], frozenset({operation})))
        candidate = scenario[candidate_name]
        setup_start = datetime.fromisoformat(candidate["shape_end"]) - shape_period * ONE
        confirmed = datetime.fromisoformat(candidate["confirmed_at"])
        available = datetime.fromisoformat(candidate["available_at"])
        if not setup_start < confirmed < available:
            raise ValueError("PLAN_REPLAY_SH_CANDIDATE_CLOCK_CHANGED")
        at = available + 4 * US
        request = Intent(before, operation, Decimal(20), source_id, at + ONE)
        facts = tuple(Condition(name, request.scope, contract, True, setup_start, available,
                                "TEST_FIXTURE:" + candidate_name, "EVENT_TIME") for name in REQUIRED[operation])
        approval = HandoffConfirmation(request.confirmation_scope(facts), f"TEST_FIXTURE:{operation}",
                                       True, available + US, available + 2 * US, "TEST_FIXTURE")
        evaluations.append(Evaluation(at, request, facts, approval))
        _, before = replay(seed, evaluations, revisions, cutoff=at + US, allow_test_fixture=True)
    cutoff = evaluations[-1].at + US
    fixture, fixture_end = replay(seed, evaluations, revisions, cutoff=cutoff, allow_test_fixture=True)
    public_events = tuple(Evaluation(event.at, event.request) for event in evaluations)
    public, public_end = replay(seed, public_events, revisions, cutoff=cutoff)
    if ([row["changed"] for row in fixture] != [True, True] or public_end != seed
            or any(row["changed"] for row in public)):
        raise ValueError("PLAN_REPLAY_SH_PROJECTION_DIVERGED")
    return dict(
        version=VERSION, seed=asdict(seed), sources=sources, frozen_case_sha256=digest,
        revisions=[asdict(row) | dict(operations=sorted(row.operations)) for row in revisions],
        candidates={
            "RECOVER_ORIGINAL": dict(shape_period=5, confirmation_period=1, **scenario["recovery_candidate"]),
            "PROTECT_EARLY": dict(shape_period=1, confirmation_period=1, **scenario["protection_candidate"]),
        },
        historical_plan_revision_verified=False, public=report_rows(public), public_end=asdict(public_end),
        test_fixture=report_rows(fixture), test_fixture_end=asdict(fixture_end), author_action_samples=0,
        author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PLAN_REPLAY_OUTPUT_EXISTS")
    try:
        result = sh_oct27_case()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("PLAN_REPLAY_")
                        else "PLAN_REPLAY_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
