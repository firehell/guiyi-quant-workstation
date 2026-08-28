from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_strategy.contracts import (
    SUBING_STRATEGY_ID,
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyEpisodeState,
    SubingStrategyFillBasis,
    SubingStrategyPositionState,
    subing_strategy_action_id,
    subing_strategy_episode_id,
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
    SubingStrategyPerformanceSourceSegment,
)
from app.market_data.subing_strategy.performance_snapshot import (
    SubingStrategyPerformancePrefixCounts,
    SubingStrategyPerformanceSegmentFact,
    SubingStrategyPerformanceSnapshotError,
    subing_strategy_performance_snapshot_from_projection,
)
from app.market_data.subing_strategy.performance_snapshot_store import (
    SubingStrategyPerformanceFileSnapshotStore,
)
from app.market_data.subing_strategy.service import SubingStrategyHistoricalRequest
from app.market_data.subing_lifecycle import ConfirmationSource


ENGINE = "e" * 64
DRIFT_ENGINE = "f" * 64
PREFIX_SOURCE = "1" * 64
TAIL_SOURCE = "2" * 64
NEW_SOURCE = "3" * 64
MANIFEST_T1 = "b" * 64
MANIFEST_T2 = "c" * 64
MANIFEST_T3 = "d" * 64
MANIFEST_T4 = "a" * 64
PREFIX_START = date(2020, 1, 2)
PREFIX_END = date(2026, 1, 4)
TAIL_START = date(2026, 1, 5)


def _episode(change: str) -> SubingStrategyEpisode:
    return _episode_at(
        change=change,
        contract="JM2605",
        segment_start=TAIL_START,
        trading_day=TAIL_START,
        hour=10,
    )


def _episode_at(
    *,
    change: str,
    contract: str,
    segment_start: date,
    trading_day: date,
    hour: int,
    kind: SubingStrategyActionKind = SubingStrategyActionKind.OPEN_LONG,
) -> SubingStrategyEpisode:
    decision_at = datetime(
        trading_day.year, trading_day.month, trading_day.day, hour, 0, tzinfo=UTC
    )
    open_at = datetime(
        trading_day.year, trading_day.month, trading_day.day, hour, 15, tzinfo=UTC
    )
    bar_end = datetime(
        trading_day.year, trading_day.month, trading_day.day, hour, 30, tzinfo=UTC
    )
    close_decision = datetime(
        trading_day.year, trading_day.month, trading_day.day, hour, 45, tzinfo=UTC
    )
    close_open = datetime(
        trading_day.year, trading_day.month, trading_day.day, hour + 1, 0, tzinfo=UTC
    )
    close_end = datetime(
        trading_day.year, trading_day.month, trading_day.day, hour + 1, 15, tzinfo=UTC
    )
    entry = _action(
        kind=kind,
        contract=contract,
        segment_start=segment_start,
        trading_day=trading_day,
        decision_at=decision_at,
        effective_open_at=open_at,
        effective_bar_end=bar_end,
    )
    close_kind = (
        SubingStrategyActionKind.CLOSE_LONG
        if kind is SubingStrategyActionKind.OPEN_LONG
        else SubingStrategyActionKind.CLOSE_SHORT
    )
    exit_action = _action(
        kind=close_kind,
        contract=contract,
        segment_start=segment_start,
        trading_day=trading_day,
        decision_at=close_decision,
        effective_open_at=close_open,
        effective_bar_end=close_end,
        episode_id=entry.episode_id,
    )
    direction = (
        SubingDirection.LONG
        if kind is SubingStrategyActionKind.OPEN_LONG
        else SubingDirection.SHORT
    )
    return SubingStrategyEpisode(
        episode_id=entry.episode_id,
        direction=direction,
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


def _action(
    *,
    kind: SubingStrategyActionKind,
    contract: str,
    segment_start: date,
    trading_day: date,
    decision_at: datetime,
    effective_open_at: datetime | None,
    effective_bar_end: datetime,
    episode_id: str | None = None,
):
    identity = {
        "strategy_id": SUBING_STRATEGY_ID,
        "formula_version": "subing_strategy_15m_v1",
        "symbol": "JM",
        "contract": contract,
        "segment_start_trading_day": segment_start.isoformat(),
        "opportunity_id": "subing-opportunity:test",
        "kind": kind.value,
        "decision_at": decision_at.isoformat(),
        "effective_bar_end": effective_bar_end.isoformat(),
        "fill_basis": SubingStrategyFillBasis.NEXT_BAR_OPEN.value,
    }
    is_open = kind in {
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.OPEN_SHORT,
    }
    return SubingStrategyAction(
        action_id=subing_strategy_action_id(identity),
        episode_id=(
            episode_id
            or (
                subing_strategy_episode_id(identity)
                if is_open
                else "subing-episode:test"
            )
        ),
        strategy_id=SUBING_STRATEGY_ID,
        formula_version="subing_strategy_15m_v1",
        kind=kind,
        symbol="JM",
        contract=contract,
        trading_day=trading_day,
        segment_start_trading_day=segment_start,
        opportunity_id="subing-opportunity:test",
        decision_at=decision_at,
        effective_open_at=effective_open_at,
        effective_bar_end=effective_bar_end,
        reference_price=Decimal("100"),
        fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
        confirmation_source=(ConfirmationSource.FORMAL_V1 if is_open else None),
        reason_codes=(() if is_open else ("EMA21_BREACH_LONG",)),
        direction_context_source_day=(trading_day if is_open else None),
        direction_context_target_day=(trading_day if is_open else None),
        bound_reference_pivot=None,
    )


def _projection(
    *,
    through: date,
    episodes: tuple[SubingStrategyEpisode, ...],
    bar_count_15m: int,
    cache_state: str = "hit",
    context_unavailable_count: int = 0,
    segment_count: int = 2,
) -> SubingStrategyPerformanceProjection:
    return SubingStrategyPerformanceProjection(
        strategy_id=SUBING_STRATEGY_ID,
        formula_version="subing_strategy_15m_v1",
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        frequency=BarFrequency.M15,
        coverage_since=date(2020, 1, 2),
        coverage_through=through,
        resolved_cutoff=datetime(
            through.year, through.month, through.day, 7, tzinfo=UTC
        ),
        segment_count=segment_count,
        bar_count_15m=bar_count_15m,
        context_unavailable_count=context_unavailable_count,
        cache_state=cache_state,  # type: ignore[arg-type]
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
                start=PREFIX_START,
                end=PREFIX_END,
                source=PREFIX_SOURCE,
            ),
            _segment(
                contract="JM2605",
                start=TAIL_START,
                end=tail_end,
                source=TAIL_SOURCE,
            ),
        ),
        source_manifest_sha256=manifest,
    )


def _rollover_lineage(
    through: date,
    *,
    manifest: str,
    old_tail_end: date,
    new_start: date | None = None,
    new_source: str = NEW_SOURCE,
):
    new_start = new_start or through
    return SubingStrategyPerformanceLineage(
        symbol="jm",
        coverage_since=PREFIX_START,
        coverage_through=through,
        ordered_segments=(
            _segment(
                contract="JM2505",
                start=PREFIX_START,
                end=PREFIX_END,
                source=PREFIX_SOURCE,
            ),
            _segment(
                contract="JM2605",
                start=TAIL_START,
                end=old_tail_end,
                source=TAIL_SOURCE,
            ),
            _segment(
                contract="JM2609",
                start=new_start,
                end=through,
                source=new_source,
            ),
        ),
        source_manifest_sha256=manifest,
    )


def _unavailable(*, trading_day: date, contract: str):
    return SimpleNamespace(
        target_trading_day=trading_day,
        physical_contract=contract,
    )


def _fact(
    through: date,
    *,
    contract: str = "JM2605",
    start: date = TAIL_START,
    source: str = TAIL_SOURCE,
    bar_count_1m: int = 500,
    bar_count_5m: int = 100,
    bar_count_15m: int = 12,
) -> SubingStrategyPerformanceSegmentFact:
    return SubingStrategyPerformanceSegmentFact(
        contract=contract,
        effective_start=start,
        effective_end=through,
        loaded_through=through,
        bar_count_1m=bar_count_1m,
        bar_count_5m=bar_count_5m,
        bar_count_15m=bar_count_15m,
        context_unavailable_count=0,
        source_identity=source,
    )


def _tail(
    *,
    summaries: tuple[object, ...],
    episodes: tuple[SubingStrategyEpisode, ...],
    resolved_cutoff: datetime,
    context_unavailable: tuple[object, ...] = (),
    engine_identity_sha256: str = ENGINE,
    actions: tuple[object, ...] | None = None,
):
    return SimpleNamespace(
        segment_summaries=summaries,
        episodes=episodes,
        context_unavailable=context_unavailable,
        resolved_cutoff=resolved_cutoff,
        engine_identity_sha256=engine_identity_sha256,
        actions=actions if actions is not None else _actions_from(episodes),
    )


def _summary(
    *,
    contract: str,
    start: date,
    end: date,
    loaded_through: date,
    source: str,
    bar_count_1m: int,
    bar_count_5m: int,
    bar_count_15m: int,
    initial: SubingStrategyPositionState = SubingStrategyPositionState.FLAT,
    final: SubingStrategyPositionState = SubingStrategyPositionState.FLAT,
    pending_action: bool = False,
):
    return SimpleNamespace(
        contract=contract,
        start_trading_day=start,
        end_trading_day=end,
        loaded_through=loaded_through,
        bar_count_1m=bar_count_1m,
        bar_count_5m=bar_count_5m,
        bar_count_15m=bar_count_15m,
        source_identity_sha256=source,
        initial_position=initial,
        final_position=final,
        pending_action=pending_action,
    )


def _actions_from(episodes: tuple[SubingStrategyEpisode, ...]):
    actions = []
    for episode in episodes:
        actions.append(episode.entry_action)
        if episode.exit_action is not None:
            actions.append(episode.exit_action)
    return tuple(actions)


class FakeLineage:
    def __init__(self, mapping: dict[date, SubingStrategyPerformanceLineage]) -> None:
        self.mapping = mapping

    def resolve(self, symbol: str, *, through: date | None = None):
        assert symbol == "jm"
        assert through in self.mapping
        return self.mapping[through]


class FakeHistorical:
    def __init__(self, tail, *, engine_identity_sha256: str = ENGINE) -> None:
        self.tail = tail
        self.engine_identity_sha256 = engine_identity_sha256
        self.calls: list[tuple[SubingStrategyHistoricalRequest, bool]] = []

    def history(self, request, *, publish_cache: bool = False):
        self.calls.append((request, publish_cache))
        return self.tail


class FakeAdopter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []

    def adopt(self, *, symbol: str, through: date):
        self.calls.append((symbol, through))
        raise AssertionError("adopter must not run")


def _store(tmp_path: Path) -> SubingStrategyPerformanceFileSnapshotStore:
    root = tmp_path / "performance"
    root.mkdir(parents=True, exist_ok=True)
    return SubingStrategyPerformanceFileSnapshotStore(
        root,
        root_validator=lambda: root,
    )


def _published_snapshot(
    store,
    through: date,
    episodes,
    *,
    manifest: str,
    bars: int,
    cache_state: str = "hit",
    prefix_counts: SubingStrategyPerformancePrefixCounts | None = None,
    segment_facts: tuple[SubingStrategyPerformanceSegmentFact, ...] | None = None,
    prefix_segment_count: int = 1,
    engine_identity_sha256: str = ENGINE,
    context_unavailable_count: int = 0,
    segment_count: int = 2,
):
    snapshot = subing_strategy_performance_snapshot_from_projection(
        _projection(
            through=through,
            episodes=episodes,
            bar_count_15m=bars,
            cache_state=cache_state,
            context_unavailable_count=context_unavailable_count,
            segment_count=segment_count,
        ),
        immutable_prefix_segment_count=prefix_segment_count,
        immutable_prefix_counts=prefix_counts
        or SubingStrategyPerformancePrefixCounts(
            bar_count_1m=1000,
            bar_count_5m=200,
            bar_count_15m=12,
            context_unavailable_count=0,
        ),
        segment_facts=segment_facts or (_fact(through),),
        source_manifest_sha256=manifest,
        generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
        engine_identity_sha256=engine_identity_sha256,
    )
    store.publish_current(snapshot)
    return snapshot


def _refresher(*, lineage, historical, store, now, adopter=None):
    return SubingStrategyPerformanceIncrementalRefresher(
        lineage=lineage,
        historical=historical,
        store=store,
        now=now,
        adopter=adopter,
    )


def test_same_day_refresh_is_hit_with_zero_historical_calls_and_zero_writes(
    tmp_path: Path,
) -> None:
    through = date(2026, 8, 26)
    store = _store(tmp_path)
    episodes = (_episode("2"),)
    snapshot = _published_snapshot(
        store,
        through,
        episodes,
        manifest=MANIFEST_T1,
        bars=24,
        cache_state="refreshed",
    )
    historical = FakeHistorical(object())
    refresher = _refresher(
        lineage=FakeLineage({through: _lineage(through, manifest=MANIFEST_T1)}),
        historical=historical,
        store=store,
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
    new_tail_episode = _episode_at(
        change="3",
        contract="JM2605",
        segment_start=TAIL_START,
        trading_day=day2,
        hour=10,
    )
    _published_snapshot(
        store,
        day1,
        (old_tail_episode,),
        manifest=MANIFEST_T1,
        bars=24,
    )
    tail = _tail(
        summaries=(
            _summary(
                contract="JM2605",
                start=TAIL_START,
                end=day2,
                loaded_through=day2,
                source=TAIL_SOURCE,
                bar_count_1m=520,
                bar_count_5m=104,
                bar_count_15m=13,
            ),
        ),
        episodes=(new_tail_episode,),
        resolved_cutoff=datetime(2026, 8, 27, 7, tzinfo=UTC),
    )
    historical = FakeHistorical(tail)
    refresher = _refresher(
        lineage=FakeLineage(
            {
                day1: _lineage(day1, manifest=MANIFEST_T1),
                day2: _lineage(day2, manifest=MANIFEST_T2, tail_end=day2),
            }
        ),
        historical=historical,
        store=store,
        now=lambda: datetime(2026, 8, 28, 8, tzinfo=UTC),
    )

    result = refresher.refresh(symbol="jm", through=day2)

    assert historical.calls == [
        (
            SubingStrategyHistoricalRequest(
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                symbol="jm",
                frequency=BarFrequency.M15,
                since=TAIL_START,
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
    assert restored.segment_facts[0].bar_count_15m == 13


def test_merged_incremental_equals_independent_full_replay_fields(
    tmp_path: Path,
) -> None:
    day1 = date(2026, 8, 26)
    day2 = date(2026, 8, 27)
    store = _store(tmp_path)
    prefix_episode = _episode_at(
        change="2",
        contract="JM2505",
        segment_start=PREFIX_START,
        trading_day=date(2025, 6, 2),
        hour=10,
    )
    old_tail_episode = _episode("-1")
    new_tail_episode = _episode_at(
        change="3",
        contract="JM2605",
        segment_start=TAIL_START,
        trading_day=day2,
        hour=11,
    )
    _published_snapshot(
        store,
        day1,
        (prefix_episode, old_tail_episode),
        manifest=MANIFEST_T1,
        bars=24,
    )
    cutoff = datetime(2026, 8, 27, 7, tzinfo=UTC)
    unavailable = (object(),)
    tail = _tail(
        summaries=(
            _summary(
                contract="JM2605",
                start=TAIL_START,
                end=day2,
                loaded_through=day2,
                source=TAIL_SOURCE,
                bar_count_1m=520,
                bar_count_5m=104,
                bar_count_15m=13,
            ),
        ),
        episodes=(new_tail_episode,),
        resolved_cutoff=cutoff,
        context_unavailable=unavailable,
    )
    independent_episodes = (prefix_episode, new_tail_episode)
    independent = _projection(
        through=day2,
        episodes=independent_episodes,
        bar_count_15m=25,
        context_unavailable_count=1,
        cache_state="refreshed",
    )
    historical = FakeHistorical(tail)
    refresher = _refresher(
        lineage=FakeLineage(
            {
                day1: _lineage(day1, manifest=MANIFEST_T1),
                day2: _lineage(day2, manifest=MANIFEST_T2, tail_end=day2),
            }
        ),
        historical=historical,
        store=store,
        now=lambda: datetime(2026, 8, 28, 8, tzinfo=UTC),
    )

    result = refresher.refresh(symbol="jm", through=day2)

    assert result.episodes == independent.episodes
    assert _actions_from(result.episodes) == _actions_from(independent.episodes)
    assert result.summary == independent.summary
    assert result.summary == summarize_subing_strategy_episodes(independent_episodes)
    assert result.bar_count_15m == independent.bar_count_15m
    assert result.context_unavailable_count == independent.context_unavailable_count
    assert result.resolved_cutoff == cutoff
    restored = store.read_current(symbol="jm", expected_through=day2)
    assert restored.source_manifest_sha256 == MANIFEST_T2
    assert restored.segment_facts[0].source_identity == TAIL_SOURCE


def test_duplicate_out_of_order_cross_contract_or_mismatched_episodes_fail_closed(
    tmp_path: Path,
) -> None:
    day1 = date(2026, 8, 26)
    day2 = date(2026, 8, 27)
    valid = _episode_at(
        change="3",
        contract="JM2605",
        segment_start=TAIL_START,
        trading_day=day2,
        hour=10,
    )
    later = _episode_at(
        change="4",
        contract="JM2605",
        segment_start=TAIL_START,
        trading_day=day2,
        hour=12,
    )
    cross = _episode_at(
        change="5",
        contract="JM9999",
        segment_start=TAIL_START,
        trading_day=day2,
        hour=10,
    )
    mismatched = replace(valid, episode_id="subing-episode:mismatched")
    cases = ((valid, valid), (later, valid), (cross,), (mismatched,))
    for index, episodes in enumerate(cases):
        local_store = _store(tmp_path / str(index))
        _published_snapshot(
            local_store, day1, (_episode("-1"),), manifest=MANIFEST_T1, bars=24
        )
        before = (
            tmp_path / str(index) / "performance" / "current" / "jm.json"
        ).read_bytes()
        tail = _tail(
            summaries=(
                _summary(
                    contract="JM2605",
                    start=TAIL_START,
                    end=day2,
                    loaded_through=day2,
                    source=TAIL_SOURCE,
                    bar_count_1m=520,
                    bar_count_5m=104,
                    bar_count_15m=13,
                ),
            ),
            episodes=episodes,
            resolved_cutoff=datetime(2026, 8, 27, 7, tzinfo=UTC),
        )
        historical = FakeHistorical(tail)
        refresher = _refresher(
            lineage=FakeLineage(
                {
                    day1: _lineage(day1, manifest=MANIFEST_T1),
                    day2: _lineage(day2, manifest=MANIFEST_T2, tail_end=day2),
                }
            ),
            historical=historical,
            store=local_store,
            now=lambda: datetime(2026, 8, 28, 8, tzinfo=UTC),
        )
        with pytest.raises(SubingStrategyPerformanceFullRebuildRequired):
            refresher.refresh(symbol="jm", through=day2)
        assert (
            tmp_path / str(index) / "performance" / "current" / "jm.json"
        ).read_bytes() == before


def test_rollover_replays_old_tail_and_compacts_closed_segment_into_prefix(
    tmp_path: Path,
) -> None:
    day1 = date(2026, 8, 26)
    day2 = date(2026, 8, 27)
    store = _store(tmp_path)
    prefix_episode = _episode_at(
        change="2",
        contract="JM2505",
        segment_start=PREFIX_START,
        trading_day=date(2025, 6, 2),
        hour=10,
    )
    old_tail_episode = _episode("-1")
    closed_old_tail = _episode_at(
        change="-1",
        contract="JM2605",
        segment_start=TAIL_START,
        trading_day=day1,
        hour=10,
    )
    new_segment_episode = _episode_at(
        change="4",
        contract="JM2609",
        segment_start=day2,
        trading_day=day2,
        hour=11,
    )
    _published_snapshot(
        store,
        day1,
        (prefix_episode, old_tail_episode),
        manifest=MANIFEST_T1,
        bars=24,
    )
    tail = _tail(
        summaries=(
            _summary(
                contract="JM2605",
                start=TAIL_START,
                end=day1,
                loaded_through=day1,
                source=TAIL_SOURCE,
                bar_count_1m=520,
                bar_count_5m=104,
                bar_count_15m=13,
                final=SubingStrategyPositionState.FLAT,
                pending_action=False,
            ),
            _summary(
                contract="JM2609",
                start=day2,
                end=day2,
                loaded_through=day2,
                source=NEW_SOURCE,
                bar_count_1m=40,
                bar_count_5m=8,
                bar_count_15m=4,
                initial=SubingStrategyPositionState.FLAT,
                pending_action=False,
            ),
        ),
        episodes=(closed_old_tail, new_segment_episode),
        resolved_cutoff=datetime(2026, 8, 27, 7, tzinfo=UTC),
    )
    historical = FakeHistorical(tail)
    refresher = _refresher(
        lineage=FakeLineage(
            {
                day1: _lineage(day1, manifest=MANIFEST_T1),
                day2: _rollover_lineage(day2, manifest=MANIFEST_T3, old_tail_end=day1),
            }
        ),
        historical=historical,
        store=store,
        now=lambda: datetime(2026, 8, 28, 8, tzinfo=UTC),
    )

    result = refresher.refresh(symbol="jm", through=day2)

    assert historical.calls == [
        (
            SubingStrategyHistoricalRequest(
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                symbol="jm",
                frequency=BarFrequency.M15,
                since=TAIL_START,
                through=day2,
            ),
            True,
        )
    ]
    assert result.episodes == (prefix_episode, closed_old_tail, new_segment_episode)
    assert result.bar_count_15m == 29
    restored = store.read_current(symbol="jm", expected_through=day2)
    assert restored.immutable_prefix_segment_count == 2
    assert restored.immutable_prefix_counts.bar_count_15m == 25
    assert restored.immutable_prefix_counts.bar_count_1m == 1520
    assert restored.immutable_prefix_counts.bar_count_5m == 304
    assert len(restored.segment_facts) == 1
    assert restored.segment_facts[0].contract == "JM2609"
    assert restored.segment_facts[0].bar_count_15m == 4
    assert restored.projection.bar_count_15m == 29


def test_engine_drift_preserves_previous_manifest(tmp_path: Path) -> None:
    through = date(2026, 8, 26)
    store = _store(tmp_path)
    _published_snapshot(store, through, (_episode("2"),), manifest=MANIFEST_T1, bars=24)
    before = (tmp_path / "performance" / "current" / "jm.json").read_bytes()
    historical = FakeHistorical(object(), engine_identity_sha256=DRIFT_ENGINE)
    refresher = _refresher(
        lineage=FakeLineage({through: _lineage(through, manifest=MANIFEST_T1)}),
        historical=historical,
        store=store,
        now=lambda: datetime(2026, 8, 27, 9, tzinfo=UTC),
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired):
        refresher.refresh(symbol="jm", through=through)

    assert historical.calls == []
    assert (tmp_path / "performance" / "current" / "jm.json").read_bytes() == before


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
    refresher = _refresher(
        lineage=FakeLineage({through: drifted}),
        historical=historical,
        store=store,
        now=lambda: datetime(2026, 8, 27, 9, tzinfo=UTC),
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired):
        refresher.refresh(symbol="jm", through=through)

    assert historical.calls == []
    assert (tmp_path / "performance" / "current" / "jm.json").read_bytes() == before


def test_coverage_regression_preserves_previous_manifest(tmp_path: Path) -> None:
    day1 = date(2026, 8, 26)
    earlier = date(2026, 8, 25)
    store = _store(tmp_path)
    _published_snapshot(store, day1, (_episode("2"),), manifest=MANIFEST_T1, bars=24)
    before = (tmp_path / "performance" / "current" / "jm.json").read_bytes()
    historical = FakeHistorical(object())
    refresher = _refresher(
        lineage=FakeLineage(
            {
                day1: _lineage(day1, manifest=MANIFEST_T1),
                earlier: _lineage(earlier, manifest=MANIFEST_T2, tail_end=earlier),
            }
        ),
        historical=historical,
        store=store,
        now=lambda: datetime(2026, 8, 27, 9, tzinfo=UTC),
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired):
        refresher.refresh(symbol="jm", through=earlier)

    assert historical.calls == []
    assert (tmp_path / "performance" / "current" / "jm.json").read_bytes() == before


def test_incomplete_tail_preserves_previous_manifest(tmp_path: Path) -> None:
    day1 = date(2026, 8, 26)
    day2 = date(2026, 8, 27)
    store = _store(tmp_path)
    _published_snapshot(store, day1, (_episode("-1"),), manifest=MANIFEST_T1, bars=24)
    before = (tmp_path / "performance" / "current" / "jm.json").read_bytes()
    tail = _tail(
        summaries=(
            _summary(
                contract="JM2605",
                start=TAIL_START,
                end=day1,
                loaded_through=day1,
                source=TAIL_SOURCE,
                bar_count_1m=520,
                bar_count_5m=104,
                bar_count_15m=13,
            ),
        ),
        episodes=(_episode("3"),),
        resolved_cutoff=datetime(2026, 8, 26, 7, tzinfo=UTC),
    )
    historical = FakeHistorical(tail)
    refresher = _refresher(
        lineage=FakeLineage(
            {
                day1: _lineage(day1, manifest=MANIFEST_T1),
                day2: _lineage(day2, manifest=MANIFEST_T2, tail_end=day2),
            }
        ),
        historical=historical,
        store=store,
        now=lambda: datetime(2026, 8, 28, 8, tzinfo=UTC),
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired):
        refresher.refresh(symbol="jm", through=day2)

    assert (tmp_path / "performance" / "current" / "jm.json").read_bytes() == before


def test_corrupt_current_snapshot_preserves_previous_manifest_and_does_not_adopt(
    tmp_path: Path,
) -> None:
    through = date(2026, 8, 26)
    store = _store(tmp_path)
    _published_snapshot(store, through, (_episode("2"),), manifest=MANIFEST_T1, bars=24)
    manifest_path = tmp_path / "performance" / "current" / "jm.json"
    before = manifest_path.read_bytes()
    payload_path = tmp_path / "performance" / "snapshots" / "jm" / through.isoformat()
    snapshot_file = next(payload_path.iterdir())
    snapshot_file.write_bytes(b"{not-json")
    snapshot_file.chmod(0o600)
    historical = FakeHistorical(object())
    adopter = FakeAdopter()
    refresher = _refresher(
        lineage=FakeLineage({through: _lineage(through, manifest=MANIFEST_T1)}),
        historical=historical,
        store=store,
        now=lambda: datetime(2026, 8, 27, 9, tzinfo=UTC),
        adopter=adopter,
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired):
        refresher.refresh(symbol="jm", through=through)

    assert adopter.calls == []
    assert historical.calls == []
    assert manifest_path.read_bytes() == before


def test_publication_failure_preserves_previous_current(tmp_path: Path) -> None:
    day1 = date(2026, 8, 26)
    day2 = date(2026, 8, 27)
    inner = _store(tmp_path)
    _published_snapshot(inner, day1, (_episode("-1"),), manifest=MANIFEST_T1, bars=24)
    before = (tmp_path / "performance" / "current" / "jm.json").read_bytes()

    class _FailingStore:
        def read_current(self, **kwargs):
            return inner.read_current(**kwargs)

        def read_current_for_refresh(self, **kwargs):
            return inner.read_current_for_refresh(**kwargs)

        def publish_current(self, snapshot):
            raise SubingStrategyPerformanceSnapshotError()

    tail = _tail(
        summaries=(
            _summary(
                contract="JM2605",
                start=TAIL_START,
                end=day2,
                loaded_through=day2,
                source=TAIL_SOURCE,
                bar_count_1m=520,
                bar_count_5m=104,
                bar_count_15m=13,
            ),
        ),
        episodes=(
            _episode_at(
                change="3",
                contract="JM2605",
                segment_start=TAIL_START,
                trading_day=day2,
                hour=10,
            ),
        ),
        resolved_cutoff=datetime(2026, 8, 27, 7, tzinfo=UTC),
    )
    historical = FakeHistorical(tail)
    refresher = _refresher(
        lineage=FakeLineage(
            {
                day1: _lineage(day1, manifest=MANIFEST_T1),
                day2: _lineage(day2, manifest=MANIFEST_T2, tail_end=day2),
            }
        ),
        historical=historical,
        store=_FailingStore(),
        now=lambda: datetime(2026, 8, 28, 8, tzinfo=UTC),
    )

    with pytest.raises(SubingStrategyPerformanceSnapshotError):
        refresher.refresh(symbol="jm", through=day2)

    assert (tmp_path / "performance" / "current" / "jm.json").read_bytes() == before


def test_rollover_non_flat_or_pending_cross_segment_action_fails_closed(
    tmp_path: Path,
) -> None:
    day1 = date(2026, 8, 26)
    day2 = date(2026, 8, 27)
    store = _store(tmp_path)
    _published_snapshot(store, day1, (_episode("-1"),), manifest=MANIFEST_T1, bars=24)
    before = (tmp_path / "performance" / "current" / "jm.json").read_bytes()
    tail = _tail(
        summaries=(
            _summary(
                contract="JM2605",
                start=TAIL_START,
                end=day1,
                loaded_through=day1,
                source=TAIL_SOURCE,
                bar_count_1m=520,
                bar_count_5m=104,
                bar_count_15m=13,
                final=SubingStrategyPositionState.LONG,
                pending_action=True,
            ),
            _summary(
                contract="JM2609",
                start=day2,
                end=day2,
                loaded_through=day2,
                source=NEW_SOURCE,
                bar_count_1m=40,
                bar_count_5m=8,
                bar_count_15m=4,
                initial=SubingStrategyPositionState.LONG,
            ),
        ),
        episodes=(_episode("-1"),),
        resolved_cutoff=datetime(2026, 8, 27, 7, tzinfo=UTC),
    )
    historical = FakeHistorical(tail)
    refresher = _refresher(
        lineage=FakeLineage(
            {
                day1: _lineage(day1, manifest=MANIFEST_T1),
                day2: _rollover_lineage(day2, manifest=MANIFEST_T3, old_tail_end=day1),
            }
        ),
        historical=historical,
        store=store,
        now=lambda: datetime(2026, 8, 28, 8, tzinfo=UTC),
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired):
        refresher.refresh(symbol="jm", through=day2)

    assert (tmp_path / "performance" / "current" / "jm.json").read_bytes() == before


def test_unknown_snapshot_episode_neither_prefix_nor_tail_fails_closed(
    tmp_path: Path,
) -> None:
    day1 = date(2026, 8, 26)
    day2 = date(2026, 8, 27)
    store = _store(tmp_path)
    prefix_episode = _episode_at(
        change="2",
        contract="JM2505",
        segment_start=PREFIX_START,
        trading_day=date(2025, 6, 2),
        hour=10,
    )
    old_tail_episode = _episode("-1")
    unknown_episode = _episode_at(
        change="9",
        contract="JM9999",
        segment_start=date(2024, 6, 1),
        trading_day=date(2024, 6, 2),
        hour=10,
    )
    _published_snapshot(
        store,
        day1,
        (prefix_episode, old_tail_episode, unknown_episode),
        manifest=MANIFEST_T1,
        bars=24,
    )
    before = (tmp_path / "performance" / "current" / "jm.json").read_bytes()
    tail = _tail(
        summaries=(
            _summary(
                contract="JM2605",
                start=TAIL_START,
                end=day2,
                loaded_through=day2,
                source=TAIL_SOURCE,
                bar_count_1m=520,
                bar_count_5m=104,
                bar_count_15m=13,
            ),
        ),
        episodes=(
            _episode_at(
                change="3",
                contract="JM2605",
                segment_start=TAIL_START,
                trading_day=day2,
                hour=10,
            ),
        ),
        resolved_cutoff=datetime(2026, 8, 27, 7, tzinfo=UTC),
    )
    historical = FakeHistorical(tail)
    refresher = _refresher(
        lineage=FakeLineage(
            {
                day1: _lineage(day1, manifest=MANIFEST_T1),
                day2: _lineage(day2, manifest=MANIFEST_T2, tail_end=day2),
            }
        ),
        historical=historical,
        store=store,
        now=lambda: datetime(2026, 8, 28, 8, tzinfo=UTC),
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired):
        refresher.refresh(symbol="jm", through=day2)

    assert (tmp_path / "performance" / "current" / "jm.json").read_bytes() == before


def test_rollover_compact_folds_closed_tail_unavailable_and_next_append_keeps_it(
    tmp_path: Path,
) -> None:
    day1 = date(2026, 8, 26)
    day2 = date(2026, 8, 27)
    day3 = date(2026, 8, 28)
    store = _store(tmp_path)
    prefix_episode = _episode_at(
        change="2",
        contract="JM2505",
        segment_start=PREFIX_START,
        trading_day=date(2025, 6, 2),
        hour=10,
    )
    old_tail_episode = _episode("-1")
    closed_old_tail = _episode_at(
        change="-1",
        contract="JM2605",
        segment_start=TAIL_START,
        trading_day=day1,
        hour=10,
    )
    new_segment_episode = _episode_at(
        change="4",
        contract="JM2609",
        segment_start=day2,
        trading_day=day2,
        hour=11,
    )
    next_segment_episode = _episode_at(
        change="5",
        contract="JM2609",
        segment_start=day2,
        trading_day=day3,
        hour=11,
    )
    _published_snapshot(
        store,
        day1,
        (prefix_episode, old_tail_episode),
        manifest=MANIFEST_T1,
        bars=24,
    )
    closed_unavailable = (
        _unavailable(trading_day=day1, contract="JM2605"),
        _unavailable(trading_day=date(2026, 8, 25), contract="JM2605"),
    )
    new_unavailable = (_unavailable(trading_day=day2, contract="JM2609"),)
    rollover_tail = _tail(
        summaries=(
            _summary(
                contract="JM2605",
                start=TAIL_START,
                end=day1,
                loaded_through=day1,
                source=TAIL_SOURCE,
                bar_count_1m=520,
                bar_count_5m=104,
                bar_count_15m=13,
                final=SubingStrategyPositionState.FLAT,
                pending_action=False,
            ),
            _summary(
                contract="JM2609",
                start=day2,
                end=day2,
                loaded_through=day2,
                source=NEW_SOURCE,
                bar_count_1m=40,
                bar_count_5m=8,
                bar_count_15m=4,
                initial=SubingStrategyPositionState.FLAT,
                pending_action=False,
            ),
        ),
        episodes=(closed_old_tail, new_segment_episode),
        resolved_cutoff=datetime(2026, 8, 27, 7, tzinfo=UTC),
        context_unavailable=closed_unavailable + new_unavailable,
    )
    rollover = _refresher(
        lineage=FakeLineage(
            {
                day1: _lineage(day1, manifest=MANIFEST_T1),
                day2: _rollover_lineage(day2, manifest=MANIFEST_T3, old_tail_end=day1),
            }
        ),
        historical=FakeHistorical(rollover_tail),
        store=store,
        now=lambda: datetime(2026, 8, 28, 8, tzinfo=UTC),
    )

    rollover.refresh(symbol="jm", through=day2)

    compacted = store.read_current(symbol="jm", expected_through=day2)
    assert compacted.immutable_prefix_counts.context_unavailable_count == 2
    assert compacted.segment_facts[0].contract == "JM2609"
    assert compacted.segment_facts[0].context_unavailable_count == 1
    assert compacted.projection.context_unavailable_count == 3

    next_tail = _tail(
        summaries=(
            _summary(
                contract="JM2609",
                start=day2,
                end=day3,
                loaded_through=day3,
                source=NEW_SOURCE,
                bar_count_1m=48,
                bar_count_5m=10,
                bar_count_15m=5,
                initial=SubingStrategyPositionState.FLAT,
                pending_action=False,
            ),
        ),
        episodes=(next_segment_episode,),
        resolved_cutoff=datetime(2026, 8, 28, 7, tzinfo=UTC),
        context_unavailable=(_unavailable(trading_day=day3, contract="JM2609"),),
    )
    next_append = _refresher(
        lineage=FakeLineage(
            {
                day2: _rollover_lineage(day2, manifest=MANIFEST_T3, old_tail_end=day1),
                day3: _rollover_lineage(
                    day3,
                    manifest=MANIFEST_T4,
                    old_tail_end=day1,
                    new_start=day2,
                ),
            }
        ),
        historical=FakeHistorical(next_tail),
        store=store,
        now=lambda: datetime(2026, 8, 29, 8, tzinfo=UTC),
    )

    next_append.refresh(symbol="jm", through=day3)

    restored = store.read_current(symbol="jm", expected_through=day3)
    assert restored.immutable_prefix_counts.context_unavailable_count == 2
    assert restored.segment_facts[0].context_unavailable_count == 1
    assert restored.projection.context_unavailable_count == 3
