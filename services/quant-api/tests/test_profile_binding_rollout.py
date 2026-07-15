from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding
from app.services.profile_binding_rollout import run_apply_mode, run_dry_run_mode, run_rollback_batch_mode, run_verify_mode


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed(tmp_path: Path) -> tuple[sessionmaker[Session], Path]:
    SessionLocal = _session_factory()
    parquet_old = tmp_path / "old.parquet"
    parquet_new = tmp_path / "new.parquet"
    pd.DataFrame({"datetime": [datetime(2023, 1, 3)]}).to_parquet(parquet_old, index=False)
    pd.DataFrame({"datetime": [datetime(2023, 1, 4)]}).to_parquet(parquet_new, index=False)

    with SessionLocal() as session:
        session.add(
            DataProfile(
                profile_id="intraday_research_v1",
                label="Intraday Research V1",
                description="test",
                contract_roles=["dominant_main"],
                periods=["1d"],
                quality_policy="passed_only",
                provider="rqdata",
            )
        )
        old_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
            start_time=datetime(2023, 1, 3, tzinfo=UTC),
            end_time=datetime(2026, 7, 7, tzinfo=UTC),
            file_path=str(parquet_old),
            row_count=1,
            checksum="a" * 64,
            data_version="old_v1",
            data_role="primary",
            quality_status="passed",
        )
        new_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
            start_time=datetime(2023, 1, 3, tzinfo=UTC),
            end_time=datetime(2026, 7, 10, tzinfo=UTC),
            file_path=str(parquet_new),
            row_count=1,
            checksum="b" * 64,
            data_version="new_v2",
            data_role="primary",
            quality_status="passed",
        )
        session.add_all([old_file, new_file])
        session.flush()
        new_file_id = new_file.id
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="1d",
                data_version="old_v1",
                market_data_file_id=old_file.id,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.commit()

    candidates_path = tmp_path / "binding_candidates.csv"
    pd.DataFrame(
        [
            {
                "profile_id": "intraday_research_v1",
                "instrument_symbol": "jm",
                "contract_code": "jm.MAIN",
                "period": "1d",
                "contract_role": "dominant_main",
                "candidate_status": "current",
                "market_data_file_id": new_file_id,
                "data_version": "new_v2",
            }
        ]
    ).to_csv(candidates_path, index=False)
    return SessionLocal, candidates_path


def test_run_dry_run_detects_change(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    with SessionLocal() as session:
        result = run_dry_run_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            project_root=tmp_path,
        )
    assert result["would_change"] == 1


def test_run_apply_and_rollback_batch(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    output_dir = tmp_path / "rollout"
    with SessionLocal() as session:
        apply_result = run_apply_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            output_dir=output_dir,
            batch_id="test_batch",
            project_root=tmp_path,
            commit=True,
        )
        assert apply_result["applied"] == 1

        verify_result = run_verify_mode(
            session,
            output_dir=output_dir,
            batch_id="test_batch",
            candidates_path=candidates_path,
            project_root=tmp_path,
        )
        assert verify_result["passed"] is True

        rollback_result = run_rollback_batch_mode(
            session,
            output_dir=output_dir,
            batch_id="test_batch",
            commit=True,
        )
        assert rollback_result["rolled_back"] == 1
