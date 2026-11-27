"""Independent target progress and recovery-price observations for a fixed published plan."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from . import Bar, Zone

VERSION = "lms405-recovery-path-v1"
_MINUTE = timedelta(minutes=1)
_MICROSECOND = timedelta(microseconds=1)


@dataclass(frozen=True)
class RecoveryPlan:
    side: str
    recovery: Zone
    targets: tuple[Zone, ...]

    def __post_init__(self):
        if self.side not in ("LONG", "SHORT") or not isinstance(self.recovery, Zone) or (
            not isinstance(self.targets, tuple) or not self.targets or any(not isinstance(zone, Zone) for zone in self.targets)
        ):
            raise ValueError("RECOVERY_PLAN_INVALID")
        zones = (self.recovery, *self.targets)
        if len({zone.id for zone in zones}) != len(zones) or any(
            (zone.contract, zone.known_at, zone.source, zone.expires_at)
            != (self.recovery.contract, self.recovery.known_at, self.recovery.source, self.recovery.expires_at)
            for zone in self.targets
        ):
            raise ValueError("RECOVERY_PLAN_SCOPE_MISMATCH")


@dataclass(frozen=True)
class RecoveryFrame:
    plan: RecoveryPlan
    bar_end: datetime
    known_at: datetime
    consecutive_recovery_closes: int
    target_seen_at: tuple[datetime | None, ...]
    previously_known_targets: tuple[str, ...]

    @property
    def price_recovery_candidate(self):
        return self.consecutive_recovery_closes >= 2

    @property
    def first_target_and_recovery_candidate(self):
        return self.price_recovery_candidate and self.plan.targets[0].id in self.previously_known_targets

    @property
    def all_targets_and_recovery_candidate(self):
        return self.price_recovery_candidate and len(self.previously_known_targets) == len(self.plan.targets)


def advance_recovery(plan: RecoveryPlan, bar: Bar, previous: RecoveryFrame | None = None) -> RecoveryFrame | None:
    """Record one completed minute. A target reached on this bar only qualifies a later bar."""
    if not isinstance(bar, Bar) or bar.completed is not True or bar.contract != plan.recovery.contract or (
        bar.start is None or bar.end - bar.start != _MINUTE
    ):
        raise ValueError("RECOVERY_REQUIRES_COMPLETED_CONTRACT_MINUTE")
    if previous is not None and (
        not isinstance(previous, RecoveryFrame) or previous.plan != plan or bar.start < previous.bar_end
    ):
        raise ValueError("RECOVERY_PREVIOUS_FRAME_SCOPE_OR_ORDER_CHANGED")
    known_at = bar.end + _MICROSECOND
    if bar.start <= plan.recovery.known_at or (
        plan.recovery.expires_at is not None and known_at >= plan.recovery.expires_at
    ):
        return None

    short = plan.side == "SHORT"
    recovered = bar.close < plan.recovery.lower if short else bar.close > plan.recovery.upper
    run = previous.consecutive_recovery_closes if previous is not None and previous.bar_end == bar.start else 0
    carried_targets = previous.target_seen_at if previous is not None else (None,) * len(plan.targets)
    known_targets = []
    seen_at = []
    for target, earlier in zip(plan.targets, carried_targets, strict=True):
        reached = bar.low <= target.lower if short else bar.high >= target.upper
        seen_at.append(earlier if earlier is not None else known_at if reached else None)
        if earlier is not None and earlier < known_at:
            known_targets.append(target.id)
    return RecoveryFrame(plan, bar.end, known_at, run + 1 if recovered else 0, tuple(seen_at), tuple(known_targets))
