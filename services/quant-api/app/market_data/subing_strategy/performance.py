"""Full-history, read-only SuBing Strategy V1 reference-change performance."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from statistics import median
from typing import Literal, Protocol, cast

from ..domain import BarFrequency, SeriesKind
from ..subing_research import SubingDirection
from .contracts import SUBING_STRATEGY_ID, SubingStrategyEpisode
from .service import (
    SubingStrategyHistoricalProjection,
    SubingStrategyHistoricalRequest,
)


class SubingStrategyPerformanceError(RuntimeError):
    code = "SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE"

    def __init__(self, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(self.code)


class _HistoricalService(Protocol):
    def history(
        self, request: SubingStrategyHistoricalRequest
    ) -> SubingStrategyHistoricalProjection: ...


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceStats:
    completed: int
    positive: int
    negative: int
    flat: int
    positive_rate_percent: Decimal | None
    mean_reference_change_percent: Decimal | None
    median_reference_change_percent: Decimal | None
    best_reference_change_percent: Decimal | None
    worst_reference_change_percent: Decimal | None
    mean_holding_15m_bars: Decimal | None


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceSummary:
    overall: SubingStrategyPerformanceStats
    long: SubingStrategyPerformanceStats
    short: SubingStrategyPerformanceStats
    open_episodes: int
    exit_reason_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceProjection:
    strategy_id: str
    formula_version: Literal["subing_strategy_15m_v1"]
    symbol: str
    series_kind: SeriesKind
    frequency: BarFrequency
    coverage_since: date
    coverage_through: date
    resolved_cutoff: datetime
    segment_count: int
    bar_count_15m: int
    context_unavailable_count: int
    cache_state: Literal["hit", "miss", "mixed", "unavailable"]
    summary: SubingStrategyPerformanceSummary
    episodes: tuple[SubingStrategyEpisode, ...]


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceWarmResult:
    status: Literal["passed", "degraded"]
    completed_products: tuple[str, ...]
    failed_products: tuple[tuple[str, str], ...]
    authoritative_writes: bool = False
    cache_writes: bool = True


def _stats(episodes: Sequence[SubingStrategyEpisode]) -> SubingStrategyPerformanceStats:
    closed = tuple(
        episode
        for episode in episodes
        if episode.exit_action is not None
        and episode.reference_change_percent is not None
    )
    values: tuple[Decimal, ...] = tuple(
        cast(Decimal, episode.reference_change_percent) for episode in closed
    )
    holdings = tuple(Decimal(episode.holding_bar_count) for episode in closed)
    completed = len(values)
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    flat = sum(value == 0 for value in values)
    if not values:
        return SubingStrategyPerformanceStats(
            completed=0,
            positive=0,
            negative=0,
            flat=0,
            positive_rate_percent=None,
            mean_reference_change_percent=None,
            median_reference_change_percent=None,
            best_reference_change_percent=None,
            worst_reference_change_percent=None,
            mean_holding_15m_bars=None,
        )
    denominator = Decimal(completed)
    return SubingStrategyPerformanceStats(
        completed=completed,
        positive=positive,
        negative=negative,
        flat=flat,
        positive_rate_percent=Decimal(positive) / denominator * Decimal("100"),
        mean_reference_change_percent=sum(values, Decimal()) / denominator,
        median_reference_change_percent=median(values),
        best_reference_change_percent=max(values),
        worst_reference_change_percent=min(values),
        mean_holding_15m_bars=sum(holdings, Decimal()) / denominator,
    )


def summarize_subing_strategy_episodes(
    episodes: Sequence[SubingStrategyEpisode],
) -> SubingStrategyPerformanceSummary:
    values = tuple(episodes)
    reasons = Counter(
        reason
        for episode in values
        if episode.exit_action is not None
        for reason in episode.exit_reason_codes
    )
    return SubingStrategyPerformanceSummary(
        overall=_stats(values),
        long=_stats(tuple(ep for ep in values if ep.direction is SubingDirection.LONG)),
        short=_stats(tuple(ep for ep in values if ep.direction is SubingDirection.SHORT)),
        open_episodes=sum(ep.exit_action is None for ep in values),
        exit_reason_counts=tuple(sorted(reasons.items())),
    )


class SubingStrategyPerformanceService:
    def __init__(
        self,
        historical: _HistoricalService,
        *,
        products: tuple[str, ...],
        window_resolver: Callable[[str], tuple[date, date]],
    ) -> None:
        normalized = tuple(product.strip().lower() for product in products)
        if not normalized or len(normalized) != len(set(normalized)):
            raise SubingStrategyPerformanceError("SUBING_STRATEGY_ACTIVE_PRODUCT_INVALID")
        self._historical = historical
        self._products = normalized
        self._window_resolver = window_resolver

    @property
    def products(self) -> tuple[str, ...]:
        return self._products

    def performance(self, symbol: str) -> SubingStrategyPerformanceProjection:
        normalized = symbol.strip().lower()
        if normalized not in self._products:
            raise SubingStrategyPerformanceError("SUBING_STRATEGY_ACTIVE_PRODUCT_INVALID")
        try:
            since, through = self._window_resolver(normalized)
        except SubingStrategyPerformanceError:
            raise
        except Exception:
            raise SubingStrategyPerformanceError() from None
        if type(since) is not date or type(through) is not date or since > through:
            raise SubingStrategyPerformanceError()
        projection = self._historical.history(
            SubingStrategyHistoricalRequest(
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                symbol=normalized,
                frequency=BarFrequency.M15,
                since=since,
                through=through,
            )
        )
        episodes = tuple(
            sorted(
                projection.episodes,
                key=lambda episode: (
                    episode.entry_action.effective_bar_end,
                    episode.episode_id,
                ),
                reverse=True,
            )
        )
        return SubingStrategyPerformanceProjection(
            strategy_id=SUBING_STRATEGY_ID,
            formula_version="subing_strategy_15m_v1",
            symbol=normalized,
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            frequency=BarFrequency.M15,
            coverage_since=since,
            coverage_through=through,
            resolved_cutoff=projection.resolved_cutoff,
            segment_count=len(projection.segment_summaries),
            bar_count_15m=sum(s.bar_count_15m for s in projection.segment_summaries),
            context_unavailable_count=len(projection.context_unavailable),
            cache_state=projection.cache_state,
            summary=summarize_subing_strategy_episodes(episodes),
            episodes=episodes,
        )


def warm_active_performance_cache(
    service: SubingStrategyPerformanceService,
    *,
    expected_products: tuple[str, ...] | None = None,
) -> SubingStrategyPerformanceWarmResult:
    if expected_products is not None and service.products != expected_products:
        return SubingStrategyPerformanceWarmResult(
            status="degraded",
            completed_products=(),
            failed_products=(
                ("scope", "SUBING_STRATEGY_ACTIVE_OPERATIONAL_SCOPE_MISMATCH"),
            ),
        )
    completed: list[str] = []
    failed: list[tuple[str, str]] = []
    for symbol in service.products:
        try:
            service.performance(symbol)
        except Exception as exc:  # noqa: BLE001 - fixed public error boundary
            code = getattr(exc, "code", "SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE")
            if not isinstance(code, str) or not code.startswith("SUBING_STRATEGY_"):
                code = "SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE"
            failed.append((symbol, code))
        else:
            completed.append(symbol)
    return SubingStrategyPerformanceWarmResult(
        status="degraded" if failed else "passed",
        completed_products=tuple(completed),
        failed_products=tuple(failed),
    )
