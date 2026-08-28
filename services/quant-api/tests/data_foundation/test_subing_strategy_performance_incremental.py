from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_strategy.contracts import (
    SUBING_STRATEGY_ID,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyEpisodeState,
)
from app.market_data.subing_strategy.performance import (
    SubingStrategyPerformanceProjection,
    summarize_subing_strategy_episodes,
)
from app.market_data.subing_strategy.performance_adoption import (
    SubingStrategyPerformanceFullRebuildRequired,
)
from app.market_data.subing_strategy.performance_incremental import (
    SubingStrategyPerformanceIncrementalRefresher,
)
from app.market_data.subing_strategy.performance_lineage import (
    SubingStrategyPerformanceLineage,
    SubingStrategyPerformanceSemanticIdentity,
    SubingStrategyPerformanceSourceSegment,
)
from app.market_data.subing_strategy.performance_snapshot import (
    SubingStrategyPerformancePrefixCounts,
    SubingStrategyPerformanceSegmentFact,
    subing_strategy_performance_snapshot_from_projection,
)
from app.market_data.subing_strategy.performance_snapshot_store import (
    SubingStrategyPerformanceFileSnapshotStore,
)
from app.market_data.subing_strategy.service import SubingStrategyHistoricalRequest
from research.subing_strategy_fixtures import action_fixture


ENGINE = "e" * 64
PREFIX_SOURCE = "1" * 64
TAIL_SOURCE = "2" * 64
MANIFEST_T1 = "b" * 64
MANIFEST_T2 = "c" * 64


def _episode(change: str) -> SubingStrategyEpisode:
    entry = action_fixture(kind=SubingStrategyActionKind.OPEN_LONG)
    exit_action = replace(
        action_fixture(
            kind=SubingStrategyActionKind.CLOSE_LONG,
            episode_id=entry.episode_id,
        ),
        reason_codes=("EMA21_BREACH_LONG",),
    )
    return SubingStrategyEpisode(
        episode_id=entry.episode_id,
        direction=SubingDirection.LONG,
        entry_action=entry,
        exit_action=exit_action,
        state=SubingStrategyEpisodeState.CLOSED,
        holding_bar_count=4,
        reference_change_percent=Decimal(change),
        current_reference_change_percent=None,
        latest_reference_price=None,
        exit_reason_codes=exit_action.reason_codes,
        structure_exit_available=False,
    )


def _projection(
    *,
    through: date,
    episodes: tuple[SubingStrategyEpisode, ...],
    bar_count_15m: int,
) -> SubingStrategyPerformanceProjection:
    return SubingStrategyPerformanceProjection(
        strategy_id=SUBING_STRATEGY_ID,
        formula_version="subing_strategy_15m_v1",
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        frequency=BarFrequency.M15,
        coverage_since=date(2020, 1, 2),
        coverage_through=through,
        resolved_cutoff=datetime(through.year, through.month, through.day, 7, tzinfo=UTC),
        segment_count=2,
        bar_count_15m=bar_count_15m,
        context_unavailable_count=0,
        cache_state="hit",
        summary=summarize_subing_strategy_episodes(episodes),
        episodes=episodes,
    )


def _segment(
    *,
    contract: str,
    start: date,
    end: date,
    source: str,
) -> SubingStrategyPerformanceSourceSegment:
    return SubingStrategyPerformanceSourceSegment(
        contract=contract,
        effective_start=start,
        effective_end=end,
        source_identity=source,
    )


def _lineage(through: date, *, manifest: str, tail_end: date | None = None):
    tail_end = tail_end or through
    return SubingStrategyPerformanceLineage(
        symbol="jm",
        coverage_since=date(2020, 1, 2),
        coverage_through=through,
        ordered_segments=(
            _segment(
                contract="JM2505",
                start=date(2020, 1, 2),
                end=date(2026, 1, 4),
                source=PREFIX_SOURCE,
            ),
            _segment(
                contract="JM2605",
                start=date(2026, 1, 5),
                end=tail_end,
                source=TAIL_SOURCE,
            ),
        ),
        source_manifest_sha256=manifest,
    )


def _fact(through: date) -> SubingStrategyPerformanceSegmentFact:
    return SubingStrategyPerformanceSegmentFact(
        contract="JM2605",
        effective_start=date(2026, 1, 5),
        effective_end=through,
        loaded_through=through,
        bar_count_1m=500,
        bar_count_5m=100,
        bar_count_15m=12,
        context_unavailable_count=0,
        source_identity=TAIL_SOURCE,
    )


class FakeLineage:
    def __init__(self, mapping: dict[date, SubingStrategyPerformanceLineage]) -> None:
        self.mapping = mapping

    def resolve(self, symbol: str, *, through: date | None = None):
        assert symbol == "jm"
        assert through in self.mapping
        return self.mapping[through]


class FakeHistorical:
    def __init__(self, tail) -> None:
        self.tail = tail
        self.calls: list[tuple[SubingStrategyHistoricalRequest, bool]] = []

    def history(self, request, *, publish_cache: bool = False):
        self.calls.append((request, publish_cache))
        return self.tail


def _identity() -> SubingStrategyPerformanceSemanticIdentity:
    return SubingStrategyPerformanceSemanticIdentity(
        strategy_id=SUBING_STRATEGY_ID,
        formula_version="subing_strategy_15m_v1",
        engine_identity_sha256=ENGINE,
    )


def _store(tmp_path: Path) -> SubingStrategyPerformanceFileSnapshotStore:
    root = tmp_path / "performance"
    root.mkdir()
    return SubingStrategyPerformanceFileSnapshotStore(
        root,
        root_validator=lambda: root,
    )


def _published_snapshot(store, through: date, episodes, *, manifest: str, bars: int):
    snapshot = subing_strategy_performance_snapshot_from_projection(
        _projection(through=through, episodes=episodes, bar_count_15m=bars),
        immutable_prefix_segment_count=1,
        immutable_prefix_counts=SubingStrategyPerformancePrefixCounts(
            bar_count_1m=1000,
            bar_count_5m=200,
            bar_count_15m=12,
            context_unavailable_count=0,
        ),
        segment_facts=(_fact(through),),
        source_manifest_sha256=manifest,
        generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
    )
    store.publish_current(snapshot)
    return snapshot


def test_same_day_refresh_is_hit_with_zero_historical_calls_and_zero_writes(
    tmp_path: Path,
) -> None:
    through = date(2026, 8, 26)
    store = _store(tmp_path)
    episodes = (_episode("2"),)
    snapshot = _published_snapshot(
        store, through, episodes, manifest=MANIFEST_T1, bars=24
    )
    historical = FakeHistorical(object())
    refresher = SubingStrategyPerformanceIncrementalRefresher(
        lineage=FakeLineage({through: _lineage(through, manifest=MANIFEST_T1)}),
        historical=historical,
        store=store,
        identity=_identity(),
        now=lambda: datetime(2026, 8, 27, 9, tzinfo=UTC),
    )
    before = (tmp_path / "performance" / "current" / "jm.json").read_bytes()

    result = refresher.refresh(symbol="jm", through=through)

    assert result.cache_state == "hit"
    assert result.episodes == snapshot.projection.episodes
    assert historical.calls == []
    assert (tmp_path / "performance" / "current" / "jm.json").read_bytes() == before


def test_new_day_replays_only_mutable_tail_and_matches_full_counts(
    tmp_path: Path,
) -> None:
    day1 = date(2026, 8, 26)
    day2 = date(2026, 8, 27)
    store = _store(tmp_path)
    old_tail_episode = _episode("-1")
    new_tail_episode = _episode("3")
    _published_snapshot(
        store,
        day1,
        (old_tail_episode,),
        manifest=MANIFEST_T1,
        bars=24,
    )
    tail = type(
        "Tail",
        (),
        {
            "segment_summaries": (
                type(
                    "Seg",
                    (),
                    {
                        "contract": "JM2605",
                        "start_trading_day": date(2026, 1, 5),
                        "end_trading_day": day2,
                        "loaded_through": day2,
                        "bar_count_1m": 520,
                        "bar_count_5m": 104,
                        "bar_count_15m": 13,
                        "source_identity_sha256": TAIL_SOURCE,
                    },
                )(),
            ),
            "episodes": (new_tail_episode,),
            "context_unavailable": (),
            "resolved_cutoff": datetime(2026, 8, 27, 7, tzinfo=UTC),
        },
    )()
    historical = FakeHistorical(tail)
    refresher = SubingStrategyPerformanceIncrementalRefresher(
        lineage=FakeLineage(
            {
                day1: _lineage(day1, manifest=MANIFEST_T1),
                day2: _lineage(day2, manifest=MANIFEST_T2, tail_end=day2),
            }
        ),
        historical=historical,
        store=store,
        identity=_identity(),
        now=lambda: datetime(2026, 8, 28, 8, tzinfo=UTC),
    )

    result = refresher.refresh(symbol="jm", through=day2)

    assert historical.calls == [
        (
            SubingStrategyHistoricalRequest(
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                symbol="jm",
                frequency=BarFrequency.M15,
                since=date(2026, 1, 5),
                through=day2,
            ),
            True,
        )
    ]
    assert result.coverage_through == day2
    assert result.bar_count_15m == 25
    assert result.episodes == (new_tail_episode,)
    restored = store.read_current(symbol="jm", expected_through=day2)
    assert restored.projection.bar_count_15m == 25


def test_prefix_drift_preserves_previous_manifest(tmp_path: Path) -> None:
    through = date(2026, 8, 26)
    store = _store(tmp_path)
    episodes = (_episode("2"),)
    _published_snapshot(store, through, episodes, manifest=MANIFEST_T1, bars=24)
    before = (tmp_path / "performance" / "current" / "jm.json").read_bytes()
    drifted = replace(
        _lineage(through, manifest="d" * 64),
        ordered_segments=(
            _segment(
                contract="JM9999",
                start=date(2020, 1, 2),
                end=date(2026, 1, 4),
                source="f" * 64,
            ),
            _lineage(through, manifest=MANIFEST_T1).ordered_segments[1],
        ),
    )
    historical = FakeHistorical(object())
    refresher = SubingStrategyPerformanceIncrementalRefresher(
        lineage=FakeLineage({through: drifted}),
        historical=historical,
        store=store,
        identity=_identity(),
        now=lambda: datetime(2026, 8, 27, 9, tzinfo=UTC),
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired):
        refresher.refresh(symbol="jm", through=through)

    assert historical.calls == []
    assert (tmp_path / "performance" / "current" / "jm.json").read_bytes() == before
