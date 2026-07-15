from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.services.rqdata_ingest.daily_weekly_overlap_batch import run_contract_audit, run_jm_pilot_overlap
from app.services.rqdata_ingest.residual_root_cause_audit import run_residual_root_cause_audit
from app.services.rqdata_ingest.schema_contract import (
    CANONICAL_BAR_SCHEMA_VERSION,
    aggregate_weekly_from_1m_readonly,
    build_schema_fingerprint,
    compare_daily_weekly_overlap,
    derive_sidecar_fields,
    infer_trading_day,
    validate_canonical_bar_contract,
    validate_canonical_bar_schema,
)


def _write_bar(path: Path, *, period: str = "1d", close: float = 1.5, trading_day: str | None = None) -> None:
    trading = trading_day or "2020-01-02"
    pd.DataFrame(
        {
            "datetime": pd.to_datetime([f"{trading} 00:00:00"]),
            "trading_day": pd.to_datetime([trading]).date,
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [close],
            "volume": [10],
            "turnover": [100.0],
            "open_interest": [100.0],
            "symbol": ["rb"],
            "contract": ["rb.MAIN"],
            "period": [period],
            "provider": ["rqdata"],
            "source_interval": ["1m"] if period == "1d" else None,
            "data_role": ["primary"],
            "quality_status": ["passed"],
            "data_version": ["test_v1"],
        }
    ).dropna(axis=1).to_parquet(path, index=False)


def test_validate_canonical_bar_schema_passes_required_columns(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    _write_bar(path)
    result = validate_canonical_bar_schema(path)
    assert result["status"] == "passed"
    assert result["missing_columns"] == []
    assert result["schema_version"] == CANONICAL_BAR_SCHEMA_VERSION
    assert result["fingerprint"]


def test_validate_canonical_bar_contract_reports_sidecar_gap_for_embedded_only(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    _write_bar(path)
    result = validate_canonical_bar_contract(path, period="1d", contract_role="dominant_main")
    assert result["embedded_status"] == "passed"
    assert result["sidecar_status"] == "passed"
    assert result["sidecar"]["product"] == "rb"
    assert result["sidecar"]["continuous_contract"] == "rb.MAIN"


def test_build_schema_fingerprint_is_stable() -> None:
    first = build_schema_fingerprint({"close": "float", "open": "float"})
    second = build_schema_fingerprint({"open": "float", "close": "float"})
    assert first == second


def test_infer_trading_day_handles_night_session() -> None:
    assert infer_trading_day(pd.Timestamp("2020-01-02 21:30:00")) == pd.Timestamp("2020-01-03").date()


def test_compare_daily_weekly_overlap_full_range_detects_block(tmp_path: Path) -> None:
    aggregated = tmp_path / "agg.parquet"
    direct = tmp_path / "direct.parquet"
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "trading_day": pd.to_datetime(["2020-01-02", "2020-01-03"]).date,
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "volume": [10, 20],
            "turnover": [100.0, 200.0],
            "open_interest": [100.0, 200.0],
        }
    )
    frame.to_parquet(aggregated, index=False)
    mismatch = frame.copy()
    mismatch.loc[0, "close"] = 9.9
    mismatch.to_parquet(direct, index=False)

    result = compare_daily_weekly_overlap(aggregated_path=aggregated, direct_path=direct, period="1d")
    assert result["overlap_rows"] == 2
    assert result["status"] == "failed"
    assert result["block_mismatches"] >= 1


def test_compare_daily_weekly_overlap_allows_datetime_alignment_warning(tmp_path: Path) -> None:
    aggregated = tmp_path / "agg.parquet"
    direct = tmp_path / "direct.parquet"
    agg = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2020-01-02 00:00:00"]),
            "trading_day": pd.to_datetime(["2020-01-02"]).date,
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [10],
            "turnover": [100.0],
            "open_interest": [100.0],
        }
    )
    direct_frame = agg.copy()
    direct_frame["datetime"] = pd.to_datetime(["2020-01-02 15:00:00"])
    agg.to_parquet(aggregated, index=False)
    direct_frame.to_parquet(direct, index=False)

    result = compare_daily_weekly_overlap(aggregated_path=aggregated, direct_path=direct, period="1d")
    assert result["status"] == "warning"
    assert result["warning_mismatches"] >= 1


def test_aggregate_weekly_from_1m_readonly(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["rb", "rb"],
            "contract": ["rb.MAIN", "rb.MAIN"],
            "exchange": ["SHFE", "SHFE"],
            "vt_symbol": ["rb.MAIN.SHFE", "rb.MAIN.SHFE"],
            "datetime": pd.to_datetime(["2020-01-02 09:01:00", "2020-01-03 09:01:00"]),
            "trading_day": pd.to_datetime(["2020-01-02", "2020-01-03"]).date,
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "volume": [10, 20],
            "turnover": [100.0, 200.0],
            "open_interest": [100.0, 200.0],
            "source": ["rqdata", "rqdata"],
            "provider": ["rqdata", "rqdata"],
            "data_role": ["primary", "primary"],
            "data_version": ["v1", "v1"],
            "source_contract": ["rb.MAIN", "rb.MAIN"],
            "created_at": [datetime.now(UTC), datetime.now(UTC)],
        }
    )
    weekly = aggregate_weekly_from_1m_readonly(frame)
    assert len(weekly) == 1
    assert weekly.iloc[0]["period"] == "1w"
    assert int(weekly.iloc[0]["volume"]) == 30


def test_derive_sidecar_fields_for_actual_contract() -> None:
    sidecar = derive_sidecar_fields(symbol="jm", contract="JM2609", contract_role="actual_contract")
    assert sidecar["actual_contract"] == "JM2609"
    assert sidecar["continuous_contract"] == "jm.MAIN"


def test_run_contract_audit_on_sealing_inventory(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    sealing_dir = project_root / "data/reports/data_sealing_audit_20260712_162941"
    if not sealing_dir.exists():
        return
    result = run_contract_audit(sealing_dir=sealing_dir, output_dir=tmp_path / "contract", limit_rows=3)
    assert result["rows"]
    assert (tmp_path / "contract" / "schema_contract_matrix.csv").exists()


def test_run_residual_root_cause_audit_generates_registers(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    sealing_dir = project_root / "data/reports/data_sealing_audit_20260712_162941"
    if not sealing_dir.exists():
        return
    result = run_residual_root_cause_audit(
        project_root=project_root,
        sealing_dir=sealing_dir,
        output_dir=tmp_path / "root_cause",
        multi_primary_csv=project_root / "data/reports/multi_primary_inventory_latest/multi_primary_inventory.csv",
        db_status="unavailable",
    )
    assert result["root_cause_count"] > 0
    assert (tmp_path / "root_cause" / "root_cause_register.csv").exists()
    assert (tmp_path / "root_cause" / "repair_classification.csv").exists()
    quality_repairs = [
        row
        for row in _read_csv(tmp_path / "root_cause" / "repair_classification.csv")
        if row.get("anomaly_type") == "quality_warning"
    ]
    assert quality_repairs
    assert all(row["repair_type"] == "no_action" for row in quality_repairs)


def test_run_jm_pilot_overlap_when_inventory_exists(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    sealing_dir = project_root / "data/reports/data_sealing_audit_20260712_162941"
    if not sealing_dir.exists():
        return
    result = run_jm_pilot_overlap(sealing_dir=sealing_dir, output_dir=tmp_path / "jm")
    assert "periods" in result
    assert (tmp_path / "jm" / "JM-PILOT-OVERLAP-SUMMARY.md").exists()


def _read_csv(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
