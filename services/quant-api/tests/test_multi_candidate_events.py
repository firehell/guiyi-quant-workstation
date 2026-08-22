from __future__ import annotations

from datetime import UTC, date, datetime

from app.research.robustness.multi_candidate_events import (
    CandidateResearchDirection,
    CandidateResearchEvent,
    from_n_completion,
    from_subing_entry,
    summarize_candidate_relationship,
)
from app.research.n_structure.n_structure_pattern import NDirection
from app.research.n_structure.n_structure_research_service import (
    NStructureCompletionResearchEvent,
)
from app.market_data.subing_lifecycle import ConfirmationSource, SubingOpportunityKey
from app.research.subing.subing_lifecycle_research_service import (
    SubingLifecycleEntryResearchEvent,
)
from app.market_data.subing_research import SubingDirection


OBSERVED = datetime(2026, 8, 18, 1, 5, tzinfo=UTC)


def test_source_events_adapt_to_exact_minimal_candidate_contract() -> None:
    key = SubingOpportunityKey(
        policy_id="subing_lifecycle_v2_research_v1",
        symbol="jm",
        contract="JM2701",
        segment_start_trading_day=date(2026, 8, 18),
        direction=SubingDirection.LONG,
        origin_at=OBSERVED,
    )
    subing = from_subing_entry(
        SubingLifecycleEntryResearchEvent(
            event_id="transition-1",
            symbol="jm",
            contract="JM2701",
            segment_start_trading_day=date(2026, 8, 18),
            observed_at=OBSERVED,
            trading_day=date(2026, 8, 18),
            segment_bar_index=7,
            direction=SubingDirection.LONG,
            opportunity_key=key,
            confirmation_source=ConfirmationSource.FORMAL_V1,
        )
    )
    n_event = from_n_completion(
        NStructureCompletionResearchEvent(
            event_id="n-1",
            symbol="jm",
            contract="JM2701",
            segment_start_trading_day=date(2026, 8, 18),
            observed_at=OBSERVED,
            trading_day=date(2026, 8, 18),
            segment_bar_index=9,
            direction=NDirection.DOWN,
        )
    )

    assert subing == CandidateResearchEvent(
        candidate_id="subing_lifecycle_v2_candidate_v1",
        source_kind="subing_lifecycle",
        source_event_kind="entry_confirmed",
        source_event_id="transition-1",
        symbol="jm",
        contract="JM2701",
        segment_start_trading_day=date(2026, 8, 18),
        observed_at=OBSERVED,
        trading_day=date(2026, 8, 18),
        segment_bar_index=7,
        direction=CandidateResearchDirection.LONG,
    )
    assert n_event.direction is CandidateResearchDirection.SHORT
    assert n_event.source_event_id == "n-1"
    assert n_event.candidate_id == "n_structure_5m_candidate_v1"


def _event(
    event_id: str,
    index: int,
    direction: CandidateResearchDirection,
    *,
    candidate_id: str = "subing_lifecycle_v2_candidate_v1",
    contract: str = "JM2701",
    segment_start: date = date(2026, 8, 18),
    trading_day: date = date(2026, 8, 18),
) -> CandidateResearchEvent:
    source_kind, source_event_kind = (
        ("subing_lifecycle", "entry_confirmed")
        if candidate_id == "subing_lifecycle_v2_candidate_v1"
        else ("n_structure", "n_completed")
    )
    return CandidateResearchEvent(
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_event_kind=source_event_kind,
        source_event_id=event_id,
        symbol="jm",
        contract=contract,
        segment_start_trading_day=segment_start,
        observed_at=OBSERVED,
        trading_day=trading_day,
        segment_bar_index=index,
        direction=direction,
    )


def test_exact_same_boundary_counts_real_event_pairs() -> None:
    sources = (
        _event("s1", 10, CandidateResearchDirection.LONG),
        _event("s2", 10, CandidateResearchDirection.LONG),
    )
    targets = (
        _event("t1", 10, CandidateResearchDirection.LONG, candidate_id="n_structure_5m_candidate_v1"),
        _event("t2", 10, CandidateResearchDirection.LONG, candidate_id="n_structure_5m_candidate_v1"),
        _event("t3", 10, CandidateResearchDirection.SHORT, candidate_id="n_structure_5m_candidate_v1"),
    )

    summary = summarize_candidate_relationship(sources, targets, proximity_bars=(3, 5, 8))

    assert summary.exact_same_direction_count == 4
    assert summary.exact_opposite_direction_count == 2
    assert summary.within_3_same_direction_source_count == 2


def test_nearest_tie_is_earlier_then_lexicographic_event_id() -> None:
    source = (_event("s", 100, CandidateResearchDirection.LONG),)
    symmetric = (
        _event("later", 103, CandidateResearchDirection.LONG, candidate_id="n_structure_5m_candidate_v1"),
        _event("earlier", 97, CandidateResearchDirection.LONG, candidate_id="n_structure_5m_candidate_v1"),
    )
    summary = summarize_candidate_relationship(source, symmetric, proximity_bars=(3, 5, 8))
    assert summary.signed_distance_median == -3
    assert summary.target_earlier_count == 1

    same_index = (
        _event(
            "z",
            100,
            CandidateResearchDirection.LONG,
            candidate_id="n_structure_5m_candidate_v1",
            trading_day=date(2026, 8, 19),
        ),
        _event("a", 100, CandidateResearchDirection.LONG, candidate_id="n_structure_5m_candidate_v1"),
    )
    lexicographic = summarize_candidate_relationship(source, same_index, proximity_bars=(3, 5, 8))
    assert lexicographic.same_trading_day_count == 1
    assert lexicographic.cross_trading_day_count == 0


def test_cross_contract_or_segment_never_matches() -> None:
    source = (_event("s", 10, CandidateResearchDirection.LONG),)
    targets = (
        _event(
            "contract",
            11,
            CandidateResearchDirection.LONG,
            candidate_id="n_structure_5m_candidate_v1",
            contract="JM2705",
        ),
        _event(
            "segment",
            11,
            CandidateResearchDirection.LONG,
            candidate_id="n_structure_5m_candidate_v1",
            segment_start=date(2026, 8, 19),
            trading_day=date(2026, 8, 19),
        ),
    )

    summary = summarize_candidate_relationship(source, targets, proximity_bars=(3, 5, 8))

    assert summary.within_8_same_direction_source_count == 0
    assert summary.nearest_match_count_within_8 == 0


def test_proximity_is_nested_source_coverage_and_target_is_reusable() -> None:
    distances: tuple[int | None, ...] = (0, 2, 4, 7, 9, None)
    sources = []
    targets = []
    for offset, distance in enumerate(distances):
        segment_day = date(2026, 7, 1 + offset)
        sources.append(
            _event(
                f"s{offset}",
                100,
                CandidateResearchDirection.LONG,
                segment_start=segment_day,
                trading_day=segment_day,
            )
        )
        if distance is not None:
            targets.append(
                _event(
                    f"t{offset}",
                    100 + distance,
                    CandidateResearchDirection.LONG,
                    candidate_id="n_structure_5m_candidate_v1",
                    segment_start=segment_day,
                    trading_day=segment_day,
                )
            )
    summary = summarize_candidate_relationship(sources, targets, proximity_bars=(3, 5, 8))
    assert summary.within_3_same_direction_source_count == 2
    assert summary.within_5_same_direction_source_count == 3
    assert summary.within_8_same_direction_source_count == 4
    assert summary.nearest_match_count_within_8 == 4

    reused = summarize_candidate_relationship(
        (
            _event("s1", 99, CandidateResearchDirection.LONG),
            _event("s2", 101, CandidateResearchDirection.LONG),
        ),
        (_event("t", 100, CandidateResearchDirection.LONG, candidate_id="n_structure_5m_candidate_v1"),),
        proximity_bars=(3, 5, 8),
    )
    assert reused.within_3_same_direction_source_count == 2


def test_signed_direction_and_day_span_are_counted_only_within_eight() -> None:
    sources = (
        _event("s1", 10, CandidateResearchDirection.LONG),
        _event("s2", 20, CandidateResearchDirection.LONG),
        _event("s3", 30, CandidateResearchDirection.LONG),
    )
    targets = (
        _event("t1", 8, CandidateResearchDirection.LONG, candidate_id="n_structure_5m_candidate_v1"),
        _event("t2", 20, CandidateResearchDirection.LONG, candidate_id="n_structure_5m_candidate_v1"),
        _event(
            "t3",
            35,
            CandidateResearchDirection.LONG,
            candidate_id="n_structure_5m_candidate_v1",
            trading_day=date(2026, 8, 19),
        ),
    )
    summary = summarize_candidate_relationship(sources, targets, proximity_bars=(3, 5, 8))
    assert summary.signed_distance_min == -2
    assert summary.signed_distance_median == 0
    assert summary.signed_distance_max == 5
    assert (summary.target_earlier_count, summary.target_same_boundary_count, summary.target_later_count) == (1, 1, 1)
    assert (summary.same_trading_day_count, summary.cross_trading_day_count) == (2, 1)

    reverse = summarize_candidate_relationship(targets, sources, proximity_bars=(3, 5, 8))
    assert reverse.source_candidate_id == "n_structure_5m_candidate_v1"
    assert reverse.target_candidate_id == "subing_lifecycle_v2_candidate_v1"
    assert reverse.signed_distance_median == 0
