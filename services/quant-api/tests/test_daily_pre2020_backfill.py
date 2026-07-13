from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from app.services.rqdata_ingest.daily_pre2020_backfill import (
    _build_batch_schedule,
    _sort_actionable_rows,
    build_daily_pre2020_backfill_plan,
    load_pre2020_applicable_products,
    plan_daily_pre2020_backfill,
)
from app.services.rqdata_ingest.target_coverage_audit import ProductWindow


def test_load_pre2020_applicable_products(tmp_path: Path) -> None:
    products_file = tmp_path / "products.txt"
    products_file.write_text("jm\nad\n", encoding="utf-8")
    windows = {
        "jm": ProductWindow(
            product="jm",
            window_start=date(2020, 1, 2),
            listed_date=date(2013, 3, 22),
            effective_1d_start=date(2020, 1, 2),
            note="",
        ),
        "ad": ProductWindow(
            product="ad",
            window_start=date(2020, 1, 2),
            listed_date=date(2025, 6, 10),
            effective_1d_start=date(2020, 1, 2),
            note="",
        ),
    }
    products = load_pre2020_applicable_products(products_file=products_file, product_windows=windows)
    assert products == ["jm"]


def test_plan_daily_pre2020_backfill_uses_2019_gap_end(tmp_path: Path) -> None:
    symbol = "ag"
    exchange = "SHFE"
    start = date(2020, 1, 2)
    end = date(2026, 7, 11)
    standard_dir = (
        tmp_path
        / "data"
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / "period=1d"
        / f"exchange={exchange}"
        / f"symbol={symbol}"
        / f"contract={symbol}.MAIN"
    )
    standard_dir.mkdir(parents=True)
    standard_path = standard_dir / f"{symbol}_MAIN_1d_{start:%Y%m%d}_{end:%Y%m%d}_v2.parquet"
    frame = pd.DataFrame({"datetime": pd.to_datetime(["2020-01-02", "2020-01-03"])})
    frame.to_parquet(standard_path, index=False)

    plan = plan_daily_pre2020_backfill(
        output_root=tmp_path / "data",
        product=symbol,
        target_start=date(2012, 5, 10),
        exchange=exchange,
    )
    assert plan.mode == "prepend"
    assert plan.gap_end == date(2019, 12, 31)


def test_build_plan_marks_prepend_for_listed_before_2020(tmp_path: Path) -> None:
    result = build_daily_pre2020_backfill_plan(
        project_root=tmp_path,
        products=["jm", "ad"],
        product_windows={
            "jm": ProductWindow(
                product="jm",
                window_start=date(2020, 1, 2),
                listed_date=date(2013, 3, 22),
                effective_1d_start=date(2020, 1, 2),
                note="",
            ),
            "ad": ProductWindow(
                product="ad",
                window_start=date(2020, 1, 2),
                listed_date=date(2025, 6, 10),
                effective_1d_start=date(2020, 1, 2),
                note="",
            ),
        },
        output_dir=tmp_path / "reports",
    )
    by_product = {row["product"]: row for row in result["rows"]}
    assert by_product["jm"]["pre_2020_applicable"] is True
    assert by_product["jm"]["mode"] in {"prepend", "full_missing", "skip"}
    assert by_product["ad"]["pre_2020_applicable"] is False
    assert by_product["ad"]["mode"] == "skip"
    assert (tmp_path / "reports" / "daily_pre2020_backfill_plan.csv").exists()
    assert (tmp_path / "reports" / "daily_pre2020_backfill_summary.json").exists()


def test_sort_actionable_rows_by_listed_date() -> None:
    rows = _sort_actionable_rows(
        [
            {"product": "jm", "listed_date": "2013-03-22", "mode": "prepend"},
            {"product": "a", "listed_date": "2002-03-15", "mode": "prepend"},
            {"product": "eb", "listed_date": "2019-09-26", "mode": "prepend"},
        ]
    )
    assert [row["product"] for row in rows] == ["a", "jm", "eb"]


def test_build_batch_schedule_splits_pending_products() -> None:
    actionable = [
        {"product": f"p{i}", "listed_date": f"201{i}-01-01", "mode": "prepend"}
        for i in range(5)
    ]
    schedule = _build_batch_schedule(actionable, batch_size=2, completed={"p0"})
    assert schedule["pending_count"] == 4
    assert schedule["completed_count"] == 1
    assert len(schedule["batches"]) == 2
    assert schedule["batches"][0]["products"] == ["p1", "p2"]


def test_resume_reads_completed_products(tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    output_dir.mkdir(parents=True)
    (output_dir / "daily_pre2020_batch_results.json").write_text(
        json.dumps({"results": [{"product": "jm", "status": "success"}]}),
        encoding="utf-8",
    )
    from app.services.rqdata_ingest.daily_pre2020_backfill import _load_completed_products

    assert _load_completed_products(output_dir) == {"jm"}
