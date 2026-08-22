"""Pure exact-boundary overlap reduction for two JDJ Candidate event streams."""

from __future__ import annotations

from dataclasses import replace

from app.research.candidate_convergence.five_candidate_relationships import (
    JdjExactOverlapResult,
    RELATIONSHIP_JDJ_PAIRS,
)
from app.research.jdj.jdj_context import JdjContextError
from app.research.jdj.jdj_events import (
    JdjDirection,
    JdjTriggerEvent,
)
from app.research.jdj.jdj_research import JdjResearchResult


def summarize_exact_jdj_overlap(
    left: JdjResearchResult,
    right: JdjResearchResult,
    *,
    symbol: str,
) -> JdjExactOverlapResult:
    """Count exact full-boundary event pairs without future outcomes."""

    validated_left = _validated_result(left)
    validated_right = _validated_result(right)
    if (
        (validated_left.candidate_id, validated_right.candidate_id)
        not in RELATIONSHIP_JDJ_PAIRS
        or validated_left.products != (symbol,)
        or validated_right.products != (symbol,)
    ):
        raise JdjContextError()

    left_by_boundary_direction = _index_events(validated_left.events)
    right_by_boundary_direction = _index_events(validated_right.events)
    same_direction_count = 0
    opposite_direction_count = 0
    left_same_direction_ids: set[str] = set()
    right_same_direction_ids: set[str] = set()

    for key, left_events in left_by_boundary_direction.items():
        boundary, direction = key
        right_same = right_by_boundary_direction.get((boundary, direction), ())
        right_opposite = right_by_boundary_direction.get(
            (boundary, _opposite(direction)),
            (),
        )
        same_direction_count += len(left_events) * len(right_same)
        opposite_direction_count += len(left_events) * len(right_opposite)
        if right_same:
            left_same_direction_ids.update(event.event_id for event in left_events)
            right_same_direction_ids.update(event.event_id for event in right_same)

    return JdjExactOverlapResult(
        left_candidate_id=validated_left.candidate_id,
        right_candidate_id=validated_right.candidate_id,
        symbol=symbol,
        status="available",
        reason_code=None,
        left_event_count=len(validated_left.events),
        right_event_count=len(validated_right.events),
        exact_same_boundary_same_direction_count=same_direction_count,
        exact_same_boundary_opposite_direction_count=opposite_direction_count,
        left_events_with_same_direction_match=len(left_same_direction_ids),
        right_events_with_same_direction_match=len(right_same_direction_ids),
    )


def _validated_result(value: object) -> JdjResearchResult:
    if not isinstance(value, JdjResearchResult):
        raise JdjContextError()
    validated = replace(value)
    events = tuple(replace(event) for event in validated.events)
    return replace(validated, events=events)


def _index_events(
    events: tuple[JdjTriggerEvent, ...],
) -> dict[tuple[tuple[object, ...], JdjDirection], tuple[JdjTriggerEvent, ...]]:
    grouped: dict[
        tuple[tuple[object, ...], JdjDirection],
        list[JdjTriggerEvent],
    ] = {}
    for event in events:
        grouped.setdefault((_boundary(event), event.direction), []).append(event)
    return {key: tuple(values) for key, values in grouped.items()}


def _boundary(event: JdjTriggerEvent) -> tuple[object, ...]:
    return (
        event.symbol,
        event.contract,
        event.segment_start_trading_day,
        event.trading_day,
        event.segment_bar_index,
        event.observed_at,
    )


def _opposite(direction: JdjDirection) -> JdjDirection:
    if direction is JdjDirection.LONG:
        return JdjDirection.SHORT
    return JdjDirection.LONG
