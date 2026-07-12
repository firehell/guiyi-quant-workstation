from __future__ import annotations

import csv
from datetime import UTC, datetime
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import MarketDataFile
from app.services.rqdata_ingest.parquet import sha256_file
from app.services.rqdata_ingest.source_interval_provenance_repair import (
    run_source_interval_provenance_repair_apply,
    run_source_interval_provenance_repair_dry_run,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_parquet(path: Path, *, rows: int = 3, with_source_interval: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "symbol": ["rb"] * rows,
            "contract": ["rb.MAIN"] * rows,
            "exchange": ["SHFE"] * rows,
            "datetime": pd.date_range("2026-01-02 09:05:00", periods=rows, freq="5min"),
            "open": range(rows),
            "high": range(rows),
            "low": range(rows),
            "close": range(rows),
            "volume": range(rows),
            "open_interest": range(rows),
            "period": ["5m"] * rows,
            "provider": ["rqdata"] * rows,
            "data_role": ["primary"] * rows,
            "quality_status": ["passed"] * rows,
        }
    )
    if with_source_interval:
        frame["source_interval"] = "1m"
    frame.to_parquet(path, index=False)


def _write_triage(path: Path, parquet_path: Path, *, years: tuple[int, ...] = (2023, 2024)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "product",
        "contract_role",
        "symbol_or_contract",
        "period",
        "year",
        "status",
        "issue_type",
        "expected_start",
        "expected_end",
        "target_reason",
        "evidence_source",
        "provider",
        "data_role",
        "quality_status",
        "start_date",
        "end_date",
        "row_count",
        "db_market_data_file_id",
        "standard_path",
        "recommended_next_task",
        "triage_result",
        "observed_source_interval_values",
        "source_interval_rows_scanned",
        "root_cause_bucket",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for year in years:
            writer.writerow(
                {
                    "product": "rb",
                    "contract_role": "dominant_main",
                    "symbol_or_contract": "rb.MAIN",
                    "period": "5m",
                    "year": year,
                    "status": "covered_warning",
                    "issue_type": "source_interval_unverified",
                    "expected_start": f"{year}-01-01",
                    "expected_end": f"{year}-12-31",
                    "target_reason": "dominant_2023_plus_derived_from_1m",
                    "evidence_source": "db_market_data_file,manifest",
                    "provider": "rqdata",
                    "data_role": "primary",
                    "quality_status": "passed",
                    "start_date": "2026-01-02",
                    "end_date": "2026-01-02",
                    "row_count": 3,
                    "db_market_data_file_id": "12.0",
                    "standard_path": str(parquet_path),
                    "recommended_next_task": "target_coverage_gap_triage",
                    "triage_result": "source_interval_column_missing",
                    "root_cause_bucket": "derived_asset_metadata_column_missing",
                }
            )


def _write_issue_register(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"issue_type": "source_interval_unverified"}, {"issue_type": "quality_failed"}]).to_csv(path, index=False)


def _write_manifest(path: Path, parquet_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "period": "5m",
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
                "row_count": 3,
                "min_datetime": "2026-01-02T09:05:00",
                "max_datetime": "2026-01-02T09:15:00",
                "checksum": sha256_file(parquet_path),
                "standard_path": str(parquet_path),
                "status": "success",
                "data_version": "test_rb_5m",
            }
        ]
    ).to_csv(path, index=False)


def _write_processed_summary(path: Path, parquet_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "symbol": "rb",
                "contract": "rb.MAIN",
                "periods": {
                    "5m": {
                        "quality_status": "passed",
                        "standard": {
                            "path": str(parquet_path),
                            "row_count": 3,
                            "checksum": sha256_file(parquet_path),
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _seed_market_file(session: Session, parquet_path: Path, *, checksum: str | None = None, file_size: int | None = None) -> None:
    session.add(
        MarketDataFile(
            id=12,
            provider="rqdata",
            data_type="bars",
            instrument_symbol="rb",
            contract_code="rb.MAIN",
            period="5m",
            start_time=datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 23, 59, 59, tzinfo=UTC),
            file_path=str(parquet_path),
            row_count=3,
            file_size_bytes=parquet_path.stat().st_size if file_size is None else file_size,
            checksum=sha256_file(parquet_path) if checksum is None else checksum,
            data_version="test_rb_5m",
            data_role="primary",
            quality_status="passed",
        )
    )
    session.commit()


def _build_dry_run(tmp_path: Path, *, with_processed_summary: bool = True) -> tuple[Path, Path, Path, Path]:
    parquet_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=5m/exchange=SHFE/symbol=rb/contract=rb.MAIN/rb_MAIN_5m.parquet"
    triage_path = tmp_path / "reports/source_interval_unverified_triage.csv"
    issue_path = tmp_path / "reports/issue_register.csv"
    manifest_path = tmp_path / "data/manifests/rqdata_rb_v2_history_20230103_20260707.csv"
    summary_path = tmp_path / "data/processed/v1b/rb/rb_v2_parquet_20230103_20260707.json"
    _write_parquet(parquet_path)
    _write_triage(triage_path, parquet_path)
    _write_issue_register(issue_path)
    _write_manifest(manifest_path, parquet_path)
    if with_processed_summary:
        _write_processed_summary(summary_path, parquet_path)
    result = run_source_interval_provenance_repair_dry_run(
        project_root=tmp_path,
        triage_report=triage_path,
        issue_register=issue_path,
        output_dir=tmp_path / "out",
    )
    return parquet_path, manifest_path, summary_path, result["outputs"]["candidate_files"]


def test_source_interval_dry_run_deduplicates_candidate_files(tmp_path: Path) -> None:
    parquet_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=5m/exchange=SHFE/symbol=rb/contract=rb.MAIN/rb_MAIN_5m.parquet"
    triage_path = tmp_path / "reports/source_interval_unverified_triage.csv"
    issue_path = tmp_path / "reports/issue_register.csv"
    manifest_path = tmp_path / "data/manifests/rqdata_rb_v2_history_20230103_20260707.csv"
    summary_path = tmp_path / "data/processed/v1b/rb/rb_v2_parquet_20230103_20260707.json"
    _write_parquet(parquet_path)
    _write_triage(triage_path, parquet_path)
    _write_issue_register(issue_path)
    _write_manifest(manifest_path, parquet_path)
    _write_processed_summary(summary_path, parquet_path)

    result = run_source_interval_provenance_repair_dry_run(
        project_root=tmp_path,
        triage_report=triage_path,
        issue_register=issue_path,
        output_dir=tmp_path / "out",
    )

    assert result["writes_database"] is False
    assert result["writes_parquet"] is False
    assert result["calls_rqdata"] is False
    assert len(result["candidate_files"]) == 1
    assert len(result["affected_coverage_rows"]) == 2
    candidate = result["candidate_files"][0]
    assert candidate["source_interval_status"] == "source_interval_column_missing"
    assert candidate["proposed_source_interval"] == "1m"
    assert candidate["manifest_checksum_sync_required"] is True
    assert candidate["processed_summary_checksum_sync_required"] is True
    assert candidate["db_checksum_sync_required"] is True
    assert candidate["apply_eligible"] is True
    assert "source_interval" not in candidate["columns_before"]
    assert result["outputs"]["candidate_files"].exists()
    assert result["outputs"]["affected_coverage_rows"].exists()
    assert result["outputs"]["summary"].exists()


def test_source_interval_dry_run_blocks_existing_source_interval_file(tmp_path: Path) -> None:
    parquet_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=5m/exchange=SHFE/symbol=rb/contract=rb.MAIN/rb_MAIN_5m.parquet"
    triage_path = tmp_path / "reports/source_interval_unverified_triage.csv"
    issue_path = tmp_path / "reports/issue_register.csv"
    manifest_path = tmp_path / "data/manifests/rqdata_rb_v2_history_20230103_20260707.csv"
    _write_parquet(parquet_path, with_source_interval=True)
    _write_triage(triage_path, parquet_path, years=(2023,))
    _write_issue_register(issue_path)
    _write_manifest(manifest_path, parquet_path)

    result = run_source_interval_provenance_repair_dry_run(
        project_root=tmp_path,
        triage_report=triage_path,
        issue_register=issue_path,
        output_dir=tmp_path / "out",
    )

    candidate = result["candidate_files"][0]
    assert candidate["source_interval_status"] == "already_source_interval_1m"
    assert candidate["apply_eligible"] is False
    assert "already_source_interval_1m" in candidate["blocked_reason"]


def test_source_interval_apply_requires_confirmation(tmp_path: Path) -> None:
    parquet_path, _, _, candidate_files = _build_dry_run(tmp_path)
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_market_file(session, parquet_path)
        result = run_source_interval_provenance_repair_apply(
            project_root=tmp_path,
            session=session,
            candidate_files=candidate_files,
            output_dir=tmp_path / "apply",
            apply=True,
            confirm=False,
        )

    assert result["writes_parquet"] is False
    assert result["blocked_reasons"] == ["confirmation_required"]
    assert "source_interval" not in pd.read_parquet(parquet_path).columns


def test_source_interval_apply_updates_parquet_manifest_summary_and_db(tmp_path: Path) -> None:
    parquet_path, manifest_path, summary_path, candidate_files = _build_dry_run(tmp_path)
    before_checksum = sha256_file(parquet_path)
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_market_file(session, parquet_path)
        result = run_source_interval_provenance_repair_apply(
            project_root=tmp_path,
            session=session,
            candidate_files=candidate_files,
            output_dir=tmp_path / "apply",
            apply=True,
            confirm=True,
            limit=1,
        )

    assert result["applied_candidate_count"] == 1
    assert result["writes_parquet"] is True
    assert pd.read_parquet(parquet_path)["source_interval"].unique().tolist() == ["1m"]
    after_checksum = sha256_file(parquet_path)
    assert after_checksum != before_checksum
    manifest_row = pd.read_csv(manifest_path).iloc[0].to_dict()
    assert manifest_row["checksum"] == after_checksum
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["periods"]["5m"]["standard"]["checksum"] == after_checksum
    with SessionLocal() as session:
        market_file = session.scalar(select(MarketDataFile).where(MarketDataFile.id == 12))
        assert market_file is not None
        assert market_file.checksum == after_checksum
        assert market_file.file_size_bytes == parquet_path.stat().st_size
        assert market_file.row_count == 3
        assert market_file.data_role == "primary"
        assert market_file.quality_status == "passed"


def test_source_interval_apply_does_not_create_missing_processed_summary(tmp_path: Path) -> None:
    parquet_path, _, summary_path, candidate_files = _build_dry_run(tmp_path, with_processed_summary=False)
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_market_file(session, parquet_path)
        result = run_source_interval_provenance_repair_apply(
            project_root=tmp_path,
            session=session,
            candidate_files=candidate_files,
            output_dir=tmp_path / "apply",
            apply=True,
            confirm=True,
        )

    assert result["applied_candidate_count"] == 1
    assert result["apply_rows"][0]["processed_summary_updates"] == 0
    assert not summary_path.exists()


def test_source_interval_apply_blocks_checksum_drift_and_preserves_file(tmp_path: Path) -> None:
    parquet_path, _, _, candidate_files = _build_dry_run(tmp_path)
    original_columns = pd.read_parquet(parquet_path).columns.tolist()
    _write_parquet(parquet_path, rows=4)
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_market_file(session, parquet_path, checksum="stale", file_size=123)
        result = run_source_interval_provenance_repair_apply(
            project_root=tmp_path,
            session=session,
            candidate_files=candidate_files,
            output_dir=tmp_path / "apply",
            apply=True,
            confirm=True,
        )

    assert result["applied_candidate_count"] == 0
    assert "parquet_checksum_changed" in result["blocked_reasons"]
    assert pd.read_parquet(parquet_path).columns.tolist() == original_columns


def test_source_interval_apply_skips_already_applied_candidate(tmp_path: Path) -> None:
    parquet_path, _, _, candidate_files = _build_dry_run(tmp_path)
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_market_file(session, parquet_path)
        first = run_source_interval_provenance_repair_apply(
            project_root=tmp_path,
            session=session,
            candidate_files=candidate_files,
            output_dir=tmp_path / "apply1",
            apply=True,
            confirm=True,
        )
        second = run_source_interval_provenance_repair_apply(
            project_root=tmp_path,
            session=session,
            candidate_files=candidate_files,
            output_dir=tmp_path / "apply2",
            apply=True,
            confirm=True,
        )

    assert first["applied_candidate_count"] == 1
    assert second["applied_candidate_count"] == 0
    assert second["skipped_candidate_count"] == 1
    assert second["apply_rows"][0]["skip_reason"] == "already_applied"
