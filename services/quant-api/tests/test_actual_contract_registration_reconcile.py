from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.rqdata_ingest.actual_contract_registration_reconcile import reconcile_actual_contract_registrations
from app.services.rqdata_ingest.parquet import sha256_file


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_fixture(tmp_path: Path, *, checksum_override: str | None = None) -> tuple[Path, Path]:
    parquet_path = (
        tmp_path
        / "data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=l_f/contract=L2602F/L2602F_1m.parquet"
    )
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range("2025-10-29 09:01:00", periods=3, freq="min"),
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [10, 11, 12],
            "open_interest": [1000, 1001, 1002],
        }
    )
    frame.to_parquet(parquet_path, index=False)
    checksum = checksum_override or sha256_file(parquet_path)
    manifest_path = tmp_path / "data/manifests/rqdata_actual_contract_bars_l_f_L2602F_20251029_20251226.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "period": "1m",
                "provider": "rqdata",
                "source": "rqdata",
                "product": "l_f",
                "continuous_contract": "l_f.MAIN",
                "actual_contract": "L2602F",
                "data_role": "primary",
                "quality_status": "passed",
                "row_count": 3,
                "min_datetime": "2025-10-29T09:01:00",
                "max_datetime": "2025-10-29T09:03:00",
                "checksum": checksum,
                "standard_path": str(parquet_path),
                "data_version": "rq_acb_l_f_L2602F_1m_v1",
                "status": "success",
            }
        ]
    ).to_csv(manifest_path, index=False)
    candidate_path = tmp_path / "candidates.csv"
    pd.DataFrame(
        [
            {
                "product": "l",
                "symbol_or_contract": "L2602F",
                "period": "1m",
                "year": "2025",
                "row_count": 3,
                "standard_path": str(parquet_path),
            },
            {
                "product": "l",
                "symbol_or_contract": "L2602F",
                "period": "1m",
                "year": "2026",
                "row_count": 3,
                "standard_path": str(parquet_path),
            },
        ]
    ).to_csv(candidate_path, index=False)
    return parquet_path, candidate_path


def _add_registration(session: Session, path: Path, *, data_version: str = "rq_acb_l_f_L2602F_1m_v1") -> MarketDataFile:
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="l_f",
        contract_code="L2602F",
        period="1m",
        start_time=datetime(2025, 10, 29, 9, 1, tzinfo=UTC),
        end_time=datetime(2025, 10, 29, 9, 3, tzinfo=UTC),
        file_path=str(path),
        row_count=3,
        file_size_bytes=path.stat().st_size,
        checksum=sha256_file(path),
        data_version=data_version,
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
            contract_code="L2602F",
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
    session.flush()
    return market_file


def test_reconcile_deduplicates_targets_and_keeps_registered_asset_readonly(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    parquet_path, candidate_path = _write_fixture(tmp_path)
    with SessionLocal() as session:
        _add_registration(session, parquet_path)
        session.commit()
        before = session.scalar(select(func.count(MarketDataFile.id)))
        result = reconcile_actual_contract_registrations(session=session, project_root=tmp_path, candidate_file=candidate_path)
        after = session.scalar(select(func.count(MarketDataFile.id)))

    assert result["candidate_target_row_count"] == 2
    assert result["unique_path_count"] == 1
    assert result["classification_counts"]["already_registered"] == 1
    assert result["eligible_for_registration_count"] == 0
    assert result["database_counts_unchanged"] is True
    assert before == after == 1
    assert result["ledger"][0]["covered_years"] == "2025|2026"
    assert result["ledger"][0]["target_row_count"] == 2


def test_reconcile_reports_duplicate_path_versions_without_cleanup(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    parquet_path, candidate_path = _write_fixture(tmp_path)
    with SessionLocal() as session:
        _add_registration(session, parquet_path, data_version="legacy_version")
        _add_registration(session, parquet_path)
        session.commit()
        result = reconcile_actual_contract_registrations(session=session, project_root=tmp_path, candidate_file=candidate_path)

    row = result["ledger"][0]
    assert row["classification"] == "duplicate_path_versions"
    assert row["db_exact_path_count"] == 2
    assert result["classification_counts"]["duplicate_path_versions"] == 1
    assert result["eligible_for_registration_count"] == 0


def test_reconcile_marks_valid_unregistered_asset_eligible_but_does_not_write(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    _, candidate_path = _write_fixture(tmp_path)
    with SessionLocal() as session:
        result = reconcile_actual_contract_registrations(session=session, project_root=tmp_path, candidate_file=candidate_path)
        market_count = session.scalar(select(func.count(MarketDataFile.id)))
        quality_count = session.scalar(select(func.count(DataQualityReport.id)))

    assert result["classification_counts"]["eligible_for_registration"] == 1
    assert result["writes_database"] is False
    assert market_count == quality_count == 0


def test_reconcile_blocks_manifest_checksum_mismatch(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    _, candidate_path = _write_fixture(tmp_path, checksum_override="0" * 64)
    with SessionLocal() as session:
        result = reconcile_actual_contract_registrations(session=session, project_root=tmp_path, candidate_file=candidate_path)

    row = result["ledger"][0]
    assert row["classification"] == "blocked_metadata_mismatch"
    assert "manifest_checksum_mismatch" in row["issues"]
    assert result["eligible_for_registration_count"] == 0
