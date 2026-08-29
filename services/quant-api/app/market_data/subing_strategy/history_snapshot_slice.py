from __future__ import annotations

from app.market_data.subing_strategy.performance import (
    SubingStrategyPerformanceProjection,
)
from app.market_data.subing_strategy.policy import SubingStrategyPolicy
from app.market_data.subing_strategy.service import (
    SubingStrategyHistoricalProjection,
    SubingStrategyHistoricalRequest,
    _episode_intersects,
)


def try_slice_history_from_snapshot(
    request: SubingStrategyHistoricalRequest,
    snapshot: SubingStrategyPerformanceProjection,
    *,
    policy: SubingStrategyPolicy,
    engine_identity_sha256: str | None,
) -> SubingStrategyHistoricalProjection | None:
    if (
        snapshot.symbol != request.symbol
        or snapshot.series_kind != request.series_kind
        or snapshot.frequency != request.frequency
        or snapshot.coverage_through != request.through
        or request.since < snapshot.coverage_since
        or snapshot.strategy_id != policy.strategy_id
        or snapshot.formula_version != policy.formula_version
    ):
        return None
    episodes = tuple(
        episode
        for episode in snapshot.episodes
        if _episode_intersects(episode, request=request)
    )
    actions = tuple(
        sorted(
            (
                action
                for episode in episodes
                for action in (episode.entry_action, episode.exit_action)
                if action is not None
                and request.since <= action.trading_day <= request.through
            ),
            key=lambda action: (action.effective_bar_end, action.action_id),
        )
    )
    return SubingStrategyHistoricalProjection(
        request=request,
        policy=policy,
        resolved_cutoff=snapshot.resolved_cutoff,
        segment_summaries=(),
        actions=actions,
        episodes=episodes,
        context_unavailable=(),
        cache_state="hit",
        engine_identity_sha256=engine_identity_sha256,
    )
