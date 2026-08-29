"""Read-only multi-segment Historical Projection for SuBing Strategy V1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from app.core.env import PROJECT_ROOT

from ..actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
)
from ..aggregation import SessionWindow
from ..domain import (
    BarFrequency,
    CanonicalBar,
    ResolvedContractSegment,
    SeriesKind,
)
from ..market_data_service import MarketDataError
from ..subing_calibration import (
    SubingCalibration,
    SubingCalibrationError,
    is_accepted_subing_calibration,
)
from ..subing_lifecycle_policy import (
    SubingLifecyclePolicy,
    SubingLifecyclePolicyError,
)
from .contracts import (
    SubingStrategyAction,
    SubingStrategyDirection,
    SubingStrategyEpisode,
    SubingStrategyPositionState,
)
from .cache import (
    CachedSubingStrategySegmentProjection,
    NullSubingStrategyCache,
    SubingStrategyCacheError,
    SubingStrategyCacheIdentity,
    digest_canonical_bars,
    digest_direction_contexts,
    digest_subing_strategy_engine_identity,
    digest_session_windows,
    digest_subing_strategy_segment_source,
    strategy_policy_sha256,
)
from .direction_context import (
    SubingStrategyContextIdentityError,
    SubingStrategyDirectionContext,
)
from .policy import SubingStrategyPolicy

if TYPE_CHECKING:
    from .performance import SubingStrategyPerformanceProjection
from .replay import SubingStrategyReplayError, replay_subing_strategy_segment


class SubingStrategySourceUnavailableError(RuntimeError):
    code = "SUBING_STRATEGY_SOURCE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingStrategySegmentIdentityError(RuntimeError):
    code = "SUBING_STRATEGY_SEGMENT_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingStrategyActiveProductError(ValueError):
    code = "SUBING_STRATEGY_ACTIVE_PRODUCT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class _ResearchSegmentLoader(Protocol):
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries: ...

    def sessions(
        self,
        *,
        symbol: str,
        trading_days: Sequence[date],
    ) -> Mapping[date, tuple[SessionWindow, ...]]: ...


class _DirectionContextResolver(Protocol):
    def resolve(
        self,
        symbol: str,
        target_days: Sequence[date],
    ) -> Mapping[date, SubingStrategyDirectionContext]: ...


class _StrategyCache(Protocol):
    available: bool

    def read(
        self,
        identity: SubingStrategyCacheIdentity,
    ) -> CachedSubingStrategySegmentProjection | None: ...

    def write(
        self,
        identity: SubingStrategyCacheIdentity,
        projection: CachedSubingStrategySegmentProjection,
    ) -> None: ...


class _SnapshotQuery(Protocol):
    def current(self, symbol: str) -> SubingStrategyPerformanceProjection: ...


@dataclass(frozen=True, slots=True)
class SubingStrategyHistoricalRequest:
    series_kind: SeriesKind
    symbol: str
    frequency: BarFrequency
    since: date
    through: date

    def __post_init__(self) -> None:
        try:
            series_kind = SeriesKind(self.series_kind)
            frequency = BarFrequency(self.frequency)
        except (TypeError, ValueError):
            raise ValueError("INVALID_SUBING_STRATEGY_REQUEST") from None
        symbol = self.symbol
        if (
            not isinstance(symbol, str)
            or not symbol.strip()
            or not symbol.strip().isascii()
            or not symbol.strip().isalpha()
            or series_kind is not SeriesKind.ACTUAL_DOMINANT
            or frequency is not BarFrequency.M15
            or type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise ValueError("INVALID_SUBING_STRATEGY_REQUEST")
        object.__setattr__(self, "series_kind", series_kind)
        object.__setattr__(self, "symbol", symbol.strip().lower())
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class SubingStrategySegmentSummary:
    contract: str
    start_trading_day: date
    end_trading_day: date
    loaded_through: date
    bar_count_1m: int
    bar_count_5m: int
    bar_count_15m: int
    initial_position: SubingStrategyPositionState
    final_position: SubingStrategyPositionState
    terminal_bar_end: datetime | None
    pending_action: bool
    source_identity_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SubingStrategyHistoricalProjection:
    request: SubingStrategyHistoricalRequest
    policy: SubingStrategyPolicy
    resolved_cutoff: datetime
    segment_summaries: tuple[SubingStrategySegmentSummary, ...]
    actions: tuple[SubingStrategyAction, ...]
    episodes: tuple[SubingStrategyEpisode, ...]
    context_unavailable: tuple[SubingStrategyDirectionContext, ...]
    cache_state: Literal["hit", "miss", "mixed", "unavailable"]
    engine_identity_sha256: str | None


class SubingStrategyHistoricalProjectionService:
    def __init__(
        self,
        segment_loader: _ResearchSegmentLoader,
        *,
        products: tuple[str, ...],
        direction_context_resolver: _DirectionContextResolver,
        calibration: SubingCalibration,
        lifecycle_policy: SubingLifecyclePolicy,
        strategy_policy: SubingStrategyPolicy,
        cache: _StrategyCache | None = None,
        strategy_policy_path: Path | None = None,
        snapshot_query: _SnapshotQuery | None = None,
    ) -> None:
        normalized = tuple(product.strip().lower() for product in products)
        if (
            not normalized
            or len(set(normalized)) != len(normalized)
            or any(
                not product or not product.isascii() or not product.isalpha()
                for product in normalized
            )
        ):
            raise SubingStrategyActiveProductError()
        if not is_accepted_subing_calibration(calibration):
            raise SubingCalibrationError()
        if not isinstance(lifecycle_policy, SubingLifecyclePolicy):
            raise SubingLifecyclePolicyError()
        if not isinstance(strategy_policy, SubingStrategyPolicy):
            raise ValueError("SUBING_STRATEGY_POLICY_INVALID")
        self._segment_loader = segment_loader
        self._products = normalized
        self._direction_context_resolver = direction_context_resolver
        self._calibration = calibration
        self._lifecycle_policy = lifecycle_policy
        self._strategy_policy = strategy_policy
        self._cache = cache or NullSubingStrategyCache()
        self._snapshot_query = snapshot_query
        self._strategy_policy_sha256: str | None
        try:
            self._strategy_policy_sha256 = strategy_policy_sha256(
                strategy_policy_path
                or PROJECT_ROOT / "data/research_policies/subing_strategy_v1.json"
            )
        except SubingStrategyCacheError:
            self._strategy_policy_sha256 = None
        calibration_id = self._calibration.calibration_id
        if self._strategy_policy_sha256 is None or calibration_id is None:
            self._engine_identity_sha256 = None
        else:
            self._engine_identity_sha256 = digest_subing_strategy_engine_identity(
                strategy_policy_sha256=self._strategy_policy_sha256,
                strategy_id=self._strategy_policy.strategy_id,
                formula_version=self._strategy_policy.formula_version,
                calibration_id=calibration_id,
                lifecycle_policy_id=self._lifecycle_policy.policy_id,
                lifecycle_formula_version=self._lifecycle_policy.formula_version,
                daily_watch_projection_version="subing_daily_watch_v2",
                daily_watch_formula_version="subing_ema21_rank1_stitched_raw_v2",
                daily_watch_history_mode="rank1_stitched_raw",
            )

    def history(
        self,
        request: SubingStrategyHistoricalRequest,
        *,
        publish_cache: bool = False,
    ) -> SubingStrategyHistoricalProjection:
        if not isinstance(request, SubingStrategyHistoricalRequest):
            raise TypeError("request must be SubingStrategyHistoricalRequest")
        if type(publish_cache) is not bool:
            raise TypeError("publish_cache must be bool")
        if request.symbol not in self._products:
            raise SubingStrategyActiveProductError()
        if self._snapshot_query is not None:
            from app.market_data.subing_strategy.history_snapshot_slice import (
                try_slice_history_from_snapshot,
            )
            from app.market_data.subing_strategy.performance_snapshot import (
                SubingStrategyPerformanceSnapshotError,
            )

            try:
                snapshot = self._snapshot_query.current(request.symbol)
            except SubingStrategyPerformanceSnapshotError:
                snapshot = None
            if snapshot is not None:
                sliced = try_slice_history_from_snapshot(
                    request,
                    snapshot,
                    policy=self._strategy_policy,
                    engine_identity_sha256=self._engine_identity_sha256,
                )
                if sliced is not None:
                    return sliced
        try:
            loaded = self._segment_loader.load(
                symbol=request.symbol,
                frequencies=(BarFrequency.M1, BarFrequency.M5, BarFrequency.M15),
                since=request.since,
                through=request.through,
            )
        except ActualDominantResearchSegmentIdentityError:
            raise SubingStrategySegmentIdentityError() from None
        except MarketDataError:
            raise SubingStrategySourceUnavailableError() from None
        results = loaded.results
        if (
            results.get(BarFrequency.M1) is None
            or results.get(BarFrequency.M5) is None
            or results.get(BarFrequency.M15) is None
            or not loaded.segments
        ):
            raise SubingStrategySegmentIdentityError()
        grouped_1m = _partition_segment_bars(
            results[BarFrequency.M1].bars,
            segments=loaded.segments,
            through=request.through,
        )
        grouped_5m = _partition_segment_bars(
            results[BarFrequency.M5].bars,
            segments=loaded.segments,
            through=request.through,
        )
        grouped_15m = _partition_segment_bars(
            results[BarFrequency.M15].bars,
            segments=loaded.segments,
            through=request.through,
        )
        all_target_days = tuple(
            dict.fromkeys(bar.trading_day for bar in results[BarFrequency.M15].bars)
        )
        try:
            sessions_by_day = self._segment_loader.sessions(
                symbol=request.symbol,
                trading_days=all_target_days,
            )
        except ActualDominantResearchSegmentIdentityError:
            raise SubingStrategySegmentIdentityError() from None
        except MarketDataError:
            raise SubingStrategySourceUnavailableError() from None
        if set(sessions_by_day) != set(all_target_days) or any(
            not windows
            or any(not isinstance(window, SessionWindow) for window in windows)
            for windows in sessions_by_day.values()
        ):
            raise SubingStrategySegmentIdentityError()

        all_actions: list[SubingStrategyAction] = []
        all_episodes: list[SubingStrategyEpisode] = []
        unavailable_contexts: dict[date, SubingStrategyDirectionContext] = {}
        summaries: list[SubingStrategySegmentSummary] = []
        resolved_cutoffs: list[datetime] = []
        cache_states: list[Literal["hit", "miss", "unavailable"]] = []
        for segment, bars_1m, bars_5m, bars_15m in zip(
            loaded.segments,
            grouped_1m,
            grouped_5m,
            grouped_15m,
            strict=True,
        ):
            if not bars_1m and not bars_5m and not bars_15m:
                continue
            if not bars_1m or not bars_5m or not bars_15m:
                raise SubingStrategySegmentIdentityError()
            target_days = tuple(dict.fromkeys(bar.trading_day for bar in bars_15m))
            sessions = tuple(
                sorted(
                    (window for day in target_days for window in sessions_by_day[day]),
                    key=lambda window: window.start,
                )
            )
            contexts = self._direction_context_resolver.resolve(
                request.symbol,
                target_days,
            )
            if set(contexts) != set(target_days):
                raise SubingStrategyContextIdentityError()
            if any(
                context.symbol != request.symbol or context.target_trading_day != day
                for day, context in contexts.items()
            ):
                raise SubingStrategyContextIdentityError()
            unavailable_contexts.update(
                {
                    day: context
                    for day, context in contexts.items()
                    if context.direction is SubingStrategyDirection.UNAVAILABLE
                }
            )
            terminal_bar_end = (
                bars_15m[-1].bar_end
                if request.through >= segment.end_trading_day
                and bars_15m[-1].trading_day == segment.end_trading_day
                else None
            )
            cache_identity, source_identity_sha256 = self._cache_identity_and_source_digest(
                request=request,
                segment=segment,
                bars_1m=bars_1m,
                bars_5m=bars_5m,
                bars_15m=bars_15m,
                sessions=sessions,
                contexts=contexts,
            )
            cached: CachedSubingStrategySegmentProjection | None = None
            cache_state: Literal["hit", "miss", "unavailable"] = "unavailable"
            if self._cache.available and cache_identity is not None:
                try:
                    cached = self._cache.read(cache_identity)
                    cache_state = "hit" if cached is not None else "miss"
                except SubingStrategyCacheError:
                    cache_state = "unavailable"
            if cached is None:
                try:
                    segment_result = replay_subing_strategy_segment(
                        symbol=request.symbol,
                        segment=segment,
                        bars_1m=bars_1m,
                        bars_5m=bars_5m,
                        bars_15m=bars_15m,
                        sessions=sessions,
                        direction_contexts=contexts,
                        calibration=self._calibration,
                        lifecycle_policy=self._lifecycle_policy,
                        strategy_policy=self._strategy_policy,
                        terminal_bar_end=terminal_bar_end,
                    )
                except SubingStrategyReplayError:
                    raise SubingStrategyContextIdentityError() from None
                cached = CachedSubingStrategySegmentProjection(
                    actions=segment_result.actions,
                    episodes=segment_result.episodes,
                    final_position=segment_result.final_position,
                    pending_action=segment_result.pending_action is not None,
                )
                if (
                    publish_cache
                    and cache_state in {"miss", "unavailable"}
                    and cache_identity is not None
                ):
                    try:
                        self._cache.write(cache_identity, cached)
                        cache_state = "miss"
                    except SubingStrategyCacheError:
                        cache_state = "unavailable"
            all_actions.extend(cached.actions)
            all_episodes.extend(cached.episodes)
            resolved_cutoffs.append(bars_15m[-1].bar_end)
            cache_states.append(cache_state)
            summaries.append(
                SubingStrategySegmentSummary(
                    contract=segment.contract,
                    start_trading_day=segment.start_trading_day,
                    end_trading_day=segment.end_trading_day,
                    loaded_through=bars_15m[-1].trading_day,
                    bar_count_1m=len(bars_1m),
                    bar_count_5m=len(bars_5m),
                    bar_count_15m=len(bars_15m),
                    initial_position=SubingStrategyPositionState.FLAT,
                    final_position=cached.final_position,
                    terminal_bar_end=terminal_bar_end,
                    pending_action=cached.pending_action,
                    source_identity_sha256=source_identity_sha256,
                )
            )
        if not resolved_cutoffs:
            raise SubingStrategySourceUnavailableError()
        actions = tuple(
            sorted(
                (
                    action
                    for action in all_actions
                    if request.since <= action.trading_day <= request.through
                ),
                key=lambda action: (action.effective_bar_end, action.action_id),
            )
        )
        episodes = tuple(
            sorted(
                (
                    episode
                    for episode in all_episodes
                    if _episode_intersects(episode, request=request)
                ),
                key=lambda episode: (
                    episode.entry_action.effective_bar_end,
                    episode.episode_id,
                ),
            )
        )
        return SubingStrategyHistoricalProjection(
            request=request,
            policy=self._strategy_policy,
            resolved_cutoff=max(resolved_cutoffs),
            segment_summaries=tuple(summaries),
            actions=actions,
            episodes=episodes,
            context_unavailable=tuple(
                context
                for day, context in sorted(unavailable_contexts.items())
                if request.since <= day <= request.through
            ),
            cache_state=_combine_cache_states(cache_states),
            engine_identity_sha256=self._engine_identity_sha256,
        )

    def _cache_identity_and_source_digest(
        self,
        *,
        request: SubingStrategyHistoricalRequest,
        segment: ResolvedContractSegment,
        bars_1m: tuple[CanonicalBar, ...],
        bars_5m: tuple[CanonicalBar, ...],
        bars_15m: tuple[CanonicalBar, ...],
        sessions: tuple[SessionWindow, ...],
        contexts: Mapping[date, SubingStrategyDirectionContext],
    ) -> tuple[SubingStrategyCacheIdentity | None, str]:
        daily_ends = tuple(
            context.daily_bar_end
            for context in contexts.values()
            if context.daily_bar_end is not None
        )
        hourly_ends = tuple(
            context.hourly_bar_end
            for context in contexts.values()
            if context.hourly_bar_end is not None
        )
        calibration_id = self._calibration.calibration_id
        bars_1m_digest = digest_canonical_bars(
            bars_1m,
            contract=segment.contract,
            segment_start=segment.start_trading_day,
        )
        bars_5m_digest = digest_canonical_bars(
            bars_5m,
            contract=segment.contract,
            segment_start=segment.start_trading_day,
        )
        bars_15m_digest = digest_canonical_bars(
            bars_15m,
            contract=segment.contract,
            segment_start=segment.start_trading_day,
        )
        session_windows_digest = digest_session_windows(sessions)
        direction_context_digest = digest_direction_contexts(contexts)
        source_identity_sha256 = digest_subing_strategy_segment_source(
            symbol=request.symbol,
            contract=segment.contract,
            segment_start=segment.start_trading_day,
            segment_end=segment.end_trading_day,
            through=request.through,
            bars_1m_digest=bars_1m_digest,
            bars_5m_digest=bars_5m_digest,
            bars_15m_digest=bars_15m_digest,
            session_windows_digest=session_windows_digest,
            direction_context_digest=direction_context_digest,
        )
        if (
            self._strategy_policy_sha256 is None
            or calibration_id is None
            or not daily_ends
            or not hourly_ends
        ):
            return None, source_identity_sha256
        return SubingStrategyCacheIdentity(
            strategy_policy_sha256=self._strategy_policy_sha256,
            strategy_id=self._strategy_policy.strategy_id,
            formula_version=self._strategy_policy.formula_version,
            calibration_id=calibration_id,
            lifecycle_policy_id=self._lifecycle_policy.policy_id,
            lifecycle_formula_version=self._lifecycle_policy.formula_version,
            daily_watch_projection_version="subing_daily_watch_v2",
            daily_watch_formula_version="subing_ema21_rank1_stitched_raw_v2",
            daily_watch_history_mode="rank1_stitched_raw",
            symbol=request.symbol,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
            segment_end_trading_day=segment.end_trading_day,
            cutoff_1m=bars_1m[-1].bar_end,
            cutoff_5m=bars_5m[-1].bar_end,
            cutoff_15m=bars_15m[-1].bar_end,
            cutoff_d1=max(daily_ends),
            cutoff_60m=max(hourly_ends),
            bars_1m_digest=bars_1m_digest,
            bars_5m_digest=bars_5m_digest,
            bars_15m_digest=bars_15m_digest,
            session_windows_digest=session_windows_digest,
            direction_context_digest=direction_context_digest,
            through=request.through,
        ), source_identity_sha256


def _partition_segment_bars(
    bars: Sequence[CanonicalBar],
    *,
    segments: Sequence[ResolvedContractSegment],
    through: date,
) -> tuple[tuple[CanonicalBar, ...], ...]:
    grouped: list[list[CanonicalBar]] = [[] for _ in segments]
    previous_end: datetime | None = None
    for bar in bars:
        if previous_end is not None and bar.bar_end <= previous_end:
            raise SubingStrategySegmentIdentityError()
        previous_end = bar.bar_end
        if bar.trading_day > through:
            continue
        matches = tuple(
            index
            for index, segment in enumerate(segments)
            if segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
        )
        if len(matches) != 1:
            raise SubingStrategySegmentIdentityError()
        grouped[matches[0]].append(bar)
    return tuple(tuple(segment_bars) for segment_bars in grouped)


def _combine_cache_states(
    states: Sequence[Literal["hit", "miss", "unavailable"]],
) -> Literal["hit", "miss", "mixed", "unavailable"]:
    values = tuple(states)
    if not values or "unavailable" in values:
        return "unavailable"
    if all(value == "hit" for value in values):
        return "hit"
    if all(value == "miss" for value in values):
        return "miss"
    return "mixed"


def _episode_intersects(
    episode: SubingStrategyEpisode,
    *,
    request: SubingStrategyHistoricalRequest,
) -> bool:
    entry_day = episode.entry_action.trading_day
    exit_day = (
        episode.exit_action.trading_day if episode.exit_action is not None else None
    )
    return entry_day <= request.through and (
        exit_day is None or exit_day >= request.since
    )
