"""One-time strict adoption of schema-v2 SuBing performance artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Protocol

from ..domain import BarFrequency, SeriesKind
from .cache import (
    SubingStrategyPerformanceCache,
    subing_strategy_performance_cache_identity_from_envelope,
)
from .contracts import SUBING_STRATEGY_ID
from .performance import _performance_snapshot_payload
from .performance_lineage import SubingStrategyPerformanceLineage
from .performance_snapshot import (
    SubingStrategyPerformancePrefixCounts,
    SubingStrategyPerformanceSegmentFact,
    SubingStrategyPerformanceSnapshot,
    subing_strategy_performance_snapshot_from_projection,
)
from .performance_snapshot_store import SubingStrategyPerformanceSnapshotStore
from .service import SubingStrategyHistoricalRequest


class SubingStrategyPerformanceFullRebuildRequired(RuntimeError):
    code = "SUBING_STRATEGY_PERFORMANCE_FULL_REBUILD_REQUIRED"

    def __init__(self) -> None:
        super().__init__(self.code)


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


class SubingStrategyPerformanceAdopter:
    def __init__(
        self,
        *,
        cache: SubingStrategyPerformanceCache,
        store: SubingStrategyPerformanceSnapshotStore,
        lineage: _LineageResolver,
        historical: _HistoricalTail,
        now: Callable[[], datetime],
    ) -> None:
        self._cache = cache
        self._store = store
        self._lineage = lineage
        self._historical = historical
        self._now = now

    def adopt(
        self,
        *,
        symbol: str,
        through: date,
    ) -> SubingStrategyPerformanceSnapshot:
        try:
            lineage = self._lineage.resolve(symbol, through=through)
            if lineage.symbol != symbol or lineage.coverage_through != through:
                raise SubingStrategyPerformanceFullRebuildRequired()
            directory = self._cache.directory_for(symbol=symbol, through=through)
            self._cache._preflight(directory / "candidate.json")
            candidate = _exactly_one_regular_json(directory)
            source_bytes = candidate.read_bytes()
            identity = subing_strategy_performance_cache_identity_from_envelope(
                source_bytes
            )
            if (
                identity.symbol != symbol
                or identity.through != through
                or identity.since != lineage.coverage_since
                or identity.strategy_id != SUBING_STRATEGY_ID
                or identity.formula_version != "subing_strategy_15m_v1"
                or identity.segment_identity_sha256s
                != tuple(segment.source_identity for segment in lineage.ordered_segments)
            ):
                raise SubingStrategyPerformanceFullRebuildRequired()
            cached = self._cache.read(identity)
            if cached is None:
                raise SubingStrategyPerformanceFullRebuildRequired()
            tail_segment = lineage.ordered_segments[-1]
            tail = self._historical.history(
                SubingStrategyHistoricalRequest(
                    series_kind=SeriesKind.ACTUAL_DOMINANT,
                    symbol=symbol,
                    frequency=BarFrequency.M15,
                    since=tail_segment.effective_start,
                    through=through,
                ),
                publish_cache=True,
            )
            snapshot = _snapshot_from_legacy(
                cached.payload,
                lineage=lineage,
                tail=tail,
                generated_at=self._now(),
            )
            published = self._store.publish_current(snapshot)
            if published.snapshot_sha256 != snapshot.snapshot_sha256:
                raise SubingStrategyPerformanceFullRebuildRequired()
            if candidate.read_bytes() != source_bytes:
                raise SubingStrategyPerformanceFullRebuildRequired()
            return snapshot
        except SubingStrategyPerformanceFullRebuildRequired:
            raise
        except Exception:
            raise SubingStrategyPerformanceFullRebuildRequired() from None


def _exactly_one_regular_json(directory) -> object:
    if not directory.is_dir() or directory.is_symlink():
        raise SubingStrategyPerformanceFullRebuildRequired()
    entries = tuple(directory.iterdir())
    if any(
        entry.name.endswith(".tmp") or entry.name.startswith(".")
        for entry in entries
    ):
        raise SubingStrategyPerformanceFullRebuildRequired()
    json_files = tuple(
        entry for entry in entries if entry.is_file() and entry.suffix == ".json"
    )
    if len(json_files) != 1 or json_files[0].is_symlink() or len(entries) != 1:
        raise SubingStrategyPerformanceFullRebuildRequired()
    return json_files[0]


def _snapshot_from_legacy(
    payload: Mapping[str, object],
    *,
    lineage: SubingStrategyPerformanceLineage,
    tail: object,
    generated_at: datetime,
) -> SubingStrategyPerformanceSnapshot:
    from .performance_snapshot import _parse_projection_payload

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise SubingStrategyPerformanceFullRebuildRequired()
    summaries = getattr(tail, "segment_summaries", ())
    if len(summaries) != 1:
        raise SubingStrategyPerformanceFullRebuildRequired()
    summary = summaries[0]
    tail_segment = lineage.ordered_segments[-1]
    if (
        summary.contract != tail_segment.contract
        or summary.start_trading_day != tail_segment.effective_start
        or summary.loaded_through != lineage.coverage_through
        or summary.source_identity_sha256 != tail_segment.source_identity
    ):
        raise SubingStrategyPerformanceFullRebuildRequired()
    projection = _parse_projection_payload(
        payload,
        symbol=lineage.symbol,
        coverage_since=lineage.coverage_since,
        coverage_through=lineage.coverage_through,
        resolved_cutoff=datetime.fromisoformat(str(payload["resolved_cutoff"])),
    )
    if (
        projection.symbol != lineage.symbol
        or projection.coverage_since != lineage.coverage_since
        or projection.coverage_through != lineage.coverage_through
        or projection.segment_count != len(lineage.ordered_segments)
    ):
        raise SubingStrategyPerformanceFullRebuildRequired()
    tail_context = len(getattr(tail, "context_unavailable", ()))
    if (
        projection.bar_count_15m < summary.bar_count_15m
        or projection.context_unavailable_count < tail_context
    ):
        raise SubingStrategyPerformanceFullRebuildRequired()
    prefix_counts = SubingStrategyPerformancePrefixCounts(
        bar_count_1m=0,
        bar_count_5m=0,
        bar_count_15m=projection.bar_count_15m - summary.bar_count_15m,
        context_unavailable_count=(
            projection.context_unavailable_count - tail_context
        ),
    )
    fact = SubingStrategyPerformanceSegmentFact(
        contract=summary.contract,
        effective_start=summary.start_trading_day,
        effective_end=summary.end_trading_day,
        loaded_through=summary.loaded_through,
        bar_count_1m=summary.bar_count_1m,
        bar_count_5m=summary.bar_count_5m,
        bar_count_15m=summary.bar_count_15m,
        context_unavailable_count=tail_context,
        source_identity=tail_segment.source_identity,
    )
    from .cache import _canonical_bytes

    expected_payload = _performance_snapshot_payload(projection)
    if _canonical_bytes(dict(payload)) != _canonical_bytes(expected_payload):
        raise SubingStrategyPerformanceFullRebuildRequired()
    return subing_strategy_performance_snapshot_from_projection(
        projection,
        immutable_prefix_segment_count=len(lineage.ordered_segments) - 1,
        immutable_prefix_counts=prefix_counts,
        segment_facts=(fact,),
        source_manifest_sha256=lineage.source_manifest_sha256,
        generated_at=generated_at.astimezone(UTC),
    )
