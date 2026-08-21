from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from app.market_data.domain import normalize_contract_for_symbol
from app.research.n_structure.n_structure_pattern import NDirection
from app.research.n_structure.n_structure_research_service import NStructureCompletionResearchEvent
from .multi_candidate_robustness import CandidateRelationshipSummary
from app.research.subing.subing_lifecycle_research_service import SubingLifecycleEntryResearchEvent
from app.market_data.subing_research import SubingDirection


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


def summarize_candidate_relationship(
    source_events: Sequence[CandidateResearchEvent],
    target_events: Sequence[CandidateResearchEvent],
    *,
    proximity_bars: tuple[int, int, int],
) -> CandidateRelationshipSummary:
    sources = tuple(source_events)
    targets = tuple(target_events)
    if proximity_bars != (3, 5, 8):
        raise ValueError("MULTI_CANDIDATE_EVENT_INVALID")
    source_candidate_id, target_candidate_id = _relationship_identities(
        sources,
        targets,
    )
    exact = Counter(
        (
            event.symbol,
            event.contract,
            event.segment_start_trading_day,
            event.segment_bar_index,
            event.direction,
        )
        for event in targets
    )
    target_by_segment: dict[
        tuple[str, str, date, CandidateResearchDirection],
        dict[int, tuple[CandidateResearchEvent, ...]],
    ] = {}
    grouped: defaultdict[
        tuple[str, str, date, CandidateResearchDirection],
        defaultdict[int, list[CandidateResearchEvent]],
    ] = defaultdict(lambda: defaultdict(list))
    for event in targets:
        grouped[_segment_direction_key(event)][event.segment_bar_index].append(event)
    for key, grouped_by_index in grouped.items():
        target_by_segment[key] = {
            index: tuple(sorted(events, key=lambda event: event.source_event_id))
            for index, events in sorted(grouped_by_index.items())
        }

    exact_same = 0
    exact_opposite = 0
    within = {3: 0, 5: 0, 8: 0}
    distances: list[int] = []
    target_earlier = 0
    target_same = 0
    target_later = 0
    same_day = 0
    cross_day = 0
    for source in sources:
        base = (
            source.symbol,
            source.contract,
            source.segment_start_trading_day,
            source.segment_bar_index,
        )
        exact_same += exact[(*base, source.direction)]
        opposite = (
            CandidateResearchDirection.SHORT
            if source.direction is CandidateResearchDirection.LONG
            else CandidateResearchDirection.LONG
        )
        exact_opposite += exact[(*base, opposite)]

        target_indexes = target_by_segment.get(_segment_direction_key(source))
        if not target_indexes:
            continue
        indexes = tuple(target_indexes)
        position = bisect_left(indexes, source.segment_bar_index)
        candidate_indexes = set()
        if position < len(indexes):
            candidate_indexes.add(indexes[position])
        if position > 0:
            candidate_indexes.add(indexes[position - 1])
        candidates = tuple(
            target
            for index in candidate_indexes
            for target in target_indexes[index]
        )
        selected = min(
            candidates,
            key=lambda target: (
                abs(target.segment_bar_index - source.segment_bar_index),
                target.segment_bar_index,
                target.source_event_id,
            ),
        )
        distance = selected.segment_bar_index - source.segment_bar_index
        absolute = abs(distance)
        for horizon in proximity_bars:
            within[horizon] += int(absolute <= horizon)
        if absolute > 8:
            continue
        distances.append(distance)
        target_earlier += int(distance < 0)
        target_same += int(distance == 0)
        target_later += int(distance > 0)
        same_day += int(selected.trading_day == source.trading_day)
        cross_day += int(selected.trading_day != source.trading_day)

    return CandidateRelationshipSummary(
        source_candidate_id=source_candidate_id,
        target_candidate_id=target_candidate_id,
        source_event_count=len(sources),
        target_event_count=len(targets),
        exact_same_direction_count=exact_same,
        exact_opposite_direction_count=exact_opposite,
        within_3_same_direction_source_count=within[3],
        within_5_same_direction_source_count=within[5],
        within_8_same_direction_source_count=within[8],
        nearest_match_count_within_8=len(distances),
        signed_distance_min=min(distances) if distances else None,
        signed_distance_median=_decimal_median(distances) if distances else None,
        signed_distance_max=max(distances) if distances else None,
        target_earlier_count=target_earlier,
        target_same_boundary_count=target_same,
        target_later_count=target_later,
        same_trading_day_count=same_day,
        cross_trading_day_count=cross_day,
    )


def _relationship_identities(
    sources: tuple[CandidateResearchEvent, ...],
    targets: tuple[CandidateResearchEvent, ...],
) -> tuple[str, str]:
    if not sources and not targets:
        raise ValueError("MULTI_CANDIDATE_EVENT_INVALID")
    source_id = sources[0].candidate_id if sources else _other(targets[0].candidate_id)
    target_id = targets[0].candidate_id if targets else _other(sources[0].candidate_id)
    if (
        source_id == target_id
        or any(event.candidate_id != source_id for event in sources)
        or any(event.candidate_id != target_id for event in targets)
    ):
        raise ValueError("MULTI_CANDIDATE_EVENT_INVALID")
    return source_id, target_id


def _other(candidate_id: str) -> str:
    if candidate_id == "subing_lifecycle_v2_candidate_v1":
        return "n_structure_5m_candidate_v1"
    if candidate_id == "n_structure_5m_candidate_v1":
        return "subing_lifecycle_v2_candidate_v1"
    raise ValueError("MULTI_CANDIDATE_EVENT_INVALID")


def _segment_direction_key(
    event: CandidateResearchEvent,
) -> tuple[str, str, date, CandidateResearchDirection]:
    return (
        event.symbol,
        event.contract,
        event.segment_start_trading_day,
        event.direction,
    )


def _decimal_median(values: Sequence[int]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return Decimal(ordered[midpoint])
    return (Decimal(ordered[midpoint - 1]) + Decimal(ordered[midpoint])) / Decimal(2)


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
