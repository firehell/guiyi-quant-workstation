from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_strategy.contracts import (
    SUBING_STRATEGY_ID,
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyEpisodeState,
    SubingStrategyFillBasis,
    subing_strategy_action_id,
    subing_strategy_episode_id,
)
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_strategy.history_snapshot_slice import (
    try_slice_history_from_snapshot,
)
from app.market_data.subing_strategy.performance import (
    SubingStrategyPerformanceProjection,
    summarize_subing_strategy_episodes,
)
from app.market_data.subing_strategy.policy import load_subing_strategy_policy
from app.market_data.subing_strategy.service import SubingStrategyHistoricalRequest

def _action(
    *,
    kind: SubingStrategyActionKind,
    trading_day: date,
    segment_start: date,
    opportunity_id: str,
    decision_at: datetime,
    effective_open_at: datetime | None,
    effective_bar_end: datetime,
    episode_id: str | None = None,
) -> SubingStrategyAction:
    identity = {
        "strategy_id": SUBING_STRATEGY_ID,
        "formula_version": "subing_strategy_15m_v1",
        "symbol": "JM",
        "contract": "JM2605",
        "segment_start_trading_day": segment_start.isoformat(),
        "opportunity_id": opportunity_id,
        "kind": kind.value,
        "decision_at": decision_at.isoformat(),
        "effective_bar_end": effective_bar_end.isoformat(),
        "fill_basis": SubingStrategyFillBasis.NEXT_BAR_OPEN.value,
    }
    is_open = kind in {
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.OPEN_SHORT,
    }
    return SubingStrategyAction(
        action_id=subing_strategy_action_id(identity),
        episode_id=(
            episode_id
            or (
                subing_strategy_episode_id(identity)
                if is_open
                else "subing-episode:test"
            )
        ),
        strategy_id=SUBING_STRATEGY_ID,
        formula_version="subing_strategy_15m_v1",
        kind=kind,
        symbol="JM",
        contract="JM2605",
        trading_day=trading_day,
        segment_start_trading_day=segment_start,
        opportunity_id=opportunity_id,
        decision_at=decision_at,
        effective_open_at=effective_open_at,
        effective_bar_end=effective_bar_end,
        reference_price=Decimal("100"),
        fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
        confirmation_source=(ConfirmationSource.FORMAL_V1 if is_open else None),
        reason_codes=(() if is_open else ("EMA21_BREACH_LONG",)),
        direction_context_source_day=(trading_day if is_open else None),
        direction_context_target_day=(trading_day if is_open else None),
        bound_reference_pivot=None,
    )


def _closed(entry_day: date, exit_day: date, tag: str) -> SubingStrategyEpisode:
    opportunity_id = f"subing-opportunity:{tag}"
    segment_start = entry_day
    entry = _action(
        kind=SubingStrategyActionKind.OPEN_LONG,
        trading_day=entry_day,
        segment_start=segment_start,
        opportunity_id=opportunity_id,
        decision_at=datetime(entry_day.year, entry_day.month, entry_day.day, 10, 0, tzinfo=UTC),
        effective_open_at=datetime(
            entry_day.year, entry_day.month, entry_day.day, 10, 15, tzinfo=UTC
        ),
        effective_bar_end=datetime(
            entry_day.year, entry_day.month, entry_day.day, 10, 30, tzinfo=UTC
        ),
    )
    exit_action = _action(
        kind=SubingStrategyActionKind.CLOSE_LONG,
        trading_day=exit_day,
        segment_start=segment_start,
        opportunity_id=opportunity_id,
        decision_at=datetime(exit_day.year, exit_day.month, exit_day.day, 10, 45, tzinfo=UTC),
        effective_open_at=datetime(
            exit_day.year, exit_day.month, exit_day.day, 11, 0, tzinfo=UTC
        ),
        effective_bar_end=datetime(
            exit_day.year, exit_day.month, exit_day.day, 11, 15, tzinfo=UTC
        ),
        episode_id=entry.episode_id,
    )
    return SubingStrategyEpisode(
        episode_id=entry.episode_id,
        direction=SubingDirection.LONG,
        entry_action=entry,
        exit_action=exit_action,
        state=SubingStrategyEpisodeState.CLOSED,
        holding_bar_count=2,
        reference_change_percent=Decimal("1"),
        current_reference_change_percent=None,
        latest_reference_price=None,
        exit_reason_codes=exit_action.reason_codes,
        structure_exit_available=False,
    )


def _snapshot(*, since: date, through: date, episodes: tuple[SubingStrategyEpisode, ...]):
    return SubingStrategyPerformanceProjection(
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        frequency=BarFrequency.M15,
        coverage_since=since,
        coverage_through=through,
        resolved_cutoff=datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
        segment_count=2,
        bar_count_15m=20186,
        context_unavailable_count=0,
        cache_state="hit",
        summary=summarize_subing_strategy_episodes(episodes),
        episodes=episodes,
    )


def _request(since: date, through: date) -> SubingStrategyHistoricalRequest:
    return SubingStrategyHistoricalRequest(
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        symbol="jm",
        frequency=BarFrequency.M15,
        since=since,
        through=through,
    )


def test_same_through_earlier_since_filters_actions_and_episodes() -> None:
    june = _closed(date(2026, 6, 4), date(2026, 6, 4), "june")
    july = _closed(date(2026, 7, 10), date(2026, 7, 13), "july")
    snapshot = _snapshot(
        since=date(2024, 1, 1),
        through=date(2026, 8, 28),
        episodes=(june, july),
    )
    policy = load_subing_strategy_policy()

    sliced = try_slice_history_from_snapshot(
        _request(date(2026, 6, 15), date(2026, 8, 28)),
        snapshot,
        policy=policy,
        engine_identity_sha256="a" * 64,
    )

    assert sliced is not None
    assert sliced.cache_state == "hit"
    assert sliced.segment_summaries == ()
    assert sliced.context_unavailable == ()
    assert sliced.resolved_cutoff == snapshot.resolved_cutoff
    assert [episode.episode_id for episode in sliced.episodes] == [july.episode_id]
    assert [action.action_id for action in sliced.actions] == [
        july.entry_action.action_id,
        july.exit_action.action_id,
    ]


def test_since_before_coverage_or_earlier_through_does_not_slice() -> None:
    snapshot = _snapshot(
        since=date(2026, 1, 1),
        through=date(2026, 8, 28),
        episodes=(_closed(date(2026, 6, 4), date(2026, 6, 4), "june"),),
    )
    policy = load_subing_strategy_policy()
    kwargs = {"snapshot": snapshot, "policy": policy, "engine_identity_sha256": None}

    assert try_slice_history_from_snapshot(
        _request(date(2025, 12, 1), date(2026, 8, 28)),
        **kwargs,
    ) is None
    assert try_slice_history_from_snapshot(
        _request(date(2026, 6, 1), date(2026, 8, 11)),
        **kwargs,
    ) is None
