from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.rqdata_ingest.daily_pre2020_backfill import load_pre2020_applicable_products
from app.services.rqdata_ingest.dominant_v2_backfill import (
    DEFAULT_GLOBAL_END,
    BackfillPlan,
    DominantCoverage,
    build_dominant_backfill_summary,
    persist_backfill_summary,
    run_dominant_period_backfill,
    summary_path_for_product,
    _manifest_quality,
)
from app.services.rqdata_ingest.dominant_v2_incremental import find_latest_main_canonical
from app.services.rqdata_ingest.dominant_v2_parquet import _raw_path
from app.services.rqdata_ingest.target_coverage_audit import ProductWindow
from app.services.rqdata_ingest.weekly_pre2020_backfill import (
    RQDATA_EARLIEST_START,
    WARNING_PRODUCTS,
)

MODE = "minute_pre2020_backfill"
PERIOD = "1m"
AUDIT_PRE2020_END = date(2019, 12, 31)
DOMINANT_2020_START = date(2020, 1, 2)
BARS_PER_TRADING_DAY = 240
BYTES_PER_BAR = 200
TRAFFIC_OVERHEAD = 1.5
DEFAULT_TRAFFIC_BUDGET_MB = 800
_1M_FILENAME_RE = re.compile(
    r"^(?P<contract>.+)_(?P<period>1m)_(?P<start>\d{8})_(?P<end>\d{8})_v2\.parquet$"
)


def estimate_pre2020_traffic(*, gap_start: date, gap_end: date) -> tuple[int, float]:
    trading_days = max(0, int(((gap_end - gap_start).days) * 252 / 365))
    bars = trading_days * BARS_PER_TRADING_DAY
    estimated_mb = bars * BYTES_PER_BAR / 1024 / 1024 * TRAFFIC_OVERHEAD
    return bars, round(estimated_mb, 2)


def build_minute_pre2020_backfill_plan(
    *,
    project_root: Path,
    products: list[str],
    product_windows: dict[str, ProductWindow],
    output_dir: Path,
    global_end: date = DEFAULT_GLOBAL_END,
    audit_pre2020_end: date = AUDIT_PRE2020_END,
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
                    "gap_start": "",
                    "gap_end": "",
                    "output_start": "",
                    "output_end": "",
                    "estimated_bars": 0,
                    "estimated_mb": 0.0,
                }
            )
            continue
        plan = plan_minute_pre2020_backfill(
            output_root=project_root / "data",
            product=product,
            target_start=max(listed, RQDATA_EARLIEST_START),
            global_end=global_end,
        )
        est_bars = 0
        est_mb = 0.0
        if plan.gap_start is not None and plan.gap_end is not None:
            est_bars, est_mb = estimate_pre2020_traffic(gap_start=plan.gap_start, gap_end=plan.gap_end)
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
                "estimated_bars": est_bars,
                "estimated_mb": est_mb,
            }
        )

    actionable = _sort_actionable_rows([row for row in rows if row["mode"] in {"prepend", "full_missing"}])
    traffic_batches = build_traffic_batches(actionable, budget_mb=DEFAULT_TRAFFIC_BUDGET_MB)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "minute_pre2020_backfill_plan.csv"
    pd.DataFrame(rows).to_csv(plan_path, index=False)
    traffic_path = output_dir / "minute_pre2020_traffic_batches.json"
    traffic_path.write_text(json.dumps(traffic_batches, indent=2), encoding="utf-8")
    summary = {
        "mode": MODE,
        "period": PERIOD,
        "product_count": len(products),
        "actionable_count": len(actionable),
        "skip_count": sum(1 for row in rows if row["mode"] == "skip"),
        "prepend_count": sum(1 for row in rows if row["mode"] == "prepend"),
        "full_missing_count": sum(1 for row in rows if row["mode"] == "full_missing"),
        "estimated_total_mb": round(sum(float(row["estimated_mb"]) for row in actionable), 2),
        "traffic_batch_count": len(traffic_batches["batches"]),
        "plan_path": str(plan_path),
        "traffic_batches_path": str(traffic_path),
        "writes_parquet": False,
        "calls_rqdata": False,
    }
    (output_dir / "minute_pre2020_backfill_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {
        "summary": summary,
        "rows": rows,
        "actionable": actionable,
        "plan_path": plan_path,
        "traffic_batches": traffic_batches,
    }


def run_minute_pre2020_backfill_batch(
    *,
    client: Any,
    project_root: Path,
    products: list[str],
    product_windows: dict[str, ProductWindow],
    output_dir: Path,
    batch_size: int = 0,
    batch_offset: int = 0,
    traffic_budget_mb: int = DEFAULT_TRAFFIC_BUDGET_MB,
    resume: bool = True,
    register: bool = False,
    allow_quality_failed: bool = False,
    resolve_exchange: Any | None = None,
) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.services.rqdata_ingest.dominant_v2_register import register_dominant_v2_quality

    if resolve_exchange is None:
        resolve_exchange = lambda product: "DCE"  # noqa: E731

    plan = build_minute_pre2020_backfill_plan(
        project_root=project_root,
        products=products,
        product_windows=product_windows,
        output_dir=output_dir,
    )
    completed = _load_completed_products(output_dir) if resume else set()
    pending_rows = [row for row in plan["actionable"] if row["product"] not in completed]

    if batch_size > 0:
        sliced = pending_rows[batch_offset:] if batch_offset > 0 else pending_rows
        selected_rows = sliced[:batch_size]
    else:
        selected_rows = select_traffic_batch(pending_rows, budget_mb=traffic_budget_mb)

    selected = [row["product"] for row in selected_rows]
    results: list[dict[str, Any]] = []
    for product in selected:
        window = product_windows[product]
        listed = window.listed_date
        assert listed is not None
        target_start = max(listed, RQDATA_EARLIEST_START)
        exchange = resolve_exchange(product)
        backfill_plan = plan_minute_pre2020_backfill(
            output_root=project_root / "data",
            product=product,
            target_start=target_start,
            global_end=DEFAULT_GLOBAL_END,
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
            period_results={PERIOD: payload},
        )
        summary_path = summary_path_for_product(
            project_root / "data",
            product,
            backfill_plan.output_start,
            backfill_plan.output_end,
        )
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
                _append_batch_results(output_dir, results)
                continue
        results.append(
            {
                "product": product,
                "status": "success",
                "mode": backfill_plan.mode,
                "summary_path": str(summary_path),
                "register_result": register_result,
                "gap_start": backfill_plan.gap_start.isoformat() if backfill_plan.gap_start else "",
                "gap_end": backfill_plan.gap_end.isoformat() if backfill_plan.gap_end else "",
            }
        )

    _append_batch_results(output_dir, results)
    new_completed = completed | {r["product"] for r in results if r["status"] == "success"}
    schedule = build_traffic_batches(
        [row for row in plan["actionable"] if row["product"] not in new_completed],
        budget_mb=traffic_budget_mb,
        completed_count=len(new_completed),
    )
    schedule_path = output_dir / "minute_pre2020_batch_schedule.json"
    schedule_path.write_text(json.dumps(schedule, indent=2), encoding="utf-8")

    selected_mb = round(sum(float(row.get("estimated_mb") or 0) for row in selected_rows), 2)
    return {
        "plan": plan["summary"],
        "batch_results": results,
        "batch_size": batch_size,
        "batch_offset": batch_offset,
        "traffic_budget_mb": traffic_budget_mb,
        "selected_count": len(selected),
        "selected_estimated_mb": selected_mb,
        "resume_skipped_count": len(completed),
        "batch_schedule_path": str(schedule_path),
        "batch_schedule": schedule,
        "traffic_batches_path": plan["summary"]["traffic_batches_path"],
    }


def plan_minute_pre2020_backfill(
    *,
    output_root: Path,
    product: str,
    target_start: date,
    global_end: date = DEFAULT_GLOBAL_END,
    exchange: str | None = None,
) -> BackfillPlan:
    symbol = product.strip().lower()
    coverage = _resolve_minute_pre2020_anchor(output_root=output_root, product=symbol)
    resolved_exchange = (exchange or (coverage.exchange if coverage else "DCE")).upper()

    if coverage is None:
        return BackfillPlan(
            mode="full_missing",
            product=symbol,
            period=PERIOD,
            exchange=resolved_exchange,
            target_start=target_start,
            gap_start=target_start,
            gap_end=global_end,
            output_start=target_start,
            output_end=global_end,
            reason="no existing canonical 1m asset; download full window",
        )

    existing_min = coverage.min_datetime.date()
    if target_start >= existing_min:
        return BackfillPlan(
            mode="skip",
            product=symbol,
            period=PERIOD,
            exchange=resolved_exchange,
            target_start=target_start,
            gap_start=None,
            gap_end=None,
            output_start=coverage.file_start,
            output_end=coverage.file_end,
            reason=f"target_start {target_start} >= existing_min {existing_min}",
            coverage=coverage,
        )

    gap_end = min(date(2019, 12, 31), existing_min - timedelta(days=1))
    if gap_end < target_start:
        return BackfillPlan(
            mode="skip",
            product=symbol,
            period=PERIOD,
            exchange=resolved_exchange,
            target_start=target_start,
            gap_start=None,
            gap_end=None,
            output_start=coverage.file_start,
            output_end=coverage.file_end,
            reason="empty gap after boundary adjustment",
            coverage=coverage,
        )

    return BackfillPlan(
        mode="prepend",
        product=symbol,
        period=PERIOD,
        exchange=resolved_exchange,
        target_start=target_start,
        gap_start=target_start,
        gap_end=gap_end,
        output_start=target_start,
        output_end=coverage.file_end,
        reason="prepend pre-2020 minute prefix before 2020+ anchor asset",
        coverage=coverage,
        superseded_paths=(str(coverage.raw_path), str(coverage.standard_path)),
    )


def _resolve_minute_pre2020_anchor(*, output_root: Path, product: str) -> DominantCoverage | None:
    symbol = product.strip().lower()
    base = (
        output_root
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / f"period={PERIOD}"
    )
    candidates: list[DominantCoverage] = []
    for path in base.glob(f"exchange=*/symbol={symbol}/contract={symbol}.MAIN/*_{PERIOD}_*_v2.parquet"):
        parsed = _parse_1m_standard_filename(path.name)
        if parsed is None:
            continue
        frame = pd.read_parquet(path, columns=["datetime"])
        datetimes = pd.to_datetime(frame["datetime"], errors="coerce").dropna()
        if datetimes.empty:
            continue
        min_dt = datetimes.min().date()
        if min_dt > DOMINANT_2020_START and parsed["start"] > DOMINANT_2020_START:
            continue
        if min_dt > date(2020, 1, 10):
            continue
        exchange = path.parents[2].name.split("=", 1)[-1]
        raw_path = _raw_path(
            output_root,
            symbol=symbol,
            period=PERIOD,
            start_date=parsed["start"],
            end_date=parsed["end"],
        )
        quality_status = _manifest_quality(output_root, symbol, PERIOD, parsed["end"]) or "unknown"
        candidates.append(
            DominantCoverage(
                product=symbol,
                period=PERIOD,
                exchange=exchange,
                file_start=parsed["start"],
                file_end=parsed["end"],
                min_datetime=datetimes.min(),
                max_datetime=datetimes.max(),
                quality_status=quality_status,
                raw_path=raw_path,
                standard_path=path,
            )
        )

    if not candidates:
        baseline = find_latest_main_canonical(output_root, symbol, PERIOD)
        if baseline is None:
            return None
        if baseline.start_date <= DOMINANT_2020_START or baseline.frame["datetime"].min().date() <= DOMINANT_2020_START:
            exchange = baseline.path.parents[2].name.split("=", 1)[-1]
            parsed = _parse_1m_standard_filename(baseline.path.name)
            if parsed is None:
                return None
            return DominantCoverage(
                product=symbol,
                period=PERIOD,
                exchange=exchange,
                file_start=parsed["start"],
                file_end=parsed["end"],
                min_datetime=pd.to_datetime(baseline.frame["datetime"]).min(),
                max_datetime=pd.to_datetime(baseline.frame["datetime"]).max(),
                quality_status=_manifest_quality(output_root, symbol, PERIOD, parsed["end"]) or "unknown",
                raw_path=_raw_path(
                    output_root,
                    symbol=symbol,
                    period=PERIOD,
                    start_date=parsed["start"],
                    end_date=parsed["end"],
                ),
                standard_path=baseline.path,
            )
        return None

    def sort_key(item: DominantCoverage) -> tuple[int, int, int]:
        quality_rank = 0 if item.quality_status == "passed" else 1 if item.quality_status == "warning" else 2
        return (
            quality_rank,
            abs(item.file_start.toordinal() - DOMINANT_2020_START.toordinal()),
            -item.file_end.toordinal(),
        )

    return sorted(candidates, key=sort_key)[0]


def build_traffic_batches(
    actionable: list[dict[str, Any]],
    *,
    budget_mb: float,
    completed_count: int = 0,
) -> dict[str, Any]:
    sorted_rows = sorted(actionable, key=lambda row: (float(row.get("estimated_mb") or 0), row["product"]))
    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_mb = 0.0
    for row in sorted_rows:
        row_mb = float(row.get("estimated_mb") or 0)
        if current and current_mb + row_mb > budget_mb:
            batches.append(_traffic_batch_payload(len(batches) + 1, current, current_mb))
            current = []
            current_mb = 0.0
        current.append(row)
        current_mb += row_mb
    if current:
        batches.append(_traffic_batch_payload(len(batches) + 1, current, current_mb))
    pending_mb = round(sum(float(row.get("estimated_mb") or 0) for row in sorted_rows), 2)
    return {
        "budget_mb": budget_mb,
        "completed_count": completed_count,
        "pending_count": len(sorted_rows),
        "pending_estimated_mb": pending_mb,
        "batch_count": len(batches),
        "batches": batches,
    }


def select_traffic_batch(actionable: list[dict[str, Any]], *, budget_mb: float) -> list[dict[str, Any]]:
    sorted_rows = sorted(actionable, key=lambda row: (float(row.get("estimated_mb") or 0), row["product"]))
    selected: list[dict[str, Any]] = []
    total_mb = 0.0
    for row in sorted_rows:
        row_mb = float(row.get("estimated_mb") or 0)
        if selected and total_mb + row_mb > budget_mb:
            break
        selected.append(row)
        total_mb += row_mb
    if not selected and sorted_rows:
        selected = [sorted_rows[0]]
    return selected


def _traffic_batch_payload(batch_index: int, rows: list[dict[str, Any]], total_mb: float) -> dict[str, Any]:
    return {
        "batch_index": batch_index,
        "product_count": len(rows),
        "estimated_mb": round(total_mb, 2),
        "products": [row["product"] for row in rows],
    }


def _sort_actionable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[str, str]:
        listed = row.get("listed_date") or "9999-12-31"
        return (listed, row["product"])

    return sorted(rows, key=sort_key)


def _load_completed_products(output_dir: Path) -> set[str]:
    completed: set[str] = set()
    results_path = output_dir / "minute_pre2020_batch_results.json"
    if not results_path.exists():
        return completed
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    for entry in payload.get("results", []):
        if entry.get("status") == "success":
            product = str(entry.get("product") or "").strip().lower()
            if product:
                completed.add(product)
    return completed


def _append_batch_results(output_dir: Path, new_results: list[dict[str, Any]]) -> None:
    if not new_results:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "minute_pre2020_batch_results.json"
    existing: list[dict[str, Any]] = []
    if results_path.exists():
        payload = json.loads(results_path.read_text(encoding="utf-8"))
        existing = list(payload.get("results", []))
    by_product = {str(item.get("product") or "").lower(): item for item in existing}
    for item in new_results:
        product = str(item.get("product") or "").lower()
        if product:
            by_product[product] = item
    merged = sorted(by_product.values(), key=lambda item: str(item.get("product") or ""))
    results_path.write_text(json.dumps({"results": merged}, indent=2, default=str), encoding="utf-8")


def _parse_1m_standard_filename(name: str) -> dict[str, date] | None:
    match = _1M_FILENAME_RE.match(name)
    if match is None or match.group("period") != PERIOD:
        return None
    return {
        "start": date.fromisoformat(
            f"{match.group('start')[:4]}-{match.group('start')[4:6]}-{match.group('start')[6:8]}"
        ),
        "end": date.fromisoformat(
            f"{match.group('end')[:4]}-{match.group('end')[4:6]}-{match.group('end')[6:8]}"
        ),
    }


__all__ = [
    "AUDIT_PRE2020_END",
    "DEFAULT_TRAFFIC_BUDGET_MB",
    "MODE",
    "PERIOD",
    "build_minute_pre2020_backfill_plan",
    "build_traffic_batches",
    "estimate_pre2020_traffic",
    "load_pre2020_applicable_products",
    "plan_minute_pre2020_backfill",
    "run_minute_pre2020_backfill_batch",
    "select_traffic_batch",
]
