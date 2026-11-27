"""Research-only original-position recovery from an explicitly authorized near edge."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from . import Bar, Zone, timestamp
from .handoff import Handoff, HandoffConfirmation, assess_handoff
from .public_conditions import Condition
from ..lms_confirmed_replay import fingerprint

VERSION = "lms405-explicit-near-recovery-v1"
EXPLICIT_NEAR = "EXPLICIT_ORIGINAL_RECOVERY_NEAR"
MINUTE = timedelta(minutes=1)
US = timedelta(microseconds=1)
PERIODS = {(MINUTE, MINUTE), (5 * MINUTE, MINUTE), (5 * MINUTE, 5 * MINUTE), (15 * MINUTE, 15 * MINUTE)}


@dataclass(frozen=True)
class NearRecoveryCase:
    request: Handoff
    zone: Zone
    role: str
    break_bar: Bar | None
    shape: Bar
    confirmation: Bar
    version_405: bool | None

    def __post_init__(self):
        if not isinstance(self.request, Handoff) or self.request.route != "RESUME_ORIGINAL":
            raise ValueError("NEAR_RECOVERY_REQUIRES_ORIGINAL_HANDOFF")
        if not isinstance(self.zone, Zone) or not isinstance(self.role, str) or not self.role.strip():
            raise ValueError("NEAR_RECOVERY_REQUIRES_ZONE_AND_ROLE")
        if self.zone.id != self.request.plan_id:
            raise ValueError("NEAR_RECOVERY_PLAN_ID_MISMATCH")
        if self.version_405 is not None and type(self.version_405) is not bool:
            raise ValueError("NEAR_RECOVERY_VERSION_MUST_BE_BOOLEAN_OR_UNKNOWN")
        contract = self.request.before.contract
        bars = (self.shape, self.confirmation) if self.break_bar is None else (self.break_bar, self.shape, self.confirmation)
        if self.zone.contract != contract or any(
            not isinstance(bar, Bar) or bar.completed is not True or bar.contract != contract or bar.start is None
            for bar in bars
        ):
            raise ValueError("NEAR_RECOVERY_BAR_OR_CONTRACT_MISMATCH")
        shape_step = self.shape.end - self.shape.start
        confirm_step = self.confirmation.end - self.confirmation.start
        after_shape = self.confirmation.end - self.shape.end
        if ((shape_step, confirm_step) not in PERIODS or self.confirmation.start < self.shape.end
                or after_shape > shape_step or after_shape % confirm_step != timedelta(0)):
            raise ValueError("NEAR_RECOVERY_CONFIRMATION_WINDOW_MISMATCH")
        if self.break_bar is not None and self.break_bar.end - self.break_bar.start != MINUTE:
            raise ValueError("NEAR_RECOVERY_REQUIRES_MINUTE_BREAK")

    @property
    def policy_source(self):
        return f"{VERSION}:{fingerprint(asdict(self))}"

    @property
    def evidence_known_at(self):
        return max(self.zone.known_at, self.request.position_known_at, self.confirmation.end + US)

    @property
    def approval_scope(self):
        return self.request.confirmation_scope(self.policy_source, self.evidence_known_at, self.version_405)


def assess_near_recovery(
    case: NearRecoveryCase, facts: tuple[Condition, ...], *, as_of: datetime,
    approval: HandoffConfirmation | None = None, allow_test_fixture: bool = False,
) -> dict:
    """Evaluate the price gate, then use the existing two-leg and approval contract."""
    timestamp(as_of)
    if approval is not None and not isinstance(approval, HandoffConfirmation):
        raise ValueError("HANDOFF_CONFIRMATION_REQUIRED")
    plan_known = case.zone.known_at < as_of
    locked_known = case.request.position_known_at < as_of
    closed = case.confirmation.end + US < as_of
    broke = case.break_bar if case.break_bar and case.break_bar.end + US < as_of else None
    long = case.request.original_side == "LONG"
    near = case.zone.lower if long else case.zone.upper

    def beyond(value):
        return value > near if long else value < near

    expires = case.zone.expires_at
    checks = dict(
        explicit_near_role=case.role == EXPLICIT_NEAR if plan_known else None,
        plan_known_before_shape=case.zone.known_at < case.shape.start if plan_known and closed else None,
        lock_known_before_shape=(
            case.request.position_known_at < case.shape.start if plan_known and locked_known and closed else None),
        plan_current_at_assessment=(expires is None or as_of < expires) if plan_known else None,
        strict_near_close=beyond(broke.close) if broke and plan_known else None,
        break_started_under_plan_and_lock=(
            max(case.zone.known_at, case.request.position_known_at) < broke.start
            if broke and plan_known and locked_known else None),
        break_known_before_shape=broke.end + US < case.shape.start if plan_known and broke and closed else None,
        confirmation_still_beyond_near=beyond(case.confirmation.close) if closed and plan_known else None,
    )
    failed = sorted(name for name, value in checks.items() if value is False)
    unknown = sorted(name for name, value in checks.items() if value is None)
    if failed or unknown:
        return dict(version=VERSION, checks=checks, failed=failed, unknown=unknown, after=None,
                    status="NOT_PERMITTED" if failed else "INDETERMINATE", executable=False)
    if any(not isinstance(fact, Condition) for fact in facts):
        raise ValueError("CONDITION_REQUIRED")
    signal = next((fact for fact in facts if fact.name == "SIGNAL" and fact.known_at < as_of), None)
    if signal and (signal.observed_at != case.confirmation.end or signal.known_at < case.confirmation.end + US):
        raise ValueError("NEAR_RECOVERY_SIGNAL_CLOCK_MISMATCH")
    result = assess_handoff(case.request, facts, as_of=as_of, source=case.policy_source,
                            source_available_at=case.evidence_known_at, version_405=case.version_405,
                            approval=approval, allow_test_fixture=allow_test_fixture)
    return result | dict(version=VERSION, checks=checks, plan_source=case.zone.source)
