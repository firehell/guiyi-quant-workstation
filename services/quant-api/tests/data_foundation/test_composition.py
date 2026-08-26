from __future__ import annotations

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
    build_subing_strategy_historical_service,
    build_subing_historical_signal_service,
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


def test_subing_historical_builder_uses_market_read_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_data = object()
    loader = object()
    calibration = object()
    result = object()
    captured: dict[str, object] = {}
    session = object()
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda value: market_data if value is session else pytest.fail("wrong session"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.ActualDominantResearchSegmentLoader",
        lambda value: loader if value is market_data else pytest.fail("wrong MDS"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_active_products",
        lambda: ("jm",),
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_accepted_subing_calibration",
        lambda _path: calibration,
    )
    monkeypatch.setattr(
        "app.market_data.composition.SubingHistoricalSignalService",
        lambda loader_arg, **kwargs: (
            captured.update(loader=loader_arg, **kwargs) or result
        ),
    )

    assert build_subing_historical_signal_service(session) is result
    assert captured == {
        "loader": loader,
        "products": ("jm",),
        "calibration": calibration,
    }


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
            SimpleNamespace(symbol="jm", product_name="焦煤", sector="black"),
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
