from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.rqdata_ingest.schema_contract import compare_daily_weekly_overlap, validate_canonical_bar_schema


def test_validate_canonical_bar_schema_passes_required_columns(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2020-01-02"]),
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [10],
            "open_interest": [100.0],
            "symbol": ["rb"],
            "contract": ["rb.MAIN"],
            "period": ["1d"],
            "provider": ["rqdata"],
        }
    ).to_parquet(path, index=False)

    result = validate_canonical_bar_schema(path)
    assert result["status"] == "passed"
    assert result["missing_columns"] == []


def test_compare_daily_weekly_overlap_detects_mismatch(tmp_path: Path) -> None:
    aggregated = tmp_path / "agg.parquet"
    direct = tmp_path / "direct.parquet"
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "volume": [10, 20],
        }
    )
    frame.to_parquet(aggregated, index=False)
    mismatch = frame.copy()
    mismatch.loc[0, "close"] = 9.9
    mismatch.to_parquet(direct, index=False)

    result = compare_daily_weekly_overlap(aggregated_path=aggregated, direct_path=direct)
    assert result["overlap_rows"] == 2
    assert result["status"] == "failed"
    assert result["mismatches"]
