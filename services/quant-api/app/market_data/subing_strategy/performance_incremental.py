"""Segment-tail incremental refresh for SuBing performance snapshots."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from typing import Protocol

from ..domain import BarFrequency, SeriesKind
from .contracts import SUBING_STRATEGY_ID, SubingStrategyEpisode
from .performance import (
    SubingStrategyPerformanceProjection,
    summarize_subing_strategy_episodes,
)
from .performance_adoption import SubingStrategyPerformanceFullRebuildRequired
from .performance_lineage import (
    FULL_REBUILD_REQUIRED,
    UNCHANGED,
    SubingStrategyPerformanceLineage,
    SubingStrategyPerformanceSemanticIdentity,
    decide_subing_strategy_performance_tail,
)
from .performance_snapshot import (
    SubingStrategyPerformancePrefixCounts,
    SubingStrategyPerformanceSegmentFact,
    SubingStrategyPerformanceSnapshot,
    SubingStrategyPerformanceSnapshotError,
    subing_strategy_performance_snapshot_from_projection,
)
from .performance_snapshot_store import SubingStrategyPerformanceSnapshotStore
from .service import SubingStrategyHistoricalRequest


_FIXED_FORMULA_VERSION = "subing_strategy_15m_v1"


class _HistoricalTail(Protocol):
    def history(
        self,
        request: SubingStrategyHistoricalRequest,
        *,
        publish_cache: bool = False,
    ) -> object: ...


class _LineageResolver(Protocol):
    def resolve(
        self,
        symbol: str,
        *,
        through: date | None = None,
    ) -> SubingStrategyPerformanceLineage: ...


class _Adopter(Protocol):
    def adopt(
        self,
        *,
        symbol: str,
        through: date,
    ) -> SubingStrategyPerformanceSnapshot: ...


class SubingStrategyPerformanceIncrementalRefresher:
    def __init__(
        self,
        *,
        lineage: _LineageResolver,
        historical: _HistoricalTail,
        store: SubingStrategyPerformanceSnapshotStore,
        identity: SubingStrategyPerformanceSemanticIdentity,
        now: Callable[[], datetime],
        adopter: _Adopter | None = None,
    ) -> None:
        self._lineage = lineage
        self._historical = historical
        self._store = store
        self._identity = identity
        self._now = now
        self._adopter = adopter

    def refresh(
        self,
        *,
        symbol: str,
        through: date,
    ) -> SubingStrategyPerformanceProjection:
        current_lineage = self._lineage.resolve(symbol, through=through)
        if current_lineage.coverage_through != through:
            raise SubingStrategyPerformanceFullRebuildRequired()
        snapshot = self._current_or_adopt(symbol=symbol, through=through)
        previous_lineage = self._lineage.resolve(
            symbol,
            through=snapshot.coverage_through,
        )
        if previous_lineage.source_manifest_sha256 != snapshot.source_manifest_sha256:
            raise SubingStrategyPerformanceFullRebuildRequired()
        if (
            snapshot.projection.strategy_id != self._identity.strategy_id
            or snapshot.projection.formula_version != self._identity.formula_version
        ):
            raise SubingStrategyPerformanceFullRebuildRequired()
        decision = decide_subing_strategy_performance_tail(
            previous=previous_lineage,
            current=current_lineage,
            previous_identity=self._identity,
            current_identity=self._identity,
        )
        if decision.kind == FULL_REBUILD_REQUIRED.kind:
            raise SubingStrategyPerformanceFullRebuildRequired()
        if decision.kind == UNCHANGED.kind:
            return snapshot.projection
        if decision.index is None:
            raise SubingStrategyPerformanceFullRebuildRequired()
        return self._replay_from(
            snapshot=snapshot,
            current_lineage=current_lineage,
            index=decision.index,
        )

    def _current_or_adopt(
        self,
        *,
        symbol: str,
        through: date,
    ) -> SubingStrategyPerformanceSnapshot:
        try:
            return self._store.read_current(
                symbol=symbol,
                expected_through=through,
                allow_older=True,
            )
        except SubingStrategyPerformanceSnapshotError:
            if self._adopter is None:
                raise SubingStrategyPerformanceFullRebuildRequired() from None
            return self._adopter.adopt(symbol=symbol, through=through)

    def _replay_from(
        self,
        *,
        snapshot: SubingStrategyPerformanceSnapshot,
        current_lineage: SubingStrategyPerformanceLineage,
        index: int,
    ) -> SubingStrategyPerformanceProjection:
        seam = current_lineage.ordered_segments[index]
        tail = self._historical.history(
            SubingStrategyHistoricalRequest(
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                symbol=current_lineage.symbol,
                frequency=BarFrequency.M15,
                since=seam.effective_start,
                through=current_lineage.coverage_through,
            ),
            publish_cache=True,
        )
        merged = _merge_snapshot(
            snapshot=snapshot,
            current_lineage=current_lineage,
            tail=tail,
            seam_index=index,
            generated_at=self._now(),
        )
        self._store.publish_current(merged)
        return merged.projection


def _merge_snapshot(
    *,
    snapshot: SubingStrategyPerformanceSnapshot,
    current_lineage: SubingStrategyPerformanceLineage,
    tail: object,
    seam_index: int,
    generated_at: datetime,
) -> SubingStrategyPerformanceSnapshot:
    summaries = tuple(getattr(tail, "segment_summaries", ()))
    tail_segments = current_lineage.ordered_segments[seam_index:]
    if len(summaries) != len(tail_segments):
        raise SubingStrategyPerformanceFullRebuildRequired()
    facts: list[SubingStrategyPerformanceSegmentFact] = []
    for summary, segment in zip(summaries, tail_segments, strict=True):
        if (
            summary.contract != segment.contract
            or summary.start_trading_day != segment.effective_start
            or summary.source_identity_sha256 != segment.source_identity
        ):
            raise SubingStrategyPerformanceFullRebuildRequired()
        facts.append(
            SubingStrategyPerformanceSegmentFact(
                contract=summary.contract,
                effective_start=summary.start_trading_day,
                effective_end=summary.end_trading_day,
                loaded_through=summary.loaded_through,
                bar_count_1m=summary.bar_count_1m,
                bar_count_5m=summary.bar_count_5m,
                bar_count_15m=summary.bar_count_15m,
                context_unavailable_count=0,
                source_identity=segment.source_identity,
            )
        )
    if not facts or facts[-1].loaded_through != current_lineage.coverage_through:
        raise SubingStrategyPerformanceFullRebuildRequired()
    prefix_episodes = _prefix_episodes(
        snapshot.projection.episodes,
        seam_start=tail_segments[0].effective_start,
    )
    tail_episodes = tuple(getattr(tail, "episodes", ()))
    _validate_tail_episodes(tail_episodes, tail_segments)
    merged_episodes = prefix_episodes + tail_episodes
    tail_15m = sum(fact.bar_count_15m for fact in facts)
    tail_context = len(getattr(tail, "context_unavailable", ()))
    facts[-1] = SubingStrategyPerformanceSegmentFact(
        contract=facts[-1].contract,
        effective_start=facts[-1].effective_start,
        effective_end=facts[-1].effective_end,
        loaded_through=facts[-1].loaded_through,
        bar_count_1m=facts[-1].bar_count_1m,
        bar_count_5m=facts[-1].bar_count_5m,
        bar_count_15m=facts[-1].bar_count_15m,
        context_unavailable_count=tail_context,
        source_identity=facts[-1].source_identity,
    )
    prefix_counts = snapshot.immutable_prefix_counts
    if seam_index > snapshot.immutable_prefix_segment_count:
        closed = facts[0]
        prefix_counts = SubingStrategyPerformancePrefixCounts(
            bar_count_1m=prefix_counts.bar_count_1m + closed.bar_count_1m,
            bar_count_5m=prefix_counts.bar_count_5m + closed.bar_count_5m,
            bar_count_15m=prefix_counts.bar_count_15m + closed.bar_count_15m,
            context_unavailable_count=(
                prefix_counts.context_unavailable_count
                + closed.context_unavailable_count
            ),
        )
        facts = facts[1:]
        seam_index = snapshot.immutable_prefix_segment_count + 1
    projection = SubingStrategyPerformanceProjection(
        strategy_id=SUBING_STRATEGY_ID,
        formula_version=_FIXED_FORMULA_VERSION,
        symbol=current_lineage.symbol,
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        frequency=BarFrequency.M15,
        coverage_since=current_lineage.coverage_since,
        coverage_through=current_lineage.coverage_through,
        resolved_cutoff=getattr(tail, "resolved_cutoff"),
        segment_count=len(current_lineage.ordered_segments),
        bar_count_15m=prefix_counts.bar_count_15m + tail_15m,
        context_unavailable_count=(
            prefix_counts.context_unavailable_count + tail_context
        ),
        cache_state="refreshed",
        summary=summarize_subing_strategy_episodes(merged_episodes),
        episodes=merged_episodes,
    )
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise SubingStrategyPerformanceFullRebuildRequired()
    return subing_strategy_performance_snapshot_from_projection(
        projection,
        immutable_prefix_segment_count=len(current_lineage.ordered_segments) - len(facts),
        immutable_prefix_counts=prefix_counts,
        segment_facts=tuple(facts),
        source_manifest_sha256=current_lineage.source_manifest_sha256,
        generated_at=generated_at.astimezone(UTC),
    )


def _prefix_episodes(
    episodes: Sequence[SubingStrategyEpisode],
    *,
    seam_start: date,
) -> tuple[SubingStrategyEpisode, ...]:
    prefix: list[SubingStrategyEpisode] = []
    for episode in episodes:
        entry_day = episode.entry_action.trading_day
        if entry_day >= seam_start:
            continue
        prefix.append(episode)
    return tuple(prefix)


def _validate_tail_episodes(
    episodes: Sequence[SubingStrategyEpisode],
    segments: Sequence[object],
) -> None:
    contracts = {segment.contract for segment in segments}
    seen: set[str] = set()
    previous_end = None
    for episode in episodes:
        episode_id = episode.episode_id
        if episode_id in seen:
            raise SubingStrategyPerformanceFullRebuildRequired()
        seen.add(episode_id)
        contract = episode.entry_action.contract
        if contract not in contracts:
            raise SubingStrategyPerformanceFullRebuildRequired()
        end = episode.entry_action.effective_bar_end
        if previous_end is not None and end < previous_end:
            raise SubingStrategyPerformanceFullRebuildRequired()
        previous_end = end
