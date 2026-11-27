"""Replay attributed LMS research proposals against the plan known at each evaluation."""

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import argparse

from guiyi_quant.lms405 import physical_contract, timestamp
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.portfolio_tasks import REQUIRED, Book, Intent, assess
from guiyi_quant.lms405.public_conditions import Condition
from lms405_portfolio_replay import input_sources
from lms405_pre_touch_protection import analyze
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_recovery_confirmation_audit import edge_candidates
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import NIGHT_RANGE, OLD_RANGE, completed, digest, signals
from lms405_sh_protection_replacement import LIFECYCLE, LIFECYCLE_SHA
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


SH_CANDIDATE_KEYS = ("shape_end", "confirmed_at", "available_at", "boundary", "close", "ibar", "pinbar")


def sh_market_candidates(session, market, contract, lifecycle):
    day, night = (read_window(session, market, contract, date(2026, 10, day)) for day in (27, 28))
    market_digests = {f"{p}m": dict(afternoon=digest(day[p]), night=digest(night[p])) for p in (1, 5)}
    if market_digests != lifecycle["market"]:
        raise ValueError("PLAN_REPLAY_SH_MARKET_CHANGED")
    day_start, day_cut, night_start, night_cut = (
        datetime.fromisoformat(lifecycle[key]) for key in ("afternoon_start", "afternoon_cut", "night_start", "night_cut")
    )

    def recovery(cut):
        return edge_candidates(
            completed(day[1], day_start, cut), signals(day, 5, 1, side="SHORT", start=day_start, cut=cut),
            OLD_RANGE[1], "SHORT",
        )["first_shape_after_fresh_cross_and_still_beyond"]

    day_event = recovery(day_cut)
    if (day_event is None or recovery(day_event["available_at"]) is not None
            or recovery(day_event["available_at"] + US) != day_event):
        raise ValueError("PLAN_REPLAY_SH_RECOVERY_PREFIX_CHANGED")

    night_event = first_early_candidate(night, start=night_start, cutoff=night_cut, band=NIGHT_RANGE)
    if night_event is None:
        raise ValueError("PLAN_REPLAY_SH_PROTECTION_CANDIDATE_MISSING")
    return {"recovery_candidate": day_event, "protection_candidate": night_event}, market_digests


def first_early_candidate(series, *, start, cutoff, band):
    """Return the first armed shape using the completed prefix at its own reveal clock."""
    for event in signals(series, 1, 1, side="LONG", start=start, cut=cutoff):
        cut = event["available_at"] + US
        if cut > cutoff:
            break
        prefix = {period: [bar for bar in rows if bar.end + US < cut] for period, rows in series.items()}
        scoped = analyze(prefix, start=start, cut=cut, band=band, side="LONG", leg=None, variants=((1, 1),))
        candidate = scoped["variants"]["1m_to_1m"][-1]
        if candidate["confirmed_at"] != event["confirmed_at"]:
            raise ValueError("PLAN_REPLAY_SH_NIGHT_PREFIX_CHANGED")
        if candidate["pre_touch_arm"]:
            return candidate
    return None


def sh_oct27_case(*, market_input=None):
    """Run the first linked case with frozen or newly computed market candidates."""
    path = Path("output/lms405-sh-cycle-permissions-20261126/final-a.json")
    digest = "f69045985afb4b72644c450627ba269eb35c3153361d6138964ffe8c022920a6"
    report = verified_json(path, digest)
    scenario = report["scenarios"]["old_near_5m_to_1m:both_immediate"]
    candidate_inputs = {name: scenario[name] for name in ("recovery_candidate", "protection_candidate")}
    market_report = {}
    plan_ids = ("A5358325972992140", "A5358686695981271")
    position_id = "WRoAkcEppg"
    index = input_sources()
    sources = {key: load_source(index, key) for key in (*plan_ids, position_id)}
    if any(source != report["sources"][key] for key, source in sources.items()):
        raise ValueError("PLAN_REPLAY_SH_SOURCES_CHANGED")
    contract = report["contract"]
    if market_input is not None:
        lifecycle = verified_json(LIFECYCLE, LIFECYCLE_SHA)
        recomputed, market_digests = sh_market_candidates(*market_input, contract, lifecycle)
        for name, candidate in recomputed.items():
            frozen = candidate_inputs[name]
            if encoded([candidate[key] for key in SH_CANDIDATE_KEYS]) != encoded(
                [frozen[key] for key in SH_CANDIDATE_KEYS]
            ):
                raise ValueError("PLAN_REPLAY_SH_CANDIDATE_CHANGED")
        candidate_inputs = recomputed
        market_report = dict(candidate_origin="LOCAL_MDS_COMPLETED_BARS", market_digests=market_digests,
                             advance_candidate_uses_only_signal_prefix=True)
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
        candidate = candidate_inputs[candidate_name]
        shape_end, confirmed, available = (
            datetime.fromisoformat(str(candidate[key])) for key in ("shape_end", "confirmed_at", "available_at")
        )
        setup_start = shape_end - shape_period * ONE
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
            "RECOVER_ORIGINAL": dict(shape_period=5, confirmation_period=1, **candidate_inputs["recovery_candidate"]),
            "PROTECT_EARLY": dict(shape_period=1, confirmation_period=1, **candidate_inputs["protection_candidate"]),
        },
        historical_plan_revision_verified=False, public=report_rows(public), public_end=asdict(public_end),
        test_fixture=report_rows(fixture), test_fixture_end=asdict(fixture_end), author_action_samples=0,
        author_match_rate=None, executable=False, fills=None, pnl=None, **market_report,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, help="Recompute candidates using local MDS and this environment file.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PLAN_REPLAY_OUTPUT_EXISTS")
    try:
        result = sh_oct27_case() if args.env_file is None else local_market_case(args.env_file)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("PLAN_REPLAY_")
                        else "PLAN_REPLAY_INPUT_UNVERIFIED") + "\n")


def local_market_case(env_file):
    from dotenv import load_dotenv

    if not env_file.is_file():
        raise ValueError("PLAN_REPLAY_ENV_FILE_MISSING")
    load_dotenv(env_file, override=False)
    from sqlalchemy.exc import OperationalError
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            return sh_oct27_case(market_input=(session, build_market_data_service(session)))
    except MarketDataError as exc:
        raise ValueError("PLAN_REPLAY_MDS_" + exc.code) from None
    except OperationalError:
        raise ValueError("PLAN_REPLAY_LOCAL_MDS_UNAVAILABLE") from None


if __name__ == "__main__":
    main()
