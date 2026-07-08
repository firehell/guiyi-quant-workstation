from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, FuturesTradingParameter, MarketDataFile
from app.services.rqdata_ingest.full_universe_active_gate import (
    audit_full_universe_active_gate,
    write_stage8_6_reports,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_bars(path: Path, *, symbol: str, contract: str, period: str, rows: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "symbol": [symbol] * rows,
            "contract": [contract] * rows,
            "exchange": ["DCE"] * rows,
            "datetime": pd.date_range("2026-07-01", periods=rows, freq="D"),
            "trading_day": pd.date_range("2026-07-01", periods=rows, freq="D").date,
            "open": [100.0 + index for index in range(rows)],
            "high": [101.0 + index for index in range(rows)],
            "low": [99.0 + index for index in range(rows)],
            "close": [100.5 + index for index in range(rows)],
            "volume": [10 + index for index in range(rows)],
            "open_interest": [1000 + index for index in range(rows)],
            "turnover": [10000 + index for index in range(rows)],
            "period": [period] * rows,
            "provider": ["rqdata"] * rows,
            "data_version": [f"test_{symbol}_{contract}_{period}"] * rows,
            "data_role": ["primary"] * rows,
            "quality_status": ["passed"] * rows,
        }
    )
    frame.to_parquet(path, index=False)


def _add_market_file(
    session: Session,
    *,
    path: Path,
    symbol: str,
    contract: str,
    period: str,
    row_count: int = 3,
    quality_status: str = "passed",
    report_status: str = "passed",
) -> MarketDataFile:
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol=symbol,
        contract_code=contract,
        period=period,
        start_time=datetime(2026, 7, 1, tzinfo=UTC),
        end_time=datetime(2026, 7, 3, tzinfo=UTC),
        file_path=str(path),
        row_count=row_count,
        file_size_bytes=path.stat().st_size if path.exists() else 0,
        checksum="a" * 64,
        data_version=f"test_{symbol}_{contract}_{period}",
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
            details={"check_rule_version": "test"},
        )
    )
    return market_file


def _write_dominant_manifest(project_root: Path, *, product: str, period: str, standard_path: Path, row_count: int = 3, quality_status: str = "passed") -> None:
    manifest = project_root / "data" / "manifests" / f"rqdata_{product}_v2_history_20230103_20260707.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "period": period,
                "data_version": f"test_{product}_{period}",
                "provider": "rqdata",
                "source": "rqdata",
                "data_role": "primary",
                "quality_status": quality_status,
                "row_count": row_count,
                "min_datetime": "2026-07-01T00:00:00",
                "max_datetime": "2026-07-03T00:00:00",
                "checksum": "a" * 64,
                "standard_path": str(standard_path),
                "raw_path": "",
                "market_data_file_id": "",
                "data_quality_report_id": "",
                "status": "success",
            }
        ]
    ).to_csv(manifest, index=False)


def _write_actual_manifest(
    project_root: Path,
    *,
    product: str,
    contract: str,
    period: str,
    standard_path: Path,
    row_count: int = 3,
    quality_status: str = "passed",
) -> None:
    manifest = project_root / "data" / "manifests" / f"rqdata_actual_contract_bars_{product}_{contract}_20260701_20260703.csv"
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
                "dominant_mapping_date": "2026-07-03",
                "data_role": "primary",
                "quality_status": quality_status,
                "row_count": row_count,
                "min_datetime": "2026-07-01T00:00:00",
                "max_datetime": "2026-07-03T00:00:00",
                "checksum": "a" * 64,
                "standard_path": str(standard_path),
                "raw_path": "",
                "market_data_file_id": "",
                "data_quality_report_id": "",
                "data_version": f"test_{product}_{contract}_{period}",
                "status": "success",
            }
        ]
    ).to_csv(manifest, index=False)


def _add_complete_params(session: Session, *, symbol: str, contract: str) -> None:
    session.add(
        FuturesTradingParameter(
            contract_code=contract,
            instrument_symbol=symbol,
            exchange_code="DCE",
            trade_date=datetime(2026, 7, 3).date(),
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


def test_audit_marks_dominant_and_actual_1d_assets_active_passed(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    dominant_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d.parquet"
    actual_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=rb/contract=RB2609/RB2609_1d.parquet"
    _write_bars(dominant_path, symbol="rb", contract="rb.MAIN", period="1d")
    _write_bars(actual_path, symbol="rb", contract="RB2609", period="1d")
    _write_dominant_manifest(tmp_path, product="rb", period="1d", standard_path=dominant_path)
    _write_actual_manifest(tmp_path, product="rb", contract="RB2609", period="1d", standard_path=actual_path)

    with SessionLocal() as session:
        _add_market_file(session, path=dominant_path, symbol="rb", contract="rb.MAIN", period="1d")
        _add_market_file(session, path=actual_path, symbol="rb", contract="RB2609", period="1d")
        _add_complete_params(session, symbol="rb", contract="RB2609")
        session.commit()

        result = audit_full_universe_active_gate(session=session, project_root=tmp_path, products=["rb"])

    statuses = {(row["asset_scope"], row["period"]): row["gate_status"] for row in result["matrix"]}
    assert statuses == {("dominant_main", "1d"): "active_passed", ("actual_contract", "1d"): "active_passed"}
    assert result["product_summary"][0]["product_status"] == "active_passed"
    assert result["stage9_readiness"][0]["stage9_status"] == "stage9_blocked"
    assert "missing_entry_periods:5m,15m" in result["stage9_readiness"][0]["blocked_reasons"]


def test_audit_keeps_product_partial_when_duckdb_row_count_differs_from_manifest(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    dominant_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d.parquet"
    _write_bars(dominant_path, symbol="rb", contract="rb.MAIN", period="1d", rows=2)
    _write_dominant_manifest(tmp_path, product="rb", period="1d", standard_path=dominant_path, row_count=3)

    with SessionLocal() as session:
        _add_market_file(session, path=dominant_path, symbol="rb", contract="rb.MAIN", period="1d", row_count=3)
        session.commit()

        result = audit_full_universe_active_gate(session=session, project_root=tmp_path, products=["rb"])

    assert result["matrix"][0]["gate_status"] == "audit_pending"
    assert "duckdb_row_count_mismatch" in result["matrix"][0]["blocked_reasons"]
    assert result["product_summary"][0]["product_status"] == "audit_pending"


def test_audit_marks_manifest_quality_failed_as_failed_even_when_file_exists(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    dominant_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d.parquet"
    _write_bars(dominant_path, symbol="rb", contract="rb.MAIN", period="1d")
    _write_dominant_manifest(tmp_path, product="rb", period="1d", standard_path=dominant_path, quality_status="failed")

    with SessionLocal() as session:
        _add_market_file(session, path=dominant_path, symbol="rb", contract="rb.MAIN", period="1d", quality_status="failed", report_status="failed")
        session.commit()

        result = audit_full_universe_active_gate(session=session, project_root=tmp_path, products=["rb"])

    assert result["matrix"][0]["gate_status"] == "failed"
    assert "manifest_quality_failed" in result["matrix"][0]["blocked_reasons"]
    assert result["product_summary"][0]["product_status"] == "failed"


def test_audit_marks_product_missing_when_no_manifest_or_db_rows_exist(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        result = audit_full_universe_active_gate(session=session, project_root=tmp_path, products=["rb"])

    assert result["matrix"][0]["gate_status"] == "missing"
    assert result["product_summary"][0]["product_status"] == "missing"
    assert result["stage9_readiness"][0]["stage9_status"] == "stage9_blocked"


def test_audit_uses_processed_summary_as_audit_pending_evidence_when_manifest_is_missing(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    dominant_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d.parquet"
    _write_bars(dominant_path, symbol="rb", contract="rb.MAIN", period="1d")
    summary_path = tmp_path / "data" / "processed" / "v1b" / "rb" / "rb_v2_parquet_20230103_20260707.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "symbol": "rb",
                "contract": "rb.MAIN",
                "periods": {
                    "1d": {
                        "data_version": "test_rb_1d",
                        "quality_status": "passed",
                        "standard": {
                            "path": str(dominant_path),
                            "row_count": 3,
                            "min_datetime": "2026-07-01T00:00:00",
                            "max_datetime": "2026-07-03T00:00:00",
                            "checksum": "a" * 64,
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with SessionLocal() as session:
        _add_market_file(session, path=dominant_path, symbol="rb", contract="rb.MAIN", period="1d")
        session.commit()

        result = audit_full_universe_active_gate(session=session, project_root=tmp_path, products=["rb"])

    assert result["matrix"][0]["gate_status"] == "audit_pending"
    assert "missing_manifest" in result["matrix"][0]["blocked_reasons"]
    assert result["matrix"][0]["standard_path"] == str(dominant_path)


def test_write_reports_outputs_csv_and_markdown(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    dominant_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=rb/contract=rb.MAIN/rb_MAIN_1d.parquet"
    _write_bars(dominant_path, symbol="rb", contract="rb.MAIN", period="1d")
    _write_dominant_manifest(tmp_path, product="rb", period="1d", standard_path=dominant_path)

    with SessionLocal() as session:
        _add_market_file(session, path=dominant_path, symbol="rb", contract="rb.MAIN", period="1d")
        session.commit()
        result = audit_full_universe_active_gate(session=session, project_root=tmp_path, products=["rb"])

    output_paths = write_stage8_6_reports(result, output_dir=tmp_path / "reports")

    assert output_paths["matrix"].name == "stage8_6_active_gate_matrix.csv"
    assert output_paths["product_summary"].exists()
    assert output_paths["stage9_readiness"].exists()
    assert "Stage 8.6 Active Gate Summary" in output_paths["summary_markdown"].read_text(encoding="utf-8")
    matrix = pd.read_csv(output_paths["matrix"])
    assert matrix.loc[0, "product"] == "rb"


def test_audit_does_not_write_market_data_or_quality_rows(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        before_files = session.scalars(select(MarketDataFile)).all()
        result = audit_full_universe_active_gate(session=session, project_root=tmp_path, products=["rb"])
        after_files = session.scalars(select(MarketDataFile)).all()

    assert result["mode"] == "stage8_6_active_gate_audit"
    assert before_files == after_files == []
