from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from app.services.rqdata_ingest.daily_pre2020_backfill import load_pre2020_applicable_products
from app.services.rqdata_ingest.minute_pre2020_backfill import (
    build_minute_pre2020_backfill_plan,
    build_traffic_batches,
    estimate_pre2020_traffic,
    plan_minute_pre2020_backfill,
    select_traffic_batch,
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


def test_estimate_pre2020_traffic() -> None:
    bars, mb = estimate_pre2020_traffic(gap_start=date(2019, 4, 30), gap_end=date(2019, 12, 31))
    assert bars > 0
    assert mb > 0


def test_build_traffic_batches_respects_budget() -> None:
    rows = [
        {"product": "sa", "estimated_mb": 1.0},
        {"product": "ss", "estimated_mb": 2.0},
        {"product": "eb", "estimated_mb": 3.0},
        {"product": "al", "estimated_mb": 900.0},
    ]
    batches = build_traffic_batches(rows, budget_mb=800)
    assert batches["batch_count"] >= 2
    assert batches["batches"][0]["estimated_mb"] <= 800


def test_select_traffic_batch_packs_until_budget() -> None:
    rows = [
        {"product": "sa", "estimated_mb": 100.0},
        {"product": "ss", "estimated_mb": 200.0},
        {"product": "eb", "estimated_mb": 600.0},
        {"product": "al", "estimated_mb": 900.0},
    ]
    selected = select_traffic_batch(rows, budget_mb=800)
    assert [row["product"] for row in selected] == ["sa", "ss"]


def test_plan_minute_pre2020_backfill_uses_2019_gap_end(tmp_path: Path) -> None:
    symbol = "jm"
    exchange = "DCE"
    start = date(2020, 1, 2)
    end = date(2026, 7, 11)
    standard_dir = (
        tmp_path
        / "data"
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / "period=1m"
        / f"exchange={exchange}"
        / f"symbol={symbol}"
        / f"contract={symbol}.MAIN"
    )
    standard_dir.mkdir(parents=True)
    standard_path = standard_dir / f"{symbol}_MAIN_1m_{start:%Y%m%d}_{end:%Y%m%d}_v2.parquet"
    frame = pd.DataFrame({"datetime": pd.to_datetime(["2020-01-02 09:01:00", "2020-01-02 09:02:00"])})
    frame.to_parquet(standard_path, index=False)

    plan = plan_minute_pre2020_backfill(
        output_root=tmp_path / "data",
        product=symbol,
        target_start=date(2013, 3, 22),
        exchange=exchange,
    )
    assert plan.mode == "prepend"
    assert plan.gap_end == date(2019, 12, 31)


def test_build_plan_includes_traffic_columns(tmp_path: Path) -> None:
    result = build_minute_pre2020_backfill_plan(
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
    assert row["estimated_bars"] >= 0
    assert (tmp_path / "reports" / "minute_pre2020_traffic_batches.json").exists()
