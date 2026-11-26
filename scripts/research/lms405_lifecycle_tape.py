"""Chronological position-scoped transitions for isolated LMS research episodes."""

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from guiyi_quant.lms405 import Action, Position, apply_action, number, timestamp
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.public_plan_handoff import PlanAction, Publication, assess_plan_action
from lms_near405_replay import encoded


@dataclass(frozen=True)
class Cursor:
    episode: str
    revision: str
    at: datetime
    position: Position
    protected_long: Decimal = Decimal(0)

    def __post_init__(self):
        timestamp(self.at)
        number(self.protected_long)
        if not self.episode or not self.revision or not self.protected_long <= min(
            self.position.long, self.position.short,
        ):
            raise ValueError("LIFECYCLE_INVALID_POSITION_OR_PROTECTION")

    @property
    def identity(self):
        return sha256(encoded(asdict(self)).encode()).hexdigest()


@dataclass(frozen=True)
class Attempt:
    id: str
    expected: Cursor
    at: datetime
    operation: str
    quantity: Decimal
    expires_at: datetime
    plan: Publication | None = None
    trigger: Condition | None = None
    approval: HandoffConfirmation | None = None
    observation: str | None = None

    def __post_init__(self):
        timestamp(self.at)
        timestamp(self.expires_at)
        number(self.quantity, positive=True)
        if not self.id or not self.expected.at < min(self.at, self.expires_at) or self.operation not in (
            "PROTECT_ADD", "PROTECT_WITHDRAW", "CLEAR", "ENTER_LONG", "REENTER_LONG",
        ):
            raise ValueError("LIFECYCLE_INVALID_ATTEMPT")

    @property
    def request(self):
        before = self.expected.position
        if self.operation == "PROTECT_ADD":
            # The scoped empty slice makes the entry permission specific to
            # this exact aggregate position, stage, quantity, and price zone.
            before, kind = Position(before.contract), "ENTER_LONG"
        else:
            kind = "EXIT_LONG" if self.operation == "PROTECT_WITHDRAW" else self.operation
        context = sha256(encoded([self.expected.identity, self.id, self.operation, self.expires_at]).encode()).hexdigest()
        return PlanAction(before, context, self.expected.at, Action(kind, self.quantity), self.plan)

    def supported_projection(self):
        before = self.expected.position
        protected = self.expected.protected_long
        if self.operation == "PROTECT_ADD":
            if before.long != protected or self.quantity > before.short - protected:
                raise ValueError("LIFECYCLE_PROTECTION_CAPACITY_EXCEEDED")
            return Position(before.contract, before.long + self.quantity, before.short), protected + self.quantity
        if self.operation == "PROTECT_WITHDRAW":
            if self.quantity > protected:
                raise ValueError("LIFECYCLE_WITHDRAW_UNASSIGNED_PROTECTION")
            return apply_action(before, self.request.action), protected - self.quantity
        return apply_action(before, self.request.action), Decimal(0)


def apply_attempt(current, attempt, publications, *, allow_test_fixture):
    if current is None or current != attempt.expected:
        return current, "STALE_OR_UNAVAILABLE_POSITION", None
    if attempt.at >= attempt.expires_at:
        return current, "ATTEMPT_EXPIRED", None
    projection, protected = attempt.supported_projection()
    request = attempt.request
    try:
        result = assess_plan_action(request, publications, as_of=attempt.at, trigger=attempt.trigger,
                                    approval=attempt.approval, allow_test_fixture=allow_test_fixture)
    except ValueError as exc:
        if str(exc) not in ("CONFIRMATION_SCOPE_MISMATCH", "PUBLIC_PLAN_FACT_SCOPE_MISMATCH"):
            raise
        return current, "AUTHORITY_SCOPE_MISMATCH", None
    if result["after"] is None:
        return current, result["status"], result
    after = Cursor(current.episode, attempt.id, attempt.at, projection, protected)
    return after, result["status"], result


def replay(seeds, attempts, publications, *, cutoff, start=None, cursors=None, allow_test_fixture=False):
    """Project a strict-before prefix or append to a checkpoint from an earlier exclusive cut."""
    timestamp(cutoff)
    if (start is None) != (cursors is None) or (start is not None and cutoff < start):
        raise ValueError("LIFECYCLE_INVALID_CHECKPOINT_WINDOW")
    if start is not None:
        timestamp(start)
        if any(key != row.episode or row.at >= start for key, row in cursors.items()):
            raise ValueError("LIFECYCLE_INVALID_CHECKPOINT_CURSOR")
        _, expected = replay(seeds, attempts, publications, cutoff=start, allow_test_fixture=allow_test_fixture)
        if cursors != expected:
            raise ValueError("LIFECYCLE_CHECKPOINT_PREFIX_MISMATCH")
    visible = sorted(
        (event for event in (*seeds, *attempts) if (start is None or start <= event.at) and event.at < cutoff),
        key=lambda event: (event.at, event.episode, event.revision) if isinstance(event, Cursor)
        else (event.at, event.expected.episode, event.id),
    )
    event_keys = [(event.episode, event.at) if isinstance(event, Cursor) else (
        event.expected.episode, event.at,
    ) for event in visible]
    conflicts = {key for key, count in Counter(event_keys).items() if count > 1}
    state = dict(cursors or {})
    rows = []
    for event, key in zip(visible, event_keys, strict=True):
        if key in conflicts:
            raise ValueError("LIFECYCLE_SAME_EPISODE_TIME_CONFLICT")
        if isinstance(event, Cursor):
            if event.episode in state:
                raise ValueError("LIFECYCLE_DUPLICATE_EPISODE")
            state[event.episode] = event
            rows.append(dict(at=event.at, episode=event.episode, kind="ASSUMED_START", after=asdict(event)))
            continue
        before = state.get(event.expected.episode)
        after, status, result = apply_attempt(before, event, publications, allow_test_fixture=allow_test_fixture)
        if after is not None:
            state[event.expected.episode] = after
        rows.append(dict(at=event.at, episode=event.expected.episode, contract=event.expected.position.contract,
                         kind="RESEARCH_ATTEMPT", operation=event.operation, id=event.observation or event.id,
                         decision_id=event.id, status=status,
                         before=asdict(before) if before else None, after=asdict(after) if after else None,
                         changed=before != after,
                         condition_position_scope="PROTECTION_SLICE" if event.operation == "PROTECT_ADD" else "EPISODE",
                         conditions=result))
    return rows, state
