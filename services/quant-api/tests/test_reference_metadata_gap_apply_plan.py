from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.rqdata_ingest.reference_metadata_gap_apply_plan import build_reference_metadata_gap_apply_plan


def test_reference_metadata_gap_apply_plan_groups_candidates_by_dataset_and_year(tmp_path: Path) -> None:
    ledger = tmp_path / "reference_metadata_gap_ledger.csv"
    pd.DataFrame(
        [
            {
                "classification": "needs_contract_universe_sync",
                "product": "rb",
                "year": 2020,
                "dataset": "contract_universe",
                "candidate_start_date": "2020-01-01",
                "candidate_end_date": "2020-12-31",
                "db_row_count_for_year": 0,
            },
            {
                "classification": "needs_contract_universe_sync",
                "product": "cu",
                "year": 2020,
                "dataset": "contract_universe",
                "candidate_start_date": "2020-01-01",
                "candidate_end_date": "2020-12-31",
                "db_row_count_for_year": 0,
            },
            {
                "classification": "needs_continuous_contract_sync",
                "product": "jm",
                "year": 2025,
                "dataset": "continuous_contract_map",
                "candidate_start_date": "2025-01-01",
                "candidate_end_date": "2025-12-31",
                "db_row_count_for_year": 0,
            },
        ]
    ).to_csv(ledger, index=False)

    result = build_reference_metadata_gap_apply_plan(project_root=tmp_path, gap_ledger=ledger)

    assert result["candidate_row_count"] == 3
    assert result["batch_count"] == 2
    assert result["writes_database"] is False
    assert result["calls_rqdata"] is False
    assert result["classification_counts"] == {
        "needs_contract_universe_sync": 2,
        "needs_continuous_contract_sync": 1,
    }
    first_batch = result["batches"][0]
    assert first_batch["dataset"] == "contract_universe"
    assert first_batch["year"] == 2020
    assert first_batch["candidate_rows"] == 2
    assert first_batch["products"] == "cu|rb"
    assert "rqdata_contract_universe_sync.py" in result["candidate_rows"][0]["apply_command"]
    assert result["candidate_rows"][0]["human_gate"] == "required_before_rqdata_or_db_write"
