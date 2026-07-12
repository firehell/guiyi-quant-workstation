from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.rqdata_ingest.duplicate_path_version_reconcile import reconcile_duplicate_path_versions
from app.services.rqdata_ingest.parquet import sha256_file


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_parquet(tmp_path: Path) -> Path:
    path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=l_f/contract=L2609F/L2609F_1m.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"datetime": pd.date_range("2026-04-01", periods=2, freq="min"), "open": [1, 2]}).to_parquet(path, index=False)
    return path


def _add_file(session: Session, path: Path, version: str) -> None:
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="l_f",
        contract_code="L2609F",
        period="1m",
        start_time=datetime(2026, 4, 1, tzinfo=UTC),
        end_time=datetime(2026, 4, 1, 0, 1, tzinfo=UTC),
        file_path=str(path),
        row_count=2,
        file_size_bytes=path.stat().st_size,
        checksum=sha256_file(path),
        data_version=version,
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    session.add(
        DataQualityReport(
            file_id=market_file.id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol="l_f",
            contract_code="L2609F",
            period="1m",
            start_time=market_file.start_time,
            end_time=market_file.end_time,
            status="passed",
            missing_bars=0,
            duplicated_bars=0,
            abnormal_price_count=0,
            abnormal_volume_count=0,
            details={},
        )
    )


def test_duplicate_path_version_reconcile_selects_manifest_current_version(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    parquet_path = _write_parquet(tmp_path)
    ledger = tmp_path / "lpv.csv"
    pd.DataFrame(
        [
            {
                "classification": "duplicate_path_versions",
                "product": "l_f",
                "actual_contract": "L2609F",
                "period": "1m",
                "standard_path": str(parquet_path),
                "manifest_data_version": "rq_acb_l_f_L2609F_1m_v1",
            }
        ]
    ).to_csv(ledger, index=False)
    with SessionLocal() as session:
        _add_file(session, parquet_path, "legacy_version")
        _add_file(session, parquet_path, "rq_acb_l_f_L2609F_1m_v1")
        session.commit()
        result = reconcile_duplicate_path_versions(session=session, project_root=tmp_path, lpv_ledger=ledger)

    row = result["ledger"][0]
    assert result["classification_counts"]["duplicate_path_versions"] == 1
    assert row["current_data_version"] == "rq_acb_l_f_L2609F_1m_v1"
    assert row["superseded_data_versions"] == "legacy_version"
    assert result["database_counts_unchanged"] is True
