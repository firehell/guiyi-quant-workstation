from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import json

import pytest

from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_strategy.contracts import (
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyEpisodeState,
)
from app.market_data.subing_strategy.cache import SubingStrategyPerformanceCache
from app.market_data.subing_strategy.performance import (
    SubingStrategyPerformanceBatchPlan,
    SubingStrategyPerformanceError,
    SubingStrategyPerformanceWindow,
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


def test_performance_service_uses_fixed_actual_dominant_15m_full_window(tmp_path) -> None:
    observed: list[tuple[SubingStrategyHistoricalRequest, bool]] = []
    projection = type(
        "Projection",
        (),
        {
            "engine_identity_sha256": "0" * 64,
            "policy": type("Policy", (), {"formula_version": "subing_strategy_15m_v1"})(),
            "episodes": (),
            "segment_summaries": (
                type(
                    "Segment",
                    (),
                    {
                        "bar_count_15m": 12,
                        "loaded_through": date(2026, 8, 26),
                        "source_identity_sha256": "1" * 64,
                    },
                )(),
            ),
            "context_unavailable": (),
            "resolved_cutoff": action_fixture().effective_bar_end,
            "cache_state": "miss",
        },
    )()

    class Historical:
        def history(
            self,
            request: SubingStrategyHistoricalRequest,
            *,
            publish_cache: bool = False,
        ):
            observed.append((request, publish_cache))
            return projection

    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    service = SubingStrategyPerformanceService(
        Historical(),
        products=("jm",),
        window_resolver=lambda symbol: (date(2020, 1, 2), date(2026, 8, 26)),
        performance_cache=SubingStrategyPerformanceCache(
            cache_root,
            root_validator=lambda: cache_root,
            now=lambda: datetime(2026, 8, 27, 8, tzinfo=UTC),
        ),
    )

    read_only = service.performance("JM")
    assert read_only.cache_state == "unavailable"
    assert read_only.cache_identity_sha256 is not None
    assert not tuple(cache_root.rglob("*.json"))

    result = service.performance("JM", publish_cache=True)
    cached = service.performance("JM")

    expected_request = SubingStrategyHistoricalRequest(
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        symbol="jm",
        frequency=BarFrequency.M15,
        since=date(2020, 1, 2),
        through=date(2026, 8, 26),
    )
    assert observed == [
        (expected_request, False),
        (expected_request, True),
        (expected_request, False),
    ]
    assert result.symbol == "jm"
    assert result.series_kind is SeriesKind.ACTUAL_DOMINANT
    assert result.frequency is BarFrequency.M15
    assert result.coverage_since == date(2020, 1, 2)
    assert result.coverage_through == date(2026, 8, 26)
    assert result.cache_state == "refreshed"
    assert result.cache_identity_sha256 is not None
    assert result.cache_generated_at == datetime(2026, 8, 27, 8, tzinfo=UTC)
    assert cached.cache_state == "hit"
    assert cached.cache_identity_sha256 == result.cache_identity_sha256

    cache_path = next(cache_root.rglob("*.json"))
    stale = json.loads(cache_path.read_text(encoding="utf-8"))
    stale["schema_version"] = 1
    cache_path.write_text(json.dumps(stale), encoding="utf-8")
    repaired = service.performance("JM", publish_cache=True)
    assert repaired.cache_state == "refreshed"
    assert service.performance("JM").cache_state == "hit"


def test_performance_rejects_projection_that_did_not_reach_requested_through() -> None:
    projection = type(
        "Projection",
        (),
        {
            "episodes": (),
            "segment_summaries": (
                type(
                    "Segment",
                    (),
                    {
                        "loaded_through": date(2026, 8, 25),
                        "bar_count_15m": 12,
                        "source_identity_sha256": "1" * 64,
                    },
                )(),
            ),
            "context_unavailable": (),
            "resolved_cutoff": action_fixture().effective_bar_end,
        },
    )()
    service = SubingStrategyPerformanceService(
        type(
            "Historical",
            (),
            {
                "history": lambda _self, _request, publish_cache=False: projection,
            },
        )(),
        products=("jm",),
        window_resolver=lambda _symbol: (date(2020, 1, 2), date(2026, 8, 26)),
    )

    with pytest.raises(SubingStrategyPerformanceError) as exc_info:
        service.performance("jm")

    assert exc_info.value.code == "SUBING_STRATEGY_SOURCE_UNAVAILABLE"


def test_active_warm_is_sequential_resumable_and_reports_partial_failure() -> None:
    calls: list[str] = []
    windows = (
        SubingStrategyPerformanceWindow("a", date(2020, 1, 2), date(2026, 8, 26)),
        SubingStrategyPerformanceWindow("b", date(2020, 1, 2), date(2026, 8, 26)),
        SubingStrategyPerformanceWindow("c", date(2020, 1, 2), date(2026, 8, 26)),
    )

    class Service:
        products = ("a", "b", "c")

        def plan(self, *, through=None):
            assert through is None
            return SubingStrategyPerformanceBatchPlan.create(
                created_at=datetime(2026, 8, 27, 7, 55, tzinfo=UTC),
                windows=windows,
            )

        def performance(self, symbol: str, *, window, publish_cache=False):
            assert publish_cache is True
            assert window == next(item for item in windows if item.symbol == symbol)
            calls.append(symbol)
            if symbol == "b":
                raise RuntimeError("private")
            return type(
                "Result",
                (),
                {
                    "cache_state": "hit" if symbol == "a" else "unavailable",
                    "cache_identity_sha256": "1" * 64 if symbol == "a" else None,
                },
            )()

    from app.market_data.subing_strategy.performance import warm_active_performance_cache

    result = warm_active_performance_cache(Service())

    assert calls == ["a", "b", "c"]
    assert result.status == "degraded"
    assert result.completed_products == ("a",)
    assert result.failed_products == (
        ("b", "SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE"),
        ("c", "SUBING_STRATEGY_CACHE_UNAVAILABLE"),
    )
    assert result.authoritative_writes is False
    assert result.cache_hit_count == 1
    assert result.cache_published_count == 0


def test_batch_plan_freezes_every_product_window_before_performance_runs() -> None:
    current_through = date(2026, 8, 26)
    resolver_calls: list[str] = []

    def resolve(symbol: str) -> tuple[date, date]:
        resolver_calls.append(symbol)
        return date(2020, 1, 2), current_through

    service = SubingStrategyPerformanceService(
        type("Historical", (), {})(),
        products=("a", "ag"),
        window_resolver=resolve,
        now=lambda: datetime(2026, 8, 27, 6, 59, tzinfo=UTC),
    )

    plan = service.plan()
    current_through = date(2026, 8, 27)

    assert resolver_calls == ["a", "ag"]
    assert tuple(window.through for window in plan.windows) == (
        date(2026, 8, 26),
        date(2026, 8, 26),
    )
    assert plan.created_at == datetime(2026, 8, 27, 6, 59, tzinfo=UTC)
    assert len(plan.batch_identity_sha256) == 64
