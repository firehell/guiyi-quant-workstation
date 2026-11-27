"""Conditionally relabel a continuing trial without creating a trade."""

from dataclasses import asdict, dataclass
from datetime import datetime

from ..lms_confirmed_replay import fingerprint
from . import Position, timestamp
from .public_conditions import Condition, check_route

VERSION = "lms405-trial-hold-study-v1"
REQUIRED = ("TRIAL_SUCCEEDED", "TREND_CONFIRMED", "SAME_TRIAL_STILL_OPEN")
ORDER = (("TRIAL_SUCCEEDED", "SAME_TRIAL_STILL_OPEN"), ("TREND_CONFIRMED", "SAME_TRIAL_STILL_OPEN"))


@dataclass(frozen=True)
class TrialHold:
    position: Position
    plan_id: str
    trial_id: str
    started_at: datetime
    plan_known_at: datetime
    snapshot_at: datetime
    version_405: bool | None

    def __post_init__(self):
        if not isinstance(self.position, Position) or bool(self.position.long) == bool(self.position.short):
            raise ValueError("SINGLE_TRIAL_LEG_REQUIRED")
        if (any(not isinstance(v, str) or not v.strip() for v in (self.plan_id, self.trial_id))
                or self.plan_id == self.trial_id):
            raise ValueError("DISTINCT_PLAN_AND_TRIAL_IDS_REQUIRED")
        if self.version_405 is not None and type(self.version_405) is not bool:
            raise ValueError("BOOLEAN_OR_UNKNOWN_VERSION_REQUIRED")
        timestamp(self.started_at)
        timestamp(self.plan_known_at)
        timestamp(self.snapshot_at)
        if self.snapshot_at <= max(self.started_at, self.plan_known_at):
            raise ValueError("TRIAL_SNAPSHOT_PRECEDES_TRIAL_OR_PLAN")

    @property
    def scope(self):
        return fingerprint((VERSION, asdict(self)))


def assess_trial_hold(request: TrialHold, facts: tuple[Condition, ...], *, as_of: datetime,
                      allow_test_fixture: bool = False) -> dict:
    """Project the role at one declared snapshot, never the current role at read time."""
    timestamp(as_of)
    if type(allow_test_fixture) is not bool:
        raise ValueError("BOOLEAN_FIXTURE_MODE_REQUIRED")
    visible = {}
    seen = set()
    for fact in facts:
        if not isinstance(fact, Condition):
            raise ValueError("CONDITION_REQUIRED")
        if fact.known_at >= as_of:
            continue
        if fact.source.startswith("TEST_FIXTURE") and not allow_test_fixture:
            raise ValueError("FIXTURE_CONFIRMATION_DISABLED")
        if (fact.case_id != request.scope or fact.contract != request.position.contract
                or fact.name not in REQUIRED or fact.name in seen):
            raise ValueError("TRIAL_HOLD_CONDITION_SCOPE_MISMATCH")
        seen.add(fact.name)
        # Research reading times and observations before the active trial cannot supply these facts.
        if fact.time_kind == "EVENT_TIME" and max(request.started_at, request.plan_known_at) < fact.observed_at:
            visible[fact.name] = fact
    checks = check_route(REQUIRED, ORDER, visible)["checks"]
    witness = visible.get("SAME_TRIAL_STILL_OPEN")
    checks["same_trial_snapshot_bound"] = witness.observed_at == request.snapshot_at if witness else None
    for name in ("TRIAL_SUCCEEDED", "TREND_CONFIRMED"):
        evidence = visible.get(name)
        checks[f"KNOWN_BEFORE_SNAPSHOT:{name}"] = (
            evidence.known_at < request.snapshot_at if evidence and evidence.known_at != request.snapshot_at else None
        )
    plan_visible = request.plan_known_at < as_of
    checks.update(
        plan_available=True if plan_visible else None,
        version_405=request.version_405 if plan_visible else None,
        snapshot_time_visible=True if request.snapshot_at < as_of else None,
    )
    status = ("NOT_PERMITTED" if False in checks.values() else
              "INDETERMINATE" if None in checks.values() else "CONDITIONAL_ROLE_CHANGE")
    after = (dict(role="TREND_HOLD", trial_id=request.trial_id, position=asdict(request.position),
                  snapshot_at=request.snapshot_at.isoformat())
             if status == "CONDITIONAL_ROLE_CHANGE" else None)
    return dict(status=status, checks=checks, after=after, scope=request.scope if request.snapshot_at < as_of else None,
                requested_action=None, executable=False, fill=None, author_action_at=None)
