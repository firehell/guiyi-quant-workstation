"""Research permission checks for entering, holding, and protecting exposure."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from hashlib import sha256
import json

from . import Position, timestamp
from .public_conditions import Condition, check_route

VERSION = "lms405-participation-v1"
RIGHT = ("POSITION_CONFIRMED", "PLAN_ACTIVE", "DIRECTION_ESTABLISHED", "SPACE_AVAILABLE",
         "RIGHT_POLICY_PERMITS", "PRICE_SETUP", "RIGHT_SIGNAL", "PRICE_SETUP_STILL_VALID")
HOLD = ("POSITION_CONFIRMED", "PLAN_ACTIVE")
PROTECT = ("POSITION_CONFIRMED", "PROTECTION_DUE", "PROTECTION_SIGNAL")
ALLOWED = frozenset(RIGHT + HOLD + PROTECT)


@dataclass(frozen=True)
class Participation:
    position: Position
    side: str
    plan_id: str
    position_id: str
    position_known_at: datetime
    plan_available_at: datetime
    source: str
    version_405: bool | None

    def __post_init__(self):
        if not isinstance(self.position, Position) or self.side not in ("LONG", "SHORT"):
            raise ValueError("PARTICIPATION_POSITION_AND_DIRECTION_REQUIRED")
        if any(not isinstance(v, str) or not v.strip() for v in (self.plan_id, self.position_id, self.source)):
            raise ValueError("PARTICIPATION_PLAN_POSITION_AND_SOURCE_REQUIRED")
        if self.version_405 is not None and type(self.version_405) is not bool:
            raise ValueError("BOOLEAN_OR_UNKNOWN_VERSION_REQUIRED")
        timestamp(self.position_known_at)
        timestamp(self.plan_available_at)

    @property
    def scope(self):
        payload = json.dumps([VERSION, asdict(self)], sort_keys=True, default=str)
        return sha256(payload.encode()).hexdigest()


def after(value, boundary):
    return value > boundary if value != boundary else None


def assess_participation(request: Participation, facts: tuple[Condition, ...], *, as_of: datetime) -> dict:
    """Check independent conditions against the same immutable position hypothesis."""
    timestamp(as_of)
    scope = request.scope
    available = request.plan_available_at < as_of
    position_visible = request.position_known_at < as_of
    visible = {}
    for fact in facts if available else ():
        if not isinstance(fact, Condition):
            raise ValueError("PARTICIPATION_CONDITION_REQUIRED")
        if fact.known_at >= as_of:
            continue
        if fact.case_id != scope or fact.contract != request.position.contract:
            raise ValueError("CONDITION_SCOPE_MISMATCH")
        if fact.name not in ALLOWED or fact.name in visible:
            raise ValueError("UNEXPECTED_OR_DUPLICATE_PARTICIPATION_CONDITION")
        if fact.time_kind != "EVENT_TIME" and fact.name != "RIGHT_POLICY_PERMITS":
            fact = replace(fact, value=None)
        visible[fact.name] = fact

    long, short = request.position.long, request.position.short
    same_side = (long > 0 and short == 0 if request.side == "LONG" else short > 0 and long == 0)
    flat = long == short == 0
    position_fact = visible.get("POSITION_CONFIRMED")
    plan_fact = visible.get("PLAN_ACTIVE")
    due = visible.get("PROTECTION_DUE")
    due_current = (due.observed_at >= request.position_known_at
                   if position_visible and due and due.value is not None else None)
    no_protection_due = not due.value if due_current else None
    lock_signal = visible.get("PROTECTION_SIGNAL")
    price, signal = visible.get("PRICE_SETUP"), visible.get("RIGHT_SIGNAL")
    right_inputs_known = price and price.value is True and signal and signal.value is True
    right = check_route(RIGHT, (("PRICE_SETUP", "RIGHT_SIGNAL"),), visible)["checks"]
    right.update(PRICE_SETUP_WITHIN_PLAN=after(price.observed_at, request.plan_available_at)
                 if price and price.value is True else None,
                 PRICE_SETUP_KNOWN_BEFORE_SIGNAL=after(signal.observed_at, price.known_at) if right_inputs_known else None,
                 SIGNAL_WITHIN_PLAN_AND_POSITION=after(signal.observed_at, max(
                     request.plan_available_at, request.position_known_at,
                 )) if signal and signal.value is True and position_visible else None,
                 EXISTING_POSITION_PROTECTION_NOT_DUE=True if flat and position_visible else no_protection_due,
                 EXISTING_POSITION_PROTECTION_ASSESSED_AT_SIGNAL_OR_LATER=(
                     True if flat and position_visible else due.observed_at >= signal.observed_at
                     if due_current and signal and signal.value is True else None))
    for name in ("SPACE_AVAILABLE", "PRICE_SETUP_STILL_VALID"):
        fact = visible.get(name)
        right[f"{name}_CHECKED_AT_SIGNAL_OR_LATER"] = (
            fact.observed_at >= signal.observed_at if fact and fact.value is True and signal and signal.value is True else None
        )
    hold = check_route(HOLD, (), visible)["checks"]
    hold.update(PROTECTION_NOT_DUE=no_protection_due, PROTECTION_ASSESSED_FOR_POSITION=due_current)
    protect = check_route(PROTECT, (), visible)["checks"]
    protect.update(PROTECTION_ASSESSED_FOR_POSITION=due_current,
                   SIGNAL_AFTER_POSITION=after(lock_signal.observed_at, request.position_known_at)
                   if position_visible and lock_signal and lock_signal.value is True else None)

    decisions = {}
    for intent, checks, compatible in (("RIGHT_PARTICIPATION", right, flat or same_side),
                                       ("KEEP_HOLDING", hold, same_side), ("LOCK_PROTECTION", protect, same_side)):
        checks.update(SOURCE_AVAILABLE=True if available else None,
                      VERSION_405=request.version_405 if available else None,
                      POSITION_COMPATIBLE=compatible if position_visible else None,
                      POSITION_CONFIRMED_FOR_SNAPSHOT=(position_fact.observed_at >= request.position_known_at
                      if position_visible and position_fact and position_fact.value is True else None))
        if "PLAN_ACTIVE" in checks:
            checks["PLAN_ACTIVE_CHECKED_FOR_POSITION"] = (
                plan_fact.observed_at >= max(request.position_known_at, request.plan_available_at)
                if position_visible and plan_fact and plan_fact.value is True else None
            )
        unknown = sorted(k for k, value in checks.items() if value is None)
        failed = sorted(k for k, value in checks.items() if value is False)
        status = "NOT_PERMITTED" if failed else "INDETERMINATE" if unknown else "CONDITIONS_MET"
        decisions[intent] = dict(status=status, failed=failed, unknown=unknown, checks=checks)

    return dict(version=VERSION, scope=scope, contract=request.position.contract, plan_id=request.plan_id,
                position_id=request.position_id,
                source=request.source if available else None, as_of=as_of.isoformat(), decisions=decisions,
                executable=False, action=None, fill=None, pnl=None)
