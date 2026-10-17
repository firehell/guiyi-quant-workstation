"""Time-aware public case predicates, not a recovered LMS/BBB signal formula.

Plans are explicitly supplied case subsets. Conditions come from external evidence;
no OHLC classifier, private gate, order or account fact is inferred here.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from . import Action, Position, apply_action, physical_contract, timestamp
from .validation import decide

VERSION = "lms405-public-conditions-v0.1"


def _identity(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("IDENTITY_REQUIRED")


def _truth(value: bool | None) -> None:
    if value is not None and type(value) is not bool:
        raise ValueError("BOOLEAN_OR_UNKNOWN_REQUIRED")


@dataclass(frozen=True)
class Condition:
    name: str
    case_id: str
    contract: str
    value: bool | None
    observed_at: datetime
    known_at: datetime
    source: str
    time_kind: str

    def __post_init__(self):
        for v in (self.name, self.case_id, self.source):
            _identity(v)
        physical_contract(self.contract)
        _truth(self.value)
        if self.time_kind not in {
            "EVENT_TIME",
            "RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME",
        }:
            raise ValueError("OBSERVATION_TIME_KIND_REQUIRED")
        timestamp(self.observed_at)
        timestamp(self.known_at)
        if self.known_at < self.observed_at:
            raise ValueError("KNOWN_BEFORE_OBSERVED")


@dataclass(frozen=True)
class PublicCase:
    id: str
    contract: str
    source: str
    available_at: datetime
    version_405: bool | None
    actions: tuple[str, ...]
    alternatives: tuple[tuple[str, ...], ...]
    precedence: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        _identity(self.id)
        _identity(self.source)
        physical_contract(self.contract)
        timestamp(self.available_at)
        _truth(self.version_405)
        if not isinstance(self.actions, tuple) or not self.actions:
            raise ValueError("CASE_ACTIONS_REQUIRED")
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("DUPLICATE_CASE_ACTION")
        for kind in self.actions:
            Action(kind, Decimal(1))
        if not isinstance(self.alternatives, tuple) or not self.alternatives:
            raise ValueError("CASE_ROUTES_REQUIRED")
        for route in self.alternatives:
            if not isinstance(route, tuple) or not route:
                raise ValueError("NONEMPTY_ROUTE_REQUIRED")
            for name in route:
                _identity(name)
            if len(set(route)) != len(route):
                raise ValueError("DUPLICATE_ROUTE_CONDITION")
        if not isinstance(self.precedence, tuple):
            raise ValueError("INVALID_PRECEDENCE")
        for edge in self.precedence:
            if (
                not isinstance(edge, tuple)
                or len(edge) != 2
                or edge[0] == edge[1]
                or not any(set(edge) <= set(r) for r in self.alternatives)
            ):
                raise ValueError("INVALID_PRECEDENCE")
        # Reject contradictory temporal requirements before any evaluation.
        pending = set(self.precedence)
        while pending:
            roots = {a for a, _ in pending} - {b for _, b in pending}
            if not roots:
                raise ValueError("CYCLIC_PRECEDENCE")
            pending = {(a, b) for a, b in pending if a not in roots}


def _all(values: list[bool | None]) -> bool | None:
    if False in values:
        return False
    return None if None in values else True


def assess_case(
    case: PublicCase,
    position: Position,
    action: Action,
    facts: tuple[Condition, ...],
    *,
    as_of: datetime,
) -> dict:
    """AND per route, OR across routes; strictly known evidence only.

    Precedence compares observation timestamps, never post/publication timestamps.
    Research reading times and equal Bar timestamps leave event order unknown. A conditional transition is
    a legal two-leg proposal from an incomplete public subset, never a prediction.
    """
    timestamp(as_of)
    if case.contract != position.contract:
        raise ValueError("CONTRACT_BOUNDARY")
    if action.kind not in case.actions:
        raise ValueError("ACTION_NOT_IN_CASE")
    apply_action(position, action)  # Reject illegal requests even with missing facts.
    allowed = set().union(*map(set, case.alternatives))
    seen: set[str] = set()
    visible: dict[str, Condition] = {}
    for fact in facts:
        if not isinstance(fact, Condition):
            raise ValueError("CONDITION_REQUIRED")
        if fact.case_id != case.id or fact.contract != case.contract:
            raise ValueError("CONDITION_SCOPE_MISMATCH")
        if fact.name not in allowed:
            raise ValueError("UNEXPECTED_CONDITION")
        if fact.name in seen:
            raise ValueError("DUPLICATE_CONDITION")
        seen.add(fact.name)
        if fact.known_at < as_of:
            visible[fact.name] = fact
    routes = []
    for route in case.alternatives:
        checks = {k: visible[k].value if k in visible else None for k in route}
        for first, second in case.precedence:
            if first not in route or second not in route:
                continue
            value = None
            if (
                checks[first] is True
                and checks[second] is True
                and visible[first].time_kind == "EVENT_TIME"
                and visible[second].time_kind == "EVENT_TIME"
            ):
                a, b = visible[first].observed_at, visible[second].observed_at
                value = a < b if a != b else None
            checks[f"ORDER:{first}<{second}"] = value
        routes.append(dict(checks=checks, value=_all(list(checks.values()))))
    values = [r["value"] for r in routes]
    ready = True if True in values else None if None in values else False
    result = decide(
        position,
        action,
        {
            "case_available": True if case.available_at < as_of else None,
            "case_version_405": case.version_405,
            "public_route": ready,
        },
        (case.source,),
    )
    return result | dict(
        policy_version=VERSION,
        case_id=case.id,
        as_of=as_of.isoformat(),
        routes=routes,
        input_kind="EXTERNAL_CASE_CONDITIONS",
        public_subset_only=True,
        eligible_golden_signal=False,
        performance=None,
    )
