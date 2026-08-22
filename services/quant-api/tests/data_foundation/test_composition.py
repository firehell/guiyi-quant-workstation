from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.market_data.composition import (
    build_historical_data_manager,
    build_metadata_synchronizer,
    build_market_data_service,
    build_subing_historical_signal_service,
    canonical_root,
)
from app.market_data.metadata import MetadataSynchronizer


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_historical_manager_uses_configured_canonical_root(tmp_path, monkeypatch) -> None:
    root = tmp_path / "canonical"
    root.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(root))
    session = _session()

    manager = build_historical_data_manager(session)

    assert manager.store.root == root.resolve()
    assert canonical_root() == root.resolve()
    session.close()


def test_market_data_service_uses_configured_canonical_root(tmp_path, monkeypatch) -> None:
    root = tmp_path / "canonical"
    root.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(root))
    session = _session()

    service = build_market_data_service(session)

    assert service.catalog.canonical_root == root.resolve()
    assert service.store.root == root.resolve()
    session.close()


def test_metadata_synchronizer_uses_existing_composition_boundary(tmp_path, monkeypatch) -> None:
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
