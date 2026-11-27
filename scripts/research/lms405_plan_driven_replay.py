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
from lms405_breakout_trial_study import price_states
from lms405_jm_first_lock_handoff import DAYS as JM_TRADING_DAYS
from lms405_jm_first_lock_handoff import FOLLOWUP as JM_FOLLOWUP
from lms405_jm_first_lock_handoff import study as study_jm_handoff
from lms405_jm_m_leg_handoff import FIRST as JM_FIRST
from lms405_jm_m_leg_handoff import NEW_PLAN as JM_NEW_PLAN
from lms405_jm_m_leg_handoff import OLD_PLAN as JM_OLD_PLAN
from lms405_portfolio_replay import input_sources
from lms405_pre_touch_protection import analyze
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_public_plan_roles import load_source
from lms405_recovery_confirmation_audit import edge_candidates
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import NIGHT_RANGE, OLD_RANGE, completed, digest, signals
from lms405_sh_protection_replacement import LIFECYCLE, LIFECYCLE_SHA
from lms_near405_replay import encoded, sha

VERSION = "lms405-plan-driven-replay-v1"
INPUT_VERSION = "lms405-plan-replay-input-v1"
MARKET_REQUEST_VERSION = "lms405-plan-market-request-v1"
MARKET_SEQUENCE_VERSION = "lms405-plan-market-sequence-v1"
MARKET_SEQUENCE_TARGET_CARRY_VERSION = "lms405-plan-market-sequence-v2"
_INTERNAL_TARGET_FIELDS = frozenset({"_counter_m_target", "_capture_counter_m_target"})
INDEPENDENT_PREFIX = "INDEPENDENT:"
INDEPENDENT_MANAGEMENT = frozenset({"CLEAR_TREND", "EXIT_COUNTER_M"})
MARKET_FACT_PREFIX = "RESEARCH_MDS_CANDIDATE:"
EXTERNAL_FACT_PREFIX = "RESEARCH_EXTERNAL_EVIDENCE:"
EXTERNAL_FIXTURE_PREFIX = "TEST_FIXTURE_EXTERNAL_EVIDENCE:"
RIGHT_ENTRY_ROUTES = frozenset({"BREAK_THEN_SIGNAL", "BREAK_PRESSURE_THEN_SIGNAL"})
ENTRY_ROUTES = RIGHT_ENTRY_ROUTES | {"IN_BAND_SIGNAL", "DO_NOT_CHASE"}
COUNTER_M_ENTRY_ROUTES = frozenset({"BREAK_THEN_SIGNAL", "DO_NOT_CHASE"})
EXIT_ROLES = frozenset({"DIRECTIONAL_TARGET", "ADVERSE_EXIT"})


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
        elif any(fact.known_at < event.at and fact.source.startswith(MARKET_FACT_PREFIX)
                 and not fact.source.startswith(f"{MARKET_FACT_PREFIX}{revision_digest(plan)}:")
                 for fact in event.facts):
            status = "MARKET_FACT_PLAN_REVISION_MISMATCH"
        elif any(fact.known_at < event.at and fact.source.startswith((EXTERNAL_FACT_PREFIX, EXTERNAL_FIXTURE_PREFIX))
                 and not fact.source.startswith((f"{EXTERNAL_FACT_PREFIX}{revision_digest(plan)}:",
                                                 f"{EXTERNAL_FIXTURE_PREFIX}{revision_digest(plan)}:"))
                 for fact in event.facts):
            status = "EXTERNAL_FACT_PLAN_REVISION_MISMATCH"
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


def revision_record(plan):
    return asdict(plan) | {"operations": sorted(plan.operations)}


def revision_digest(plan):
    return sha(encoded(revision_record(plan)).encode())


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


def first_early_candidate(series, *, start, cutoff, band, side="LONG", setup_not_before=None, periods=(1, 1)):
    """Return the first armed shape using the completed prefix at its own reveal clock."""
    shape, confirm = periods
    for event in signals(series, shape, confirm, side=side, start=start, cut=cutoff):
        if setup_not_before is not None and event["shape_end"] - shape * ONE < setup_not_before:
            continue
        cut = event["available_at"] + US
        if cut > cutoff:
            break
        prefix = {period: [bar for bar in rows if bar.end + US < cut] for period, rows in series.items()}
        scoped = analyze(prefix, start=start, cut=cut, band=band, side=side, leg=None, variants=(periods,))
        candidate = scoped["variants"][f"{shape}m_to_{confirm}m"][-1]
        if candidate["confirmed_at"] != event["confirmed_at"]:
            raise ValueError("PLAN_REPLAY_SH_NIGHT_PREFIX_CHANGED")
        if candidate["pre_touch_arm"]:
            return candidate
    return None


def entry_candidate(series, *, route, side, start, cutoff, lower, upper, next_reference,
                    shape_period, confirmation_period):
    if route == "DO_NOT_CHASE":
        return None, {"status": "PLAN_WAIT_NO_CHASE"}
    if route == "IN_BAND_SIGNAL":
        events = signals(series, shape_period, confirmation_period, side=side, start=start, cut=cutoff)
        candidate = next((row for row in events if lower <= row["close"] <= upper), None)
        return candidate, {"status": "CANDIDATE_FOUND" if candidate else "NO_IN_BAND_CONFIRMATION"}

    edge, risk_edge = (upper, lower) if side == "LONG" else (lower, upper)
    minutes = completed(series[1], start, cutoff)
    pressure = route == "BREAK_PRESSURE_THEN_SIGNAL"
    paths = price_states(minutes, side, edge, risk_edge if pressure else None)
    # A bar overlapping plan activation can rule out a fresh attempt, but cannot establish a breakout.
    reference_at = next((bar.end + US for bar in series[1] if start < bar.end and bar.end + US < cutoff and (
        bar.high >= next_reference if side == "LONG" else bar.low <= next_reference
    )), None)
    first_cross_at = next((end + US for end, row in paths.items() if row["crossing"]), None)
    first_pressure_at = next((row["retest_confirmed_at"] + US for row in paths.values()
                              if row["retest_confirmed_at"] is not None), None)
    candidate = None
    for event in signals(series, shape_period, confirmation_period, side=side, start=start, cut=cutoff):
        if reference_at is not None and reference_at <= event["available_at"]:
            break
        path = paths[event["confirmed_at"]]
        entry_at = path["retest_confirmed_at"] if pressure else path["active_cross_at"]
        shape_start = event["shape_end"] - shape_period * ONE
        # A preceding close must already be known when the next shape starts.
        if path["outside"] and entry_at is not None and entry_at + US < shape_start:
            candidate = event | {"entry_precondition_known_at": entry_at + US}
            break
    return candidate, dict(status="CANDIDATE_FOUND" if candidate else "NO_FRESH_ENTRY_CONFIRMATION",
                           first_cross_known_at=first_cross_at, first_pressure_known_at=first_pressure_at,
                           next_reference_known_at=reference_at)


def exit_candidate(series, *, role, side, plan_start, fresh_start, cutoff, lower, upper,
                   shape_period, confirmation_period):
    edge = (upper if side == "LONG" else lower) if role == "DIRECTIONAL_TARGET" else (
        lower if side == "LONG" else upper
    )
    if role == "ADVERSE_EXIT":
        bar = next((bar for bar in completed(series[1], fresh_start, cutoff)
                    if (bar.close < edge if side == "LONG" else bar.close > edge)), None)
        candidate = None if bar is None else dict(
            confirmed_at=bar.end, available_at=bar.end + US, observed_at=bar.start, close=bar.close, boundary=edge,
        )
        return candidate, dict(edge=edge, status="CANDIDATE_FOUND" if candidate else "NO_ADVERSE_CLOSE")

    touched = next((bar.end + US for bar in completed(series[1], plan_start, cutoff)
                    if bar.low <= edge <= bar.high), None)
    if touched is None:
        return None, dict(edge=edge, status="TARGET_NOT_TOUCHED", target_known_at=None)
    opposite = "SHORT" if side == "LONG" else "LONG"
    candidate = next(iter(signals(series, shape_period, confirmation_period, side=opposite,
                                  start=max(fresh_start, touched + US), cut=cutoff)), None)
    return candidate, dict(edge=edge, target_known_at=touched,
                           status="CANDIDATE_FOUND" if candidate else "NO_FRESH_REVERSAL_AFTER_TARGET")


def market_position_ready(position, operation, quantity):
    original, protection, counter = position.original, position.protection, position.counter_m
    match operation:
        case "ENTER_TREND" | "REENTER_TREND":
            return not (original or protection or counter) and (position.attempt == 0) == (operation == "ENTER_TREND")
        case "ENTER_COUNTER_M":
            return not counter and position.attempt > 0
        case "CLEAR_TREND":
            return quantity == original + protection
        case "EXIT_COUNTER_M":
            return quantity <= counter
        case "RECOVER_ORIGINAL":
            return quantity == protection
        case "PROTECT_EARLY":
            return not protection and quantity <= original
        case "PROTECT_REGULAR":
            return not protection and quantity == original
        case "PROTECT_TOPUP":
            return bool(protection) and quantity == original - protection
        case _:
            raise ValueError("PLAN_REPLAY_MARKET_OPERATION_UNSUPPORTED")


def sequence_position_ready(position, operation, quantity, *, has_evidence):
    if has_evidence and operation == "ROTATE_TO_COUNTER_M":
        return not position.counter_m and quantity <= position.protection == position.original
    return market_position_ready(position, operation, quantity)


@dataclass(frozen=True)
class _CounterMTargetCarry:
    position: Book
    plan_digest: str
    trading_day: date
    band: tuple[Decimal, Decimal]
    known_at: datetime
    bar_sha256: str


def market_request(*, session, market, version, seed, revision, trading_day, start, cutoff, request_expires_at,
                   band, operation, quantity, shape_period, confirmation_period, entry_route=None,
                   next_reference=None, exit_role=None, inherit_observed_target=False, sequence_window=False,
                   _counter_m_target=None, _capture_counter_m_target=False):
    """Compile one explicitly scoped market candidate into an unsigned replay tape."""
    if version != MARKET_REQUEST_VERSION or type(sequence_window) is not bool:
        raise ValueError("PLAN_REPLAY_MARKET_REQUEST_VERSION_UNSUPPORTED")
    position, plan = input_book(seed), input_revision(revision)
    day = date.fromisoformat(trading_day)
    start, cutoff = map(datetime.fromisoformat, (start, cutoff))
    timestamp(start)
    timestamp(cutoff)
    expires = datetime.fromisoformat(request_expires_at)
    timestamp(expires)
    if (type(shape_period) is not int or type(confirmation_period) is not int
            or (shape_period, confirmation_period) not in VARIANTS):
        raise ValueError("PLAN_REPLAY_MARKET_TIMEFRAME_UNSUPPORTED")
    if not isinstance(band, list) or len(band) != 2:
        raise ValueError("PLAN_REPLAY_MARKET_BAND_ARRAY_REQUIRED")
    lower, upper = map(decimal_text, band)
    quantity = decimal_text(quantity)
    counter_m_entry = operation == "ENTER_COUNTER_M"
    entry_operation = counter_m_entry or operation in ("ENTER_TREND", "REENTER_TREND")
    entry_side = ("SHORT" if position.direction == "LONG" else "LONG") if counter_m_entry else position.direction
    exit_operation = operation in ("CLEAR_TREND", "EXIT_COUNTER_M")
    plan_wait = entry_operation and entry_route == "DO_NOT_CHASE"
    plan_permits = operation in plan.operations
    if (position.contract != plan.contract or plan_permits == plan_wait
            or not lower.is_finite() or not upper.is_finite() or not quantity.is_finite() or quantity <= 0
            or lower > upper or (lower == upper and not (
                exit_operation or entry_operation and entry_route in ("BREAK_THEN_SIGNAL", "DO_NOT_CHASE")
            ))
            or not start < cutoff or max(position.known_at, plan.known_at) >= min(cutoff, expires)
            or plan.expires_at is not None and plan.expires_at < cutoff):
        raise ValueError("PLAN_REPLAY_MARKET_REQUEST_SCOPE_INVALID")
    if entry_operation:
        routes = COUNTER_M_ENTRY_ROUTES if counter_m_entry else ENTRY_ROUTES
        if (not market_position_ready(position, operation, quantity)
                or not isinstance(entry_route, str) or entry_route not in routes):
            raise ValueError("PLAN_REPLAY_MARKET_ENTRY_SCOPE_INVALID")
        if entry_route in RIGHT_ENTRY_ROUTES:
            next_reference = decimal_text(next_reference)
            edge = upper if entry_side == "LONG" else lower
            if not next_reference.is_finite() or not (
                next_reference > edge if entry_side == "LONG" else next_reference < edge
            ):
                raise ValueError("PLAN_REPLAY_MARKET_ENTRY_REFERENCE_INVALID")
        elif next_reference is not None:
            raise ValueError("PLAN_REPLAY_MARKET_ENTRY_REFERENCE_UNEXPECTED")
    elif entry_route is not None or next_reference is not None:
        raise ValueError("PLAN_REPLAY_MARKET_ENTRY_FIELDS_UNEXPECTED")
    if exit_operation:
        if not isinstance(exit_role, str) or exit_role not in EXIT_ROLES:
            raise ValueError("PLAN_REPLAY_MARKET_EXIT_ROLE_REQUIRED")
        if not market_position_ready(position, operation, quantity):
            raise ValueError("PLAN_REPLAY_MARKET_EXIT_QUANTITY_INVALID")
        if exit_role == "ADVERSE_EXIT" and (shape_period, confirmation_period) != (1, 1):
            raise ValueError("PLAN_REPLAY_MARKET_ADVERSE_CLOSE_REQUIRES_1M")
    elif exit_role is not None:
        raise ValueError("PLAN_REPLAY_MARKET_EXIT_FIELDS_UNEXPECTED")
    carry_counter_target = (sequence_window and inherit_observed_target is True and operation == "EXIT_COUNTER_M"
                            and exit_role == "DIRECTIONAL_TARGET" and isinstance(_counter_m_target, _CounterMTargetCarry))
    carry_trend_target = operation == "CLEAR_TREND" and exit_role == "DIRECTIONAL_TARGET"
    if (type(inherit_observed_target) is not bool or type(_capture_counter_m_target) is not bool
            or (_capture_counter_m_target and not (
                sequence_window and operation == "EXIT_COUNTER_M" and exit_role == "DIRECTIONAL_TARGET"
            ))
            or (inherit_observed_target and not (carry_trend_target or carry_counter_target))
            or (_counter_m_target is not None and not (carry_counter_target and _capture_counter_m_target))):
        raise ValueError("PLAN_REPLAY_MARKET_TARGET_CARRY_SCOPE_INVALID")
    if carry_counter_target and not (
        _counter_m_target.position == position and _counter_m_target.plan_digest == revision_digest(plan)
        and _counter_m_target.trading_day == day and _counter_m_target.band == (lower, upper)
        and plan.known_at < _counter_m_target.known_at < position.known_at
    ):
        raise ValueError("PLAN_REPLAY_COUNTER_M_TARGET_IDENTITY_MISMATCH")
    series = read_window(session, market, position.contract, day)
    if start < series[1][0].start or cutoff > series[1][-1].end + 2 * US:
        raise ValueError("PLAN_REPLAY_MARKET_WINDOW_OUTSIDE_COVERAGE")
    # Strictly later than both the applicable plan and the position pre-image.
    effective_start = max(start, position.known_at + US, plan.known_at + US)
    side = position.direction
    diagnostics = {}
    if entry_operation:
        candidate, diagnostic = entry_candidate(series, route=entry_route, side=entry_side, start=effective_start,
                                               cutoff=cutoff, lower=lower, upper=upper, next_reference=next_reference,
                                               shape_period=shape_period, confirmation_period=confirmation_period)
        diagnostics["entry"] = dict(route=entry_route, next_reference=next_reference, **diagnostic)
        if counter_m_entry:
            diagnostics["entry"].update(managed_side=entry_side, band_role="COUNTER_M_INTERRUPTION")
    elif exit_operation:
        exit_side = side if operation == "CLEAR_TREND" else ("SHORT" if side == "LONG" else "LONG")
        target_start = max(start, plan.known_at + US) if inherit_observed_target else effective_start
        if carry_counter_target:
            target_start = _counter_m_target.known_at - ONE - US
        candidate, diagnostic = exit_candidate(
            series, role=exit_role, side=exit_side, plan_start=target_start,
            fresh_start=effective_start, cutoff=cutoff, lower=lower, upper=upper,
            shape_period=shape_period, confirmation_period=confirmation_period,
        )
        diagnostics["exit"] = dict(role=exit_role, managed_side=exit_side,
                                   inherit_observed_target=inherit_observed_target, **diagnostic)
        if _capture_counter_m_target:
            target_known_at = diagnostic["target_known_at"]
            target_rows = [bar for bar in series[1] if bar.end + US == target_known_at]
            if target_known_at is not None and len(target_rows) != 1:
                raise ValueError("PLAN_REPLAY_COUNTER_M_TARGET_BAR_UNVERIFIED")
            target_digest = digest(target_rows) if target_rows else None
            if carry_counter_target and (target_known_at != _counter_m_target.known_at
                                         or target_digest != _counter_m_target.bar_sha256):
                raise ValueError("PLAN_REPLAY_COUNTER_M_TARGET_MARKET_MISMATCH")
            diagnostics["exit"]["target_bar_sha256"] = target_digest
    elif operation == "RECOVER_ORIGINAL":
        if not market_position_ready(position, operation, quantity):
            raise ValueError("PLAN_REPLAY_MARKET_RECOVERY_SCOPE_INVALID")
        events = signals(series, shape_period, confirmation_period, side=side, start=effective_start, cut=cutoff)
        edge = upper if side == "SHORT" else lower
        candidate = edge_candidates(
            completed(series[confirmation_period], effective_start, cutoff), events, edge, side,
        )["first_shape_after_fresh_cross_and_still_beyond"]
    elif operation in ("PROTECT_EARLY", "PROTECT_REGULAR", "PROTECT_TOPUP"):
        if not market_position_ready(position, operation, quantity):
            raise ValueError("PLAN_REPLAY_MARKET_PROTECTION_SCOPE_INVALID")
        side = "LONG" if side == "SHORT" else "SHORT"
        if operation == "PROTECT_EARLY":
            if (shape_period, confirmation_period) not in ((1, 1), (15, 15)):
                raise ValueError("PLAN_REPLAY_MARKET_EARLY_SCOPE_UNSUPPORTED")
            candidate = first_early_candidate(series, start=start, cutoff=cutoff, band=(lower, upper),
                                              side=side, setup_not_before=effective_start,
                                              periods=(shape_period, confirmation_period))
            if (side, shape_period, confirmation_period) != ("LONG", 1, 1):
                diagnostics["protection"] = dict(protective_side=side, status=(
                    "CANDIDATE_FOUND" if candidate else "NO_FRESH_PRE_TOUCH_CONFIRMATION"
                ))
        else:
            events = signals(series, shape_period, confirmation_period, side=side, start=effective_start, cut=cutoff)
            candidate = next((row for row in events if lower <= row["close"] <= upper), None)
    else:
        raise ValueError("PLAN_REPLAY_MARKET_OPERATION_UNSUPPORTED")

    digest_start = min(start, target_start) if carry_counter_target else start
    market_digests = {f"{period}m": digest(completed(rows, digest_start, cutoff)) for period, rows in series.items()}
    evaluations = []
    cap_approval = bool(diagnostics) or sequence_window
    if cap_approval and candidate is not None:
        # The next minute can change the premise. A saved tape cannot authorize across it.
        expires = min(expires, candidate["confirmed_at"] + ONE + US)
        if diagnostics:
            diagnostics["entry" if entry_operation else "exit" if exit_operation else "protection"][
                "candidate_expires_at"
            ] = expires
    ready_before = min(cutoff, expires) if cap_approval else cutoff
    if candidate is not None and candidate["available_at"] + US < ready_before:
        known_at = candidate["available_at"]
        setup = candidate["observed_at"] if exit_role == "ADVERSE_EXIT" else candidate["shape_end"] - shape_period * ONE
        request = Intent(position, operation, quantity, plan.id, expires)
        plan_digest = revision_digest(plan)
        scope = [plan.id, position.contract, operation, shape_period, confirmation_period, lower, upper, candidate]
        if entry_operation:
            scope.extend((entry_route, next_reference))
        if exit_operation:
            scope.extend((exit_role, inherit_observed_target, diagnostics["exit"].get("target_known_at")))
            if _capture_counter_m_target:
                scope.append(diagnostics["exit"]["target_bar_sha256"])
        candidate_id = sha(encoded(scope).encode())
        facts = [
            asdict(Condition(name, request.scope, position.contract, True, setup, known_at,
                             f"{MARKET_FACT_PREFIX}{plan_digest}:{candidate_id}", "EVENT_TIME"))
            for name in REQUIRED[operation]
        ]
        evaluations.append(asdict(request) | dict(at=known_at + US, facts=facts))
    tape = json.loads(encoded(dict(
        version=INPUT_VERSION, cutoff=cutoff, seed=asdict(position),
        revisions=[revision_record(plan)], evaluations=evaluations,
    )))
    return dict(
        version=MARKET_REQUEST_VERSION, contract=position.contract, trading_day=day, operation=operation,
        candidate=candidate, timeframe=dict(shape_minutes=shape_period, confirmation_minutes=confirmation_period),
        band=(lower, upper), market_digests=market_digests, tape=tape, replay=replay_input(**tape),
        declared_plan_revision=plan.id, plan_historical_revision_verified=False, **diagnostics,
    )


def market_sequence(*, session, market, version, seed, revisions, steps, cutoff, approvals=None,
                    allow_test_fixture=False):
    """Chain nonoverlapping market windows using each prior confirmed research book."""
    if (version not in (MARKET_SEQUENCE_VERSION, MARKET_SEQUENCE_TARGET_CARRY_VERSION)
            or not isinstance(steps, list) or not isinstance(revisions, list)
            or type(allow_test_fixture) is not bool):
        raise ValueError("PLAN_REPLAY_MARKET_SEQUENCE_CONTRACT_INVALID")
    position = input_book(seed)
    plans = tuple(input_revision(row) for row in revisions)
    limit = datetime.fromisoformat(cutoff)
    timestamp(limit)
    if any(plan.contract != position.contract for plan in plans):
        raise ValueError("PLAN_REPLAY_MARKET_SEQUENCE_CONTRACT_MISMATCH")

    windows = []
    seen = set()
    previous_end = None
    for step in steps:
        key = step["id"]
        start, end = (datetime.fromisoformat(step[field]) for field in ("start", "cutoff"))
        timestamp(start)
        timestamp(end)
        if (not isinstance(key, str) or not key.strip() or key in seen
                or not start < end or (previous_end is not None and start < previous_end)
                or ({"seed", "revision", "version", "sequence_window"} | _INTERNAL_TARGET_FIELDS) & step.keys()):
            raise ValueError("PLAN_REPLAY_MARKET_SEQUENCE_WINDOW_INVALID")
        seen.add(key)
        previous_end = end
        windows.append((key, start, end, step))
    if approvals is None:
        approvals = {}
    if not isinstance(approvals, dict) or not approvals.keys() <= seen:
        raise ValueError("PLAN_REPLAY_MARKET_SEQUENCE_APPROVAL_STEP_INVALID")

    rows = []
    counter_target = None
    for key, start, end, step in windows:
        if start >= limit or position.known_at >= limit:
            break
        end = min(end, limit)
        plan, unavailable = current_plan(position.contract, plans, start)
        operation = step["operation"]
        evidence = step.get("evidence")
        quantity = decimal_text(step["quantity"])
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("PLAN_REPLAY_MARKET_SEQUENCE_QUANTITY_INVALID")
        before = asdict(position)
        row = dict(id=key, operation=operation, before=before, after=before, start=start, cutoff_exclusive=end,
                   current_plan_id=plan.id if plan else None)
        rows.append(row)
        if unavailable or plan.id != step["plan_id"]:
            row["status"] = unavailable or "PLAN_SUPERSEDED"
            continue
        if operation not in plan.operations:
            row["status"] = "PLAN_DOES_NOT_ALLOW_ACTION"
            continue
        if not sequence_position_ready(position, operation, quantity, has_evidence=evidence is not None):
            row["status"] = "POSITION_PREREQUISITE_UNMET"
            continue
        if plan.expires_at is not None:
            end = min(end, plan.expires_at)
            row["cutoff_exclusive"] = end
        if max(position.known_at, plan.known_at) + US >= end:
            row["status"] = "NO_VISIBLE_EVALUATION"
            continue

        compiled = None
        if evidence is not None:
            if (set(evidence) != {"at", "facts"} or not isinstance(evidence["facts"], list)
                    or set(step) != {"id", "plan_id", "start", "cutoff", "operation", "quantity",
                                     "request_expires_at", "evidence"}):
                raise ValueError("PLAN_REPLAY_MARKET_SEQUENCE_EVIDENCE_INVALID")
            at = datetime.fromisoformat(evidence["at"])
            timestamp(at)
            if not max(start, position.known_at) < at:
                raise ValueError("PLAN_REPLAY_MARKET_SEQUENCE_EVIDENCE_TIME_INVALID")
            if at >= end:
                row["status"] = "NO_VISIBLE_EVALUATION"
                continue
            source = input_evaluation(at=evidence["at"], before=json.loads(encoded(before)), operation=operation,
                                      quantity=step["quantity"], plan_id=plan.id, expires_at=step["request_expires_at"],
                                      facts=evidence["facts"])
            if any(fact.known_at < at and not fact.source.startswith((EXTERNAL_FACT_PREFIX, EXTERNAL_FIXTURE_PREFIX))
                   for fact in source.facts):
                row["status"] = "EXTERNAL_FACT_SCOPE_REQUIRED"
                continue
            if any(fact.known_at < at and (fact.case_id != source.request.scope or fact.contract != position.contract)
                   for fact in source.facts):
                row["status"] = "EVIDENCE_POSITION_OR_REQUEST_MISMATCH"
                continue
            row["evidence_at"] = at
            tape = dict(version=INPUT_VERSION, cutoff=end.isoformat(), seed=json.loads(encoded(before)),
                        revisions=revisions, evaluations=[dict(at=evidence["at"], before=json.loads(encoded(before)),
                            operation=operation, quantity=step["quantity"], plan_id=plan.id,
                            expires_at=step["request_expires_at"], facts=evidence["facts"])])
        else:
            arguments = {name: value for name, value in step.items() if name not in {"id", "plan_id", "cutoff"}}
            if (version == MARKET_SEQUENCE_TARGET_CARRY_VERSION and operation == "EXIT_COUNTER_M"
                    and step.get("exit_role") == "DIRECTIONAL_TARGET"):
                arguments["_capture_counter_m_target"] = True
                if step.get("inherit_observed_target") is True:
                    if (counter_target is None or counter_target.position != position
                            or counter_target.plan_digest != revision_digest(plan)
                            or counter_target.trading_day.isoformat() != step["trading_day"]
                            or counter_target.band != tuple(map(decimal_text, step["band"]))):
                        row["status"] = "COUNTER_M_TARGET_NOT_CARRIED"
                        continue
                    arguments["_counter_m_target"] = counter_target
            compiled = market_request(session=session, market=market, version=MARKET_REQUEST_VERSION,
                                      seed=json.loads(encoded(before)), revision=json.loads(encoded(revision_record(plan))),
                                      cutoff=end.isoformat(), sequence_window=True, **arguments)
            row["market"] = compiled
            tape = compiled["tape"] | {"revisions": revisions}
            if not tape["evaluations"]:
                row["status"] = "NO_MARKET_CANDIDATE"
                continue
        result = replay_input(**tape, allow_test_fixture=allow_test_fixture)
        event, = result["events"]
        pending = event.get("pending_approval_scope")
        confirmation = approvals.get(key)
        if pending is not None and confirmation is not None:
            known = datetime.fromisoformat(confirmation["known_at"])
            timestamp(known)
            if (known < event["at"] if evidence is not None else known + US < end):
                evaluation, = tape["evaluations"]
                at = max(event["at"], known + US)
                tape["evaluations"] = [evaluation | {"at": at.isoformat(), "approval": confirmation}]
                result = replay_input(**tape, allow_test_fixture=allow_test_fixture)
                event, = result["events"]
        row.update(status=event["status"], evaluation=event, after=result["final"])
        position = input_book(json.loads(encoded(result["final"])))
        if version == MARKET_SEQUENCE_TARGET_CARRY_VERSION and event["changed"]:
            counter_target = None
            if (compiled is not None and operation == "EXIT_COUNTER_M" and position.counter_m > 0
                    and step["exit_role"] == "DIRECTIONAL_TARGET"):
                counter_target = _CounterMTargetCarry(
                    position, revision_digest(plan), date.fromisoformat(step["trading_day"]), compiled["band"],
                    compiled["exit"]["target_known_at"], compiled["exit"]["target_bar_sha256"],
                )

    return dict(version=version, cutoff_exclusive=limit, steps=rows,
                final=asdict(position) if position.known_at < limit else None, test_fixture_allowed=allow_test_fixture,
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


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
    mode.add_argument("--market-request", type=Path, help="Compile a declared price band and completed bars into a tape.")
    mode.add_argument("--market-sequence", type=Path, help="Chain planned market windows with scoped approvals.")
    parser.add_argument("--allow-test-fixture", action="store_true", help="Allow fixture permissions in an input tape.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PLAN_REPLAY_OUTPUT_EXISTS")
    if ((args.input is not None and args.env_file is not None)
            or (args.allow_test_fixture and args.input is None and args.market_sequence is None)
            or ((args.market_request is not None or args.market_sequence is not None) and args.env_file is None)):
        parser.error("PLAN_REPLAY_INPUT_MODE_CONFLICT")
    try:
        if args.input is not None:
            tape = json.loads(args.input.read_text(encoding="utf-8"), object_pairs_hook=unique_fields)
            result = replay_input(**tape, allow_test_fixture=args.allow_test_fixture)
        elif args.market_request is not None:
            definition = json.loads(args.market_request.read_text(encoding="utf-8"), object_pairs_hook=unique_fields)
            if _INTERNAL_TARGET_FIELDS & definition.keys():
                raise ValueError("PLAN_REPLAY_MARKET_REQUEST_INTERNAL_FIELDS")
            result = local_market_case(args.env_file, case=lambda market_input: market_request(
                session=market_input[0], market=market_input[1], **definition,
            ))
        elif args.market_sequence is not None:
            definition = json.loads(args.market_sequence.read_text(encoding="utf-8"), object_pairs_hook=unique_fields)
            result = local_market_case(args.env_file, case=lambda market_input: market_sequence(
                session=market_input[0], market=market_input[1], allow_test_fixture=args.allow_test_fixture, **definition,
            ))
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
