from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import FuturesContractUniverse
from app.services.rqdata_ingest.reference_metadata_gap_reconcile import reconcile_reference_metadata_gaps


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_reference_metadata_gap_reconcile_classifies_sync_candidates(tmp_path: Path) -> None:
    matrix = tmp_path / "metadata.csv"
    pd.DataFrame(
        [
            {
                "product": "rb",
                "year": 2020,
                "dataset": "contract_universe",
                "status": "metadata_gap",
                "issue_type": "missing_contract_universe",
            },
            {
                "product": "jm",
                "year": 2025,
                "dataset": "continuous_contract_map",
                "status": "metadata_gap",
                "issue_type": "missing_continuous_contract_map",
            },
            {
                "product": "cu",
                "year": 2020,
                "dataset": "contract_universe",
                "status": "metadata_gap",
                "issue_type": "missing_contract_universe",
            },
        ]
    ).to_csv(matrix, index=False)
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        session.add(FuturesContractUniverse(instrument_symbol="cu", trade_date=date(2020, 6, 1), contract_code="CU2007", provider="rqdata", data_version="test"))
        session.commit()
        result = reconcile_reference_metadata_gaps(session=session, project_root=tmp_path, metadata_matrix=matrix)

    assert result["input_gap_rows"] == 3
    assert result["classification_counts"]["needs_contract_universe_sync"] == 1
    assert result["classification_counts"]["needs_continuous_contract_sync"] == 1
    assert result["classification_counts"]["partial_year_rows"] == 1
    assert all(row["recommended_action"] == "metadata_only_sync_requires_human_gate" for row in result["ledger"])
