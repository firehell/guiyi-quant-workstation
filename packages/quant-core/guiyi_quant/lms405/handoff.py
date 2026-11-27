"""Conditional research handoffs between trend protection and short-term M."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json

from . import Action, Position, timestamp
from .public_conditions import Condition, PublicCase, assess_case

VERSION = "lms405-plan-handoff-v1"
LOCK_ROUTES = {"RESUME_ORIGINAL", "COUNTER_M_FROM_LOCK"}
COUNTER_ROUTES = {"COUNTER_M_FROM_LOCK", "COUNTER_M_AFTER_CLEAR"}
ROUTES = LOCK_ROUTES | COUNTER_ROUTES | {"REENTER_ORIGINAL"}


@dataclass(frozen=True)
class Handoff:
    route: str
    before: Position
    original_side: str
    plan_id: str
    cycle_id: str
    next_id: str | None
    position_since: datetime
    position_known_at: datetime

    def __post_init__(self):
        if self.route not in ROUTES or self.original_side not in {"LONG", "SHORT"}:
            raise ValueError("UNKNOWN_HANDOFF_ROUTE_OR_SIDE")
        if not isinstance(self.before, Position):
            raise ValueError("HANDOFF_POSITION_REQUIRED")
        if not all(isinstance(v, str) and v.strip() for v in (self.plan_id, self.cycle_id)):
            raise ValueError("PLAN_AND_CYCLE_REQUIRED")
        if self.route == "RESUME_ORIGINAL":
            if self.next_id is not None:
                raise ValueError("RESUMPTION_MUST_KEEP_CYCLE")
        elif (not isinstance(self.next_id, str) or not self.next_id.strip()
              or self.next_id in (self.plan_id, self.cycle_id)):
            raise ValueError("DISTINCT_HANDOFF_ID_REQUIRED")
        long, short = self.before.long, self.before.short
        if not (long == short > 0 if self.route in LOCK_ROUTES else long == short == 0):
            raise ValueError("HANDOFF_POSITION_MISMATCH")
        timestamp(self.position_since)
        timestamp(self.position_known_at)
        if self.position_known_at < self.position_since:
            raise ValueError("POSITION_KNOWN_BEFORE_EFFECTIVE")

    @property
    def scope(self):
        payload = json.dumps([VERSION, asdict(self)], sort_keys=True, default=str)
        return sha256(payload.encode()).hexdigest()

    def confirmation_scope(self, source, source_available_at, version_405):
        policy = (self.scope, source, source_available_at.isoformat(), version_405)
        return sha256(json.dumps(policy).encode()).hexdigest()


@dataclass(frozen=True)
class HandoffConfirmation:
    scope: str
    id: str
    accepted: bool
    decided_at: datetime
    known_at: datetime
    record_kind: str

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip() or type(self.accepted) is not bool:
            raise ValueError("INVALID_HANDOFF_CONFIRMATION")
        if self.record_kind not in {"HUMAN_RESEARCH_DECISION", "TEST_FIXTURE"}:
            raise ValueError("HANDOFF_CONFIRMATION_KIND_REQUIRED")
        timestamp(self.decided_at)
        timestamp(self.known_at)
        if self.known_at < self.decided_at:
            raise ValueError("CONFIRMATION_KNOWN_BEFORE_DECISION")


def assess_handoff(
    request: Handoff, facts: tuple[Condition, ...], *, as_of: datetime,
    source: str, source_available_at: datetime, version_405: bool | None,
    approval: HandoffConfirmation | None = None, allow_test_fixture: bool = False,
) -> dict:
    """Check a proposed research path. The result does not apply the action."""
    timestamp(as_of)
    timestamp(source_available_at)
    scope = request.scope
    if type(allow_test_fixture) is not bool:
        raise ValueError("BOOLEAN_FIXTURE_MODE_REQUIRED")
    if approval is not None and not isinstance(approval, HandoffConfirmation):
        raise ValueError("HANDOFF_CONFIRMATION_REQUIRED")
    available = source_available_at < as_of
    approval = approval if available and approval and approval.known_at < as_of else None
    if approval:
        if approval.scope != request.confirmation_scope(source, source_available_at, version_405):
            raise ValueError("CONFIRMATION_SCOPE_MISMATCH")
        if approval.record_kind == "TEST_FIXTURE" and not allow_test_fixture:
            raise ValueError("FIXTURE_CONFIRMATION_DISABLED")
    is_counter = request.route in COUNTER_ROUTES
    side = request.original_side
    if is_counter:
        side = {"LONG": "SHORT", "SHORT": "LONG"}[side]
    if request.route in LOCK_ROUTES:
        action = Action(f"UNLOCK_{side}", request.before.long)
    else:
        prefix = "ENTER" if is_counter else "REENTER"
        action = Action(f"{prefix}_{side}", Decimal(1))

    required = ("POSITION_PATH_CONFIRMED", "SIGNAL") + (
        ("M_CONFIG_PERMITS", "INTERRUPTION") if is_counter else ("ORIGINAL_PLAN_VALID",)
    )
    scoped = []
    for fact in facts if available else ():
        if not isinstance(fact, Condition):
            raise ValueError("CONDITION_REQUIRED")
        if fact.known_at >= as_of:
            continue
        if fact.case_id != scope or fact.contract != request.before.contract:
            raise ValueError("CONDITION_SCOPE_MISMATCH")
        if fact.name not in required:
            raise ValueError("UNEXPECTED_CONDITION")
        if fact.time_kind != "EVENT_TIME" and fact.name != "M_CONFIG_PERMITS":
            fact = replace(fact, value=None)
        scoped.append(fact)
    if not available:
        # The definition and its version cannot be used before source availability.
        version_405 = None
    known = {fact.name: fact for fact in scoped}
    confirmation = (Condition("RESEARCH_CONFIRMATION", scope, request.before.contract, approval.accepted,
                              approval.decided_at, approval.known_at, approval.id, "EVENT_TIME") if approval else None)
    prerequisite_order = None
    if confirmation and confirmation.value is True and all(
        name in known and known[name].value is True for name in required
    ):
        last_known = max(request.position_known_at, source_available_at,
                         *(known[name].known_at for name in required))
        prerequisite_order = last_known < confirmation.observed_at if last_known != confirmation.observed_at else None

    def derived(name, value, at):
        return Condition(name, scope, request.before.contract, value, at, at, source, "EVENT_TIME")

    evidence = tuple(scoped) + (
        derived("POSITION_KNOWN", True, request.position_known_at),
        derived("PRECONDITIONS_BEFORE_CONFIRMATION", prerequisite_order,
                confirmation.known_at if confirmation else as_of),
    )
    if confirmation:
        evidence += (confirmation,)
    order = (("POSITION_KNOWN", "SIGNAL"), ("SIGNAL", "RESEARCH_CONFIRMATION"))
    if is_counter:
        order += (("INTERRUPTION", "SIGNAL"),)
    case = PublicCase(
        scope, request.before.contract, source, source_available_at, version_405, (action.kind,),
        (required + ("RESEARCH_CONFIRMATION", "POSITION_KNOWN", "PRECONDITIONS_BEFORE_CONFIRMATION"),), order,
    )
    result = assess_case(case, request.before, action, evidence, as_of=as_of)
    if not available:
        result["sources"] = []
    result.update(handoff_version=VERSION, route=request.route, plan_id=request.plan_id,
                  original_side=request.original_side, parent_cycle_id=request.cycle_id,
                  confirmation_id=approval.id if approval else None,
                  confirmation_kind=approval.record_kind if approval else None,
                  hypothetical_active_id=(request.next_id or request.cycle_id) if result["after"] else None,
                  hypothetical_task=("COUNTER_M" if is_counter else "ORIGINAL_PLAN") if result["after"] else None)
    return result
