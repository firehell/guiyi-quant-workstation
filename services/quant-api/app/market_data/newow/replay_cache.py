"""Reuse pure replay only after the caller has established current MDS facts.

Request cutoffs and snapshot tokens deliberately remain outside this module.
The complete kernel inputs (including lifecycle, quality provenance and gaps)
are hashed; results consume the existing snapshot cache's shared budget.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256

from guiyi_quant.newow.product_adapters import replay_strategy
from guiyi_quant.newow.product_contracts import (
    DataInterruption, LifecycleReplayEvidence, ProductBar, ProductIdentity,
    StrategyReplay,
)

from .inflight import NewowComputationCancelled
from .snapshot_cache import SnapshotCache


def verified_replay(
    cache: SnapshotCache,
    identity: ProductIdentity,
    bars: tuple[ProductBar, ...],
    *,
    lifecycle_evidence: tuple[LifecycleReplayEvidence, ...] = (),
    data_interruptions: tuple[DataInterruption, ...] = (),
    quality_identity: object = (),
    cancelled: Callable[[], bool] | None = None,
) -> StrategyReplay:
    # Process-local reuse: repr covers every frozen input field without
    # manufacturing a public data identity or serializing a second huge graph.
    digest = sha256(b"newow-pure-replay-v1")
    for group in ((identity, quality_identity), bars, lifecycle_evidence, data_interruptions):
        for index, item in enumerate(group):
            if index % 256 == 0 and cancelled is not None and cancelled():
                raise NewowComputationCancelled(NewowComputationCancelled.code)
            digest.update(repr(item).encode())
            digest.update(b"\0")
    key = "pure-replay:" + digest.hexdigest()

    def compute(shared_cancelled: Callable[[], bool]) -> StrategyReplay:
        if shared_cancelled():
            raise NewowComputationCancelled(NewowComputationCancelled.code)
        cached = cache.get(key, ("replay",), touch=False)
        if isinstance(cached, StrategyReplay):
            return cached
        result = replay_strategy(identity, bars, lifecycle_evidence=lifecycle_evidence,
                                 data_interruptions=data_interruptions)
        if shared_cancelled():
            raise NewowComputationCancelled(NewowComputationCancelled.code)
        cache.put(key, ("replay",), result)
        return result

    return cache.calculations.execute(("pure-replay", key), compute, cancelled)
