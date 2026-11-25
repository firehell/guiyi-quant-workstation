"""Conditional research checks for trend and counter-M tasks on one contract."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json

from . import Action, Position, timestamp
from .public_conditions import Condition
from .validation import decide

VERSION = "lms405-task-roles-v1"
ROUTES = {
    "LOCK_TREND": ("POSITION_CONFIRMED", "PROTECTION_DUE", "PROTECTION_SIGNAL"),
    "RESUME_TREND": ("POSITION_CONFIRMED", "ORIGINAL_PLAN_VALID", "ORIGINAL_SIGNAL"),
    "EXIT_COUNTER_M": ("POSITION_CONFIRMED", "COUNTER_M_EXIT_PERMISSION", "COUNTER_M_EXIT_TRIGGER"),
}
OPPOSITE = {"LONG": "SHORT", "SHORT": "LONG"}


@dataclass(frozen=True)
class TaskBook:
    trend: Position
    counter_m: Position
    original_side: str
    trend_id: str
    counter_m_id: str
    known_at: datetime

    def __post_init__(self):
        if (not isinstance(self.trend, Position) or not isinstance(self.counter_m, Position)
                or self.trend.contract != self.counter_m.contract or self.original_side not in OPPOSITE):
            raise ValueError("TASK_BOOK_CONTRACT_OR_SIDE_INVALID")
        if (any(not isinstance(value, str) or not value.strip() for value in (self.trend_id, self.counter_m_id))
                or self.trend_id == self.counter_m_id):
            raise ValueError("DISTINCT_TASK_IDENTITIES_REQUIRED")
        original = getattr(self.trend, self.original_side.lower())
        protection = getattr(self.trend, OPPOSITE[self.original_side].lower())
        if original <= 0 or protection not in (0, original) or getattr(self.counter_m, self.original_side.lower()):
            raise ValueError("TASK_BOOK_ROLE_MISMATCH")
        timestamp(self.known_at)

    def scope(self, purpose, quantity, source, source_available_at, version_405):
        payload = (VERSION, asdict(self), purpose, quantity, source, source_available_at, version_405)
        return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def position_view(trend, counter_m):
    return dict(trend=asdict(trend), counter_m=asdict(counter_m),
                aggregate=asdict(Position(trend.contract, trend.long + counter_m.long, trend.short + counter_m.short)))


def assess_task_action(book, purpose, quantity: Decimal, facts: tuple[Condition, ...], *, as_of, source,
                       source_available_at, version_405):
    """Project a task-scoped action from supplied conditions without applying account changes."""
    if purpose not in ROUTES or not isinstance(book, TaskBook):
        raise ValueError("TASK_ROLE_ROUTE_REQUIRED")
    if version_405 is not None and type(version_405) is not bool:
        raise ValueError("BOOLEAN_OR_UNKNOWN_VERSION_REQUIRED")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("TASK_ROLE_SOURCE_REQUIRED")
    timestamp(as_of)
    timestamp(source_available_at)
    available = source_available_at < as_of
    snapshot_available = book.known_at < as_of
    exit_m = purpose == "EXIT_COUNTER_M"
    action_kind = "LOCK"
    if snapshot_available and purpose == "RESUME_TREND":
        action_kind = f"UNLOCK_{book.original_side}"
    elif snapshot_available and exit_m:
        action_kind = f"EXIT_{OPPOSITE[book.original_side]}"
    action = Action(action_kind, quantity)
    selected = book.counter_m if exit_m else book.trend
    scope = book.scope(purpose, quantity, source, source_available_at, version_405) if (
        available and snapshot_available
    ) else None
    names = ROUTES[purpose]
    checks = dict.fromkeys(names)
    seen = set()
    for fact in facts if scope is not None else ():
        if not isinstance(fact, Condition):
            raise ValueError("TASK_ROLE_CONDITION_REQUIRED")
        if fact.known_at >= as_of:
            continue
        if (fact.case_id != scope or fact.contract != book.trend.contract
                or fact.name not in names or fact.name in seen):
            raise ValueError("TASK_ROLE_CONDITION_SCOPE_MISMATCH")
        seen.add(fact.name)
        if fact.time_kind == "EVENT_TIME" and book.known_at < fact.observed_at:
            checks[fact.name] = fact.value
    checks.update(source_available=True if available else None,
                  version_405=version_405 if available else None,
                  snapshot_available=True if snapshot_available else None)
    result = decide(selected, action, checks, (source,))
    if not available:
        result["sources"] = []
    if not snapshot_available:
        result["requested_action"] = None
    after = None
    if result["after"] is not None:
        projected = Position(selected.contract, Decimal(result["after"]["long"]), Decimal(result["after"]["short"]))
        after = (position_view(book.trend, projected) if exit_m else position_view(projected, book.counter_m))
    return result | dict(version=VERSION, scope=scope, purpose=purpose,
                         acting_task_id=(book.counter_m_id if exit_m else book.trend_id) if snapshot_available else None,
                         before=position_view(book.trend, book.counter_m) if snapshot_available else None,
                         after=after, checks=checks, author_action=None, qty=quantity, pnl=None)
