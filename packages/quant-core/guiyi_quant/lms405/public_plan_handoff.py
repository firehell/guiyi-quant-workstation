"""Research-only plan revision and position authority for public-region replay."""

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json

from . import Action, Position, Zone, apply_action, physical_contract, timestamp
from .handoff import HandoffConfirmation
from .public_conditions import Condition
from .validation import decide

VERSION = "lms405-public-plan-handoff-v1"
ENTRY = frozenset({"ENTER_LONG", "ENTER_SHORT", "REENTER_LONG", "REENTER_SHORT"})


def _identity(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("PUBLIC_PLAN_IDENTITY_REQUIRED")


@dataclass(frozen=True)
class Publication:
    revision: str
    contract: str
    published_at: datetime
    known_at: datetime
    source: str
    zone: Zone | None

    def __post_init__(self):
        _identity(self.revision)
        physical_contract(self.contract)
        timestamp(self.published_at)
        timestamp(self.known_at)
        if self.known_at < self.published_at:
            raise ValueError("PUBLIC_PLAN_KNOWN_BEFORE_PUBLISHED")
        _identity(self.source)
        if self.zone is not None and (
            not isinstance(self.zone, Zone)
            or (self.zone.id, self.zone.contract, self.zone.known_at, self.zone.source)
            != (self.revision, self.contract, self.known_at, self.source)
        ):
            raise ValueError("PUBLIC_PLAN_ZONE_SCOPE_MISMATCH")


@dataclass(frozen=True)
class PlanAction:
    position: Position
    position_revision: str
    position_known_at: datetime
    action: Action
    public_plan: Publication | None = None
    independent_entry: bool = False

    def __post_init__(self):
        _identity(self.position_revision)
        timestamp(self.position_known_at)
        apply_action(self.position, self.action)
        if type(self.independent_entry) is not bool:
            raise ValueError("PUBLIC_PLAN_EXPLICIT_ROUTE_REQUIRED")
        if self.public_plan is not None and (
            not isinstance(self.public_plan, Publication) or self.public_plan.contract != self.position.contract
        ):
            raise ValueError("PUBLIC_PLAN_CONTRACT_SCOPE_MISMATCH")
        count = (self.public_plan is not None) + self.independent_entry
        if count != (1 if self.action.kind in ENTRY else 0):
            raise ValueError("PUBLIC_PLAN_EXPLICIT_ROUTE_REQUIRED")

    @property
    def scope(self):
        return sha256(json.dumps([VERSION, asdict(self)], sort_keys=True, default=str).encode()).hexdigest()

    def confirmation_scope(self, trigger: Condition):
        return sha256(json.dumps([self.scope, asdict(trigger)], sort_keys=True, default=str).encode()).hexdigest()


def _current_publication(contract, publications, *, as_of):
    revisions = {}
    for item in publications:
        if item.contract != contract or not item.known_at < as_of:
            continue
        if item.revision in revisions and revisions[item.revision] != item:
            raise ValueError("PUBLIC_PLAN_REVISION_CONFLICT")
        revisions[item.revision] = item
    if not revisions:
        return None, "UNKNOWN"
    latest = max(row.published_at for row in revisions.values())
    current = [row for row in revisions.values() if row.published_at == latest]
    if len(current) != 1:
        return None, "CONFLICT_AT_SAME_TIME"
    (item,) = current
    if item.zone is None:
        return item, "WITHHELD"
    if item.zone.expires_at is not None and item.zone.expires_at <= as_of:
        return item, "EXPIRED"
    return item, "PUBLISHED"


def assess_plan_action(request: PlanAction, publications: tuple[Publication, ...], *, as_of: datetime,
                       trigger: Condition | None = None, approval: HandoffConfirmation | None = None,
                       allow_test_fixture: bool = False) -> dict:
    """Gate new public-region entry by revision; protect and exit using position-scoped evidence."""
    timestamp(as_of)
    contract = request.position.contract
    scope = request.scope
    plan, state = _current_publication(contract, publications, as_of=as_of)
    case = "PUBLIC_REGION_ENTRY" if request.public_plan is not None else (
        "INDEPENDENT_ENTRY" if request.action.kind in ENTRY else "EXISTING_POSITION"
    )
    if type(allow_test_fixture) is not bool:
        raise ValueError("BOOLEAN_FIXTURE_MODE_REQUIRED")
    if trigger is not None and not isinstance(trigger, Condition):
        raise ValueError("PUBLIC_PLAN_FACT_REQUIRED")
    if trigger is not None and trigger.known_at < as_of:
        if trigger.contract != contract or trigger.case_id != scope or trigger.name != "TRIGGER":
            raise ValueError("PUBLIC_PLAN_FACT_SCOPE_MISMATCH")
        trigger = trigger if trigger.time_kind == "EVENT_TIME" else None
    else:
        trigger = None
    if approval is not None and not isinstance(approval, HandoffConfirmation):
        raise ValueError("HANDOFF_CONFIRMATION_REQUIRED")
    approval = approval if approval is not None and approval.known_at < as_of else None
    if approval:
        if approval.record_kind == "TEST_FIXTURE" and not allow_test_fixture:
            raise ValueError("FIXTURE_CONFIRMATION_DISABLED")
        if trigger is not None and approval.scope != request.confirmation_scope(trigger):
            raise ValueError("CONFIRMATION_SCOPE_MISMATCH")
        if trigger is None:
            approval = None
    checks = {
        "position_known": True if request.position_known_at < as_of else None,
        "trigger": trigger.value if trigger else None,
        "specific_permission": approval.accepted if approval else None,
        "trigger_after_position": request.position_known_at < trigger.observed_at if trigger else None,
        "permission_after_trigger_known": trigger.known_at < approval.decided_at if trigger and approval else None,
    }
    if case == "PUBLIC_REGION_ENTRY":
        checks["current_public_revision"] = (
            plan == request.public_plan if state == "PUBLISHED" else None if state == "UNKNOWN" else False
        )
        checks["trigger_after_publication"] = plan.known_at < trigger.observed_at if (
            checks["current_public_revision"] is True and trigger
        ) else None
    sources = tuple(dict.fromkeys(source for source in (
        plan.source if case == "PUBLIC_REGION_ENTRY" and plan is not None else None,
        trigger.source if trigger else None,
        approval.id if approval else None,
    ) if source is not None))
    result = decide(request.position, request.action, checks, sources or (VERSION,))
    result["sources"] = list(sources)
    return result | dict(
        policy_version=VERSION, scope=scope, route=case, checks=checks,
        observed_publication_state=state, observed_publication_revision=plan.revision if plan else None,
        observed_publication_source=plan.source if plan else None,
        approval_kind=approval.record_kind if approval else None,
        fills=None, pnl=None,
    )
