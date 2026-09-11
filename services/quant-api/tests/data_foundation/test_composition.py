from __future__ import annotations

import sys
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.market_data.composition import (
    build_historical_data_manager,
    build_market_data_service,
    build_metadata_synchronizer,
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
    adapter = SimpleNamespace()
    catalog = SimpleNamespace()

    synchronizer = build_metadata_synchronizer(
        session,
        adapter=adapter,
        catalog=catalog,
    )

    assert isinstance(synchronizer, MetadataSynchronizer)
    assert synchronizer.adapter is adapter
    assert synchronizer.catalog is catalog
    session.close()


def test_historical_manager_lazily_constructs_provider_from_explicit_settings(
    tmp_path, monkeypatch
) -> None:
    from app.market_data import rqdata_adapter

    root = tmp_path / "canonical"
    root.mkdir()
    received = []
    client = SimpleNamespace()

    def build_client(*, settings=None):
        received.append(settings)
        return client

    monkeypatch.setattr(rqdata_adapter, "RQDataClient", build_client)
    session = _session()
    settings = {"RQDATA_LICENSE_KEY": "runtime-bound-license"}

    manager = build_historical_data_manager(
        session,
        data_root=root,
        provider_settings=settings,
    )

    assert received == []
    assert manager.provider.client is client
    assert received == [settings]
    assert manager.provider.matches_provider_settings(settings)
    session.close()


def test_rqdata_client_explicit_settings_do_not_load_ambient_configuration(
    monkeypatch,
) -> None:
    from app.market_data import rqdata_adapter

    calls = []
    fake_rqdatac = SimpleNamespace(
        init=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "rqdatac", fake_rqdatac)
    monkeypatch.setenv("RQDATA_LICENSE_KEY", "ambient-license")
    monkeypatch.setattr(
        rqdata_adapter,
        "load_project_env",
        lambda: (_ for _ in ()).throw(
            AssertionError("explicit Runtime settings must not load project env")
        ),
    )

    rqdata_adapter.RQDataClient(
        settings={"RQDATA_LICENSE_KEY": "runtime-license"}
    )

    assert calls == [(('license', 'runtime-license'), {})]
