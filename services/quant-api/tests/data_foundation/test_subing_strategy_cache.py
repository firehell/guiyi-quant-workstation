from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.market_data.subing_strategy.cache import (
    CachedSubingStrategySegmentProjection,
    NullSubingStrategyCache,
    SubingStrategyCache,
    SubingStrategyCacheError,
    SubingStrategyCacheIdentity,
    SubingStrategyPerformanceCache,
    SubingStrategyPerformanceCacheIdentity,
    digest_canonical_bars,
    digest_direction_contexts,
    digest_session_windows,
    subing_strategy_performance_cache_identity_sha256,
)
from app.market_data.aggregation import SessionWindow
from app.market_data.subing_strategy.contracts import (
    SubingStrategyActionKind,
    SubingStrategyDirection,
    SubingStrategyEpisode,
    SubingStrategyPositionState,
)
from research.subing_strategy_fixtures import action_fixture, aware_dt
from research.test_subing_strategy_engine import (
    CONTRACT,
    SEGMENT_START,
    _bar,
    _context,
)


def _identity() -> SubingStrategyCacheIdentity:
    return SubingStrategyCacheIdentity(
        strategy_policy_sha256="a" * 64,
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        calibration_id="subing_intraday_v1",
        lifecycle_policy_id="subing_lifecycle_v2_research_v1",
        lifecycle_formula_version="subing_lifecycle_v2_structure_binding_v1",
        daily_watch_projection_version="subing_daily_watch_v2",
        daily_watch_formula_version="subing_ema21_rank1_stitched_raw_v2",
        daily_watch_history_mode="rank1_stitched_raw",
        symbol="jm",
        contract=CONTRACT,
        segment_start_trading_day=SEGMENT_START,
        segment_end_trading_day=SEGMENT_START,
        cutoff_1m=datetime(2026, 8, 3, 2, tzinfo=UTC),
        cutoff_5m=datetime(2026, 8, 3, 2, tzinfo=UTC),
        cutoff_15m=datetime(2026, 8, 3, 2, tzinfo=UTC),
        cutoff_d1=datetime(2026, 8, 2, 7, tzinfo=UTC),
        cutoff_60m=datetime(2026, 8, 2, 7, tzinfo=UTC),
        bars_1m_digest="b" * 64,
        bars_5m_digest="c" * 64,
        bars_15m_digest="d" * 64,
        session_windows_digest="f" * 64,
        direction_context_digest="e" * 64,
        through=SEGMENT_START,
    )


def _projection() -> CachedSubingStrategySegmentProjection:
    return CachedSubingStrategySegmentProjection(
        actions=(),
        episodes=(),
        final_position=SubingStrategyPositionState.FLAT,
        pending_action=False,
    )


def _performance_identity() -> SubingStrategyPerformanceCacheIdentity:
    return SubingStrategyPerformanceCacheIdentity(
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        engine_identity_sha256="0" * 64,
        symbol="jm",
        since=SEGMENT_START,
        through=SEGMENT_START,
        resolved_cutoff=datetime(2026, 8, 3, 7, tzinfo=UTC),
        segment_identity_sha256s=("1" * 64, "2" * 64),
    )


def test_cache_hit_requires_exact_identity(tmp_path: Path) -> None:
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)
    identity = _identity()
    projection = _projection()

    cache.write(identity, projection)

    assert cache.read(identity) == projection
    assert cache.read(replace(identity, calibration_id="other")) is None


def test_performance_cache_identity_changes_with_engine_policy() -> None:
    identity = _performance_identity()

    assert subing_strategy_performance_cache_identity_sha256(identity) != (
        subing_strategy_performance_cache_identity_sha256(
            replace(identity, engine_identity_sha256="f" * 64)
        )
    )


def test_cache_creates_missing_namespace_below_trusted_base(tmp_path: Path) -> None:
    base = tmp_path / "observation"
    base.mkdir(mode=0o700)
    root = base / "cache" / "subing-strategy-v1"
    cache = SubingStrategyCache(
        root,
        root_validator=lambda: root,
        trusted_base_validator=lambda: base,
    )

    cache.write(_identity(), _projection())

    path = cache.path_for(_identity())
    assert path.is_file()
    assert path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert root.stat().st_mode & 0o777 == 0o700


def test_performance_cache_atomically_publishes_and_reads_product_snapshot(
    tmp_path: Path,
) -> None:
    base = tmp_path / "observation"
    base.mkdir(mode=0o700)
    root = base / "cache" / "subing-strategy-v1"
    cache = SubingStrategyPerformanceCache(
        root,
        root_validator=lambda: root,
        trusted_base_validator=lambda: base,
        now=lambda: datetime(2026, 8, 27, 8, tzinfo=UTC),
    )
    payload = {"summary": {"completed": 3}, "episodes": []}

    receipt = cache.publish(_performance_identity(), payload)
    snapshot = cache.read(_performance_identity())

    assert snapshot is not None
    assert snapshot.payload == payload
    assert snapshot.generated_at == datetime(2026, 8, 27, 8, tzinfo=UTC)
    assert snapshot.identity_sha256 == receipt.identity_sha256
    assert snapshot.payload_sha256 == receipt.payload_sha256
    assert receipt.byte_count > 0
    assert cache.path_for(_performance_identity()).stat().st_mode & 0o777 == 0o600


def test_performance_cache_rejects_tampered_product_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    cache = SubingStrategyPerformanceCache(root, root_validator=lambda: root)
    identity = _performance_identity()
    cache.publish(identity, {"summary": {"completed": 3}})
    path = cache.path_for(identity)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["payload"]["summary"]["completed"] = 4
    path.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(SubingStrategyCacheError):
        cache.read(identity)


def test_cache_path_changes_with_lifecycle_formula_version(tmp_path: Path) -> None:
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)
    identity = _identity()

    assert cache.path_for(identity) != cache.path_for(
        replace(identity, lifecycle_formula_version="subing_lifecycle_v2")
    )


def test_cache_path_binds_authoritative_1m_bytes(tmp_path: Path) -> None:
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)
    identity = _identity()

    assert cache.path_for(identity) != cache.path_for(
        replace(identity, bars_1m_digest="f" * 64)
    )


def test_cache_path_binds_authoritative_session_windows(tmp_path: Path) -> None:
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)
    identity = _identity()

    assert cache.path_for(identity) != cache.path_for(
        replace(identity, session_windows_digest="0" * 64)
    )


def test_session_digest_changes_with_bucket_start_identity() -> None:
    first = SessionWindow(aware_dt(9, 0), aware_dt(10, 0))
    shifted = SessionWindow(aware_dt(9, 1), aware_dt(10, 0))

    assert digest_session_windows((first,)) != digest_session_windows((shifted,))


def test_cache_round_trips_actions_and_episodes(tmp_path: Path) -> None:
    entry = action_fixture(kind=SubingStrategyActionKind.OPEN_LONG)
    completed_bar = _bar(1, close="100")
    completed_bar = replace(
        completed_bar,
        bar_end=aware_dt(10, 30),
        trading_day=entry.trading_day,
    )
    episode = SubingStrategyEpisode.from_actions(
        entry_action=entry,
        exit_action=None,
        completed_15m_bars=(completed_bar,),
        latest_reference_price=Decimal("100"),
    )
    projection = CachedSubingStrategySegmentProjection(
        actions=(entry,),
        episodes=(episode,),
        final_position=SubingStrategyPositionState.LONG,
        pending_action=False,
    )
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)

    cache.write(_identity(), projection)

    assert cache.read(_identity()) == projection


def test_previous_cache_schema_is_unavailable(tmp_path: Path) -> None:
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)
    identity = _identity()
    cache.write(identity, _projection())
    path = cache.path_for(identity)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 3
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SubingStrategyCacheError):
        cache.read(identity)


def test_corrupt_cache_is_typed_failure(tmp_path: Path) -> None:
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)
    path = cache.path_for(_identity())
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(SubingStrategyCacheError):
        cache.read(_identity())


def test_cache_rejects_symlink_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "linked"
    root.symlink_to(target, target_is_directory=True)
    cache = SubingStrategyCache(root, root_validator=lambda: root)

    with pytest.raises(SubingStrategyCacheError):
        cache.write(_identity(), _projection())


def test_bar_digest_changes_when_content_changes_without_cutoff() -> None:
    first = _bar(1, close="100")
    changed = _bar(1, close="101", high="105", low="95")

    assert digest_canonical_bars(
        (first,), contract=CONTRACT, segment_start=SEGMENT_START
    ) != digest_canonical_bars(
        (changed,), contract=CONTRACT, segment_start=SEGMENT_START
    )


def test_direction_context_digest_binds_reasons_and_provenance() -> None:
    bar = _bar(1)
    context = _context(bar, SubingStrategyDirection.LONG_ONLY)
    changed = replace(context, reason_codes=("OTHER",))

    assert digest_direction_contexts({bar.trading_day: context}) != (
        digest_direction_contexts({bar.trading_day: changed})
    )


def test_null_cache_always_misses_and_ignores_writes() -> None:
    cache = NullSubingStrategyCache()

    cache.write(_identity(), _projection())

    assert cache.read(_identity()) is None
    assert cache.available is False
