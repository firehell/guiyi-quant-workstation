from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.market_data.composition import (
    build_historical_data_manager,
    build_metadata_synchronizer,
    build_market_data_service,
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
