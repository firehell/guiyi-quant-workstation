from __future__ import annotations

from pathlib import Path

from app.services.rqdata_ingest.residual_root_cause_audit import (
    _audit_duplicates,
    _audit_quality_warnings,
    _is_subset_parquet,
    run_residual_root_cause_audit,
)


def test_audit_duplicates_splits_acb_and_weekly_patterns() -> None:
    rows = [
        {
            "physical_path": "/data/parquet/.../period=15m/.../IF2607_15m.parquet",
            "data_versions": "rq_acb_if_IF2607_15m_v1;rqdata_actual_contract_bars_if_IF2607_15m_v1",
            "db_file_ids": "1;2",
        },
        {
            "physical_path": "/data/parquet/.../period=1w/.../ad_MAIN_1w_v2.parquet",
            "data_versions": "rqdata_ad_standard_1w_v2;rqdata_ad_standard_1w_v2",
            "db_file_ids": "44115;55569",
        },
    ]
    result = _audit_duplicates(rows)
    assert result["details"]["acb_duplicate_count"] == 1
    assert result["details"]["weekly_duplicate_count"] == 1
    assert len(result["register"]) == 2


def test_audit_quality_warnings_forbids_upgrade() -> None:
    issues = [
        {"issue_type": "quality_warning", "product": "bb", "period": "1d"},
        {"issue_type": "quality_warning", "product": "bb", "period": "1w"},
    ]
    result = _audit_quality_warnings(issues)
    assert result["details"]["quality_warning_count"] == 2
    assert result["details"]["upgrade_forbidden"] is True
    assert all(item["repair_type"] == "no_action" for item in result["repairs"])


def test_is_subset_parquet_detects_full_overlap(tmp_path: Path) -> None:
    import pandas as pd

    short = tmp_path / "short.parquet"
    long = tmp_path / "long.parquet"
    short_frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "volume": [10, 20],
        }
    )
    long_frame = pd.concat(
        [
            short_frame,
            pd.DataFrame(
                {
                    "datetime": pd.to_datetime(["2020-01-06"]),
                    "open": [3.0],
                    "high": [4.0],
                    "low": [2.5],
                    "close": [3.5],
                    "volume": [30],
                }
            ),
        ],
        ignore_index=True,
    )
    short_frame.to_parquet(short, index=False)
    long_frame.to_parquet(long, index=False)
    assert _is_subset_parquet(short, long) is True
    assert _is_subset_parquet(long, short) is False


def test_run_residual_root_cause_audit_writes_gate_register(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    sealing_dir = project_root / "data/reports/data_sealing_audit_20260712_162941"
    if not sealing_dir.exists():
        return
    result = run_residual_root_cause_audit(
        project_root=project_root,
        sealing_dir=sealing_dir,
        output_dir=tmp_path / "audit",
        db_status="unavailable",
    )
    assert result["gate_count"] > 0
    assert (tmp_path / "audit" / "gate_register.csv").exists()
    assert (tmp_path / "audit" / "RESIDUAL-ROOT-CAUSE-SUMMARY.md").exists()
