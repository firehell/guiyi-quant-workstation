"""Application coordination for immutable Core feature calculation."""

from collections import ChainMap, OrderedDict
from collections.abc import Callable, Hashable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event, RLock
from typing import TYPE_CHECKING

from guiyi_quant.compute import BarSeries, ComputeRegistry, FeatureIdentity, FeatureRequest, FeatureResult, SeriesIdentity
from guiyi_quant.compute.contracts import hash_parameters, require_aware

from .contracts import CommittedLiveBar, ComputeCheckpoint, ComputeScope, ComputeWindow, FeatureUpdate
from .owned_live import OwnedLiveCommit, OwnedLiveScope, OwnedLiveUpdate
from .scheduler import JobQueue
from .state_updates import StateUpdates

if TYPE_CHECKING:
    from app.market_data.market_archive import MarketArchiveReceipt


@dataclass(frozen=True, slots=True)
class BatchKey:
    window: ComputeWindow
    identities: tuple[FeatureIdentity, ...]
    use: str = field(compare=False)


class ComputeRuntime:
    def __init__(
        self, registry: ComputeRegistry, *, batch_pending: int = 4, canonical_pending: int = 4,
        live_pending: int = 32, max_batch_bars: int = 100_000, max_batch_work_points: int = 500_000,
        cache_entries: int = 64, cache_points: int = 250_000, max_checkpoints: int = 1024,
        canonical_scopes: tuple[ComputeScope, ...] = (), live_scopes: tuple[ComputeScope, ...] = (),
        owned_live_scopes: tuple[OwnedLiveScope, ...] = (),
    ) -> None:
        if min(max_batch_bars, max_batch_work_points, cache_entries, cache_points) < 1:
            raise ValueError("COMPUTE_LIMIT_INVALID")
        self._registry = registry
        self._state = StateUpdates(
            registry, canonical_scopes=canonical_scopes, live_scopes=live_scopes,
            owned_live_scopes=owned_live_scopes,
            canonical_pending=canonical_pending, live_pending=live_pending,
            max_prefix_bars=max_batch_bars, max_checkpoints=max_checkpoints,
        )
        self._batch = JobQueue[tuple[FeatureResult, ...]]("batch", batch_pending)
        self._max_batch_bars = max_batch_bars
        self._max_batch_work_points = max_batch_work_points
        self._cache_entries = cache_entries
        self._cache_points = cache_points
        self._cached_weight = 0
        self._results: OrderedDict[FeatureIdentity, FeatureResult] = OrderedDict()
        self._lock = RLock()

    def read_batch(
        self, window: ComputeWindow, requests: tuple[FeatureRequest, ...], *, use: str,
    ) -> tuple[FeatureResult, ...] | None:
        """Resolve a cache hit on the caller's thread without opening a series."""
        key = self._batch_key(window, requests, use)
        with self._lock:
            return self._read_results(key.identities)

    def submit_batch(
        self, window: ComputeWindow, requests: tuple[FeatureRequest, ...], *, use: str,
        load: Callable[[], BarSeries],
    ) -> Future[tuple[FeatureResult, ...]]:
        key = self._batch_key(window, requests, use)
        with self._lock:
            if (cached := self._read_results(key.identities)) is not None:
                completed = Future[tuple[FeatureResult, ...]]()
                completed.set_result(cached)
                return completed
            return self._batch.submit(key, lambda invalidated: self._run_batch(key, requests, load, invalidated))

    def submit_canonical(
        self, receipt: "MarketArchiveReceipt", window: ComputeWindow, *, consumer: str,
        load: Callable[[], BarSeries],
    ) -> Future[tuple[FeatureUpdate, ...]]:
        """Admit only a retained, verified after-close Market receipt and its frozen series."""
        return self._state.submit_canonical(receipt, window, consumer=consumer, load=load)

    def submit_live(
        self, consumer: str, commit: CommittedLiveBar, *, load: Callable[[], BarSeries],
        checkpoints: tuple[ComputeCheckpoint, ...] = (),
    ) -> Future[tuple[FeatureUpdate, ...]]:
        """Advance only explicitly subscribed simulation features on a completed commit."""
        return self._state.submit_live(consumer, commit, load=load, checkpoints=checkpoints)

    def admit_htdy_scope(self, scope: OwnedLiveScope) -> None:
        self._state.admit_htdy_scope(scope)

    def submit_owned_live[T](
        self, commit: OwnedLiveCommit, *, owner: object, run: Callable[[], T],
    ) -> Future[OwnedLiveUpdate[T]]:
        """Schedule an existing simulation kernel without changing its formula or state."""
        return self._state.submit_owned_live(commit, owner=owner, run=run)

    def _batch_key(self, window: ComputeWindow, requests: tuple[FeatureRequest, ...], use: str) -> BatchKey:
        if use not in {"web", "research", "backtest"}:
            raise ValueError("COMPUTE_BATCH_CONSUMER_NOT_ALLOWED")
        if not requests or window.bar_count > self._max_batch_bars or len(requests) > self._cache_entries:
            raise ValueError("COMPUTE_BATCH_LIMIT_EXCEEDED")

        checked: set[tuple[str, str]] = set()

        def validate(request: FeatureRequest) -> FeatureIdentity:
            definition = self._registry.validate_request(
                request, frequency=window.source.frequency, use=use, mode="batch",
            )
            parameters = definition.resolve(request)
            parameter_hash = hash_parameters(parameters)
            identity = self._registry.request_identity(
                window.source, request, as_of=window.as_of,
                first_bar_end=window.first_bar_end, last_bar_end=window.last_bar_end,
                bar_count=window.bar_count, input_digest=window.input_digest,
            )
            node = (request.feature_id, parameter_hash)
            if node not in checked:
                checked.add(node)
                for dependency in definition.dependencies:
                    validate(dependency)
                for parameter, dependency in definition.optional_dependencies:
                    if parameters[parameter]:
                        validate(dependency)
            return identity

        identities = tuple(validate(request) for request in requests)
        if len(checked) > self._cache_entries or len(checked) * window.bar_count > self._max_batch_work_points:
            raise ValueError("COMPUTE_BATCH_LIMIT_EXCEEDED")
        return BatchKey(window, identities, use)

    def _run_batch(
        self, key: BatchKey, requests: tuple[FeatureRequest, ...], load: Callable[[], BarSeries],
        invalidated: Event,
    ) -> tuple[FeatureResult, ...]:
        with self._lock:
            if invalidated.is_set():
                raise ValueError("COMPUTE_REVISION_INVALIDATED")
            if (cached := self._read_results(key.identities)) is not None:
                return cached
            known = {
                identity: result for identity, result in self._results.items()
                if _matches_window(identity, key.window)
            }
        series = load()
        if (
            not isinstance(series, BarSeries) or len(series.bars) > self._max_batch_bars
            or ComputeWindow.from_series(series, as_of=key.window.as_of) != key.window
        ):
            raise ValueError("COMPUTE_WINDOW_MISMATCH")
        staged: dict[FeatureIdentity, FeatureResult] = {}
        results = self._registry.calculate(
            series, requests, as_of=key.window.as_of, use=key.use, result_cache=ChainMap(staged, known),
        )
        if tuple(result.identity for result in results) != key.identities:
            raise ValueError("COMPUTE_RESULT_IDENTITY_MISMATCH")
        with self._lock:
            if invalidated.is_set():
                raise ValueError("COMPUTE_REVISION_INVALIDATED")
            for identity in known:
                self._results.move_to_end(identity)
            for identity, result in staged.items():
                weight = _result_weight(result)
                if weight <= self._cache_points:
                    self._results[identity] = result
                    self._cached_weight += weight
            self._prune_results()
        return results

    def _read_results(self, identities: tuple[FeatureIdentity, ...]) -> tuple[FeatureResult, ...] | None:
        if not all(identity in self._results for identity in identities):
            return None
        for identity in identities:
            self._results.move_to_end(identity)
        return tuple(self._results[identity] for identity in identities)

    def _prune_results(self) -> None:
        while len(self._results) > self._cache_entries or self._cached_weight > self._cache_points:
            _, result = self._results.popitem(last=False)
            self._cached_weight -= _result_weight(result)

    def invalidate_revision(self, source: SeriesIdentity, *, from_bar_end: datetime) -> None:
        """Evict windows reaching the first changed Bar of the superseded owner/revision."""
        require_aware(from_bar_end)

        def affects(window: ComputeWindow) -> bool:
            return (
                window.source == source and window.last_bar_end is not None
                and window.last_bar_end >= from_bar_end
            )

        def running(key: Hashable) -> bool:
            return isinstance(key, BatchKey) and affects(key.window)

        with self._lock:
            self._state.invalidate_revision(source, from_bar_end=from_bar_end)
            self._batch.invalidate(running)
            expired = [
                identity for identity in self._results
                if identity.source == source and identity.last_bar_end is not None
                and identity.last_bar_end >= from_bar_end
            ]
            for identity in expired:
                self._cached_weight -= _result_weight(self._results.pop(identity))

    def queue_load(self) -> dict[str, dict[str, int]]:
        return {"batch": self._batch.queue_load(), **self._state.queue_load()}

    def close(self) -> None:
        self._state.close()
        self._batch.close()

    def __enter__(self) -> "ComputeRuntime":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _matches_window(identity: FeatureIdentity, window: ComputeWindow) -> bool:
    return (
        identity.source, identity.as_of, identity.first_bar_end, identity.last_bar_end,
        identity.bar_count, identity.input_digest,
    ) == (
        window.source, window.as_of, window.first_bar_end, window.last_bar_end,
        window.bar_count, window.input_digest,
    )


def _result_weight(result: FeatureResult) -> int:
    return 1 + len(result.points) + len(result.markers)
