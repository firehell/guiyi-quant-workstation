from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import MainContractMap, MarketDataFile
from app.services.rqdata_ingest.data_layer_final_audit import (
    build_claim_verdicts,
    build_duplicate_active_assets,
    build_quality_issue_register,
    build_stale_metrics_verdict,
    run_extended_final_audit,
    write_final_audit_reports,
)
from app.services.rqdata_ingest.target_coverage_audit import ProductWindow


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_build_duplicate_active_assets_detects_multiple_primary_rows() -> None:
    rows = [
        _market_file(product="rb", period="1d", version="v1"),
        _market_file(product="rb", period="1d", version="v2"),
    ]
    result = build_duplicate_active_assets(rows)
    assert len(result) == 2
    assert all(item["duplicate_group_size"] == 2 for item in result)


def test_build_quality_issue_register_marks_warning_not_upgradable() -> None:
    rows = build_quality_issue_register([{"product": "bb", "issue_type": "quality_warning", "status": "covered_warning"}])
    assert rows[0]["issue_class"] == "quality_warning"
    assert rows[0]["upgrade_to_passed_allowed"] == "false"


def test_build_stale_metrics_verdict_counts_stage8_6_rows() -> None:
    result = build_stale_metrics_verdict(
        stage8_6_1d_result={
            "matrix": [
                {"gate_status": "active_passed"},
                {"gate_status": "audit_pending"},
            ],
            "product_summary": [
                {"product_status": "active_passed"},
                {"product_status": "active_partial"},
            ],
        }
    )
    assert result["stage8_6_asset_active_passed"] == 1
    assert result["stage8_6_asset_audit_pending"] == 1
    assert result["stage8_6_product_active_passed"] == 1
    assert result["stage8_6_product_active_partial"] == 1


def test_write_final_audit_reports_outputs_required_files(tmp_path) -> None:
    target = {
        "target_asset_catalog": [{"product": "rb"}],
        "asset_physical_inventory": [{"product": "rb"}],
        "target_coverage_matrix": [{"product": "rb", "coverage_status": "covered_passed"}],
        "metadata_consistency_matrix": [{"product": "rb", "status": "covered_passed"}],
        "issue_register": [],
        "coverage_summary": "# summary",
    }
    extended = run_extended_final_audit(
        session=None,
        project_root=tmp_path,
        products=["rb"],
        product_windows={
            "rb": ProductWindow(
                product="rb",
                window_start=date(2020, 1, 2),
                listed_date=date(2009, 3, 27),
                effective_1d_start=date(2020, 1, 2),
                note="test",
            )
        },
        audit_end=date(2026, 7, 10),
        target_coverage_result=target,
        stage8_6_1d_result={"matrix": [], "product_summary": []},
        jm_six_period_result={"matrix": [], "product_summary": []},
        git_commit="test",
        db_snapshot_time="now",
    )
    paths = write_final_audit_reports(output_dir=tmp_path / "out", target_coverage_result=target, extended_result=extended)
    assert (tmp_path / "out" / "DATA_LAYER_FINAL_AUDIT.md").exists()
    assert (tmp_path / "out" / "audit_evidence.json").exists()
    assert (tmp_path / "out" / "weekly_history_audit.csv").exists()
    assert paths["target_asset_catalog"].exists()


def test_build_claim_verdicts_includes_architecture_and_user_claims() -> None:
    coverage = [
        {
            "product": "rb",
            "period": "1m",
            "contract_role": "dominant_main",
            "year": 2023,
            "target_status": "expected",
            "coverage_status": "covered_passed",
        }
    ]
    weekly = [
        {
            "product": "rb",
            "pre_2020_applicable": True,
            "pre_2020_status": "missing_pre2020",
            "post_2020_passed_years": 0,
            "post_2020_expected_years": 1,
            "direct_1w_present": False,
        }
    ]
    claims = build_claim_verdicts(
        products=["rb"],
        product_windows={
            "rb": ProductWindow(
                product="rb",
                window_start=date(2020, 1, 2),
                listed_date=date(2009, 3, 27),
                effective_1d_start=date(2020, 1, 2),
                note="test",
            )
        },
        coverage_matrix=coverage,
        weekly_history=weekly,
        stage8_6_1d_result={"matrix": [], "product_summary": []},
        audit_end=date(2026, 7, 10),
    )
    claim_ids = {item["claim_id"] for item in claims}
    assert "claim_1" in claim_ids
    assert "claim_1_arch" in claim_ids
    assert "claim_4" in claim_ids


def _market_file(*, product: str, period: str, version: str) -> MarketDataFile:
    return MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol=product,
        contract_code=f"{product}.MAIN",
        period=period,
        start_time=datetime(2020, 1, 2, tzinfo=UTC),
        end_time=datetime(2026, 7, 10, tzinfo=UTC),
        file_path=f"/tmp/{product}_{period}_{version}.parquet",
        row_count=10,
        data_version=version,
        data_role="primary",
        quality_status="passed",
    )
