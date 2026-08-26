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
    digest_canonical_bars,
    digest_direction_contexts,
)
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
        cutoff_5m=datetime(2026, 8, 3, 2, tzinfo=UTC),
        cutoff_15m=datetime(2026, 8, 3, 2, tzinfo=UTC),
        cutoff_d1=datetime(2026, 8, 2, 7, tzinfo=UTC),
        cutoff_60m=datetime(2026, 8, 2, 7, tzinfo=UTC),
        bars_5m_digest="b" * 64,
        bars_15m_digest="c" * 64,
        direction_context_digest="d" * 64,
        through=SEGMENT_START,
    )


def _projection() -> CachedSubingStrategySegmentProjection:
    return CachedSubingStrategySegmentProjection(
        actions=(),
        episodes=(),
        final_position=SubingStrategyPositionState.FLAT,
        pending_action=False,
    )


def test_cache_hit_requires_exact_identity(tmp_path: Path) -> None:
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)
    identity = _identity()
    projection = _projection()

    cache.write(identity, projection)

    assert cache.read(identity) == projection
    assert cache.read(replace(identity, calibration_id="other")) is None


def test_cache_path_changes_with_lifecycle_formula_version(tmp_path: Path) -> None:
    cache = SubingStrategyCache(tmp_path, root_validator=lambda: tmp_path)
    identity = _identity()

    assert cache.path_for(identity) != cache.path_for(
        replace(identity, lifecycle_formula_version="subing_lifecycle_v2")
    )


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
    payload["schema_version"] = 1
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
