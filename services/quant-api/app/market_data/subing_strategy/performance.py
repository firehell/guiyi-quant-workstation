"""Full-history, read-only SuBing Strategy V1 reference-change performance."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from statistics import median
from typing import Literal, Protocol, cast

from ..domain import BarFrequency, SeriesKind
from ..subing_research import SubingDirection
from .contracts import SUBING_STRATEGY_ID, SubingStrategyEpisode
from .cache import (
    CachedSubingStrategyPerformanceSnapshot,
    NullSubingStrategyPerformanceCache,
    SubingStrategyCacheError,
    SubingStrategyPerformanceCacheIdentity,
    SubingStrategyPerformanceCacheReceipt,
    subing_strategy_episode_payload,
    subing_strategy_performance_cache_identity_sha256,
)
from .service import (
    SubingStrategyHistoricalProjection,
    SubingStrategyHistoricalRequest,
)


class SubingStrategyPerformanceError(RuntimeError):
    code = "SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE"

    def __init__(self, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceWindow:
    symbol: str
    since: date
    through: date

    def __post_init__(self) -> None:
        if (
            not self.symbol
            or not self.symbol.isascii()
            or not self.symbol.isalpha()
            or self.symbol != self.symbol.lower()
            or type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise SubingStrategyPerformanceError(
                "SUBING_STRATEGY_BATCH_WINDOW_UNAVAILABLE"
            )


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceBatchPlan:
    created_at: datetime
    windows: tuple[SubingStrategyPerformanceWindow, ...]
    batch_identity_sha256: str

    @classmethod
    def create(
        cls,
        *,
        created_at: datetime,
        windows: Sequence[SubingStrategyPerformanceWindow],
    ) -> SubingStrategyPerformanceBatchPlan:
        values = tuple(windows)
        if (
            created_at.tzinfo is None
            or created_at.utcoffset() is None
            or not values
            or len({window.symbol for window in values}) != len(values)
        ):
            raise SubingStrategyPerformanceError(
                "SUBING_STRATEGY_BATCH_WINDOW_UNAVAILABLE"
            )
        payload = {
            "created_at": created_at.astimezone(UTC).isoformat(),
            "windows": [
                {
                    "symbol": window.symbol,
                    "since": window.since.isoformat(),
                    "through": window.through.isoformat(),
                }
                for window in values
            ],
        }
        digest = sha256(json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        return cls(created_at.astimezone(UTC), values, digest)

    def window_for(self, symbol: str) -> SubingStrategyPerformanceWindow:
        normalized = symbol.strip().lower()
        matches = tuple(window for window in self.windows if window.symbol == normalized)
        if len(matches) != 1:
            raise SubingStrategyPerformanceError(
                "SUBING_STRATEGY_BATCH_WINDOW_UNAVAILABLE"
            )
        return matches[0]


class _HistoricalService(Protocol):
    def history(
        self,
        request: SubingStrategyHistoricalRequest,
        *,
        publish_cache: bool = False,
    ) -> SubingStrategyHistoricalProjection: ...


class _PerformanceCache(Protocol):
    available: bool

    def read(
        self,
        identity: SubingStrategyPerformanceCacheIdentity,
    ) -> CachedSubingStrategyPerformanceSnapshot | None: ...

    def publish(
        self,
        identity: SubingStrategyPerformanceCacheIdentity,
        payload: Mapping[str, object],
    ) -> SubingStrategyPerformanceCacheReceipt: ...


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
    cache_state: Literal["hit", "refreshed", "unavailable"]
    summary: SubingStrategyPerformanceSummary
    episodes: tuple[SubingStrategyEpisode, ...]
    cache_identity_sha256: str | None = None
    cache_generated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceWarmResult:
    status: Literal["passed", "degraded"]
    completed_products: tuple[str, ...]
    failed_products: tuple[tuple[str, str], ...]
    authoritative_writes: bool = False
    cache_hit_count: int = 0
    cache_published_count: int = 0
    batch_identity_sha256: str | None = None
    batch_created_at: datetime | None = None


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
        performance_cache: _PerformanceCache | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        normalized = tuple(product.strip().lower() for product in products)
        if not normalized or len(normalized) != len(set(normalized)):
            raise SubingStrategyPerformanceError("SUBING_STRATEGY_ACTIVE_PRODUCT_INVALID")
        self._historical = historical
        self._products = normalized
        self._window_resolver = window_resolver
        self._performance_cache = performance_cache or NullSubingStrategyPerformanceCache()
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def products(self) -> tuple[str, ...]:
        return self._products

    def plan(
        self,
        *,
        through: date | None = None,
    ) -> SubingStrategyPerformanceBatchPlan:
        windows: list[SubingStrategyPerformanceWindow] = []
        for symbol in self._products:
            since, resolved_through = self._window_resolver(symbol)
            windows.append(SubingStrategyPerformanceWindow(
                symbol=symbol,
                since=since,
                through=through if through is not None else resolved_through,
            ))
        return SubingStrategyPerformanceBatchPlan.create(
            created_at=self._now(),
            windows=windows,
        )

    def performance(
        self,
        symbol: str,
        *,
        window: SubingStrategyPerformanceWindow | None = None,
        publish_cache: bool = False,
    ) -> SubingStrategyPerformanceProjection:
        if type(publish_cache) is not bool:
            raise SubingStrategyPerformanceError()
        normalized = symbol.strip().lower()
        if normalized not in self._products:
            raise SubingStrategyPerformanceError("SUBING_STRATEGY_ACTIVE_PRODUCT_INVALID")
        try:
            if window is None:
                since, through = self._window_resolver(normalized)
            else:
                if window.symbol != normalized:
                    raise SubingStrategyPerformanceError(
                        "SUBING_STRATEGY_BATCH_WINDOW_UNAVAILABLE"
                    )
                since, through = window.since, window.through
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
            ),
            publish_cache=publish_cache,
        )
        loaded_through = tuple(
            summary.loaded_through for summary in projection.segment_summaries
        )
        if (
            not loaded_through
            or any(type(value) is not date for value in loaded_through)
            or max(loaded_through) != through
        ):
            raise SubingStrategyPerformanceError(
                "SUBING_STRATEGY_SOURCE_UNAVAILABLE"
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
        fresh = SubingStrategyPerformanceProjection(
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
            cache_state="unavailable",
            cache_identity_sha256=None,
            cache_generated_at=None,
            summary=summarize_subing_strategy_episodes(episodes),
            episodes=episodes,
        )
        source_identities = tuple(
            summary.source_identity_sha256
            for summary in projection.segment_summaries
            if summary.source_identity_sha256 is not None
        )
        if (
            not self._performance_cache.available
            or projection.engine_identity_sha256 is None
            or len(source_identities) != len(projection.segment_summaries)
            or not source_identities
        ):
            return fresh
        identity = SubingStrategyPerformanceCacheIdentity(
            strategy_id=fresh.strategy_id,
            formula_version=fresh.formula_version,
            engine_identity_sha256=projection.engine_identity_sha256,
            symbol=fresh.symbol,
            since=fresh.coverage_since,
            through=fresh.coverage_through,
            resolved_cutoff=fresh.resolved_cutoff,
            segment_identity_sha256s=source_identities,
        )
        identity_sha256 = subing_strategy_performance_cache_identity_sha256(identity)
        payload = _performance_snapshot_payload(fresh)
        try:
            cached = self._performance_cache.read(identity)
            if cached is not None and cached.payload == payload:
                return replace(
                    fresh,
                    cache_state="hit",
                    cache_identity_sha256=identity_sha256,
                    cache_generated_at=cached.generated_at,
                )
        except SubingStrategyCacheError:
            cached = None

        if not publish_cache:
            return replace(fresh, cache_identity_sha256=identity_sha256)

        try:
            receipt = self._performance_cache.publish(identity, payload)
            verified = self._performance_cache.read(identity)
            if (
                verified is None
                or verified.identity_sha256 != receipt.identity_sha256
                or verified.payload_sha256 != receipt.payload_sha256
                or verified.payload != payload
            ):
                raise SubingStrategyCacheError()
            return replace(
                fresh,
                cache_state="refreshed",
                cache_identity_sha256=identity_sha256,
                cache_generated_at=verified.generated_at,
            )
        except SubingStrategyCacheError:
            return replace(fresh, cache_identity_sha256=identity_sha256)


def warm_active_performance_cache(
    service: SubingStrategyPerformanceService,
    *,
    expected_products: tuple[str, ...] | None = None,
    through: date | None = None,
) -> SubingStrategyPerformanceWarmResult:
    if expected_products is not None and service.products != expected_products:
        return SubingStrategyPerformanceWarmResult(
            status="degraded",
            completed_products=(),
            failed_products=(
                ("scope", "SUBING_STRATEGY_ACTIVE_OPERATIONAL_SCOPE_MISMATCH"),
            ),
        )
    try:
        plan = service.plan(through=through)
    except Exception:
        return SubingStrategyPerformanceWarmResult(
            status="degraded",
            completed_products=(),
            failed_products=tuple(
                (symbol, "SUBING_STRATEGY_BATCH_WINDOW_UNAVAILABLE")
                for symbol in service.products
            ),
        )
    completed: list[str] = []
    failed: list[tuple[str, str]] = []
    cache_hit_count = 0
    cache_published_count = 0
    for window in plan.windows:
        symbol = window.symbol
        try:
            projection = service.performance(
                symbol,
                window=window,
                publish_cache=True,
            )
        except Exception as exc:  # noqa: BLE001 - fixed public error boundary
            code = getattr(exc, "code", "SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE")
            if not isinstance(code, str) or not code.startswith("SUBING_STRATEGY_"):
                code = "SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE"
            failed.append((symbol, code))
        else:
            if (
                projection.cache_identity_sha256 is None
                or projection.cache_state not in {"hit", "refreshed"}
            ):
                failed.append((symbol, "SUBING_STRATEGY_CACHE_UNAVAILABLE"))
                continue
            completed.append(symbol)
            if projection.cache_state == "hit":
                cache_hit_count += 1
            else:
                cache_published_count += 1
    return SubingStrategyPerformanceWarmResult(
        status="degraded" if failed else "passed",
        completed_products=tuple(completed),
        failed_products=tuple(failed),
        cache_hit_count=cache_hit_count,
        cache_published_count=cache_published_count,
        batch_identity_sha256=plan.batch_identity_sha256,
        batch_created_at=plan.created_at,
    )


def _performance_snapshot_payload(
    projection: SubingStrategyPerformanceProjection,
) -> dict[str, object]:
    return {
        "strategy_id": projection.strategy_id,
        "formula_version": projection.formula_version,
        "symbol": projection.symbol,
        "series_kind": projection.series_kind.value,
        "frequency": projection.frequency.value,
        "coverage_since": projection.coverage_since.isoformat(),
        "coverage_through": projection.coverage_through.isoformat(),
        "resolved_cutoff": projection.resolved_cutoff.isoformat(),
        "segment_count": projection.segment_count,
        "bar_count_15m": projection.bar_count_15m,
        "context_unavailable_count": projection.context_unavailable_count,
        "summary": {
            "overall": _stats_payload(projection.summary.overall),
            "long": _stats_payload(projection.summary.long),
            "short": _stats_payload(projection.summary.short),
            "open_episodes": projection.summary.open_episodes,
            "exit_reason_counts": [
                {"reason_code": code, "count": count}
                for code, count in projection.summary.exit_reason_counts
            ],
        },
        "episodes": [
            subing_strategy_episode_payload(episode) for episode in projection.episodes
        ],
    }


def _stats_payload(stats: SubingStrategyPerformanceStats) -> dict[str, object]:
    return {
        "completed": stats.completed,
        "positive": stats.positive,
        "negative": stats.negative,
        "flat": stats.flat,
        "positive_rate_percent": _decimal_text(stats.positive_rate_percent),
        "mean_reference_change_percent": _decimal_text(
            stats.mean_reference_change_percent
        ),
        "median_reference_change_percent": _decimal_text(
            stats.median_reference_change_percent
        ),
        "best_reference_change_percent": _decimal_text(
            stats.best_reference_change_percent
        ),
        "worst_reference_change_percent": _decimal_text(
            stats.worst_reference_change_percent
        ),
        "mean_holding_15m_bars": _decimal_text(stats.mean_holding_15m_bars),
    }


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
