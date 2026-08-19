from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from .subing_research import SubingDirection


class LifecycleAvailability(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


class LifecycleStage(StrEnum):
    IDLE = "idle"
    SETUP_ARMED = "setup_armed"
    ENTRY_CONFIRMED = "entry_confirmed"
    CONTINUATION = "continuation"
    EXIT_RISK = "exit_risk"
    CLOSED = "closed"


class EntryProgress(StrEnum):
    WAITING_TRIGGER = "waiting_trigger"
    HOLD_CONFIRMING = "hold_confirming"
    RETEST_CONFIRMING = "retest_confirming"


class ConfirmationSource(StrEnum):
    FORMAL_V1 = "formal_v1"
    MOMENTUM_HOLD = "momentum_hold"
    PIVOT_BREAK_HOLD = "pivot_break_hold"
    PIVOT_RETEST_REBREAK = "pivot_retest_rebreak"


class SubingLifecycleStateError(ValueError):
    code = "SUBING_LIFECYCLE_STATE_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingOpportunityKey:
    policy_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    direction: SubingDirection
    origin_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.policy_id, str)
            or not self.policy_id.strip()
            or not isinstance(self.symbol, str)
            or not self.symbol.strip()
            or not isinstance(self.contract, str)
            or not self.contract.strip()
            or type(self.segment_start_trading_day) is not date
            or not isinstance(self.direction, SubingDirection)
            or self.direction not in {SubingDirection.LONG, SubingDirection.SHORT}
            or not isinstance(self.origin_at, datetime)
            or self.origin_at.tzinfo is None
            or self.origin_at.utcoffset() is None
        ):
            raise ValueError("SUBING_OPPORTUNITY_KEY_INVALID")


@dataclass(frozen=True, slots=True)
class SubingLifecycleState:
    availability: LifecycleAvailability
    direction: SubingDirection
    stage: LifecycleStage
    opportunity_key: SubingOpportunityKey | None = None
    entry_progress: EntryProgress | None = None
    confirmation_source: ConfirmationSource | None = None
    confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        invalid_type = (
            not isinstance(self.availability, LifecycleAvailability)
            or not isinstance(self.direction, SubingDirection)
            or not isinstance(self.stage, LifecycleStage)
            or (
                self.opportunity_key is not None
                and not isinstance(self.opportunity_key, SubingOpportunityKey)
            )
            or (
                self.entry_progress is not None
                and not isinstance(self.entry_progress, EntryProgress)
            )
            or (
                self.confirmation_source is not None
                and not isinstance(self.confirmation_source, ConfirmationSource)
            )
            or (self.confirmed_at is not None and not isinstance(self.confirmed_at, datetime))
        )
        if invalid_type:
            raise SubingLifecycleStateError()

        directional = self.direction in {
            SubingDirection.LONG,
            SubingDirection.SHORT,
        }
        has_matching_key = (
            isinstance(self.opportunity_key, SubingOpportunityKey)
            and self.opportunity_key.direction is self.direction
        )
        has_aware_confirmation_time = (
            isinstance(self.confirmed_at, datetime)
            and self.confirmed_at.tzinfo is not None
            and self.confirmed_at.utcoffset() is not None
        )
        invalid = self.confirmed_at is not None and not has_aware_confirmation_time
        if (
            has_aware_confirmation_time
            and isinstance(self.confirmed_at, datetime)
            and isinstance(self.opportunity_key, SubingOpportunityKey)
            and self.confirmed_at < self.opportunity_key.origin_at
        ):
            invalid = True
        if self.stage is LifecycleStage.IDLE:
            invalid = invalid or any(
                (
                    self.direction is not SubingDirection.NONE,
                    self.opportunity_key is not None,
                    self.entry_progress is not None,
                    self.confirmation_source is not None,
                    self.confirmed_at is not None,
                )
            )
        elif self.stage is LifecycleStage.SETUP_ARMED:
            invalid = invalid or not directional or not has_matching_key
            invalid = (
                invalid
                or self.entry_progress is None
                or self.confirmation_source is not None
                or self.confirmed_at is not None
            )
        elif self.stage in {
            LifecycleStage.ENTRY_CONFIRMED,
            LifecycleStage.CONTINUATION,
            LifecycleStage.EXIT_RISK,
        }:
            invalid = invalid or not directional or not has_matching_key
            invalid = (
                invalid
                or self.entry_progress is not None
                or self.confirmation_source is None
                or not has_aware_confirmation_time
            )
        else:
            invalid = invalid or not directional or not has_matching_key
            invalid = invalid or self.entry_progress is not None
            invalid = invalid or (
                (self.confirmation_source is None) != (self.confirmed_at is None)
            )

        if invalid:
            raise SubingLifecycleStateError()
