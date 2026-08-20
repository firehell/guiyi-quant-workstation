from __future__ import annotations

from datetime import UTC, date, datetime

from app.market_data.multi_candidate_events import (
    CandidateResearchDirection,
    CandidateResearchEvent,
    from_n_completion,
    from_subing_entry,
)
from app.market_data.n_structure_pattern import NDirection
from app.market_data.n_structure_research_service import (
    NStructureCompletionResearchEvent,
)
from app.market_data.subing_lifecycle import ConfirmationSource, SubingOpportunityKey
from app.market_data.subing_lifecycle_research_service import (
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
