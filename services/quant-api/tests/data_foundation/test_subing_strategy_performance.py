from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_strategy.contracts import (
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyEpisodeState,
)
from app.market_data.subing_strategy.performance import (
    SubingStrategyPerformanceService,
    summarize_subing_strategy_episodes,
)
from app.market_data.subing_strategy.service import SubingStrategyHistoricalRequest

from research.subing_strategy_fixtures import action_fixture


def _episode(
    change: str | None,
    *,
    direction: SubingDirection,
    holding: int,
    reason_codes: tuple[str, ...] = (),
) -> SubingStrategyEpisode:
    open_kind = (
        SubingStrategyActionKind.OPEN_LONG
        if direction is SubingDirection.LONG
        else SubingStrategyActionKind.OPEN_SHORT
    )
    entry = action_fixture(kind=open_kind)
    exit_action = None
    if change is not None:
        close_kind = (
            SubingStrategyActionKind.CLOSE_LONG
            if direction is SubingDirection.LONG
            else SubingStrategyActionKind.CLOSE_SHORT
        )
        exit_action = replace(
            action_fixture(kind=close_kind, episode_id=entry.episode_id),
            reason_codes=reason_codes or ("EMA21_BREACH_LONG",),
        )
    return SubingStrategyEpisode(
        episode_id=entry.episode_id,
        direction=direction,
        entry_action=entry,
        exit_action=exit_action,
        state=(
            SubingStrategyEpisodeState.CLOSED
            if change is not None
            else SubingStrategyEpisodeState.OPEN
        ),
        holding_bar_count=holding,
        reference_change_percent=(Decimal(change) if change is not None else None),
        current_reference_change_percent=(Decimal("1.5") if change is None else None),
        latest_reference_price=(Decimal("101.5") if change is None else None),
        exit_reason_codes=(exit_action.reason_codes if exit_action is not None else ()),
        structure_exit_available=False,
    )


def test_summarizes_closed_reference_changes_without_counting_open_episode() -> None:
    episodes = (
        _episode("2", direction=SubingDirection.LONG, holding=4, reason_codes=("A",)),
        _episode("-1", direction=SubingDirection.LONG, holding=2, reason_codes=("B",)),
        _episode("0", direction=SubingDirection.SHORT, holding=3, reason_codes=("A", "B")),
        _episode(None, direction=SubingDirection.SHORT, holding=9),
    )

    result = summarize_subing_strategy_episodes(episodes)

    assert result.overall.completed == 3
    assert (result.overall.positive, result.overall.negative, result.overall.flat) == (1, 1, 1)
    assert result.overall.positive_rate_percent == Decimal("33.33333333333333333333333333")
    assert result.overall.mean_reference_change_percent == Decimal("0.3333333333333333333333333333")
    assert result.overall.median_reference_change_percent == Decimal("0")
    assert result.overall.best_reference_change_percent == Decimal("2")
    assert result.overall.worst_reference_change_percent == Decimal("-1")
    assert result.overall.mean_holding_15m_bars == Decimal("3")
    assert result.long.completed == 2
    assert result.short.completed == 1
    assert result.open_episodes == 1
    assert result.exit_reason_counts == (("A", 2), ("B", 2))


def test_zero_completed_has_null_aggregates() -> None:
    result = summarize_subing_strategy_episodes(
        (_episode(None, direction=SubingDirection.LONG, holding=1),)
    )

    assert result.overall.completed == 0
    assert result.overall.positive_rate_percent is None
    assert result.overall.mean_reference_change_percent is None
    assert result.overall.median_reference_change_percent is None
    assert result.overall.mean_holding_15m_bars is None


def test_performance_service_uses_fixed_actual_dominant_15m_full_window() -> None:
    observed: list[SubingStrategyHistoricalRequest] = []
    projection = type(
        "Projection",
        (),
        {
            "policy": type("Policy", (), {"formula_version": "subing_strategy_15m_v1"})(),
            "episodes": (),
            "segment_summaries": (),
            "context_unavailable": (),
            "resolved_cutoff": action_fixture().effective_bar_end,
            "cache_state": "hit",
        },
    )()

    class Historical:
        def history(self, request: SubingStrategyHistoricalRequest):
            observed.append(request)
            return projection

    service = SubingStrategyPerformanceService(
        Historical(),
        products=("jm",),
        window_resolver=lambda symbol: (date(2020, 1, 2), date(2026, 8, 26)),
    )

    result = service.performance("JM")

    assert observed == [
        SubingStrategyHistoricalRequest(
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            symbol="jm",
            frequency=BarFrequency.M15,
            since=date(2020, 1, 2),
            through=date(2026, 8, 26),
        )
    ]
    assert result.symbol == "jm"
    assert result.series_kind is SeriesKind.ACTUAL_DOMINANT
    assert result.frequency is BarFrequency.M15
    assert result.coverage_since == date(2020, 1, 2)
    assert result.coverage_through == date(2026, 8, 26)


def test_active_warm_is_sequential_resumable_and_reports_partial_failure() -> None:
    calls: list[str] = []

    class Service:
        products = ("a", "b", "c")

        def performance(self, symbol: str):
            calls.append(symbol)
            if symbol == "b":
                raise RuntimeError("private")
            return type("Result", (), {"cache_state": "hit" if symbol == "a" else "miss"})()

    from app.market_data.subing_strategy.performance import warm_active_performance_cache

    result = warm_active_performance_cache(Service())

    assert calls == ["a", "b", "c"]
    assert result.status == "degraded"
    assert result.completed_products == ("a", "c")
    assert result.failed_products == (("b", "SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE"),)
    assert result.authoritative_writes is False
    assert result.cache_writes is True
