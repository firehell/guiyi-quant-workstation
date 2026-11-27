"""Versioned, time-gated area input for near405 research replays."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from .lms405 import Zone, number, timestamp
from .lms_confirmed_replay import fingerprint


@dataclass(frozen=True)
class AuthorRegion:
    zone: Zone
    effective_at: datetime
    purpose: str
    time_basis: str
    recovery_long: Decimal | None = None
    recovery_short: Decimal | None = None

    def __post_init__(self):
        timestamp(self.effective_at)
        if self.purpose not in {"PLAN_RANGE", "DIVIDE", "TARGET", "PROTECTION"}:
            raise ValueError("UNKNOWN_REGION_PURPOSE")
        if self.time_basis not in {
            "VERIFIED_PRE_EVENT",
            "RETROSPECTIVE",
            "TEST_FIXTURE",
        }:
            raise ValueError("UNKNOWN_REGION_TIME_BASIS")
        if (
            self.zone.expires_at is not None
            and self.zone.expires_at <= self.effective_at
        ):
            raise ValueError("EXPIRED_BEFORE_EFFECTIVE")
        if self.purpose == "PLAN_RANGE" and self.zone.lower == self.zone.upper:
            raise ValueError("DEGENERATE_PLAN_RANGE")
        for price in (self.recovery_long, self.recovery_short):
            if price is not None:
                number(price, positive=True)
                if self.purpose != "PLAN_RANGE":
                    raise ValueError("RECOVERY_REQUIRES_PLAN_RANGE")

    @property
    def starts_at(self):
        return max(self.zone.known_at, self.effective_at)

    def has_expired(self, at):
        return self.zone.expires_at is not None and self.zone.expires_at <= at


@dataclass(frozen=True)
class RegionInput:
    source_mode: str = "INDEPENDENT"
    recovery_rule: str = "KEYBAR"
    regions: tuple[AuthorRegion, ...] = ()

    def __post_init__(self):
        if self.source_mode not in {"INDEPENDENT", "AUTHOR"}:
            raise ValueError("UNKNOWN_REGION_MODE")
        if self.recovery_rule not in {"KEYBAR", "TWO_CLOSES_BEYOND"}:
            raise ValueError("UNKNOWN_RECOVERY_RULE")
        if self.source_mode == "INDEPENDENT" and self.regions:
            raise ValueError("INDEPENDENT_DISALLOWS_AUTHOR_REGIONS")
        if not isinstance(self.regions, tuple) or any(
            not isinstance(r, AuthorRegion) for r in self.regions
        ):
            raise ValueError("REGION_TUPLE_REQUIRED")
        ids = [r.zone.id for r in self.regions]
        if len(set(ids)) != len(ids):
            raise ValueError("DUPLICATE_REGION_ID")

    def prefix_hash(self, at):
        return fingerprint(
            [
                asdict(r)
                for r in sorted(self.regions, key=lambda r: r.zone.id)
                if r.zone.known_at <= at
            ]
        )

    def resolve(self, pattern, decision_at, *, timely_fixture):
        usable = {"VERIFIED_PRE_EVENT"}
        if timely_fixture:
            usable.add("TEST_FIXTURE")
        current = [
            r
            for r in self.regions
            if r.purpose == "PLAN_RANGE"
            and r.time_basis in usable
            and r.starts_at <= decision_at
        ]
        if not current:
            return None, "AUTHOR_PLAN_RANGE_UNAVAILABLE"
        latest = max(r.starts_at for r in current)
        winners = [r for r in current if r.starts_at == latest]
        if len(winners) != 1:
            return None, "AUTHOR_PLAN_RANGE_CONFLICT"
        region = winners[0]
        if region.has_expired(decision_at):
            return None, "AUTHOR_PLAN_RANGE_EXPIRED"
        if latest >= pattern.start:
            return None, "AUTHOR_PLAN_RANGE_NOT_KNOWN_BEFORE_PATTERN"
        return region, None
