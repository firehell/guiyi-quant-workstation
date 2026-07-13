from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.rqdata_ingest.dominant_v2_backfill import (
    DEFAULT_GLOBAL_END,
    build_dominant_backfill_summary,
    persist_backfill_summary,
    plan_dominant_period_backfill,
    run_dominant_period_backfill,
    summary_path_for_product,
)
from app.services.rqdata_ingest.target_coverage_audit import ProductWindow


MODE = "weekly_pre2020_backfill"
RQDATA_EARLIEST_START = date(2000, 1, 4)
WARNING_PRODUCTS = frozenset({"bb", "rs", "wh", "wr", "zc"})


def build_weekly_pre2020_backfill_plan(
    *,
    project_root: Path,
    products: list[str],
    product_windows: dict[str, ProductWindow],
    output_dir: Path,
    global_end: date = DEFAULT_GLOBAL_END,
    audit_pre2020_end: date = date(2019, 12, 31),
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for product in products:
        window = product_windows.get(product)
        listed = window.listed_date if window else None
        pre_applicable = listed is not None and listed <= audit_pre2020_end
        if not pre_applicable or listed is None:
            rows.append(
                {
                    "product": product,
                    "listed_date": listed.isoformat() if listed else "",
                    "pre_2020_applicable": False,
                    "decision": "skip_not_applicable",
                    "mode": "skip",
                    "reason": "listed_after_2019",
                }
            )
            continue
        plan = plan_dominant_period_backfill(
            output_root=project_root / "data",
            product=product,
            period="1w",
            target_start=max(listed, RQDATA_EARLIEST_START),
            global_end=global_end,
        )
        rows.append(
            {
                "product": product,
                "listed_date": listed.isoformat(),
                "pre_2020_applicable": True,
                "decision": plan.mode,
                "mode": plan.mode,
                "reason": plan.reason,
                "gap_start": plan.gap_start.isoformat() if plan.gap_start else "",
                "gap_end": plan.gap_end.isoformat() if plan.gap_end else "",
                "output_start": plan.output_start.isoformat(),
                "output_end": plan.output_end.isoformat(),
            }
        )

    actionable = [row for row in rows if row["mode"] in {"prepend", "full_missing"}]
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "weekly_pre2020_backfill_plan.csv"
    pd.DataFrame(rows).to_csv(plan_path, index=False)
    summary = {
        "mode": MODE,
        "product_count": len(products),
        "actionable_count": len(actionable),
        "skip_count": sum(1 for row in rows if row["mode"] == "skip"),
        "prepend_count": sum(1 for row in rows if row["mode"] == "prepend"),
        "full_missing_count": sum(1 for row in rows if row["mode"] == "full_missing"),
        "plan_path": str(plan_path),
        "writes_parquet": False,
        "calls_rqdata": False,
    }
    (output_dir / "weekly_pre2020_backfill_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"summary": summary, "rows": rows, "actionable": actionable, "plan_path": plan_path}


def run_weekly_pre2020_backfill_batch(
    *,
    client: Any,
    project_root: Path,
    products: list[str],
    product_windows: dict[str, ProductWindow],
    output_dir: Path,
    batch_size: int = 15,
    register: bool = False,
    allow_quality_failed: bool = False,
    resolve_exchange: Any | None = None,
) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.services.rqdata_ingest.dominant_v2_register import register_dominant_v2_quality

    if resolve_exchange is None:
        resolve_exchange = lambda product: "DCE"  # noqa: E731

    plan = build_weekly_pre2020_backfill_plan(
        project_root=project_root,
        products=products,
        product_windows=product_windows,
        output_dir=output_dir,
    )
    results: list[dict[str, Any]] = []
    actionable = [row["product"] for row in plan["actionable"]]
    selected = actionable[:batch_size] if batch_size > 0 else actionable
    for product in selected:
        window = product_windows[product]
        listed = window.listed_date
        assert listed is not None
        target_start = max(listed, RQDATA_EARLIEST_START)
        exchange = resolve_exchange(product)
        backfill_plan = plan_dominant_period_backfill(
            output_root=project_root / "data",
            product=product,
            period="1w",
            target_start=target_start,
            exchange=exchange,
        )
        if backfill_plan.mode not in {"prepend", "full_missing"}:
            results.append({"product": product, "status": "skipped", "reason": backfill_plan.reason})
            continue
        try:
            payload = run_dominant_period_backfill(
                client=client,
                output_root=project_root / "data",
                plan=backfill_plan,
                exchange=exchange,
            )
        except Exception as exc:  # noqa: BLE001
            results.append({"product": product, "status": "failed", "error": str(exc)})
            continue
        summary = build_dominant_backfill_summary(
            product=product,
            exchange=exchange,
            start_date=backfill_plan.output_start,
            end_date=backfill_plan.output_end,
            period_results={"1w": payload},
        )
        summary_path = summary_path_for_product(project_root / "data", product, backfill_plan.output_start, backfill_plan.output_end)
        persist_backfill_summary(summary, summary_path)
        register_result = None
        if register:
            try:
                with SessionLocal() as session:
                    register_result = register_dominant_v2_quality(
                        session=session,
                        summary_path=summary_path,
                        allow_quality_failed=allow_quality_failed or product in WARNING_PRODUCTS,
                    )
                    session.commit()
            except Exception as exc:  # noqa: BLE001
                register_result = {"status": "register_failed", "error": str(exc)}
                results.append(
                    {
                        "product": product,
                        "status": "register_failed",
                        "mode": backfill_plan.mode,
                        "summary_path": str(summary_path),
                        "register_result": register_result,
                    }
                )
                continue
        results.append(
            {
                "product": product,
                "status": "success",
                "mode": backfill_plan.mode,
                "summary_path": str(summary_path),
                "register_result": register_result,
            }
        )
    return {"plan": plan["summary"], "batch_results": results, "batch_size": batch_size, "selected_count": len(selected)}


def load_pre2020_gap_products(
    *,
    weekly_history_csv: Path,
) -> list[str]:
    frame = pd.read_csv(weekly_history_csv)
    mask = frame["pre_2020_status"].isin(["partial_or_missing_pre2020", "missing_pre2020"])
    return sorted(frame.loc[mask, "product"].astype(str).str.lower().tolist())
