from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.market_data import composition
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
    monkeypatch.setattr(composition, "PROJECT_ROOT", tmp_path)
    production = tmp_path / "data/parquet/canonical"
    production.mkdir(parents=True)
    candidate = tmp_path / "data/canonical-candidates/jm"
    candidate.mkdir(parents=True)
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(production))

    session = _session()
    manager = build_candidate_historical_data_manager(session, candidate)

    assert manager.legacy is None
    assert manager.store.root == candidate.resolve()
    assert canonical_root() == production.resolve()
    session.close()


def test_candidate_historical_manager_rejects_production_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(composition, "PROJECT_ROOT", tmp_path)
    production = tmp_path / "data/parquet/canonical"
    production.mkdir(parents=True)
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(production))
    session = _session()

    with pytest.raises(composition.CandidateTargetError, match="CANDIDATE_PRECONDITION_FAILED"):
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
    monkeypatch.setattr(composition, "PROJECT_ROOT", tmp_path)
    production = tmp_path / "data/parquet/canonical"
    production.mkdir(parents=True)
    candidate = tmp_path / "data/canonical-candidates/jm"
    candidate.mkdir(parents=True)
    (tmp_path / "data/raw/rqdata/actual_contract_bars").mkdir(parents=True)
    (tmp_path / "data/raw/rqdata/dominant_contract_bars").mkdir(parents=True)
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(production))
    session = _session()

    manager = build_candidate_bootstrap_manager(session, candidate)

    assert manager.legacy is not None
    assert manager.store.root == candidate.resolve()
    session.close()


def test_candidate_root_rejects_nested_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(composition, "PROJECT_ROOT", tmp_path)
    production = tmp_path / "data/parquet/canonical"
    production.mkdir(parents=True)
    nested = production / "nested"
    nested.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(production))
    session = _session()

    with pytest.raises(composition.CandidateTargetError, match="CANDIDATE_PRECONDITION_FAILED"):
        build_candidate_historical_data_manager(session, nested)
    session.close()


def test_candidate_target_records_only_monotonic_non_sensitive_provenance(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(composition, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(composition, "_code_sha", lambda: "a" * 40)
    active_root = tmp_path / "data/parquet/canonical"
    active_root.mkdir(parents=True)
    candidate_root = tmp_path / "data/canonical-candidates/jm"
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(active_root))
    monkeypatch.setenv("GUIYI_CANDIDATE_DATABASE_URL", "sqlite+pysqlite://")
    (tmp_path / "data/universe").mkdir(parents=True)
    (tmp_path / "data/universe/active_products.txt").write_text("jm\n", encoding="utf-8")
    (tmp_path / "data/universe/active_history_floor.txt").write_text(
        "2023-01-01\n", encoding="utf-8"
    )

    session = _session()
    fresh = composition.HistoricalDataTarget.candidate(candidate_root, mode="fresh")
    identity = fresh.validate_update(session, date(2026, 8, 7))
    published = candidate_root / "kind=continuous/symbol=JM/series=MAIN/frequency=1d"
    published.mkdir(parents=True)
    (published / "part.parquet").write_bytes(b"published-after-fresh-preflight")
    fresh.record_through(date(2026, 8, 7), identity)

    metadata = json.loads((candidate_root / "candidate.json").read_text(encoding="utf-8"))
    assert set(metadata) == {"identity", "recorded_through"}
    assert metadata["recorded_through"] == "2026-08-07"
    assert metadata["identity"]["source_policy"] == "RQData-only/legacy=None"
    assert str(candidate_root) not in json.dumps(metadata)

    extend = composition.HistoricalDataTarget.candidate(candidate_root, mode="extend")
    assert extend.validate_update(session, date(2026, 8, 8)) == identity
    extend.validate_audit(session)
    with pytest.raises(composition.CandidateTargetError, match="CANDIDATE_THROUGH_REGRESSION"):
        extend.validate_update(session, date(2026, 8, 6))
    session.close()


def test_candidate_target_rejects_roots_outside_the_candidate_parent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(composition, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("GUIYI_CANDIDATE_DATABASE_URL", "sqlite+pysqlite://")

    with pytest.raises(composition.CandidateTargetError, match="CANDIDATE_PRECONDITION_FAILED"):
        composition.HistoricalDataTarget.candidate(tmp_path / "outside", mode="fresh")


def test_relative_candidate_root_rejects_a_symlink_component_from_project_root(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(composition, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("GUIYI_CANDIDATE_DATABASE_URL", "sqlite+pysqlite://")
    candidate_parent = tmp_path / "data/canonical-candidates"
    physical = candidate_parent / "physical"
    physical.mkdir(parents=True)
    (candidate_parent / "linked").symlink_to(physical, target_is_directory=True)
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    with pytest.raises(composition.CandidateTargetError, match="CANDIDATE_PRECONDITION_FAILED"):
        composition.HistoricalDataTarget.candidate(
            Path("data/canonical-candidates/linked/jm"), mode="fresh"
        )
