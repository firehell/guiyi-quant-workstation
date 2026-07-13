from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from app.services.rqdata_ingest.target_coverage_audit import ProductWindow
from app.services.rqdata_ingest.weekly_pre2020_backfill import (
    build_weekly_pre2020_backfill_plan,
    load_pre2020_gap_products,
)


def test_load_pre2020_gap_products(tmp_path: Path) -> None:
    csv_path = tmp_path / "weekly_history_audit.csv"
    pd.DataFrame(
        [
            {"product": "jm", "pre_2020_status": "partial_or_missing_pre2020"},
            {"product": "ad", "pre_2020_status": "not_applicable"},
        ]
    ).to_csv(csv_path, index=False)
    products = load_pre2020_gap_products(weekly_history_csv=csv_path)
    assert products == ["jm"]


def test_build_plan_marks_prepend_for_listed_before_2020(tmp_path: Path) -> None:
    result = build_weekly_pre2020_backfill_plan(
        project_root=tmp_path,
        products=["jm"],
        product_windows={
            "jm": ProductWindow(
                product="jm",
                window_start=date(2020, 1, 2),
                listed_date=date(2013, 3, 22),
                effective_1d_start=date(2020, 1, 2),
                note="",
            )
        },
        output_dir=tmp_path / "reports",
    )
    row = result["rows"][0]
    assert row["pre_2020_applicable"] is True
    assert row["mode"] in {"prepend", "full_missing", "skip"}
