from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.rqdata_ingest.weekly_row_count_reconcile import (
    DbMarketFileSnapshot,
    reconcile_weekly_row_counts,
)


def _write_weekly_parquet(path: Path, *, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-02", periods=rows, freq="W-FRI"),
            "open": range(rows),
            "high": range(rows),
            "low": range(rows),
            "close": range(rows),
            "volume": range(rows),
            "open_interest": range(rows),
        }
    )
    frame.to_parquet(path, index=False)


def _write_manifest(project_root: Path, path: Path, *, product: str = "ad", rows: int = 3) -> None:
    manifest = project_root / "data" / "manifests" / f"rqdata_{product}_v2_history_20230103_20260707.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "period": "1w",
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
                "row_count": rows,
                "min_datetime": "2026-01-02T00:00:00",
                "max_datetime": "2026-01-16T00:00:00",
                "standard_path": str(path),
                "status": "success",
                "data_version": f"test_{product}_1w",
            }
        ]
    ).to_csv(manifest, index=False)


def _write_processed_summary(project_root: Path, path: Path, *, product: str = "ad", rows: int = 3) -> None:
    summary = project_root / "data" / "processed" / "v1b" / product / f"{product}_v2_parquet_20230103_20260707.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        f"""
{{
  "symbol": "{product}",
  "contract": "{product}.MAIN",
  "periods": {{
    "1w": {{
      "quality_status": "passed",
      "standard": {{
        "path": "{path}",
        "row_count": {rows},
        "min_datetime": "2026-01-02T00:00:00",
        "max_datetime": "2026-01-16T00:00:00"
      }}
    }}
  }}
}}
""".strip(),
        encoding="utf-8",
    )


def _run_reconcile(
    tmp_path: Path,
    *,
    db_status: str = "available",
    db_row_count: int | None = 3,
    manifest_rows: int = 3,
    processed_rows: int = 3,
    parquet_rows: int = 3,
) -> dict:
    path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1w/exchange=SHFE/symbol=ad/contract=ad.MAIN/ad_MAIN_1w_20230103_20260707_v2.parquet"
    _write_weekly_parquet(path, rows=parquet_rows)
    _write_manifest(tmp_path, path, rows=manifest_rows)
    _write_processed_summary(tmp_path, path, rows=processed_rows)
    db_rows = []
    if db_row_count is not None:
        db_rows.append(
            DbMarketFileSnapshot(
                id=1,
                file_path=str(path),
                row_count=db_row_count,
                start_time="2026-01-02T00:00:00",
                end_time="2026-01-16T00:00:00",
                checksum="",
                data_role="primary",
                quality_status="passed",
                data_version="test",
            )
        )
    return reconcile_weekly_row_counts(
        project_root=tmp_path,
        products=["ad"],
        period="1w",
        output_dir=tmp_path / "reports",
        db_status=db_status,
        db_rows=db_rows,
    )


def test_weekly_reconcile_marks_db_unavailable_partial(tmp_path: Path) -> None:
    result = _run_reconcile(tmp_path, db_status="unavailable", db_row_count=None)

    assert result["rows"][0]["classification"] == "db_unavailable_partial"
    assert result["outputs"]["row_count_reconcile"].exists()
    assert result["outputs"]["summary"].exists()


def test_weekly_reconcile_marks_db_row_count_stale(tmp_path: Path) -> None:
    result = _run_reconcile(tmp_path, db_row_count=2)

    assert result["rows"][0]["classification"] == "db_row_count_stale"
    assert result["rows"][0]["manifest_row_count"] == 3
    assert result["rows"][0]["duckdb_row_count"] == 3


def test_weekly_reconcile_marks_manifest_or_summary_stale(tmp_path: Path) -> None:
    result = _run_reconcile(tmp_path, manifest_rows=2)

    assert result["rows"][0]["classification"] == "manifest_or_summary_stale"


def test_weekly_reconcile_marks_matched(tmp_path: Path) -> None:
    result = _run_reconcile(tmp_path)

    assert result["rows"][0]["classification"] == "matched"
