from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.market_data.composition import (
    build_candidate_bootstrap_manager,
    build_candidate_historical_data_manager,
    build_historical_data_manager,
    canonical_root,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_candidate_historical_manager_is_rqdata_only_and_isolated(tmp_path, monkeypatch) -> None:
    production = tmp_path / "production_canonical"
    production.mkdir()
    candidate = tmp_path / "candidate_canonical"
    candidate.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(production))

    session = _session()
    manager = build_candidate_historical_data_manager(session, candidate)

    assert manager.legacy is None
    assert manager.store.root == candidate.resolve()
    assert canonical_root() == production.resolve()
    session.close()


def test_candidate_historical_manager_rejects_production_root(tmp_path, monkeypatch) -> None:
    production = tmp_path / "production_canonical"
    production.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(production))
    session = _session()

    with pytest.raises(ValueError, match="CANDIDATE_ROOT_MUST_BE_ISOLATED"):
        build_candidate_historical_data_manager(session, production)
    session.close()


def test_daily_composition_keeps_legacy_none(tmp_path, monkeypatch) -> None:
    production = tmp_path / "production_canonical"
    production.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(production))
    session = _session()

    manager = build_historical_data_manager(session)

    assert manager.legacy is None
    session.close()


def test_legacy_candidate_bootstrap_remains_frozen_migration_only(tmp_path, monkeypatch) -> None:
    production = tmp_path / "production_canonical"
    production.mkdir()
    candidate = tmp_path / "candidate_canonical"
    candidate.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(production))
    session = _session()

    manager = build_candidate_bootstrap_manager(session, candidate)

    assert manager.legacy is not None
    assert manager.store.root == candidate.resolve()
    session.close()


def test_candidate_root_rejects_nested_paths(tmp_path, monkeypatch) -> None:
    production = tmp_path / "production_canonical"
    production.mkdir()
    nested = production / "nested"
    nested.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(production))
    session = _session()

    with pytest.raises(ValueError, match="CANDIDATE_ROOT_MUST_BE_ISOLATED"):
        build_candidate_historical_data_manager(session, nested)
    session.close()
