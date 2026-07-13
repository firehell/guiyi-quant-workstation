from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import (
    DataQualityReport,
    FuturesContinuousContractMap,
    FuturesContractUniverse,
    FuturesTradingParameter,
    MainContractMap,
    MarketDataFile,
    TradingCalendar,
    TradingSession,
)
from app.services.rqdata_ingest.target_coverage_audit import (
    ProductWindow,
    audit_target_coverage,
    build_rev1_exact_statistics,
    validate_rev1_matrix,
    write_target_coverage_reports,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _window(product: str = "rb") -> dict[str, ProductWindow]:
    return {
        product: ProductWindow(
            product=product,
            window_start=date(2020, 1, 2),
            listed_date=date(2009, 3, 27),
            effective_1d_start=date(2020, 1, 2),
            note="test",
        )
    }


def _write_bars(path: Path, *, symbol: str = "rb", contract: str = "rb.MAIN", period: str = "1d", rows: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "symbol": [symbol] * rows,
            "contract": [contract] * rows,
            "exchange": ["SHFE"] * rows,
            "datetime": pd.date_range("2020-01-02", periods=rows, freq="D"),
            "trading_day": pd.date_range("2020-01-02", periods=rows, freq="D").date,
            "open": [100.0 + index for index in range(rows)],
            "high": [101.0 + index for index in range(rows)],
            "low": [99.0 + index for index in range(rows)],
            "close": [100.5 + index for index in range(rows)],
            "volume": [10 + index for index in range(rows)],
            "open_interest": [1000 + index for index in range(rows)],
            "period": [period] * rows,
            "provider": ["rqdata"] * rows,
            "data_role": ["primary"] * rows,
            "quality_status": ["passed"] * rows,
        }
    )
    frame.to_parquet(path, index=False)


def _write_manifest(
    project_root: Path,
    path: Path,
    *,
    product: str = "rb",
    contract: str = "rb.MAIN",
    period: str = "1d",
    rows: int = 3,
    quality_status: str = "passed",
) -> None:
    manifest = project_root / "data" / "manifests" / f"rqdata_{product}_v2_history_20200102_20260710.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "period": period,
                "provider": "rqdata",
                "source": "rqdata",
                "data_role": "primary",
                "quality_status": quality_status,
                "row_count": rows,
                "min_datetime": "2020-01-02T00:00:00",
                "max_datetime": "2020-01-04T00:00:00",
                "checksum": "a" * 64,
                "standard_path": str(path),
                "status": "success",
                "data_version": f"test_{product}_{period}",
            }
        ]
    ).to_csv(manifest, index=False)


def _write_actual_contract_manifest(
    project_root: Path,
    path: Path,
    *,
    product: str = "l_f",
    contract: str = "L2602F",
    period: str = "1d",
    rows: int = 3,
) -> None:
    manifest = project_root / "data" / "manifests" / f"rqdata_actual_contract_bars_{product}_{contract}_20200102_20260710.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "period": period,
                "provider": "rqdata",
                "source": "rqdata",
                "product": product,
                "continuous_contract": f"{product}.MAIN",
                "actual_contract": contract,
                "data_role": "primary",
                "quality_status": "passed",
                "row_count": rows,
                "min_datetime": "2020-01-02T00:00:00",
                "max_datetime": "2020-01-04T00:00:00",
                "checksum": "a" * 64,
                "standard_path": str(path),
                "status": "success",
                "data_version": f"test_{product}_{contract}_{period}",
            }
        ]
    ).to_csv(manifest, index=False)


def _write_processed_summary(
    project_root: Path,
    path: Path,
    *,
    product: str = "rb",
    contract: str = "rb.MAIN",
    period: str = "1d",
    quality_status: str = "failed",
) -> None:
    summary = project_root / "data" / "processed" / "v1b" / product / f"{product}_v2_parquet_20200102_20260710.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        json.dumps(
            {
                "symbol": product,
                "contract": contract,
                "periods": {
                    period: {
                        "quality_status": quality_status,
                        "data_version": f"test_{product}_{period}",
                        "standard": {
                            "path": str(path),
                            "row_count": 3,
                            "checksum": "a" * 64,
                            "min_datetime": "2020-01-02T00:00:00",
                            "max_datetime": "2020-01-04T00:00:00",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _add_market_file(
    session: Session,
    path: Path,
    *,
    symbol: str = "rb",
    contract: str = "rb.MAIN",
    period: str = "1d",
    rows: int = 3,
    quality_status: str = "passed",
    report_status: str = "passed",
) -> None:
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol=symbol,
        contract_code=contract,
        period=period,
        start_time=datetime(2020, 1, 2, tzinfo=UTC),
        end_time=datetime(2020, 1, 4, tzinfo=UTC),
        file_path=str(path),
        row_count=rows,
        file_size_bytes=path.stat().st_size if path.exists() else 0,
        checksum="a" * 64,
        data_version=f"test_{symbol}_{period}",
        data_role="primary",
        quality_status=quality_status,
    )
    session.add(market_file)
    session.flush()
    session.add(
        DataQualityReport(
            file_id=market_file.id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol=symbol,
            contract_code=contract,
            period=period,
            start_time=market_file.start_time,
            end_time=market_file.end_time,
            status=report_status,
            missing_bars=0,
            duplicated_bars=0,
            abnormal_price_count=0,
            abnormal_volume_count=0,
            details={},
        )
    )


def _add_superseded_market_file(
    session: Session,
    path: Path,
    *,
    symbol: str = "rb",
    contract: str = "rb.MAIN",
    period: str = "1d",
    rows: int = 3,
    quality_status: str = "passed",
) -> None:
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol=symbol,
        contract_code=contract,
        period=period,
        start_time=datetime(2020, 1, 2, tzinfo=UTC),
        end_time=datetime(2020, 1, 4, tzinfo=UTC),
        file_path=str(path),
        row_count=rows,
        file_size_bytes=path.stat().st_size if path.exists() else 0,
        checksum="b" * 64,
        data_version=f"test_{symbol}_{period}_superseded",
        data_role="superseded",
        quality_status=quality_status,
    )
    session.add(market_file)


def _add_metadata(session: Session, *, product: str = "rb", contract: str = "RB2005") -> None:
    session.add(MainContractMap(instrument_symbol=product, trade_date=date(2020, 1, 2), rank=1, contract_code=contract, provider="rqdata", data_version="test"))
    session.add(FuturesContractUniverse(instrument_symbol=product, trade_date=date(2020, 1, 2), contract_code=contract, provider="rqdata", data_version="test"))
    session.add(
        FuturesContinuousContractMap(
            instrument_symbol=product,
            trade_date=date(2020, 1, 2),
            continuous_type="main",
            contract_code=contract,
            provider="rqdata",
            data_version="test",
        )
    )
    session.add(
        FuturesTradingParameter(
            contract_code=contract,
            instrument_symbol=product,
            exchange_code="SHFE",
            trade_date=date(2020, 1, 2),
            long_margin_ratio=Decimal("0.12"),
            short_margin_ratio=Decimal("0.13"),
            open_commission=Decimal("0.0001"),
            close_commission=Decimal("0.0001"),
            close_today_commission=Decimal("0.0002"),
            commission_type="by_money",
            price_tick=Decimal("1"),
            contract_multiplier=10,
            provider="rqdata",
            data_version="test",
        )
    )
    session.add(TradingCalendar(exchange_code="SHFE", trade_date=date(2020, 1, 2), is_trading_day=True, has_night_session=True, provider="rqdata"))
    session.add(
        TradingSession(
            exchange_code="SHFE",
            instrument_symbol=product,
            session_name="day",
            start_time=time(9, 0),
            end_time=time(15, 0),
            provider="rqdata",
        )
    )


def test_target_coverage_marks_complete_dominant_asset_passed(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    parquet_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=SHFE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d.parquet"
    _write_bars(parquet_path)
    _write_manifest(tmp_path, parquet_path)

    with SessionLocal() as session:
        _add_market_file(session, parquet_path)
        _add_metadata(session)
        session.commit()

        result = audit_target_coverage(session=session, project_root=tmp_path, product_windows=_window(), audit_end=date(2020, 1, 4))

    row = next(
        item
        for item in result["target_coverage_matrix"]
        if item["product"] == "rb" and item["symbol_or_contract"] == "rb.MAIN" and item["period"] == "1d" and item["year"] == 2020
    )
    assert row["actual_status"] == "covered_passed"
    assert row["status"] == "covered_passed"
    assert row["expected"] is True
    assert row["evidence_id"]
    assert result["mode"] == "target_coverage_audit"
    assert result["writes_database"] is False


def test_target_coverage_marks_manifest_without_db_as_missing(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    parquet_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=SHFE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d.parquet"
    _write_bars(parquet_path)
    _write_manifest(tmp_path, parquet_path)

    with SessionLocal() as session:
        result = audit_target_coverage(session=session, project_root=tmp_path, product_windows=_window(), audit_end=date(2020, 1, 4))

    row = next(item for item in result["target_coverage_matrix"] if item["period"] == "1d" and item["year"] == 2020)
    assert row["actual_status"] == "missing"
    assert row["status_reason"] == "missing_db_registration"
    assert row["recommended_next_task"] == "controlled_metadata_registration_plan"


def test_target_coverage_merges_underscore_actual_contract_product_with_db_evidence(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    parquet_path = (
        tmp_path
        / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=l_f/contract=L2602F/L2602F_1d.parquet"
    )
    _write_bars(parquet_path, symbol="l_f", contract="L2602F")
    _write_actual_contract_manifest(tmp_path, parquet_path)

    with SessionLocal() as session:
        _add_market_file(session, parquet_path, symbol="l_f", contract="L2602F")
        session.commit()
        result = audit_target_coverage(
            session=session,
            project_root=tmp_path,
            product_windows=_window("l_f"),
            audit_end=date(2020, 1, 4),
        )

    row = next(
        item
        for item in result["target_coverage_matrix"]
        if item["product"] == "l_f" and item["symbol_or_contract"] == "L2602F" and item["period"] == "1d"
    )
    assert row["actual_status"] == "covered_passed"
    assert row["evidence_source"] == "db_market_data_file,manifest"


def test_target_coverage_uses_active_quality_before_stale_processed_summary(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    parquet_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=SHFE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d.parquet"
    _write_bars(parquet_path)
    _write_manifest(tmp_path, parquet_path, quality_status="warning")
    _write_processed_summary(tmp_path, parquet_path, quality_status="failed")

    with SessionLocal() as session:
        _add_market_file(session, parquet_path, quality_status="warning", report_status="warning")
        _add_metadata(session)
        session.commit()

        result = audit_target_coverage(session=session, project_root=tmp_path, product_windows=_window(), audit_end=date(2020, 1, 4))

    row = next(item for item in result["target_coverage_matrix"] if item["period"] == "1d" and item["year"] == 2020)
    assert row["actual_status"] == "covered_warning"
    assert row["status_reason"] == "quality_warning"
    assert row["quality_status"] == "warning"


def test_target_coverage_marks_missing_physical_file(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    missing_path = tmp_path / "missing.parquet"
    _write_manifest(tmp_path, missing_path)

    with SessionLocal() as session:
        _add_market_file(session, missing_path)
        session.commit()
        result = audit_target_coverage(session=session, project_root=tmp_path, product_windows=_window(), audit_end=date(2020, 1, 4))

    row = next(item for item in result["target_coverage_matrix"] if item["period"] == "1d" and item["year"] == 2020)
    assert row["actual_status"] == "missing"
    assert row["status_reason"] == "missing_physical_file"


def test_metadata_matrix_records_gap_without_db_snapshot(tmp_path: Path) -> None:
    result = audit_target_coverage(
        session=None,
        project_root=tmp_path,
        product_windows=_window(),
        audit_end=date(2020, 1, 4),
        db_snapshot_source="manifest_only",
        db_error="test db unavailable",
    )

    metadata_rows = [row for row in result["metadata_consistency_matrix"] if row["year"] == 2020]
    assert metadata_rows
    assert {row["status"] for row in metadata_rows} == {"missing"}
    assert {row["issue_type"] for row in metadata_rows} == {"db_unavailable"}


def test_write_target_coverage_reports_outputs_all_files(tmp_path: Path) -> None:
    result = audit_target_coverage(session=None, project_root=tmp_path, product_windows=_window(), audit_end=date(2020, 1, 4))
    outputs = write_target_coverage_reports(result, output_dir=tmp_path / "reports")

    assert set(outputs) == {
        "target_asset_catalog",
        "asset_physical_inventory",
        "target_coverage_matrix",
        "metadata_consistency_matrix",
        "issue_register",
        "coverage_summary",
        "target_coverage_summary_json",
        "superseded_classification",
    }
    assert all(path.exists() for path in outputs.values())
    assert "Target Coverage Audit Summary" in outputs["coverage_summary"].read_text(encoding="utf-8")
    assert result["target_asset_catalog"]
    assert result["issue_register"]


def test_missing_expected_blocks_final_gate_and_requires_reason(tmp_path: Path) -> None:
    result = audit_target_coverage(session=None, project_root=tmp_path, product_windows=_window(), audit_end=date(2020, 1, 4))

    row = next(item for item in result["target_coverage_matrix"] if item["period"] == "1m" and item["year"] == 2020)
    assert row["actual_status"] == "missing_expected"
    assert row["status_reason"] == "pre_2023_minute_target_requires_DATA_1M_003_or_HIST_GATE_001"

    validation = validate_rev1_matrix(result["target_coverage_matrix"], final_gate=True)
    assert validation["passed"] is False
    assert "missing_expected" in validation["blocking_statuses"]


def test_superseded_without_valid_primary_is_not_covered_passed(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    superseded_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=SHFE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d_old.parquet"
    _write_bars(superseded_path)
    _write_manifest(tmp_path, superseded_path)

    with SessionLocal() as session:
        _add_superseded_market_file(session, superseded_path)
        session.commit()
        result = audit_target_coverage(session=session, project_root=tmp_path, product_windows=_window(), audit_end=date(2020, 1, 4))

    row = next(item for item in result["target_coverage_matrix"] if item["period"] == "1d" and item["year"] == 2020)
    assert row["actual_status"] == "missing"
    assert row["status_reason"] == "superseded_without_valid_primary"
    assert "superseded" not in {item["actual_status"] for item in result["target_coverage_matrix"]}
    assert result["superseded_classification"]["target_without_valid_primary"] == 1


def test_superseded_with_valid_primary_passes_by_primary_evidence_only(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    primary_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=SHFE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d_new.parquet"
    superseded_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=SHFE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d_old.parquet"
    _write_bars(primary_path)
    _write_bars(superseded_path)
    _write_manifest(tmp_path, primary_path)

    with SessionLocal() as session:
        _add_market_file(session, primary_path)
        _add_superseded_market_file(session, superseded_path)
        session.commit()
        result = audit_target_coverage(session=session, project_root=tmp_path, product_windows=_window(), audit_end=date(2020, 1, 4))

    row = next(item for item in result["target_coverage_matrix"] if item["period"] == "1d" and item["year"] == 2020)
    assert row["actual_status"] == "covered_passed"
    assert row["data_role"] == "primary"
    assert result["superseded_classification"]["target_has_valid_primary"] == 1


def test_approved_warning_requires_approval_evidence() -> None:
    rows = [
        {
            "product": "rb",
            "contract_role": "dominant_main",
            "period": "1d",
            "year": 2020,
            "expected": True,
            "actual_status": "approved_warning",
            "status_reason": "quality_warning",
            "evidence_id": "",
            "data_version": "v1",
            "quality_status": "warning",
            "missing_count": 0,
            "na_reason": "",
            "recommended_next_task": "",
            "audit_end": "2026-07-10",
        }
    ]
    validation = validate_rev1_matrix(rows)
    assert validation["passed"] is False
    assert "approved_warning_without_evidence" in validation["errors"]


def test_required_matrix_status_fields_are_not_nullable() -> None:
    rows = [
        {
            "product": "rb",
            "contract_role": "dominant_main",
            "period": "1d",
            "year": 2020,
            "expected": True,
            "actual_status": None,
            "status_reason": "",
            "evidence_id": "",
            "data_version": "",
            "quality_status": "",
            "missing_count": 0,
            "na_reason": "",
            "recommended_next_task": "target_coverage_gap_triage",
            "audit_end": "2026-07-10",
        }
    ]
    validation = validate_rev1_matrix(rows)
    assert validation["passed"] is False
    assert "status_null" in validation["errors"]


def test_missing_not_applicable_and_missing_expected_require_explanations() -> None:
    rows = [
        {
            "product": "rb",
            "contract_role": "dominant_main",
            "period": "1d",
            "year": 2020,
            "expected": True,
            "actual_status": "missing",
            "status_reason": "missing_target_asset",
            "evidence_id": "",
            "data_version": "",
            "quality_status": "",
            "missing_count": 1,
            "na_reason": "",
            "recommended_next_task": "",
            "audit_end": "2026-07-10",
        },
        {
            "product": "rb",
            "contract_role": "actual_contract",
            "period": "1w",
            "year": 2020,
            "expected": False,
            "actual_status": "not_applicable",
            "status_reason": "not_applicable",
            "evidence_id": "",
            "data_version": "",
            "quality_status": "",
            "missing_count": 0,
            "na_reason": "",
            "recommended_next_task": "",
            "audit_end": "2026-07-10",
        },
        {
            "product": "rb",
            "contract_role": "dominant_main",
            "period": "1m",
            "year": 2020,
            "expected": True,
            "actual_status": "missing_expected",
            "status_reason": "",
            "evidence_id": "",
            "data_version": "",
            "quality_status": "",
            "missing_count": 1,
            "na_reason": "",
            "recommended_next_task": "DATA-1M-003",
            "audit_end": "2026-07-10",
        },
    ]
    validation = validate_rev1_matrix(rows)
    assert validation["passed"] is False
    assert "missing_without_recommended_next_task" in validation["errors"]
    assert "not_applicable_without_na_reason" in validation["errors"]
    assert "missing_expected_without_reason" in validation["errors"]


def test_exact_statistics_match_matrix_rows(tmp_path: Path) -> None:
    result = audit_target_coverage(session=None, project_root=tmp_path, product_windows=_window(), audit_end=date(2020, 1, 4))
    stats = build_rev1_exact_statistics(result["target_coverage_matrix"])
    assert stats["total_rows"] == len(result["target_coverage_matrix"])
    assert sum(stats["actual_status_counts"].values()) == len(result["target_coverage_matrix"])
