from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from .domain import normalize_contract_for_symbol
from .n_structure_pattern import NDirection
from .n_structure_research_service import NStructureCompletionResearchEvent
from .subing_lifecycle_research_service import SubingLifecycleEntryResearchEvent
from .subing_research import SubingDirection


class CandidateResearchDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True, slots=True)
class CandidateResearchEvent:
    candidate_id: str
    source_kind: str
    source_event_kind: str
    source_event_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    observed_at: datetime
    trading_day: date
    segment_bar_index: int
    direction: CandidateResearchDirection

    def __post_init__(self) -> None:
        expected = {
            "subing_lifecycle_v2_candidate_v1": (
                "subing_lifecycle",
                "entry_confirmed",
            ),
            "n_structure_5m_candidate_v1": ("n_structure", "n_completed"),
        }.get(self.candidate_id)
        if (
            expected is None
            or (self.source_kind, self.source_event_kind) != expected
            or not isinstance(self.source_event_id, str)
            or not self.source_event_id
            or not _symbol(self.symbol)
            or normalize_contract_for_symbol(self.symbol, self.contract)
            != self.contract
            or type(self.segment_start_trading_day) is not date
            or type(self.trading_day) is not date
            or self.trading_day < self.segment_start_trading_day
            or not _aware(self.observed_at)
            or type(self.segment_bar_index) is not int
            or self.segment_bar_index < 0
            or not isinstance(self.direction, CandidateResearchDirection)
        ):
            raise ValueError("MULTI_CANDIDATE_EVENT_INVALID")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))


def from_subing_entry(
    event: SubingLifecycleEntryResearchEvent,
) -> CandidateResearchEvent:
    if not isinstance(event, SubingLifecycleEntryResearchEvent):
        raise TypeError("event must be SubingLifecycleEntryResearchEvent")
    return CandidateResearchEvent(
        candidate_id="subing_lifecycle_v2_candidate_v1",
        source_kind="subing_lifecycle",
        source_event_kind="entry_confirmed",
        source_event_id=event.event_id,
        symbol=event.symbol,
        contract=event.contract,
        segment_start_trading_day=event.segment_start_trading_day,
        observed_at=event.observed_at,
        trading_day=event.trading_day,
        segment_bar_index=event.segment_bar_index,
        direction=(
            CandidateResearchDirection.LONG
            if event.direction is SubingDirection.LONG
            else CandidateResearchDirection.SHORT
        ),
    )


def from_n_completion(
    event: NStructureCompletionResearchEvent,
) -> CandidateResearchEvent:
    if not isinstance(event, NStructureCompletionResearchEvent):
        raise TypeError("event must be NStructureCompletionResearchEvent")
    return CandidateResearchEvent(
        candidate_id="n_structure_5m_candidate_v1",
        source_kind="n_structure",
        source_event_kind="n_completed",
        source_event_id=event.event_id,
        symbol=event.symbol,
        contract=event.contract,
        segment_start_trading_day=event.segment_start_trading_day,
        observed_at=event.observed_at,
        trading_day=event.trading_day,
        segment_bar_index=event.segment_bar_index,
        direction=(
            CandidateResearchDirection.LONG
            if event.direction is NDirection.UP
            else CandidateResearchDirection.SHORT
        ),
    )


def _symbol(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.isascii()
        and value.isalpha()
        and value == value.lower()
    )


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )
