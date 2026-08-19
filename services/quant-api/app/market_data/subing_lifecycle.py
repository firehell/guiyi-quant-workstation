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

    def __post_init__(self) -> None:
        directional = self.direction in {
            SubingDirection.LONG,
            SubingDirection.SHORT,
        }
        has_matching_key = (
            self.opportunity_key is not None
            and self.opportunity_key.direction is self.direction
        )
        invalid = (
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
        )
        if self.stage is LifecycleStage.IDLE:
            invalid = invalid or any(
                (
                    self.direction is not SubingDirection.NONE,
                    self.opportunity_key is not None,
                    self.entry_progress is not None,
                    self.confirmation_source is not None,
                )
            )
        elif self.stage is LifecycleStage.SETUP_ARMED:
            invalid = invalid or not directional or not has_matching_key
            invalid = (
                invalid
                or self.entry_progress is None
                or self.confirmation_source is not None
            )
        elif self.stage is LifecycleStage.ENTRY_CONFIRMED:
            invalid = invalid or not directional or not has_matching_key
            invalid = (
                invalid
                or self.entry_progress is not None
                or self.confirmation_source is None
            )
        else:
            invalid = invalid or not directional or not has_matching_key
            invalid = invalid or self.entry_progress is not None

        if invalid:
            raise ValueError("SUBING_LIFECYCLE_STATE_INVALID")
