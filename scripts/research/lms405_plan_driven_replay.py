"""Replay attributed LMS research proposals against the plan known at each evaluation."""

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import argparse
import json

from guiyi_quant.lms405 import physical_contract, timestamp
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.portfolio_tasks import REQUIRED, ROTATION_VERSION, Book, Intent, assess
from guiyi_quant.lms405.public_conditions import Condition
from lms405_jm_first_lock_handoff import DAYS as JM_TRADING_DAYS
from lms405_jm_first_lock_handoff import FOLLOWUP as JM_FOLLOWUP
from lms405_jm_first_lock_handoff import study as study_jm_handoff
from lms405_jm_m_leg_handoff import FIRST as JM_FIRST
from lms405_jm_m_leg_handoff import NEW_PLAN as JM_NEW_PLAN
from lms405_jm_m_leg_handoff import OLD_PLAN as JM_OLD_PLAN
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
INPUT_VERSION = "lms405-plan-replay-input-v1"
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


def unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("PLAN_REPLAY_DUPLICATE_INPUT_FIELD")
    return result


def decimal_text(value):
    if not isinstance(value, str):
        raise ValueError("PLAN_REPLAY_DECIMAL_STRING_REQUIRED")
    return Decimal(value)


def input_book(record):
    values = record.copy()
    values["known_at"] = datetime.fromisoformat(values["known_at"])
    for name in ("original", "protection", "counter_m"):
        values[name] = decimal_text(values[name])
    return Book(**values)


def input_revision(record):
    values = record.copy()
    for name in ("published_at", "known_at", "expires_at"):
        if values.get(name) is not None:
            values[name] = datetime.fromisoformat(values[name])
    operations = values["operations"]
    if (not isinstance(operations, list) or any(not isinstance(item, str) for item in operations)
            or len(set(operations)) != len(operations)):
        raise ValueError("PLAN_REPLAY_OPERATION_LIST_REQUIRED")
    values["operations"] = frozenset(operations)
    return PlanRevision(**values)


def input_evaluation(*, at, before, operation, quantity, plan_id, expires_at, facts=(), approval=None,
                     uses_public_plan=True):
    request = Intent(input_book(before), operation, decimal_text(quantity), plan_id, datetime.fromisoformat(expires_at))
    conditions = tuple(Condition(
        **(row | {
            "observed_at": datetime.fromisoformat(row["observed_at"]),
            "known_at": datetime.fromisoformat(row["known_at"]),
        }),
    ) for row in facts)
    confirmation = None if approval is None else HandoffConfirmation(**(approval | {
        "decided_at": datetime.fromisoformat(approval["decided_at"]),
        "known_at": datetime.fromisoformat(approval["known_at"]),
    }))
    return Evaluation(datetime.fromisoformat(at), request, conditions, confirmation, uses_public_plan)


def replay_input(*, version, cutoff, seed, revisions, evaluations, allow_test_fixture=False):
    if version != INPUT_VERSION:
        raise ValueError("PLAN_REPLAY_INPUT_VERSION_UNSUPPORTED")
    if not isinstance(revisions, list) or not isinstance(evaluations, list):
        raise ValueError("PLAN_REPLAY_REVISION_AND_EVALUATION_LISTS_REQUIRED")
    start = input_book(seed)
    plans = tuple(input_revision(row) for row in revisions)
    events = tuple(input_evaluation(**row) for row in evaluations)
    as_of = datetime.fromisoformat(cutoff)
    if not allow_test_fixture and any(
        fact.source.startswith("TEST_FIXTURE") and fact.known_at < event.at
        for event in events if event.at < as_of for fact in event.facts
    ):
        raise ValueError("PLAN_REPLAY_FIXTURE_FACT_DISABLED")
    if not allow_test_fixture and any(
        event.approval is not None and event.approval.record_kind == "TEST_FIXTURE"
        and event.approval.known_at < event.at < as_of for event in events
    ):
        raise ValueError("PLAN_REPLAY_FIXTURE_APPROVAL_DISABLED")
    rows, final = replay(start, events, plans, cutoff=as_of, allow_test_fixture=allow_test_fixture)
    by_time = {event.at: event for event in events if event.at < as_of}
    rendered = report_rows(rows)
    for row, raw in zip(rendered, rows, strict=True):
        request = by_time[raw["at"]].request
        row["request"] = asdict(request)
        if raw["unknown"] == ["SCOPED_APPROVAL"] and raw["status"] == "INDETERMINATE":
            admitted = tuple(fact for fact in raw["known_facts"]
                             if fact.time_kind == "EVENT_TIME" and raw["before"].known_at < fact.observed_at)
            row["pending_approval_scope"] = request.confirmation_scope(admitted)
    return dict(
        version=VERSION, input_version=version, cutoff_exclusive=as_of,
        seed=asdict(start) if start.known_at < as_of else None,
        events=rendered, final=asdict(final) if final is not None else None,
        test_fixture_allowed=allow_test_fixture, author_action_samples=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
    )


SH_CANDIDATE_KEYS = ("shape_end", "confirmed_at", "available_at", "boundary", "close", "ibar", "pinbar")
JM_CASE = (
    Path("output/lms405-jm-partial-carry-20261126/verified-a.json"),
    "eddece8ff04e266bd3722a5b1153bb55712266414b7837c1bbaaa92afc03945e",
)
JM_PATH = "m_far_strict_close/m_near_5m_to_1m_same_run/day_close/divider_near_1m_to_1m_same_run"


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


def jm_projection(seed, revisions, path, retained):
    gates, starts = path["gates"], path["shape_starts"]
    before, evaluations = seed, []
    size = seed.protection
    rotation = (
        (("open_m", "ROTATE_TO_COUNTER_M", size - retained),) if retained else
        (("clear_old", "CLEAR_TREND", seed.original + size), ("open_m", "ENTER_COUNTER_M", size))
    )
    for key, operation, quantity in (*rotation, ("exit_m", "EXIT_COUNTER_M", size),
                                     ("new_short", "REENTER_TREND", seed.original)):
        revision = revisions[1] if key == "new_short" else revisions[0]
        confirmed = datetime.fromisoformat(str(gates[key]))
        setup = datetime.fromisoformat(str(starts.get(key, gates[key])))
        available, at = confirmed + US, confirmed + 6 * US
        if not before.known_at < setup <= confirmed:
            raise ValueError("PLAN_REPLAY_JM_SETUP_NOT_FRESH")
        request = Intent(before, operation, quantity, revision.id, at + ONE)
        facts = tuple(Condition(name, request.scope, seed.contract, True, setup, available,
                                f"TEST_FIXTURE_JM:{key}", "EVENT_TIME") for name in REQUIRED[operation])
        approval = HandoffConfirmation(request.confirmation_scope(facts), f"TEST_FIXTURE:{request.scope}",
                                       True, available + US, available + 2 * US, "TEST_FIXTURE")
        evaluations.append(Evaluation(at, request, facts, approval))
        _, before = replay(seed, evaluations, revisions, cutoff=at + US, allow_test_fixture=True)
        if before.known_at != at:
            raise ValueError("PLAN_REPLAY_JM_FIXTURE_STEP_REJECTED")
    cutoff = evaluations[-1].at + US
    fixture, final = replay(seed, evaluations, revisions, cutoff=cutoff, allow_test_fixture=True)
    public, public_end = replay(seed, [Evaluation(row.at, row.request) for row in evaluations], revisions, cutoff=cutoff)
    if final.original != seed.original or final.attempt != seed.attempt + 1 or public_end != seed:
        raise ValueError("PLAN_REPLAY_JM_FRESH_SHORT_DIVERGED")
    return dict(
        retained_old_protection_as_m=retained, closed_old_short=seed.original,
        replaced_old_long=size - retained, opened_new_m_long=size - retained, fresh_short=final.original,
        before_night_entry=asdict(fixture[-1]["before"]), new_short_attempt=final.attempt,
        research_traded_lot_count=seed.original + 2 * (size - retained) + size + final.original,
        public=report_rows(public), test_fixture=[
            row | {"request_quantity": event.request.quantity}
            for row, event in zip(report_rows(fixture), evaluations, strict=True)
        ], within_rotation_order_known=False,
    )


def jm_oct23_case(*, market_input=None):
    frozen = verified_json(*JM_CASE)
    report = frozen
    if market_input is not None:
        report = study_jm_handoff(*market_input, with_partial_carry=True)
        if encoded(report) != encoded(frozen):
            raise ValueError("PLAN_REPLAY_JM_MDS_RESULT_CHANGED")
    source_ids = (JM_FIRST, JM_OLD_PLAN, JM_NEW_PLAN)
    index = input_sources()
    sources = {key: load_source(index, key) for key in source_ids}
    if any(source != report["sources"][key] for key, source in sources.items()):
        raise ValueError("PLAN_REPLAY_JM_SOURCES_CHANGED")
    full = report["action_clock_comparison"]["paths"][JM_PATH]
    partial = report["partial_carry_comparison"]["paths"][JM_PATH]
    joint = partial["first_mixed_post_and_close"]
    full_checks = full["checks"]
    compatible_day_triplets = {key: [0, *values] for key, values in joint.items() if (
        full_checks["first_to_mixed_post"].get(" / ".join(key.split(" / ")[:2]))
        and full_checks["first_to_close"].get(" / ".join(key.split(" / ")[::2]))
    )}
    retained = {n for values in compatible_day_triplets.values() for n in values}
    if not compatible_day_triplets or not partial["compatible_night_quote_labels"]:
        raise ValueError("PLAN_REPLAY_JM_COMPARABLE_PRICE_PATH_MISSING")
    visible = verified_json(*JM_FOLLOWUP)["visible"]
    legs = visible[JM_FIRST]["legs"]
    seed_at = datetime.fromisoformat(sources[JM_FIRST]["published_at"]) + ONE
    seed = Book("JM2701", "JM:OCT22-23:CONDITIONAL", "SHORT", seed_at,
                Decimal(legs["short"]["quantity"]), Decimal(legs["long"]["quantity"]), attempt=1)
    revisions = []
    for key, operations in (
        (JM_OLD_PLAN, {"CLEAR_TREND", "ENTER_COUNTER_M", "ROTATE_TO_COUNTER_M", "EXIT_COUNTER_M"}),
        (JM_NEW_PLAN, {"REENTER_TREND"}),
    ):
        source = sources[key]
        published = datetime.fromisoformat(source["published_at"])
        revisions.append(PlanRevision(seed.contract, key, published, published + ONE,
                                      source["source_url"], frozenset(operations)))
    return dict(
        version=VERSION, contract=seed.contract, seed=asdict(seed), sources=sources, compared_path=JM_PATH,
        rotation_version=ROTATION_VERSION,
        trading_days=JM_TRADING_DAYS, frozen_case_sha256=JM_CASE[1],
        local_market_recomputed=market_input is not None,
        joint_day_price_constraints=compatible_day_triplets,
        compatible_night_quote_labels=partial["compatible_night_quote_labels"],
        historical_plan_revision_verified=False, actual_release_or_entry_at=None,
        cases={str(n): jm_projection(seed, revisions, full, Decimal(n)) for n in sorted(retained)},
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, help="Recompute candidates using local MDS and this environment file.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--case", choices=("sh-oct27", "jm-oct23"))
    mode.add_argument("--input", type=Path, help="Replay a versioned JSON tape with supplied market facts and permissions.")
    parser.add_argument("--allow-test-fixture", action="store_true", help="Allow fixture permissions in an input tape.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PLAN_REPLAY_OUTPUT_EXISTS")
    if (args.input is not None and args.env_file is not None) or (args.allow_test_fixture and args.input is None):
        parser.error("PLAN_REPLAY_INPUT_MODE_CONFLICT")
    try:
        if args.input is not None:
            tape = json.loads(args.input.read_text(encoding="utf-8"), object_pairs_hook=unique_fields)
            result = replay_input(**tape, allow_test_fixture=args.allow_test_fixture)
        else:
            case = jm_oct23_case if args.case == "jm-oct23" else sh_oct27_case
            result = case() if args.env_file is None else local_market_case(args.env_file, case=case)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (KeyError, ValueError, OSError, TypeError, AttributeError, ArithmeticError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("PLAN_REPLAY_")
                        else "PLAN_REPLAY_INPUT_UNVERIFIED") + "\n")


def local_market_case(env_file, *, case=sh_oct27_case):
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
            return case(market_input=(session, build_market_data_service(session)))
    except MarketDataError as exc:
        raise ValueError("PLAN_REPLAY_MDS_" + exc.code) from None
    except OperationalError:
        raise ValueError("PLAN_REPLAY_LOCAL_MDS_UNAVAILABLE") from None


if __name__ == "__main__":
    main()
