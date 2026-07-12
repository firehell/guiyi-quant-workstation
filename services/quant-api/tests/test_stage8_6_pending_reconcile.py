from pathlib import Path

import pandas as pd
import pytest

from app.services.rqdata_ingest.stage8_6_pending_reconcile import reconcile_stage8_6_pending


def _write_fixture(path: Path) -> None:
    rows = [
        {
            "product": "bb",
            "asset_scope": "dominant_main",
            "contract": "bb.MAIN",
            "period": "1d",
            "gate_status": "audit_pending",
            "blocked_reasons": "manifest_quality_warning,db_quality_warning,quality_report_warning,quality_report_abnormal_price",
            "manifest_quality_status": "warning",
            "db_quality_status": "warning",
            "standard_path": "/tmp/bb.parquet",
        },
        {
            "product": "l",
            "asset_scope": "actual_contract",
            "contract": "L2609F",
            "period": "1d",
            "gate_status": "audit_pending",
            "blocked_reasons": "missing_market_data_file",
            "manifest_quality_status": "passed",
            "db_quality_status": "passed",
            "standard_path": "/tmp/L2609F.parquet",
        },
        {
            "product": "l_f",
            "asset_scope": "actual_contract",
            "contract": "L2609F",
            "period": "1d",
            "gate_status": "active_passed",
            "blocked_reasons": "",
            "manifest_quality_status": "passed",
            "db_quality_status": "passed",
            "standard_path": "/tmp/L2609F.parquet",
        },
    ]
    for product in ("rs", "wh", "wr", "zc"):
        rows.append(
            {
                "product": product,
                "asset_scope": "dominant_main",
                "contract": f"{product}.MAIN",
                "period": "1d",
                "gate_status": "audit_pending",
                "blocked_reasons": "manifest_quality_warning,db_quality_warning,quality_report_warning,quality_report_abnormal_price",
                "manifest_quality_status": "warning",
                "db_quality_status": "warning",
                "standard_path": f"/tmp/{product}.parquet",
            }
        )
    for product, contract in (("pp", "PP2609F"), ("v", "V2609F")):
        canonical = {"pp": "pp_f", "v": "v_f"}[product]
        rows.extend(
            [
                {
                    "product": product,
                    "asset_scope": "actual_contract",
                    "contract": contract,
                    "period": "1d",
                    "gate_status": "audit_pending",
                    "blocked_reasons": "missing_market_data_file",
                    "manifest_quality_status": "passed",
                    "db_quality_status": "passed",
                    "standard_path": f"/tmp/{contract}.parquet",
                },
                {
                    "product": canonical,
                    "asset_scope": "actual_contract",
                    "contract": contract,
                    "period": "1d",
                    "gate_status": "active_passed",
                    "blocked_reasons": "",
                    "manifest_quality_status": "passed",
                    "db_quality_status": "passed",
                    "standard_path": f"/tmp/{contract}.parquet",
                },
            ]
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def test_reconcile_stage8_6_pending_classifies_eight_rows(tmp_path: Path) -> None:
    matrix_file = tmp_path / "stage8_6_active_gate_matrix.csv"
    _write_fixture(matrix_file)
    result = reconcile_stage8_6_pending(matrix_file=matrix_file)
    assert result["pending_count"] == 8
    assert result["disposition_counts"]["accepted_warning"] == 5
    assert result["disposition_counts"]["registration_not_needed"] == 3
    assert result["requires_apply_gate_count"] == 0
