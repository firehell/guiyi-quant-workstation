"""Evidence validation v0.1; external permissions are not an LMS signal formula.

No orders, fills, risk allocation or original private formula are produced here.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json

from . import Action, Event, Position, apply_action, number, replay_events, timestamp


@dataclass(frozen=True)
class FrozenRules:
    version: str
    sources: tuple[str, ...]
    identified: tuple[str, ...]
    unknown: tuple[str, ...]
    frozen_at: datetime
    definition_digest: str

    def __post_init__(self):
        timestamp(self.frozen_at)
        if (
            not isinstance(self.definition_digest, str)
            or len(self.definition_digest) != 64
            or any(c not in "0123456789abcdef" for c in self.definition_digest)
        ):
            raise ValueError("DEFINITION_DIGEST_REQUIRED")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("RULE_VERSION_REQUIRED")
        for values in (self.sources, self.identified, self.unknown):
            if (
                not isinstance(values, tuple)
                or any(not isinstance(v, str) or not v.strip() for v in values)
                or len(values) != len(set(values))
            ):
                raise ValueError("INVALID_RULE_IDENTITIES")
        if not self.sources:
            raise ValueError("RULE_SOURCES_REQUIRED")
        if set(self.identified) & set(self.unknown):
            raise ValueError("OVERLAPPING_RULES")

    @property
    def fingerprint(self) -> str:
        # A scope fingerprint, not proof that a formula has been recovered.
        payload = dict(
            version=self.version,
            sources=sorted(self.sources),
            identified=sorted(self.identified),
            unknown=sorted(self.unknown),
            frozen_at=self.frozen_at.isoformat(),
            definition_digest=self.definition_digest,
        )
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def decide(
    position: Position,
    action: Action,
    conditions: dict[str, bool | None],
    sources: tuple[str, ...],
) -> dict:
    """Evaluate an externally supplied condition set without deriving private gates.

    Empty/missing conditions are UNKNOWN. A conditional result checks state legality
    only; it cannot assert all original preconditions have been identified.
    """
    if not sources or any(not isinstance(s, str) or not s.strip() for s in sources):
        raise ValueError("DECISION_SOURCES_REQUIRED")
    if any(not isinstance(k, str) or not k.strip() for k in conditions):
        raise ValueError("CONDITION_ID_REQUIRED")
    if any(v is not None and type(v) is not bool for v in conditions.values()):
        raise ValueError("BOOLEAN_OR_UNKNOWN_REQUIRED")
    unknown = sorted(k for k, v in conditions.items() if v is None)
    failed = sorted(k for k, v in conditions.items() if v is False)
    if not conditions:
        unknown = ["TRIGGER_CONDITIONS_UNIDENTIFIED"]
    status = (
        "NOT_PERMITTED"
        if failed
        else "INDETERMINATE"
        if unknown
        else "CONDITIONAL_ACTION"
    )
    after = apply_action(position, action) if status == "CONDITIONAL_ACTION" else None
    return dict(
        status=status,
        requested_action=action.kind,
        sources=list(sources),
        unknown=unknown,
        failed=failed,
        after=None
        if after is None
        else dict(long=str(after.long), short=str(after.short)),
        executable=False,
        original_trigger_identified=False,
        input_kind="EXTERNAL_CONDITIONS",
        fill=None,
    )


@dataclass(frozen=True)
class Checkpoint:
    fingerprint: str
    position: Position
    through: datetime
    seen_events: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        timestamp(self.through)
        if (
            not isinstance(self.fingerprint, str)
            or len(self.fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in self.fingerprint)
        ):
            raise ValueError("INVALID_FROZEN_IDENTITY")
        if not isinstance(self.position, Position):
            raise ValueError("POSITION_REQUIRED")
        if not isinstance(self.seen_events, tuple) or any(
            not isinstance(row, tuple)
            or len(row) != 2
            or not isinstance(row[0], str)
            or not row[0]
            or not isinstance(row[1], str)
            or len(row[1]) != 64
            or any(c not in "0123456789abcdef" for c in row[1])
            for row in self.seen_events
        ):
            raise ValueError("INVALID_EVENT_HISTORY")
        if len({row[0] for row in self.seen_events}) != len(self.seen_events):
            raise ValueError("EVENT_HISTORY_ID_CONFLICT")

    def to_dict(self) -> dict:
        return dict(
            fingerprint=self.fingerprint,
            contract=self.position.contract,
            long=str(self.position.long),
            short=str(self.position.short),
            through=self.through.isoformat(),
            seen_events=[list(row) for row in self.seen_events],
        )

    @classmethod
    def from_dict(cls, value: dict):
        if set(value) != {
            "fingerprint",
            "contract",
            "long",
            "short",
            "through",
            "seen_events",
        }:
            raise ValueError("INVALID_CHECKPOINT_FIELDS")
        if any(not isinstance(v, str) for k, v in value.items() if k != "seen_events"):
            raise ValueError("CHECKPOINT_STRINGS_REQUIRED")
        if not isinstance(value["seen_events"], list) or any(
            not isinstance(row, list) for row in value["seen_events"]
        ):
            raise ValueError("INVALID_EVENT_HISTORY")
        return cls(
            value["fingerprint"],
            Position(
                value["contract"], Decimal(value["long"]), Decimal(value["short"])
            ),
            datetime.fromisoformat(value["through"]),
            tuple(tuple(row) for row in value["seen_events"]),
        )


def event_digest(event: Event) -> str:
    quantity = format(event.action.quantity, "f")
    if "." in quantity:
        quantity = quantity.rstrip("0").rstrip(".")
    payload = dict(
        id=event.id,
        contract=event.contract,
        effective_at=event.effective_at.astimezone(UTC).isoformat(),
        known_at=event.known_at.astimezone(UTC).isoformat(),
        action=event.action.kind,
        quantity=quantity,
        source=event.source,
        manual=event.manual,
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def advance(
    checkpoint: Checkpoint, events: list[Event], cutoff: datetime, rules: FrozenRules
) -> Checkpoint:
    """Advance only a strict suffix; late disclosures never rewrite prior positions."""
    timestamp(cutoff)
    if checkpoint.fingerprint != rules.fingerprint:
        raise ValueError("FROZEN_IDENTITY_MISMATCH")
    if cutoff < checkpoint.through:
        raise ValueError("CURSOR_REGRESSION")
    history = dict(checkpoint.seen_events)
    for event in events:
        if event.id in history and history[event.id] != event_digest(event):
            raise ValueError("EVENT_ID_CONFLICT")
    if any(e.effective_at <= checkpoint.through for e in events):
        raise ValueError("CHECKPOINT_SUFFIX_REQUIRED")
    position = replay_events(
        checkpoint.position.contract, events, cutoff=cutoff, initial=checkpoint.position
    )
    for event in events:
        if event.effective_at <= cutoff:
            history[event.id] = event_digest(event)
    return Checkpoint(
        checkpoint.fingerprint, position, cutoff, tuple(sorted(history.items()))
    )


def compare_labels(truth: list[str | None], predicted: list[str | None]) -> dict:
    """Aligned event/signal labels. NONE is explicit absence; unpublished is None.

    This reports classification error only, not a time-tolerance match. Replayed
    author actions must not be supplied as predictions of those same actions.
    """
    if len(truth) != len(predicted):
        raise ValueError("ALIGNED_SAMPLES_REQUIRED")
    if any(
        v is not None and (not isinstance(v, str) or not v.strip())
        for v in truth + predicted
    ):
        raise ValueError("LABEL_OR_UNKNOWN_REQUIRED")
    known = [(t, p) for t, p in zip(truth, predicted) if t is not None]
    evaluated = [(t, p) for t, p in known if p is not None]
    matches = sum(t == p for t, p in evaluated)
    return dict(
        known_truth=len(known),
        evaluated=len(evaluated),
        matches=matches,
        mismatches=len(evaluated) - matches,
        unresolved=len(known) - len(evaluated),
        unknown_truth=len(truth) - len(known),
        false_positive=sum(t == "NONE" and p != "NONE" for t, p in evaluated),
        false_negative=sum(t != "NONE" and p == "NONE" for t, p in evaluated),
        match_rate=str(Decimal(matches) / Decimal(len(evaluated)))
        if evaluated
        else None,
    )


def holdout_status(
    first_seen: datetime | None, rules: FrozenRules, used_for_fit: bool
) -> str:
    if type(used_for_fit) is not bool:
        raise ValueError("FIT_FLAG_REQUIRED")
    if used_for_fit:
        return "DEVELOPMENT_USED_FOR_FIT"
    if first_seen is None:
        return "UNKNOWN_FIRST_SEEN"
    timestamp(first_seen)
    return (
        "DEVELOPMENT_ALREADY_SEEN"
        if first_seen <= rules.frozen_at
        else "ELIGIBLE_NEW_EVIDENCE"
    )


CAUSAL_FACTS = (
    "behavior_validation",
    "completed_only",
    "strict_before",
    "next_executable_time",
    "physical_contract",
    "tick_size",
    "contract_multiplier",
    "fee_profile",
    "slippage",
    "trading_session",
    "limit_rule",
    "zero_volume_rule",
    "roll_rule",
    "two_leg_costs",
    "execution_facts",
    "prefix_invariance",
    "batch_incremental_parity",
    "restart_parity",
    "historical_known_at",
)

REQUIRED_RULES = (
    "KEYBAR",
    "ENVIRONMENT",
    "ZONE_GENERATOR",
    "STAND_FIRM",
    "ENTRY",
    "PROTECTION",
    "RESTORE_EXIT",
    "TIMEFRAME_POLICY",
    "QUANTITY_POLICY",
)


def causal_preflight(rules: FrozenRules, facts: dict[str, bool | None]) -> dict:
    """Declarations of checked evidence, not automatic verification of those facts."""
    if set(facts) - set(CAUSAL_FACTS):
        raise ValueError("UNKNOWN_CAUSAL_FACT")
    if any(v is not None and type(v) is not bool for v in facts.values()):
        raise ValueError("BOOLEAN_OR_UNKNOWN_REQUIRED")
    blockers = ["FORMULA_UNKNOWN:" + name for name in sorted(rules.unknown)]
    blockers += [
        "RULE_UNIDENTIFIED:" + name
        for name in REQUIRED_RULES
        if name not in rules.identified
    ]
    blockers += [
        name.upper() + "_MISSING"
        for name in CAUSAL_FACTS
        if facts.get(name) is not True
    ]
    return dict(
        status="BLOCKED" if blockers else "READY_FOR_CAUSAL_STUDY",
        blockers=blockers,
        required_facts=list(CAUSAL_FACTS),
        evidence_kind="CALLER_ATTESTED",
        executable=False,
        performance=None,
    )


def endpoint_error(author: Decimal, candidate: Decimal, tick: Decimal) -> Decimal:
    number(author, positive=True)
    number(candidate, positive=True)
    number(tick, positive=True)
    return abs(candidate - author) / tick
