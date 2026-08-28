from __future__ import annotations

from datetime import date
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.market_data.actual_dominant_research import (
    ActualDominantStitchedResearchLoader,
)
from app.market_data.composition import (
    build_historical_data_manager,
    build_metadata_synchronizer,
    build_market_data_service,
    build_subing_daily_watch_current_service,
    build_subing_daily_watch_generator,
    build_subing_strategy_performance_service,
    build_subing_strategy_historical_service,
    canonical_root,
)
from app.market_data.metadata import MetadataSynchronizer
from app.market_data.subing_daily_watch_store import (
    PathMountInspector,
    SubingDailyWatchStoreError,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _sixty_products() -> tuple[str, ...]:
    return tuple(
        f"{chr(ord('a') + index // 26)}{chr(ord('a') + index % 26)}"
        for index in range(60)
    )


def test_historical_manager_uses_configured_canonical_root(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "canonical"
    root.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(root))
    session = _session()

    manager = build_historical_data_manager(session)

    assert manager.store.root == root.resolve()
    assert canonical_root() == root.resolve()
    session.close()


def test_market_data_service_uses_configured_canonical_root(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "canonical"
    root.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(root))
    session = _session()

    service = build_market_data_service(session)

    assert service.catalog.canonical_root == root.resolve()
    assert service.store.root == root.resolve()
    session.close()


def test_metadata_synchronizer_uses_existing_composition_boundary(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "canonical"
    root.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(root))
    session = _session()

    synchronizer = build_metadata_synchronizer(session)

    assert isinstance(synchronizer, MetadataSynchronizer)
    assert synchronizer.catalog.session is session
    session.close()


def test_subing_daily_watch_generator_uses_stitched_loader_and_v2_root(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches Daily Watch composition reusing V1 loader or the base Store root."""
    products = _sixty_products()
    base = (tmp_path / "observations").resolve()
    changed_base = (tmp_path / "changed-observations").resolve()
    base.mkdir()
    changed_base.mkdir()
    resolved = {"base": base}
    resolve_calls: list[tuple[object, object]] = []

    def resolve_root(*, environ, inspector):
        resolve_calls.append((environ, inspector))
        return resolved["base"]

    market_data = SimpleNamespace(
        list_latest_dominants=lambda: tuple(
            SimpleNamespace(
                symbol=symbol,
                product_name=f"Product {symbol.upper()}",
                sector="test-sector",
            )
            for symbol in products
        )
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_active_products",
        lambda: products,
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_operational_products",
        lambda: products,
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: market_data,
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        resolve_root,
    )

    generator = build_subing_daily_watch_generator(object())

    assert isinstance(
        generator.builder._projector._stitched_loader,
        ActualDominantStitchedResearchLoader,
    )
    assert generator._store._root == base / "v2"
    generator._store._revalidate_root()
    assert resolve_calls
    assert all(
        environ is os.environ and isinstance(inspector, PathMountInspector)
        for environ, inspector in resolve_calls
    )

    resolved["base"] = changed_base
    with pytest.raises(SubingDailyWatchStoreError) as raised:
        generator._store._revalidate_root()

    assert raised.value.code == "OBSERVATION_ROOT_UNAVAILABLE"


def test_subing_daily_watch_current_service_reads_only_v2_root(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches current reads lacking exact V2 root identity revalidation."""
    products = _sixty_products()
    base = (tmp_path / "observations").resolve()
    changed_base = (tmp_path / "changed-observations").resolve()
    base.mkdir()
    changed_base.mkdir()
    resolved = {"base": base}
    monkeypatch.setattr(
        "app.market_data.composition.load_active_products",
        lambda: products,
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_operational_products",
        lambda: products,
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        lambda *, environ, inspector: resolved["base"],
    )

    service = build_subing_daily_watch_current_service(object())
    store = service._store_factory()

    assert store._root == base / "v2"
    assert store.read_current() is None
    assert not (base / "v2").exists()

    resolved["base"] = changed_base
    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.read_current()

    assert raised.value.code == "OBSERVATION_ROOT_UNAVAILABLE"


def test_subing_strategy_cache_is_sibling_of_daily_watch_v2(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = (tmp_path / "observations").resolve()
    base.mkdir()
    market_data = SimpleNamespace(
        list_latest_dominants=lambda: (
            SimpleNamespace(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                dominant_mapping_date=date(2026, 8, 25),
            ),
        )
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_active_products",
        lambda: ("jm",),
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: market_data,
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        lambda *, environ, inspector: base,
    )

    service = build_subing_strategy_historical_service(object())

    assert service._cache._root == base / "cache" / "subing-strategy-v1"
    assert service._cache._root.parent != base / "v2"
    assert isinstance(
        service._direction_context_resolver._projector._stitched_loader,
        ActualDominantStitchedResearchLoader,
    )


def test_subing_strategy_performance_uses_effective_history_floor_for_context(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = (tmp_path / "observations").resolve()
    base.mkdir()
    market_data = SimpleNamespace(
        list_latest_dominants=lambda: (
            SimpleNamespace(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                dominant_mapping_date=date(2026, 8, 25),
            ),
        )
    )

    class Coverage:
        product_start_calls = 0

        def __init__(self, session, starts, *, history_floor_path, now=None) -> None:
            pass

        def product_start(self, symbol: str) -> date:
            assert symbol == "jm"
            type(self).product_start_calls += 1
            assert type(self).product_start_calls == 1
            return date(2024, 1, 2)

        def latest_complete_day(self, symbols: tuple[str, ...]) -> date:
            return date(2026, 8, 26)

    monkeypatch.setattr(
        "app.market_data.composition.load_active_products",
        lambda: ("jm",),
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: market_data,
    )
    monkeypatch.setattr(
        "app.market_data.coverage_source.DatabaseCoverageSource",
        Coverage,
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        lambda *, environ, inspector: base,
    )

    service = build_subing_strategy_performance_service(object())

    assert service._performance_cache._root == base / "cache" / "subing-strategy-v1"
    assert service.plan().windows[0].through == date(2026, 8, 25)

    resolver = service._historical._direction_context_resolver
    resolver._previous_trading_day = lambda target: date(2023, 12, 29)
    projector_calls: list[tuple[str, date]] = []
    resolver._projector = SimpleNamespace(
        project=lambda symbol, *, source_trading_day: projector_calls.append(
            (symbol, source_trading_day)
        )
    )

    contexts = resolver.resolve(
        "jm",
        (date(2024, 1, 2), date(2024, 1, 3)),
    )

    assert all(context.direction.value == "unavailable" for context in contexts.values())
    assert all(
        context.reason_codes == ("PREVIOUS_TRADING_DAY_UNAVAILABLE",)
        for context in contexts.values()
    )
    assert projector_calls == []


def test_lineage_resolver_builder_uses_catalog_adapter_without_historical(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from app.market_data.catalog import CatalogPartition
    from app.market_data.composition import (
        build_subing_strategy_performance_lineage_resolver,
    )
    from app.market_data.domain import DatasetKey, ResolvedContractSegment
    from app.market_data.subing_strategy.performance_lineage import (
        CatalogSubingStrategyPerformanceLineageResolver,
    )

    root = tmp_path / "canonical"
    root.mkdir()
    historical_calls: list[object] = []
    query_calls: list[object] = []

    class Coverage:
        def __init__(self, session, starts, *, history_floor_path, now=None) -> None:
            del session, starts, history_floor_path, now

        def product_start(self, symbol: str) -> date:
            assert symbol == "jm"
            return date(2025, 1, 2)

        def latest_complete_day(self, products: tuple[str, ...]) -> date:
            assert products == ("jm",)
            return date(2025, 1, 8)

    class MarketData:
        def __init__(self) -> None:
            self.catalog = SimpleNamespace(
                canonical_root=root.resolve(),
                main_map_before=lambda symbol, before: (
                    SimpleNamespace(trade_date=date(2025, 1, 8)),
                ),
                main_map=lambda symbol, start, end: (
                    SimpleNamespace(trade_date=date(2025, 1, 2), contract="JM2505"),
                    SimpleNamespace(trade_date=date(2025, 1, 8), contract="JM2505"),
                ),
                partitions=self._partitions,
            )
            self.store = SimpleNamespace(
                read_month=lambda *args, **kwargs: (_ for _ in ()).throw(
                    AssertionError("Canonical Bar read")
                )
            )

        def actual_dominant_segments(self, symbol, since, through):
            assert symbol == "jm"
            assert since == date(2025, 1, 2)
            assert through == date(2025, 1, 8)
            return (
                ResolvedContractSegment("JM2505", date(2025, 1, 2), date(2025, 1, 8)),
            )

        def query(self, request):
            query_calls.append(request)
            raise AssertionError("Canonical query invoked")

        def query_actual_dominant_trading_days(self, request):
            query_calls.append(request)
            raise AssertionError("Canonical actual-dominant read invoked")

        def _partitions(self, key: DatasetKey, start, end):
            relative = key.relative_root / "year=2025/month=01/part.parquet"
            path = (root.resolve() / relative).resolve()
            return (
                CatalogPartition(
                    dataset=key,
                    year=2025,
                    month=1,
                    coverage_start=datetime(2025, 1, 1, tzinfo=UTC),
                    coverage_end=datetime(2025, 1, 31, tzinfo=UTC),
                    file_path=path,
                    row_count=4,
                ),
            )

    monkeypatch.setattr(
        "app.market_data.composition.build_subing_strategy_historical_service",
        lambda *args, **kwargs: historical_calls.append((args, kwargs)) or None,
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: MarketData(),
    )
    monkeypatch.setattr(
        "app.market_data.coverage_source.DatabaseCoverageSource",
        Coverage,
    )

    session = _session()
    resolver = build_subing_strategy_performance_lineage_resolver(session)
    lineage = resolver.resolve("jm")

    assert historical_calls == []
    assert query_calls == []
    assert isinstance(resolver, CatalogSubingStrategyPerformanceLineageResolver)
    assert lineage.symbol == "jm"
    assert lineage.coverage_through == date(2025, 1, 8)
    assert lineage.ordered_segments[0].contract == "JM2505"
    session.close()


def test_snapshot_query_builder_does_not_construct_historical(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from app.market_data.composition import (
        build_subing_strategy_performance_snapshot_query,
    )
    from app.market_data.subing_strategy.performance import (
        SubingStrategyPerformanceProjection,
        SubingStrategyPerformanceStats,
        SubingStrategyPerformanceSummary,
    )
    from app.market_data.subing_strategy.performance_snapshot import (
        SubingStrategyPerformancePrefixCounts,
        SubingStrategyPerformanceSegmentFact,
        subing_strategy_performance_snapshot_from_projection,
    )
    from app.market_data.subing_strategy.performance_snapshot_store import (
        SubingStrategyPerformanceFileSnapshotStore,
    )
    from app.market_data.domain import BarFrequency, SeriesKind

    base = (tmp_path / "observations").resolve()
    base.mkdir()
    performance_root = base / "cache" / "subing-strategy-v1" / "performance"
    historical_calls: list[object] = []
    query_calls: list[object] = []
    adoption_calls: list[object] = []

    class Coverage:
        def __init__(self, session, starts, *, history_floor_path, now=None) -> None:
            del session, starts, history_floor_path, now

        def product_start(self, symbol: str) -> date:
            assert symbol == "jm"
            return date(2020, 1, 2)

        def latest_complete_day(self, products: tuple[str, ...]) -> date:
            assert products == ("jm",)
            return date(2026, 8, 26)

    class MarketData:
        def __init__(self) -> None:
            self.catalog = SimpleNamespace(
                canonical_root=base,
                main_map_before=lambda symbol, before: (
                    SimpleNamespace(trade_date=date(2026, 8, 26)),
                ),
            )
            self.store = SimpleNamespace(
                read_month=lambda *args, **kwargs: (_ for _ in ()).throw(
                    AssertionError("Canonical Bar read")
                )
            )

        def actual_dominant_segments(self, symbol, since, through):
            raise AssertionError("HTTP query must not resolve segments")

        def query(self, request):
            query_calls.append(request)
            raise AssertionError("Canonical query invoked")

        def query_actual_dominant_trading_days(self, request):
            query_calls.append(request)
            raise AssertionError("Canonical actual-dominant read invoked")

    monkeypatch.setattr(
        "app.market_data.composition.build_subing_strategy_historical_service",
        lambda *args, **kwargs: historical_calls.append((args, kwargs)) or None,
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: MarketData(),
    )
    monkeypatch.setattr(
        "app.market_data.coverage_source.DatabaseCoverageSource",
        Coverage,
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_active_products",
        lambda: ("jm",),
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        lambda *, environ, inspector: base,
    )
    monkeypatch.setattr(
        "app.market_data.subing_strategy.performance_adoption.SubingStrategyPerformanceAdopter.adopt",
        lambda *args, **kwargs: adoption_calls.append((args, kwargs)),
        raising=False,
    )

    empty = SubingStrategyPerformanceStats(0, 0, 0, 0, None, None, None, None, None, None)
    snapshot = subing_strategy_performance_snapshot_from_projection(
        SubingStrategyPerformanceProjection(
            strategy_id="subing_strategy_v1",
            formula_version="subing_strategy_15m_v1",
            symbol="jm",
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            frequency=BarFrequency.M15,
            coverage_since=date(2020, 1, 2),
            coverage_through=date(2026, 8, 26),
            resolved_cutoff=datetime(2026, 8, 26, 7, tzinfo=UTC),
            segment_count=1,
            bar_count_15m=12,
            context_unavailable_count=0,
            cache_state="hit",
            summary=SubingStrategyPerformanceSummary(empty, empty, empty, 0, ()),
            episodes=(),
        ),
        immutable_prefix_segment_count=0,
        immutable_prefix_counts=SubingStrategyPerformancePrefixCounts(0, 0, 0, 0),
        segment_facts=(
            SubingStrategyPerformanceSegmentFact(
                contract="jm2609",
                effective_start=date(2020, 1, 2),
                effective_end=date(2026, 8, 26),
                loaded_through=date(2026, 8, 26),
                bar_count_1m=1,
                bar_count_5m=1,
                bar_count_15m=12,
                context_unavailable_count=0,
                source_identity="a" * 64,
            ),
        ),
        source_manifest_sha256="b" * 64,
        generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
        engine_identity_sha256="e" * 64,
    )
    SubingStrategyPerformanceFileSnapshotStore(
        performance_root,
        root_validator=lambda: performance_root,
        trusted_base_validator=lambda: base,
    ).publish_current(snapshot)
    before = {
        str(path.relative_to(base)): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }

    query = build_subing_strategy_performance_snapshot_query(object())
    projection = query.current("jm")

    assert historical_calls == []
    assert query_calls == []
    assert adoption_calls == []
    assert projection.symbol == "jm"
    assert projection.cache_state == "hit"
    assert projection.coverage_through == date(2026, 8, 26)
    assert {
        str(path.relative_to(base)): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    } == before
