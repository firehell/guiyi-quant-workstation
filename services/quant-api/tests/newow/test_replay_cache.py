from dataclasses import replace
from unittest.mock import patch

import pytest

from app.market_data.newow.inflight import NewowComputationCancelled
from app.market_data.newow.replay_cache import verified_replay
from app.market_data.newow.snapshot_cache import SnapshotCache
from guiyi_quant.newow.product_adapters import build_product_identity, replay_strategy


def test_verified_equal_inputs_share_kernel_not_request_envelope(product_cases):
    case = product_cases.closed()
    case = replace(case, identity=build_product_identity("rb", "trend", "1d"))
    cache = SnapshotCache()
    with patch("app.market_data.newow.replay_cache.replay_strategy", wraps=replay_strategy) as kernel:
        first = verified_replay(cache, case.identity, case.bars, quality_identity="quality-a")
        assert verified_replay(cache, case.identity, case.bars, quality_identity="quality-a") == first
        assert kernel.call_count == 1
        verified_replay(cache, case.identity, case.bars, quality_identity="quality-b")
        assert kernel.call_count == 2
        changed = (*case.bars[:-1], replace(case.bars[-1], source_bar_sha256="a" * 64))
        verified_replay(cache, case.identity, changed, quality_identity="quality-b")
        assert kernel.call_count == 3


def test_disabled_budget_preserves_numeric_results_and_cancel_does_not_admit(product_cases):
    case = product_cases.closed()
    case = replace(case, identity=build_product_identity("rb", "trend", "1d"))
    expected = replay_strategy(case.identity, case.bars)
    cache = SnapshotCache(enabled=False)
    assert verified_replay(cache, case.identity, case.bars) == expected
    with pytest.raises(NewowComputationCancelled):
        verified_replay(cache, case.identity, case.bars, cancelled=lambda: True)


def test_replay_expires_and_does_not_increase_budget(product_cases):
    case = product_cases.closed()
    case = replace(case, identity=build_product_identity("rb", "trend", "1d"))
    clock = [0.0]
    cache = SnapshotCache(now=lambda: clock[0], ttl_seconds=5, max_entries=2)
    with patch("app.market_data.newow.replay_cache.replay_strategy", wraps=replay_strategy) as kernel:
        verified_replay(cache, case.identity, case.bars)
        clock[0] = 6
        verified_replay(cache, case.identity, case.bars)
        assert kernel.call_count == 2
        assert len(cache._entries) <= 2
        assert cache._bytes <= cache._max_bytes
