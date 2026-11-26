"""Attributed-quantity transitions for the independent LMS portfolio candidate."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal

from ..lms_confirmed_replay import fingerprint
from . import Position, ZERO, number, physical_contract, timestamp
from .handoff import HandoffConfirmation
from .public_conditions import Condition

VERSION = "lms-near405-portfolio-tasks-v1"
REQUIRED = {
    "ENTER_TREND": ("DIRECTIONAL_SIGNAL",),
    "REENTER_TREND": ("FRESH_REENTRY_SIGNAL", "PLAN_REENTRY_ALLOWED"),
    "PROTECT_EARLY": ("PROTECTION_ZONE_APPLIES", "EARLY_PROTECTION_TRIGGER"),
    "PROTECT_REGULAR": ("PROTECTION_ZONE_APPLIES", "REGULAR_PROTECTION_SIGNAL"),
    "PROTECT_TOPUP": ("PROTECTION_ZONE_APPLIES", "REGULAR_PROTECTION_SIGNAL"),
    "RECOVER_ORIGINAL": ("ORIGINAL_PLAN_VALID", "ORIGINAL_DIRECTION_SIGNAL"),
    "ENTER_COUNTER_M": ("COUNTER_M_ENTRY_PERMITTED", "COUNTER_M_ENTRY_SIGNAL"),
    "EXIT_COUNTER_M": ("COUNTER_M_EXIT_PERMITTED", "COUNTER_M_EXIT_SIGNAL"),
    "CLEAR_TREND": ("TREND_EXIT_SIGNAL",),
}


@dataclass(frozen=True)
class Book:
    contract: str
    episode: str
    direction: str
    known_at: datetime
    original: Decimal = ZERO
    protection: Decimal = ZERO
    counter_m: Decimal = ZERO
    attempt: int = 0

    def __post_init__(self):
        physical_contract(self.contract)
        timestamp(self.known_at)
        for qty in (self.original, self.protection, self.counter_m):
            number(qty)
        if (not isinstance(self.episode, str) or not self.episode.strip()
                or self.direction not in ("LONG", "SHORT") or type(self.attempt) is not int
                or self.attempt < 0 or ((self.original or self.counter_m) and self.attempt == 0)
                or self.protection > self.original):
            raise ValueError("PORTFOLIO_TASK_BOOK_INVALID")

    @property
    def visible(self) -> Position:
        opposite = self.protection + self.counter_m
        return (Position(self.contract, self.original, opposite) if self.direction == "LONG"
                else Position(self.contract, opposite, self.original))


@dataclass(frozen=True)
class Intent:
    before: Book
    operation: str
    quantity: Decimal
    plan_id: str
    expires_at: datetime

    def __post_init__(self):
        timestamp(self.expires_at)
        number(self.quantity, positive=True)
        if (self.operation not in REQUIRED or not isinstance(self.plan_id, str) or not self.plan_id.strip()
                or self.expires_at <= self.before.known_at):
            raise ValueError("PORTFOLIO_TASK_INTENT_INVALID")

    @property
    def scope(self) -> str:
        return fingerprint((VERSION, asdict(self)))

    def confirmation_scope(self, facts: tuple[Condition, ...]) -> str:
        return fingerprint((self.scope, [asdict(fact) for fact in sorted(facts, key=lambda fact: fact.name)]))


def _project(request: Intent, known_at: datetime) -> Book | None:
    before, qty = request.before, request.quantity
    match request.operation:
        case "ENTER_TREND" | "REENTER_TREND":
            is_reentry = request.operation == "REENTER_TREND"
            if not (before.original or before.counter_m) and (before.attempt > 0) == is_reentry:
                return replace(before, original=qty, attempt=before.attempt + 1, known_at=known_at)
        case "PROTECT_EARLY" | "PROTECT_REGULAR" | "PROTECT_TOPUP":
            unprotected = before.original - before.protection
            if (request.operation == "PROTECT_EARLY" and not before.protection and qty <= unprotected
                    or request.operation == "PROTECT_REGULAR" and not before.protection and qty == unprotected
                    or request.operation == "PROTECT_TOPUP" and before.protection and qty == unprotected):
                return replace(before, protection=before.protection + qty, known_at=known_at)
        case "RECOVER_ORIGINAL":
            if qty == before.protection:
                return replace(before, protection=ZERO, known_at=known_at)
        case "ENTER_COUNTER_M":
            # The scoped entry conditions carry any interruption requirement.
            if not before.counter_m and before.attempt > 0:
                return replace(before, counter_m=qty, known_at=known_at)
        case "EXIT_COUNTER_M":
            if qty <= before.counter_m:
                return replace(before, counter_m=before.counter_m - qty, known_at=known_at)
        case "CLEAR_TREND":
            if qty == before.original + before.protection:
                return replace(before, original=ZERO, protection=ZERO, known_at=known_at)
    return None


def assess(current: Book, request: Intent, facts: tuple[Condition, ...], *, as_of: datetime,
           approval: HandoffConfirmation | None = None, allow_test_fixture: bool = False) -> dict:
    """Gate exact scoped proposals. Reading a snapshot cannot supply an event-time trigger."""
    timestamp(as_of)
    if type(allow_test_fixture) is not bool:
        raise ValueError("BOOLEAN_FIXTURE_MODE_REQUIRED")
    if approval is not None and not isinstance(approval, HandoffConfirmation):
        raise ValueError("HANDOFF_CONFIRMATION_REQUIRED")
    missing_status = dict(after=None, unknown=[], executable=False)
    if not current.known_at < as_of or current != request.before:
        return missing_status | dict(status="POSITION_UNAVAILABLE_OR_SUPERSEDED")
    if request.expires_at <= as_of:
        return missing_status | dict(status="EXPIRED")
    names = REQUIRED[request.operation]
    visible = {}
    for fact in facts:
        if not fact.known_at < as_of:
            continue
        if (fact.contract != current.contract or fact.case_id != request.scope
                or fact.name not in names or fact.name in visible):
            raise ValueError("PORTFOLIO_TASK_CONDITION_SCOPE_MISMATCH")
        visible[fact.name] = fact
    admitted = tuple(fact for fact in visible.values() if fact.time_kind == "EVENT_TIME"
                     and current.known_at < fact.observed_at)
    values = {fact.name: fact.value for fact in admitted}
    unknown = [name for name in names if values.get(name) is None]
    if approval is not None and approval.known_at < as_of:
        if approval.record_kind == "TEST_FIXTURE" and not allow_test_fixture:
            raise ValueError("FIXTURE_CONFIRMATION_DISABLED")
        if unknown or approval.scope != request.confirmation_scope(admitted):
            raise ValueError("PORTFOLIO_TASK_APPROVAL_SCOPE_MISMATCH")
        if not all(fact.known_at < approval.decided_at for fact in admitted):
            raise ValueError("PORTFOLIO_TASK_APPROVAL_PRECEDES_FACT")
    else:
        approval = None
        unknown.append("SCOPED_APPROVAL")
    if False in values.values() or (approval is not None and not approval.accepted):
        return missing_status | dict(status="REJECTED")
    if unknown:
        return missing_status | dict(status="INDETERMINATE", unknown=unknown)
    after = _project(request, as_of)
    if after is None:
        return missing_status | dict(status="ACTION_STATE_CONFLICT")
    return missing_status | dict(status="CONDITIONAL_ACTION", after=after)
