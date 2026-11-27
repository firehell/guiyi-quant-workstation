"""Checkpoint discipline and scoped post-close/completed-bar advancement."""

from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Callable, Hashable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import date, datetime
from threading import Event, RLock
from typing import TYPE_CHECKING, cast

from guiyi_quant.compute import (
    STATE_SCHEMA_VERSION, BarSeries, ComputeRegistry, FeatureIdentity, FeatureRequest, SeriesIdentity,
)
from guiyi_quant.compute.contracts import hash_parameters
from guiyi_quant.compute.incremental import IncrementalState, advance, open_incremental, rebind_incremental

from .contracts import CommittedLiveBar, ComputeCheckpoint, ComputeScope, ComputeWindow, FeatureUpdate
from .owned_live import OwnedLiveCommit, OwnedLiveScope, OwnedLiveState, OwnedLiveUpdate
from .scheduler import JobQueue

if TYPE_CHECKING:
    from app.market_data.market_archive import MarketArchiveReceipt


# Newow strategy reference is owned by the existing Market receipt consumer.
_CANONICAL_USES = {"canonical_research": "research"}
_CANONICAL_CHECKPOINTS_PER_FEATURE = 4
_LIVE_CONSUMERS = frozenset(("htdy_simulation", "subing_simulation"))
_Updates = tuple[FeatureUpdate, ...]
_Node = tuple[str, str, str, str]
_Owner = tuple[str, str, str, str]
_ScopeKey = tuple[str, _Owner, str | None]


@dataclass(frozen=True, slots=True)
class _State:
    first_bar_end: datetime | None
    value: IncrementalState
    commit_id: str | None = None
    predecessor: datetime | None = None


@dataclass(frozen=True, slots=True)
class _CanonicalJob:
    window: ComputeWindow
    day: date
    nodes: tuple[_Node, ...]
    use: str
    prefix: tuple[SeriesIdentity, datetime | None, datetime | None, int, str] = field(init=False)

    def __post_init__(self) -> None:
        window = self.window
        # A successful retry retains the original publication time for the same day and committed input.
        object.__setattr__(self, "prefix", (
            window.source, window.first_bar_end, window.last_bar_end, window.bar_count, window.input_digest,
        ))


class StateUpdates:
    def __init__(
        self, registry: ComputeRegistry, *,
        canonical_scopes: tuple[ComputeScope, ...],
        live_scopes: tuple[ComputeScope, ...],
        owned_live_scopes: tuple[OwnedLiveScope, ...],
        canonical_pending: int, live_pending: int, max_prefix_bars: int, max_checkpoints: int,
    ) -> None:
        if min(max_prefix_bars, max_checkpoints) < 1:
            raise ValueError("COMPUTE_CHECKPOINT_LIMIT_INVALID")
        self._registry = registry
        self._max_prefix_bars = max_prefix_bars
        self._max_checkpoints = max_checkpoints
        self._canonical_scopes = self._register(canonical_scopes, mode="incremental")
        self._live_scopes = self._register(live_scopes, mode="live")
        if sum(len(features) for features in self._live_scopes.values()) + len(owned_live_scopes) > max_checkpoints:
            raise ValueError("COMPUTE_LIVE_SCOPE_LIMIT")
        self._canonical = JobQueue[_Updates]("incremental", canonical_pending)
        self._live = JobQueue[object]("live", live_pending)
        self._owned_live = OwnedLiveState(owned_live_scopes)
        self._lock = RLock()
        self._canonical_states: OrderedDict[tuple[FeatureIdentity, str], _State] = OrderedDict()
        self._canonical_results: OrderedDict[_CanonicalJob, _Updates] = OrderedDict()
        self._live_states: dict[tuple[SeriesIdentity, _Node], _State] = {}

    def _register(
        self, scopes: tuple[ComputeScope, ...], *, mode: str,
    ) -> dict[_ScopeKey, tuple[FeatureRequest, ...]]:
        indexed: dict[_ScopeKey, tuple[FeatureRequest, ...]] = {}
        for scope in scopes:
            if mode == "live":
                if scope.consumer not in _LIVE_CONSUMERS or not scope.source_revision:
                    raise ValueError("COMPUTE_LIVE_SCOPE_INVALID")
                use = "simulation"
            else:
                if scope.consumer not in _CANONICAL_USES or scope.source_revision is not None:
                    raise ValueError("COMPUTE_CANONICAL_SCOPE_INVALID")
                use = _CANONICAL_USES[scope.consumer]
            owner = (scope.product, scope.physical_contract, scope.segment_id, scope.frequency)
            key = (scope.consumer, owner, scope.source_revision)
            SeriesIdentity(*owner, scope.source_revision or "canonical_scope")
            if key in indexed or not 0 < len(scope.features) <= self._max_checkpoints:
                raise ValueError("COMPUTE_SCOPE_INVALID")
            nodes = set()
            for request in scope.features:
                definition = self._registry.validate_request(request, frequency=scope.frequency, use=use, mode=mode)
                if definition.category != "generic" or definition.dependencies or definition.optional_dependencies:
                    raise ValueError("COMPUTE_STATE_KERNEL_UNSUPPORTED")
                nodes.add(self._node(request))
            if len(nodes) != len(scope.features):
                raise ValueError("COMPUTE_SCOPE_FEATURE_DUPLICATE")
            indexed[key] = tuple(scope.features)
        return indexed

    def _node(self, request: FeatureRequest) -> _Node:
        definition = self._registry.definition(request.feature_id)
        return (
            request.feature_id, definition.formula_version, definition.backend_version,
            hash_parameters(definition.resolve(request)),
        )

    def submit_canonical(
        self, receipt: "MarketArchiveReceipt", window: ComputeWindow, *, consumer: str,
        load: Callable[[], BarSeries],
    ) -> Future[_Updates]:
        from app.market_data.market_archive import MarketArchiveReceipt

        if not isinstance(receipt, MarketArchiveReceipt):
            raise ValueError("COMPUTE_CANONICAL_RECEIPT_REQUIRED")
        if (
            not receipt.identity or receipt.revisions.get(window.source.product) != window.source.source_revision
            or receipt.finished_at != window.as_of
        ):
            raise ValueError("COMPUTE_CANONICAL_RECEIPT_MISMATCH")
        if window.bar_count > self._max_prefix_bars:
            raise ValueError("COMPUTE_PREFIX_LIMIT_EXCEEDED")
        requests = self._canonical_scopes.get((consumer, _owner(window.source), None))
        if requests is None:
            raise ValueError("COMPUTE_SCOPE_NOT_ENABLED")
        use = _CANONICAL_USES[consumer]
        key = _CanonicalJob(window, receipt.trading_day, tuple(map(self._node, requests)), use)
        with self._lock:
            return self._canonical.submit(key, lambda invalidated: self._run_canonical(key, requests, load, invalidated))

    def _run_canonical(
        self, key: _CanonicalJob, requests: tuple[FeatureRequest, ...], load: Callable[[], BarSeries],
        invalidated: Event,
    ) -> _Updates:
        with self._lock:
            _require_current(invalidated)
            matching = (
                candidate for candidate in self._canonical_results
                if candidate.day == key.day and candidate.nodes == key.nodes and candidate.use == key.use
                and candidate.prefix == key.prefix and candidate.window.as_of <= key.window.as_of
            )
            prior = min(matching, default=None, key=lambda candidate: candidate.window.as_of)
            if prior is not None:
                self._canonical_results.move_to_end(prior)
                return self._canonical_results[prior]

        window = key.window
        series = load()
        if (
            not isinstance(series, BarSeries) or len(series.bars) > self._max_prefix_bars
            or ComputeWindow.from_series(series, as_of=window.as_of) != window
            or any(bar.trading_day > key.day for bar in series.bars[:window.bar_count])
        ):
            raise ValueError("COMPUTE_CANONICAL_PREFIX_UNVERIFIED")

        records = []
        for request, node in zip(requests, key.nodes, strict=True):
            state = self._resume_canonical(key, series, node)
            resumed = state.bar_count if state is not None else 0
            if state is None:
                state = open_incremental(
                    self._registry, series, request, as_of=window.as_of, mode="incremental", use=key.use,
                )
            else:
                for bar in series.bars[resumed:window.bar_count]:
                    state, _ = advance(self._registry, state, series.identity, bar)
            update = _update(state, window.first_bar_end, window.as_of, resumed_bars=resumed)
            records.append((update, _State(window.first_bar_end, state)))

        with self._lock:
            _require_current(invalidated)
            for update, record in records:
                self._remember_canonical_state(update.checkpoint.identity, key.use, record)
            updates = tuple(update for update, _ in records)
            self._canonical_results[key] = updates
            while len(self._canonical_states) > self._max_checkpoints:
                self._canonical_states.popitem(last=False)
            while len(self._canonical_results) > self._max_checkpoints:
                self._canonical_results.popitem(last=False)
        return updates

    def _remember_canonical_state(self, identity: FeatureIdentity, use: str, record: _State) -> None:
        key = (identity, use)
        self._canonical_states[key] = record
        self._canonical_states.move_to_end(key)
        same_feature = [
            candidate for candidate in self._canonical_states
            if (
                candidate[1] == use and _owner(candidate[0].source) == _owner(identity.source)
                and _identity_node(candidate[0]) == _identity_node(identity)
            )
        ]
        if len(same_feature) > _CANONICAL_CHECKPOINTS_PER_FEATURE:
            del self._canonical_states[same_feature[0]]

    def _resume_canonical(
        self, key: _CanonicalJob, series: BarSeries, node: _Node,
    ) -> IncrementalState | None:
        window = key.window
        with self._lock:
            candidates = [
                record.value for (identity, use), record in self._canonical_states.items()
                if (
                    use == key.use and _owner(identity.source) == _owner(window.source)
                    and _identity_node(identity) == node and record.first_bar_end == window.first_bar_end
                    and 0 < identity.bar_count <= window.bar_count
                    and record.value.state_schema_version == STATE_SCHEMA_VERSION
                    and identity.as_of <= window.as_of
                )
            ]
        # The closest proven predecessor minimizes replay of unaffected Bars.
        for state in sorted(candidates, key=lambda candidate: candidate.bar_count, reverse=True):
            try:
                return rebind_incremental(state, series, prefix_count=state.bar_count)
            except ValueError as error:
                if str(error) != "STATE_PREFIX_CHANGED":
                    raise
        return None

    def submit_live(
        self, consumer: str, commit: CommittedLiveBar, *, load: Callable[[], BarSeries],
        checkpoints: tuple[ComputeCheckpoint, ...] = (),
    ) -> Future[_Updates]:
        if not isinstance(commit, CommittedLiveBar):
            raise ValueError("COMPUTE_LIVE_COMMIT_REQUIRED")
        requests = self._live_scopes.get((consumer, _owner(commit.source), commit.source.source_revision))
        if requests is None:
            raise ValueError("COMPUTE_SCOPE_NOT_ENABLED")
        nodes = tuple(map(self._node, requests))
        by_node = {_identity_node(item.identity): item for item in checkpoints}
        if len(by_node) != len(checkpoints) or not by_node.keys() <= set(nodes):
            raise ValueError("COMPUTE_CHECKPOINT_SCOPE_INVALID")
        ordered_checkpoints = tuple(by_node.get(node) for node in nodes)
        key = (commit, nodes, ordered_checkpoints)
        return cast(Future[_Updates], self._live.submit(
            key, lambda _: self._run_live(commit, requests, nodes, load, ordered_checkpoints),
        ))

    def submit_owned_live[T](
        self, commit: OwnedLiveCommit, *, owner: object, run: Callable[[], T],
    ) -> Future[OwnedLiveUpdate[T]]:
        if not isinstance(commit, OwnedLiveCommit) or commit.scope not in self._owned_live.scopes:
            raise ValueError("COMPUTE_SCOPE_NOT_ENABLED")
        # Do not coalesce concurrent callers. The second caller must receive
        # duplicate=True only after the first really advanced the owner state.
        return cast(Future[OwnedLiveUpdate[T]], self._live.submit(
            object(), lambda _: self._owned_live.advance(commit, owner, run),
        ))

    def _run_live(
        self, commit: CommittedLiveBar, requests: tuple[FeatureRequest, ...], nodes: tuple[_Node, ...],
        load: Callable[[], BarSeries], checkpoints: tuple[ComputeCheckpoint | None, ...],
    ) -> _Updates:
        records = {}
        updates = []
        series = None
        bar = commit.bar
        first: datetime | None
        for request, node, checkpoint in zip(requests, nodes, checkpoints, strict=True):
            key = (commit.source, node)
            previous = self._live_states.get(key)
            if previous is None:
                if series is None:
                    series = self._verified_live_prefix(commit, load)
                state, duplicate, recovery = self._restore_live(commit, series, request, checkpoint)
                first = series.bars[0].bar_end
                resumed = 0
            else:
                first = previous.first_bar_end
                state = previous.value
                last = state.last_bar
                point = state.last_point
                if last is None or point is None:
                    raise ValueError("COMPUTE_LIVE_STATE_INVALID")
                if bar.bar_end == last.bar_end:
                    if commit.previous_bar_end != previous.predecessor:
                        raise ValueError("COMPUTE_LIVE_PREDECESSOR_CONFLICT")
                    if commit.commit_id != previous.commit_id:
                        raise ValueError("COMPUTE_LIVE_COMMIT_CONFLICT")
                if bar.bar_end > last.bar_end and (
                    commit.previous_bar_end != last.bar_end or bar.available_at < point.available_at
                    or commit.commit_id == previous.commit_id
                ):
                    raise ValueError("COMPUTE_LIVE_NONCONTIGUOUS")
                resumed = state.bar_count
                state, _ = advance(self._registry, state, commit.source, bar)
                duplicate = state is previous.value
                recovery = None

            updates.append(_update(
                state, first, bar.available_at, resumed, duplicate, recovery, live_commit_id=commit.commit_id,
            ))
            records[key] = previous if duplicate and previous is not None else _State(
                first, state, commit.commit_id, commit.previous_bar_end,
            )
        # Validate the entire subscribed feature set before committing any checkpoint.
        self._live_states.update(records)
        return tuple(updates)

    def _verified_live_prefix(
        self, commit: CommittedLiveBar, load: Callable[[], BarSeries],
    ) -> BarSeries:
        series = load()
        if (
            not isinstance(series, BarSeries) or series.identity != commit.source
            or len(series.bars) > self._max_prefix_bars
        ):
            raise ValueError("COMPUTE_LIVE_PREFIX_UNVERIFIED")
        available = series.available_count(commit.bar.available_at)
        count = bisect_right(series.bars, commit.bar.bar_end, hi=available, key=lambda bar: bar.bar_end)
        if not count or series.bars[count - 1].bar_end != commit.bar.bar_end:
            raise ValueError("COMPUTE_LIVE_PREFIX_UNVERIFIED")
        predecessor = series.bars[count - 2].bar_end if count > 1 else None
        if predecessor != commit.previous_bar_end:
            raise ValueError("COMPUTE_LIVE_PREFIX_UNVERIFIED")
        # Multiple recovered commits can share an availability time. This job
        # may seed only through the committed Bar's own endpoint.
        return series if count == available else BarSeries(series.identity, series.bars[:count])

    def _restore_live(
        self, commit: CommittedLiveBar, series: BarSeries, request: FeatureRequest,
        checkpoint: ComputeCheckpoint | None,
    ) -> tuple[IncrementalState, bool, str]:
        recovery = "VERIFIED_PREFIX_REBUILT"
        matching_cursor = (
            checkpoint
            if checkpoint is not None and checkpoint.mode == "live" and checkpoint.identity.source == commit.source
            else None
        )
        duplicate = False
        if matching_cursor is not None:
            identity = matching_cursor.identity
            checkpoint_end = identity.last_bar_end
            if checkpoint_end is not None and (
                checkpoint_end > commit.bar.bar_end or identity.as_of > commit.bar.available_at
            ):
                raise ValueError("COMPUTE_LIVE_CHECKPOINT_AHEAD")
            count = identity.bar_count
            if (
                not 0 < count <= series.available_count(identity.as_of)
                or series.bars[0].bar_end != identity.first_bar_end
                or series.bars[count - 1].bar_end != checkpoint_end
                or series.prefix_digest(count) != identity.input_digest
            ):
                raise ValueError("COMPUTE_LIVE_CHECKPOINT_CONFLICT")
            if matching_cursor.state_schema_version != STATE_SCHEMA_VERSION:
                recovery = "STATE_SCHEMA_REBUILT"
            elif matching_cursor.prefix_digest != identity.input_digest:
                raise ValueError("COMPUTE_LIVE_CHECKPOINT_CONFLICT")
            duplicate = checkpoint_end == commit.bar.bar_end
            same_commit = matching_cursor.live_commit_id == commit.commit_id
            if duplicate != same_commit:
                raise ValueError("COMPUTE_LIVE_COMMIT_CONFLICT")
            if not duplicate and commit.previous_bar_end != checkpoint_end:
                raise ValueError("COMPUTE_LIVE_NONCONTIGUOUS")
        elif checkpoint is not None:
            recovery = "STATE_SOURCE_REBUILT"

        state = open_incremental(
            self._registry, series, request, as_of=commit.bar.available_at, mode="live", use="simulation",
        )
        # Use the kernel's exact duplicate guard, which also recognizes non-finite input.
        state, _ = advance(self._registry, state, commit.source, commit.bar)
        return state, duplicate, recovery

    def invalidate_revision(self, source: SeriesIdentity, *, from_bar_end: datetime) -> None:
        """Invalidate Historical Canonical state. Live cursors bind their own commit lineage."""
        def affects(window: ComputeWindow) -> bool:
            return (
                window.source == source and window.last_bar_end is not None
                and window.last_bar_end >= from_bar_end
            )

        def running(key: Hashable) -> bool:
            return isinstance(key, _CanonicalJob) and affects(key.window)

        with self._lock:
            self._canonical.invalidate(running)
            for key in tuple(self._canonical_results):
                if affects(key.window):
                    del self._canonical_results[key]
            for state_key in tuple(self._canonical_states):
                identity, _ = state_key
                if (
                    identity.source == source and identity.last_bar_end is not None
                    and identity.last_bar_end >= from_bar_end
                ):
                    del self._canonical_states[state_key]

    def queue_load(self) -> dict[str, dict[str, int]]:
        return {"incremental": self._canonical.queue_load(), "live": self._live.queue_load()}

    def close(self) -> None:
        self._canonical.close()
        self._live.close()


def _require_current(invalidated: Event) -> None:
    if invalidated.is_set():
        raise ValueError("COMPUTE_REVISION_INVALIDATED")


def _owner(source: SeriesIdentity) -> _Owner:
    return source.product, source.physical_contract, source.segment_id, source.frequency


def _identity_node(identity: FeatureIdentity) -> _Node:
    return identity.feature_id, identity.formula_version, identity.backend_version, identity.parameters_hash


def _update(
    state: IncrementalState, first: datetime | None, as_of: datetime,
    resumed_bars: int = 0, duplicate: bool = False, recovery: str | None = None,
    *, live_commit_id: str | None = None,
) -> FeatureUpdate:
    identity = FeatureIdentity(
        state.identity, state.request.feature_id, state.formula_version, hash_parameters(state.request.parameters),
        state.backend_version, as_of, first, state.last_bar.bar_end if state.last_bar else None,
        state.bar_count, state.prefix_digest,
    )
    checkpoint = ComputeCheckpoint(identity, state.state_schema_version, state.prefix_digest, state.mode, live_commit_id)
    return FeatureUpdate(checkpoint, state.last_point, resumed_bars, duplicate, recovery)
