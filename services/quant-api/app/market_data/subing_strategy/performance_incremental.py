"""Segment-tail incremental refresh for SuBing performance snapshots."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from hashlib import sha256
import json
from typing import Protocol

from ..domain import BarFrequency, SeriesKind
from .contracts import (
    SUBING_STRATEGY_ID,
    SubingStrategyEpisode,
    SubingStrategyPositionState,
)
from .performance import (
    SubingStrategyPerformanceProjection,
    SubingStrategyPerformanceWarmResult,
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
    SubingStrategyPerformanceSnapshotMissingError,
    subing_strategy_performance_projection_from_snapshot,
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
        adopter: _Adopter | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._lineage = lineage
        self._historical = historical
        self._store = store
        self._adopter = adopter
        self._now = now or (lambda: datetime.now(UTC))

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
        previous_identity = _identity_from_snapshot(snapshot)
        current_identity = _identity_from_current(
            historical=self._historical,
            previous=previous_identity,
        )
        decision = decide_subing_strategy_performance_tail(
            previous=previous_lineage,
            current=current_lineage,
            previous_identity=previous_identity,
            current_identity=current_identity,
        )
        if decision.kind == FULL_REBUILD_REQUIRED.kind:
            raise SubingStrategyPerformanceFullRebuildRequired()
        if decision.kind == UNCHANGED.kind:
            return subing_strategy_performance_projection_from_snapshot(snapshot)
        if decision.index is None:
            raise SubingStrategyPerformanceFullRebuildRequired()
        return self._replay_from(
            snapshot=snapshot,
            current_lineage=current_lineage,
            previous_identity=previous_identity,
            index=decision.index,
        )

    def _current_or_adopt(
        self,
        *,
        symbol: str,
        through: date,
    ) -> SubingStrategyPerformanceSnapshot:
        try:
            return self._store.read_current_for_refresh(
                symbol=symbol,
                expected_through=through,
            )
        except SubingStrategyPerformanceSnapshotMissingError:
            if self._adopter is None:
                raise SubingStrategyPerformanceFullRebuildRequired() from None
            return self._adopter.adopt(symbol=symbol, through=through)
        except SubingStrategyPerformanceSnapshotError:
            raise SubingStrategyPerformanceFullRebuildRequired() from None

    def _replay_from(
        self,
        *,
        snapshot: SubingStrategyPerformanceSnapshot,
        current_lineage: SubingStrategyPerformanceLineage,
        previous_identity: SubingStrategyPerformanceSemanticIdentity,
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
        tail_engine = getattr(tail, "engine_identity_sha256", None)
        if (
            isinstance(tail_engine, str)
            and tail_engine != previous_identity.engine_identity_sha256
        ):
            raise SubingStrategyPerformanceFullRebuildRequired()
        merged = _merge_snapshot(
            snapshot=snapshot,
            current_lineage=current_lineage,
            tail=tail,
            seam_index=index,
            generated_at=self._now(),
            engine_identity_sha256=previous_identity.engine_identity_sha256,
        )
        self._store.publish_current(merged)
        return merged.projection


def _identity_from_snapshot(
    snapshot: SubingStrategyPerformanceSnapshot,
) -> SubingStrategyPerformanceSemanticIdentity:
    return SubingStrategyPerformanceSemanticIdentity(
        strategy_id=snapshot.projection.strategy_id,
        formula_version=snapshot.projection.formula_version,
        engine_identity_sha256=snapshot.engine_identity_sha256,
    )


def _identity_from_current(
    *,
    historical: object,
    previous: SubingStrategyPerformanceSemanticIdentity,
) -> SubingStrategyPerformanceSemanticIdentity:
    engine = getattr(historical, "engine_identity_sha256", None)
    if engine is None:
        engine = getattr(historical, "_engine_identity_sha256", None)
    if not isinstance(engine, str):
        engine = previous.engine_identity_sha256
    return SubingStrategyPerformanceSemanticIdentity(
        strategy_id=SUBING_STRATEGY_ID,
        formula_version=_FIXED_FORMULA_VERSION,
        engine_identity_sha256=engine,
    )


def _merge_snapshot(
    *,
    snapshot: SubingStrategyPerformanceSnapshot,
    current_lineage: SubingStrategyPerformanceLineage,
    tail: object,
    seam_index: int,
    generated_at: datetime,
    engine_identity_sha256: str,
) -> SubingStrategyPerformanceSnapshot:
    summaries = tuple(getattr(tail, "segment_summaries", ()))
    tail_segments = current_lineage.ordered_segments[seam_index:]
    if len(summaries) != len(tail_segments):
        raise SubingStrategyPerformanceFullRebuildRequired()
    if len(summaries) > 1:
        _require_isolated_rollover(summaries)
    unavailable_counts = _unavailable_counts_by_segment(
        tuple(getattr(tail, "context_unavailable", ())),
        summaries,
    )
    facts: list[SubingStrategyPerformanceSegmentFact] = []
    for summary, segment, unavailable_count in zip(
        summaries, tail_segments, unavailable_counts, strict=True
    ):
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
                context_unavailable_count=unavailable_count,
                source_identity=segment.source_identity,
            )
        )
    if not facts or facts[-1].loaded_through != current_lineage.coverage_through:
        raise SubingStrategyPerformanceFullRebuildRequired()
    prefix_segments = current_lineage.ordered_segments[:seam_index]
    prefix_episodes = _prefix_episodes(
        snapshot.projection.episodes,
        prefix_segments=prefix_segments,
        old_tail_facts=snapshot.segment_facts,
        tail_segments=tail_segments,
    )
    tail_episodes = tuple(getattr(tail, "episodes", ()))
    _validate_tail_episodes(tail_episodes, tail_segments)
    merged_episodes = prefix_episodes + tail_episodes
    prefix_counts = snapshot.immutable_prefix_counts
    if len(facts) > 1:
        for closed in facts[:-1]:
            prefix_counts = SubingStrategyPerformancePrefixCounts(
                bar_count_1m=prefix_counts.bar_count_1m + closed.bar_count_1m,
                bar_count_5m=prefix_counts.bar_count_5m + closed.bar_count_5m,
                bar_count_15m=prefix_counts.bar_count_15m + closed.bar_count_15m,
                context_unavailable_count=(
                    prefix_counts.context_unavailable_count
                    + closed.context_unavailable_count
                ),
            )
        facts = facts[-1:]
    remaining_15m = sum(fact.bar_count_15m for fact in facts)
    remaining_context = sum(fact.context_unavailable_count for fact in facts)
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
        bar_count_15m=prefix_counts.bar_count_15m + remaining_15m,
        context_unavailable_count=(
            prefix_counts.context_unavailable_count + remaining_context
        ),
        cache_state="refreshed",
        summary=summarize_subing_strategy_episodes(merged_episodes),
        episodes=merged_episodes,
    )
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise SubingStrategyPerformanceFullRebuildRequired()
    return subing_strategy_performance_snapshot_from_projection(
        projection,
        immutable_prefix_segment_count=len(current_lineage.ordered_segments)
        - len(facts),
        immutable_prefix_counts=prefix_counts,
        segment_facts=tuple(facts),
        source_manifest_sha256=current_lineage.source_manifest_sha256,
        generated_at=generated_at.astimezone(UTC),
        engine_identity_sha256=engine_identity_sha256,
    )


def _require_isolated_rollover(summaries: Sequence[object]) -> None:
    closed = summaries[0]
    incoming = summaries[-1]
    if (
        getattr(closed, "final_position", None) is not SubingStrategyPositionState.FLAT
        or bool(getattr(closed, "pending_action", False))
        or getattr(incoming, "initial_position", None)
        is not SubingStrategyPositionState.FLAT
    ):
        raise SubingStrategyPerformanceFullRebuildRequired()


def _segment_key(item: object) -> tuple[object, object]:
    contract = getattr(item, "contract", None)
    start = getattr(item, "effective_start", None)
    if start is None:
        start = getattr(item, "start_trading_day", None)
    return (contract, start)


def _unavailable_counts_by_segment(
    context_unavailable: Sequence[object],
    summaries: Sequence[object],
) -> tuple[int, ...]:
    counts = [0] * len(summaries)
    for item in context_unavailable:
        index = _index_for_unavailable(item, summaries)
        if index is None:
            if len(summaries) == 1:
                counts[0] += 1
                continue
            raise SubingStrategyPerformanceFullRebuildRequired()
        counts[index] += 1
    return tuple(counts)


def _index_for_unavailable(
    item: object,
    summaries: Sequence[object],
) -> int | None:
    day = getattr(item, "target_trading_day", None)
    contract = getattr(item, "physical_contract", None)
    if day is None and contract is None:
        return None
    matches: list[int] = []
    for index, summary in enumerate(summaries):
        day_ok = day is None or (
            summary.start_trading_day <= day <= summary.end_trading_day
        )
        contract_ok = contract is None or contract == summary.contract
        if day_ok and contract_ok:
            matches.append(index)
    if len(matches) == 1:
        return matches[0]
    return None


def _prefix_episodes(
    episodes: Sequence[SubingStrategyEpisode],
    *,
    prefix_segments: Sequence[object],
    old_tail_facts: Sequence[object],
    tail_segments: Sequence[object],
) -> tuple[SubingStrategyEpisode, ...]:
    prefix_keys = {_segment_key(segment) for segment in prefix_segments}
    old_tail_keys = {_segment_key(fact) for fact in old_tail_facts}
    affected_tail_keys = {_segment_key(segment) for segment in tail_segments}
    prefix: list[SubingStrategyEpisode] = []
    for episode in episodes:
        key = (
            episode.entry_action.contract,
            episode.entry_action.segment_start_trading_day,
        )
        if key in prefix_keys:
            prefix.append(episode)
        elif key in old_tail_keys:
            if key not in affected_tail_keys:
                raise SubingStrategyPerformanceFullRebuildRequired()
        elif key not in affected_tail_keys:
            raise SubingStrategyPerformanceFullRebuildRequired()
    return tuple(prefix)


def _validate_tail_episodes(
    episodes: Sequence[SubingStrategyEpisode],
    segments: Sequence[object],
) -> None:
    keys = {(segment.contract, segment.effective_start) for segment in segments}
    seen: set[str] = set()
    previous_end = None
    for episode in episodes:
        episode_id = episode.episode_id
        if episode_id in seen or episode_id != episode.entry_action.episode_id:
            raise SubingStrategyPerformanceFullRebuildRequired()
        seen.add(episode_id)
        key = (
            episode.entry_action.contract,
            episode.entry_action.segment_start_trading_day,
        )
        if key not in keys:
            raise SubingStrategyPerformanceFullRebuildRequired()
        if (
            episode.exit_action is not None
            and episode.exit_action.contract != episode.entry_action.contract
        ):
            raise SubingStrategyPerformanceFullRebuildRequired()
        end = episode.entry_action.effective_bar_end
        if previous_end is not None and end < previous_end:
            raise SubingStrategyPerformanceFullRebuildRequired()
        previous_end = end


class _ProductRefresher(Protocol):
    def refresh(
        self,
        *,
        symbol: str,
        through: date,
    ) -> object: ...


class SubingStrategyPerformanceIncrementalBatchRefresher:
    def __init__(
        self,
        *,
        refresher: _ProductRefresher,
        products: tuple[str, ...],
        store: object | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._refresher = refresher
        self._products = products
        self._store = store
        self._now = now or (lambda: datetime.now(UTC))

    def refresh(
        self,
        through: date,
        expected_products: tuple[str, ...],
    ) -> SubingStrategyPerformanceWarmResult:
        created_at = self._now()
        if expected_products != self._products:
            identities = {symbol: None for symbol in expected_products}
            return SubingStrategyPerformanceWarmResult(
                status="degraded",
                completed_products=(),
                failed_products=tuple(
                    (symbol, "SUBING_STRATEGY_ACTIVE_OPERATIONAL_SCOPE_MISMATCH")
                    for symbol in expected_products
                ),
                cache_hit_count=0,
                cache_published_count=0,
                batch_identity_sha256=_batch_identity_sha256(
                    products=expected_products,
                    through=through,
                    current_identities=identities,
                    resulting_identities=identities,
                ),
                batch_created_at=created_at,
            )
        completed: list[str] = []
        failed: list[tuple[str, str]] = []
        cache_hit_count = 0
        cache_published_count = 0
        current_identities: dict[str, str | None] = {}
        resulting_identities: dict[str, str | None] = {}
        for symbol in expected_products:
            current_identities[symbol] = self._peek(symbol, through)
            try:
                projection = self._refresher.refresh(symbol=symbol, through=through)
                cache_state = getattr(projection, "cache_state", None)
                if cache_state not in {"hit", "refreshed"}:
                    raise RuntimeError("SUBING_STRATEGY_CACHE_UNAVAILABLE")
            except Exception as exc:  # noqa: BLE001 - fixed public error boundary
                failed.append((symbol, _public_performance_code(exc)))
                resulting_identities[symbol] = None
                continue
            completed.append(symbol)
            if cache_state == "hit":
                cache_hit_count += 1
                resulting_identities[symbol] = current_identities[symbol]
            else:
                cache_published_count += 1
                resulting_identities[symbol] = self._peek(symbol, through)
        return SubingStrategyPerformanceWarmResult(
            status="degraded" if failed else "passed",
            completed_products=tuple(completed),
            failed_products=tuple(failed),
            cache_hit_count=cache_hit_count,
            cache_published_count=cache_published_count,
            batch_identity_sha256=_batch_identity_sha256(
                products=expected_products,
                through=through,
                current_identities=current_identities,
                resulting_identities=resulting_identities,
            ),
            batch_created_at=created_at,
        )

    def _peek(self, symbol: str, through: date) -> str | None:
        if self._store is None:
            return None
        try:
            snapshot = self._store.read_current_for_refresh(
                symbol=symbol,
                expected_through=through,
            )
        except Exception:  # noqa: BLE001 - identity peek is observational
            return None
        identity = getattr(snapshot, "identity_sha256", None)
        if not isinstance(identity, str) or len(identity) != 64:
            return None
        if any(character not in "0123456789abcdef" for character in identity):
            return None
        return identity


def _public_performance_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.startswith("SUBING_STRATEGY_"):
        return code
    if str(exc) == "SUBING_STRATEGY_CACHE_UNAVAILABLE":
        return "SUBING_STRATEGY_CACHE_UNAVAILABLE"
    return "SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE"


def _batch_identity_sha256(
    *,
    products: tuple[str, ...],
    through: date,
    current_identities: dict[str, str | None],
    resulting_identities: dict[str, str | None],
) -> str:
    payload = {
        "products": list(products),
        "through": through.isoformat(),
        "current_snapshot_identities": [
            {"symbol": symbol, "identity_sha256": current_identities.get(symbol)}
            for symbol in products
        ],
        "resulting_snapshot_identities": [
            {"symbol": symbol, "identity_sha256": resulting_identities.get(symbol)}
            for symbol in products
        ],
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
