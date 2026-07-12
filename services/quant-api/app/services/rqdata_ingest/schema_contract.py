from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

CANONICAL_BAR_COLUMNS: dict[str, str] = {
    "datetime": "timestamp",
    "open": "float",
    "high": "float",
    "low": "float",
    "close": "float",
    "volume": "int",
    "open_interest": "float",
    "symbol": "string",
    "contract": "string",
    "period": "string",
    "provider": "string",
}


def validate_canonical_bar_schema(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "failed", "issue_type": "missing_physical_file", "columns": [], "missing_columns": sorted(CANONICAL_BAR_COLUMNS)}
    try:
        with duckdb.connect(database=":memory:") as connection:
            columns = {
                item[0]: item[1]
                for item in connection.execute("describe select * from read_parquet(?)", [str(path)]).fetchall()
            }
    except Exception as exc:
        return {"status": "failed", "issue_type": "duckdb_read_failed", "error": str(exc), "columns": [], "missing_columns": sorted(CANONICAL_BAR_COLUMNS)}
    missing_columns = sorted(column for column in CANONICAL_BAR_COLUMNS if column not in columns)
    status = "passed" if not missing_columns else "failed"
    return {
        "status": status,
        "issue_type": "" if status == "passed" else "schema_mismatch",
        "columns": sorted(columns),
        "missing_columns": missing_columns,
    }


def compare_daily_weekly_overlap(*, aggregated_path: Path, direct_path: Path, sample_rows: int = 20) -> dict[str, Any]:
    if not aggregated_path.exists() or not direct_path.exists():
        return {"status": "failed", "issue_type": "missing_physical_file", "overlap_rows": 0, "mismatches": []}
    agg = pd.read_parquet(aggregated_path)
    direct = pd.read_parquet(direct_path)
    if agg.empty or direct.empty:
        return {"status": "warning", "issue_type": "empty_overlap", "overlap_rows": 0, "mismatches": []}
    merged = agg.merge(direct, on="datetime", suffixes=("_agg", "_direct"), how="inner")
    mismatches: list[dict[str, Any]] = []
    for _, row in merged.head(sample_rows).iterrows():
        for field in ("open", "high", "low", "close", "volume"):
            agg_value = row.get(f"{field}_agg")
            direct_value = row.get(f"{field}_direct")
            if pd.isna(agg_value) and pd.isna(direct_value):
                continue
            if float(agg_value) != float(direct_value):
                mismatches.append(
                    {
                        "datetime": str(row["datetime"]),
                        "field": field,
                        "aggregated": float(agg_value),
                        "direct": float(direct_value),
                    }
                )
    status = "passed" if not mismatches else "failed"
    return {
        "status": status,
        "issue_type": "" if status == "passed" else "overlap_mismatch",
        "overlap_rows": int(len(merged)),
        "mismatches": mismatches,
    }
