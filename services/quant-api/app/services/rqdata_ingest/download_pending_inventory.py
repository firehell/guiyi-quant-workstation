from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import MainContractMap
from app.services.rqdata_ingest.data_layer_final_audit import (
    _duckdb_summary,
    _index_dominant_files,
    _load_market_files,
    _resolve_path,
)
from app.services.rqdata_ingest.dominant_v2_parquet import contract_segments_from_mapping
from app.services.rqdata_ingest.target_coverage_audit import (
    DEFAULT_AUDIT_END,
    ProductWindow,
    load_product_windows,
)


MODE = "download_pending_inventory"
RQDATA_EARLIEST_START = date(2000, 1, 4)
RQDATA_MINUTE_EARLIEST_START = date(2010, 1, 4)
TARGET_PERIODS = ("1m", "1d", "1w")
START_TOLERANCE_DAYS = 14
END_TOLERANCE_DAYS = 7
QUALITY_OK = frozenset({"passed", "warning", "unchecked"})


def rqdata_start_floor(period: str) -> date:
    if period == "1m":
        return RQDATA_MINUTE_EARLIEST_START
    return RQDATA_EARLIEST_START


def expected_rqdata_start(window: ProductWindow, *, period: str = "1d") -> date:
    floor = rqdata_start_floor(period)
    listed = window.listed_date or floor
    return max(listed, floor)


def classify_window_coverage(
    *,
    expected_start: date,
    expected_end: date,
    actual_min: date | None,
    actual_max: date | None,
    start_tolerance_days: int = START_TOLERANCE_DAYS,
    end_tolerance_days: int = END_TOLERANCE_DAYS,
) -> tuple[str, date | None, date | None]:
    if actual_min is None or actual_max is None:
        return "missing", expected_start, expected_end

    start_ok = actual_min <= expected_start + timedelta(days=start_tolerance_days)
    end_ok = actual_max >= expected_end - timedelta(days=end_tolerance_days)
    if start_ok and end_ok:
        return "covered", None, None
    if not start_ok and not end_ok:
        gap_start = expected_start
        gap_end = min(expected_end, actual_min - timedelta(days=1)) if actual_min > expected_start else expected_end
        if gap_start <= gap_end:
            return "partial_both", gap_start, gap_end
        return "partial_end", expected_end if actual_max < expected_end else None, expected_end
    if not start_ok:
        gap_end = min(expected_end, actual_min - timedelta(days=1))
        if expected_start <= gap_end:
            return "partial_start", expected_start, gap_end
        return "covered", None, None
    return "partial_end", actual_max + timedelta(days=1), expected_end


def recommended_action_for_dominant(*, period: str, status: str) -> str:
    if status == "covered":
        return "none"
    if status == "missing":
        return f"dominant_v2_download_{period}"
    if status == "partial_start":
        if period == "1m":
            return "minute_pre2020_backfill"
        if period == "1d":
            return "daily_pre2020_backfill"
        if period == "1w":
            return "weekly_pre2020_backfill"
    if status in {"partial_end", "partial_both"}:
        return f"dominant_v2_incremental_{period}"
    return "review"


def recommended_action_for_roll(*, status: str) -> str:
    if status == "covered":
        return "none"
    if status in {"missing_segment", "partial_segment"}:
        return "actual_contract_roll_write"
    return "review"


def _parse_summary_datetime(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")[:19]).date()


def audit_dominant_main_inventory(
    *,
    project_root: Path,
    products: list[str],
    product_windows: dict[str, ProductWindow],
    market_files: list[Any],
    audit_end: date,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for period in TARGET_PERIODS:
        indexed = _index_dominant_files(market_files, period=period)
        for product in products:
            window = product_windows.get(product)
            expected_start = (
                expected_rqdata_start(window, period=period) if window else rqdata_start_floor(period)
            )
            expected_end = audit_end
            candidate = indexed.get(product)
            quality_status = ""
            file_path = ""
            actual_min: date | None = None
            actual_max: date | None = None
            if candidate:
                resolved = _resolve_path(project_root, candidate.get("file_path", ""))
                if resolved and resolved.exists():
                    file_path = str(resolved)
                    summary = _duckdb_summary(resolved)
                    actual_min = _parse_summary_datetime(summary.get("min_datetime", ""))
                    actual_max = _parse_summary_datetime(summary.get("max_datetime", ""))
            status, gap_start, gap_end = classify_window_coverage(
                expected_start=expected_start,
                expected_end=expected_end,
                actual_min=actual_min,
                actual_max=actual_max,
            )
            rows.append(
                {
                    "product": product,
                    "contract_type": "main",
                    "contract_role": "dominant_main",
                    "symbol_or_contract": f"{product}.MAIN",
                    "period": period,
                    "expected_start": expected_start.isoformat(),
                    "expected_end": expected_end.isoformat(),
                    "actual_min": actual_min.isoformat() if actual_min else "",
                    "actual_max": actual_max.isoformat() if actual_max else "",
                    "status": status,
                    "gap_start": gap_start.isoformat() if gap_start else "",
                    "gap_end": gap_end.isoformat() if gap_end else "",
                    "quality_status": quality_status,
                    "file_path": file_path,
                    "recommended_action": recommended_action_for_dominant(period=period, status=status),
                    "segment_contract": "",
                    "segment_start": "",
                    "segment_end": "",
                }
            )
    return rows


def _index_actual_contract_files(market_files: list[Any]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in market_files:
        if str(getattr(row, "data_type", "")).strip() != "bars":
            continue
        if str(getattr(row, "data_role", "")).strip() != "primary":
            continue
        if str(getattr(row, "quality_status", "")).strip() == "failed":
            continue
        product = str(getattr(row, "instrument_symbol", "")).strip().lower()
        contract = str(getattr(row, "contract_code", "")).strip()
        period = str(getattr(row, "period", "")).strip()
        if not product or not contract or not period:
            continue
        if contract.upper().endswith(".MAIN"):
            continue
        if period not in TARGET_PERIODS:
            continue
        grouped[(product, contract.lower(), period)].append(
            {
                "file_path": str(getattr(row, "file_path", "")).strip(),
                "start_time": getattr(row, "start_time", None),
                "end_time": getattr(row, "end_time", None),
            }
        )
    return grouped


def _segment_physical_bounds(
    *,
    project_root: Path,
    files: list[dict[str, Any]],
    physical_cache: dict[str, dict[str, Any]],
) -> tuple[date | None, date | None]:
    mins: list[date] = []
    maxs: list[date] = []
    for item in files:
        path = _resolve_path(project_root, item.get("file_path", ""))
        if path is None:
            continue
        key = str(path)
        summary = physical_cache.get(key)
        if summary is None:
            summary = _duckdb_summary(path)
            physical_cache[key] = summary
        if not summary.get("exists"):
            continue
        min_dt = _parse_summary_datetime(summary.get("min_datetime", ""))
        max_dt = _parse_summary_datetime(summary.get("max_datetime", ""))
        if min_dt:
            mins.append(min_dt)
        if max_dt:
            maxs.append(max_dt)
    if not mins or not maxs:
        return None, None
    return min(mins), max(maxs)


def classify_segment_coverage(
    *,
    segment_start: date,
    segment_end: date,
    actual_min: date | None,
    actual_max: date | None,
) -> str:
    status, _, _ = classify_window_coverage(
        expected_start=segment_start,
        expected_end=segment_end,
        actual_min=actual_min,
        actual_max=actual_max,
        start_tolerance_days=7,
        end_tolerance_days=7,
    )
    if status == "covered":
        return "covered"
    if actual_min is None or actual_max is None:
        return "missing_segment"
    return "partial_segment"


def audit_roll_segment_inventory(
    *,
    session: Session | None,
    project_root: Path,
    products: list[str],
    product_windows: dict[str, ProductWindow],
    market_files: list[Any],
    audit_end: date,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    actual_index = _index_actual_contract_files(market_files)
    physical_cache: dict[str, dict[str, Any]] = {}

    for product in products:
        window = product_windows.get(product)
        if session is None:
            for period in TARGET_PERIODS:
                expected_start = (
                    expected_rqdata_start(window, period=period) if window else rqdata_start_floor(period)
                )
                rows.append(
                    {
                        "product": product,
                        "contract_type": "roll",
                        "contract_role": "actual_contract",
                        "symbol_or_contract": "",
                        "period": period,
                        "expected_start": expected_start.isoformat(),
                        "expected_end": audit_end.isoformat(),
                        "actual_min": "",
                        "actual_max": "",
                        "status": "db_unavailable",
                        "gap_start": expected_start.isoformat(),
                        "gap_end": audit_end.isoformat(),
                        "quality_status": "",
                        "file_path": "",
                        "recommended_action": "review",
                        "segment_contract": "",
                        "segment_start": "",
                        "segment_end": "",
                    }
                )
            continue

        for period in TARGET_PERIODS:
            expected_start = (
                expected_rqdata_start(window, period=period) if window else rqdata_start_floor(period)
            )
            mappings = list(
                session.scalars(
                    select(MainContractMap)
                    .where(
                        MainContractMap.instrument_symbol == product,
                        MainContractMap.rank == 1,
                        MainContractMap.provider == "rqdata",
                        MainContractMap.trade_date >= expected_start,
                        MainContractMap.trade_date <= audit_end,
                    )
                    .order_by(MainContractMap.trade_date.asc())
                )
            )
            records = [
                {
                    "trade_date": mapping.trade_date,
                    "rqdata_order_book_id": str(mapping.contract_code or "").strip(),
                }
                for mapping in mappings
                if str(mapping.contract_code or "").strip()
            ]
            segments = contract_segments_from_mapping(records, start_date=expected_start, end_date=audit_end)
            if not segments:
                rows.append(
                    {
                        "product": product,
                        "contract_type": "roll",
                        "contract_role": "actual_contract",
                        "symbol_or_contract": "",
                        "period": period,
                        "expected_start": expected_start.isoformat(),
                        "expected_end": audit_end.isoformat(),
                        "actual_min": "",
                        "actual_max": "",
                        "status": "missing_mapping",
                        "gap_start": expected_start.isoformat(),
                        "gap_end": audit_end.isoformat(),
                        "quality_status": "",
                        "file_path": "",
                        "recommended_action": "main_contract_map_sync",
                        "segment_contract": "",
                        "segment_start": "",
                        "segment_end": "",
                    }
                )
                continue

            for segment in segments:
                contract = str(segment["rqdata_order_book_id"]).strip()
                segment_start = segment["start_date"]
                segment_end = segment["end_date"]
                files = actual_index.get((product, contract.lower(), period), [])
                actual_min, actual_max = _segment_physical_bounds(
                    project_root=project_root,
                    files=files,
                    physical_cache=physical_cache,
                )
                status = classify_segment_coverage(
                    segment_start=segment_start,
                    segment_end=segment_end,
                    actual_min=actual_min,
                    actual_max=actual_max,
                )
                gap_start = segment_start if status != "covered" else None
                gap_end = segment_end if status != "covered" else None
                file_path = files[0]["file_path"] if files else ""
                rows.append(
                    {
                        "product": product,
                        "contract_type": "roll",
                        "contract_role": "actual_contract",
                        "symbol_or_contract": contract,
                        "period": period,
                        "expected_start": expected_start.isoformat(),
                        "expected_end": audit_end.isoformat(),
                        "actual_min": actual_min.isoformat() if actual_min else "",
                        "actual_max": actual_max.isoformat() if actual_max else "",
                        "status": status,
                        "gap_start": gap_start.isoformat() if gap_start else "",
                        "gap_end": gap_end.isoformat() if gap_end else "",
                        "quality_status": "",
                        "file_path": file_path,
                        "recommended_action": recommended_action_for_roll(status=status),
                        "segment_contract": contract,
                        "segment_start": segment_start.isoformat(),
                        "segment_end": segment_end.isoformat(),
                    }
                )
    return rows


def aggregate_product_period_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["product"], row["contract_type"], row["period"])
        grouped[key].append(row)

    priority = {
        "missing": 0,
        "missing_mapping": 1,
        "db_unavailable": 2,
        "missing_segment": 3,
        "partial_segment": 4,
        "partial_both": 5,
        "partial_start": 6,
        "partial_end": 7,
        "covered": 8,
    }
    summaries: list[dict[str, Any]] = []
    for (product, contract_type, period), items in sorted(grouped.items()):
        statuses = [item["status"] for item in items]
        worst = min(statuses, key=lambda status: priority.get(status, 99))
        gap_items = [item for item in items if item["status"] != "covered"]
        summaries.append(
            {
                "product": product,
                "contract_type": contract_type,
                "period": period,
                "worst_status": worst,
                "segment_total": len(items),
                "segment_gap_count": len(gap_items),
                "covered_count": len(items) - len(gap_items),
            }
        )
    return summaries


def build_inventory_summary(
    *,
    products: list[str],
    audit_end: date,
    dominant_rows: list[dict[str, Any]],
    roll_rows: list[dict[str, Any]],
    product_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    dominant_gaps = [row for row in dominant_rows if row["status"] != "covered"]
    roll_gaps = [row for row in roll_rows if row["status"] not in {"covered", "db_unavailable"}]
    summary_by_type_period: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in dominant_rows + roll_rows:
        summary_by_type_period[row["contract_type"]][row["period"]] += 1 if row["status"] != "covered" else 0

    product_level = [row for row in product_summaries if row["worst_status"] != "covered"]
    return {
        "mode": MODE,
        "audit_end": audit_end.isoformat(),
        "product_count": len(products),
        "dominant_row_count": len(dominant_rows),
        "roll_row_count": len(roll_rows),
        "dominant_gap_count": len(dominant_gaps),
        "roll_gap_segment_count": len(roll_gaps),
        "product_period_gap_count": len(product_level),
        "dominant_gap_by_period": {
            period: sum(1 for row in dominant_rows if row["period"] == period and row["status"] != "covered")
            for period in TARGET_PERIODS
        },
        "roll_gap_by_period": {
            period: sum(1 for row in roll_rows if row["period"] == period and row["status"] not in {"covered", "db_unavailable"})
            for period in TARGET_PERIODS
        },
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
    }


def render_pending_inventory_markdown(
    *,
    audit_end: date,
    products: list[str],
    summary: dict[str, Any],
    dominant_rows: list[dict[str, Any]],
    roll_rows: list[dict[str, Any]],
    product_summaries: list[dict[str, Any]],
) -> str:
    lines = [
        "# Download Pending Inventory",
        "",
        f"- mode: `{MODE}`",
        f"- audit_end: `{audit_end.isoformat()}`",
        f"- products: `{len(products)}`",
        f"- rqdata_start_policy: `1d/1w=max(listed, {RQDATA_EARLIEST_START.isoformat()}); 1m=max(listed, {RQDATA_MINUTE_EARLIEST_START.isoformat()})`",
        f"- writes_database: `{summary['writes_database']}`",
        f"- writes_parquet: `{summary['writes_parquet']}`",
        f"- calls_rqdata: `{summary['calls_rqdata']}`",
        "",
        "## Gap Summary",
        "",
        "| metric | count |",
        "|---|---:|",
        f"| dominant gaps (product×period) | {summary['dominant_gap_count']} |",
        f"| roll gap segments | {summary['roll_gap_segment_count']} |",
        f"| product-period worst-status gaps | {summary['product_period_gap_count']} |",
        "",
        "## Dominant Main Gaps By Period",
        "",
        "| period | gap_count |",
        "|---|---:|",
    ]
    for period in TARGET_PERIODS:
        lines.append(f"| `{period}` | {summary['dominant_gap_by_period'][period]} |")
    lines.extend(["", "## Roll Gap Segments By Period", "", "| period | gap_count |", "|---|---:|"])
    for period in TARGET_PERIODS:
        lines.append(f"| `{period}` | {summary['roll_gap_by_period'][period]} |")

    dominant_pending = [row for row in dominant_rows if row["status"] != "covered"]
    if dominant_pending:
        lines.extend(["", "## Dominant Main Pending (first 30)", ""])
        for row in dominant_pending[:30]:
            lines.append(
                f"- `{row['product']}` `{row['period']}` `{row['status']}` "
                f"gap `{row['gap_start']}`..`{row['gap_end']}` action `{row['recommended_action']}`"
            )

    roll_product_gaps = [
        row
        for row in product_summaries
        if row["contract_type"] == "roll" and row["worst_status"] != "covered"
    ]
    if roll_product_gaps:
        lines.extend(["", "## Roll Product-Period Worst Status (first 30)", ""])
        for row in sorted(roll_product_gaps, key=lambda item: (-item["segment_gap_count"], item["product"]))[:30]:
            lines.append(
                f"- `{row['product']}` `{row['period']}` `{row['worst_status']}` "
                f"gaps `{row['segment_gap_count']}/{row['segment_total']}`"
            )

    roll_1w_by_product: dict[str, list[str]] = defaultdict(list)
    for row in roll_rows:
        if row["period"] != "1w":
            continue
        roll_1w_by_product[row["product"]].append(row["status"])
    zero_roll_1w = sorted(
        product
        for product in products
        if not roll_1w_by_product.get(product)
        or all(status in {"missing_segment", "missing_mapping"} for status in roll_1w_by_product[product])
    )
    if zero_roll_1w:
        lines.extend(["", "## Products With No Covered Roll 1w", "", ", ".join(zero_roll_1w)])

    return "\n".join(lines) + "\n"


def run_download_pending_inventory(
    *,
    session: Session | None,
    project_root: Path,
    products: list[str],
    product_windows: dict[str, ProductWindow],
    audit_end: date = DEFAULT_AUDIT_END,
) -> dict[str, Any]:
    market_files = _load_market_files(session)
    dominant_rows = audit_dominant_main_inventory(
        project_root=project_root,
        products=products,
        product_windows=product_windows,
        market_files=market_files,
        audit_end=audit_end,
    )
    roll_rows = audit_roll_segment_inventory(
        session=session,
        project_root=project_root,
        products=products,
        product_windows=product_windows,
        market_files=market_files,
        audit_end=audit_end,
    )
    product_summaries = aggregate_product_period_summary(dominant_rows + roll_rows)
    summary = build_inventory_summary(
        products=products,
        audit_end=audit_end,
        dominant_rows=dominant_rows,
        roll_rows=roll_rows,
        product_summaries=product_summaries,
    )
    matrix_rows = dominant_rows + roll_rows
    return {
        "mode": MODE,
        "audit_end": audit_end.isoformat(),
        "products": products,
        "summary": summary,
        "pending_download_matrix": matrix_rows,
        "product_period_summary": product_summaries,
        "dominant_rows": dominant_rows,
        "roll_rows": roll_rows,
        "markdown": render_pending_inventory_markdown(
            audit_end=audit_end,
            products=products,
            summary=summary,
            dominant_rows=dominant_rows,
            roll_rows=roll_rows,
            product_summaries=product_summaries,
        ),
    }


def write_pending_inventory_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = output_dir / "pending_download_matrix.csv"
    summary_path = output_dir / "pending_download_summary.md"
    product_summary_path = output_dir / "pending_download_product_summary.csv"
    evidence_path = output_dir / "pending_download_evidence.json"
    queue_path = output_dir / "download_queue_commands.md"

    pd.DataFrame(result["pending_download_matrix"]).to_csv(matrix_path, index=False)
    pd.DataFrame(result["product_period_summary"]).to_csv(product_summary_path, index=False)
    summary_path.write_text(result["markdown"], encoding="utf-8")
    evidence = {
        "summary": result["summary"],
        "audit_end": result["audit_end"],
        "products": result["products"],
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    queue_path.write_text(render_download_queue_commands(result), encoding="utf-8")
    return {
        "pending_download_matrix": matrix_path,
        "pending_download_summary": summary_path,
        "pending_download_product_summary": product_summary_path,
        "pending_download_evidence": evidence_path,
        "download_queue_commands": queue_path,
    }


def render_download_queue_commands(result: dict[str, Any]) -> str:
    dominant_rows = result["dominant_rows"]
    roll_rows = result["roll_rows"]
    audit_end = result["audit_end"]

    weekly_products = sorted({row["product"] for row in dominant_rows if row["period"] == "1w" and row["status"] == "partial_start"})
    daily_products = sorted({row["product"] for row in dominant_rows if row["period"] == "1d" and row["status"] == "partial_start"})
    minute_products = sorted({row["product"] for row in dominant_rows if row["period"] == "1m" and row["status"] == "partial_start"})

    roll_1w_by_product: dict[str, list[str]] = defaultdict(list)
    for row in roll_rows:
        if row["period"] == "1w":
            roll_1w_by_product[row["product"]].append(row["status"])
    roll_1w_products = sorted(
        product
        for product, statuses in roll_1w_by_product.items()
        if statuses and all(status in {"missing_segment", "missing_mapping", "partial_segment"} for status in statuses)
    )

    roll_gap_products = sorted(
        {
            row["product"]
            for row in roll_rows
            if row["status"] in {"missing_segment", "partial_segment"}
            and row["period"] in TARGET_PERIODS
        }
    )

    lines = [
        "# Download Queue Commands",
        "",
        f"Generated from `{MODE}` audit_end=`{audit_end}`.",
        "",
        "## P0 — Dominant 1w pre-2020",
        "",
        f"Products ({len(weekly_products)}): `{', '.join(weekly_products)}`",
        "",
        "```bash",
        "uv run --project services/quant-api python scripts/rqdata_weekly_pre2020_backfill.py \\",
        "  --weekly-history-csv data/reports/download_pending_inventory_YYYYMMDD/pending_download_matrix.csv \\",
        "  --run-write --register",
        "```",
        "",
        "## P1 — Dominant 1d pre-2020",
        "",
        f"Products ({len(daily_products)}): `{', '.join(daily_products)}`",
        "",
        "```bash",
        "uv run --project services/quant-api python scripts/rqdata_daily_pre2020_backfill.py \\",
        "  --run-write --register",
        "```",
        "",
        "## P2 — Roll 1w missing products",
        "",
        f"Products ({len(roll_1w_products)}): `{', '.join(roll_1w_products)}`",
        "",
        "```bash",
        "# Example for one product; repeat for each in the list above",
        "uv run --project services/quant-api python scripts/rqdata_actual_contract_bars_batch.py \\",
        f"  --product {roll_1w_products[0] if roll_1w_products else 'jm'} \\",
        f"  --start-date 2020-01-02 --end-date {audit_end} \\",
        "  --periods 1w --roll-segments --run-write",
        "```",
        "",
        "## P3 — Roll segment gaps (1m/1d/1w)",
        "",
        f"Products with any roll segment gap ({len(roll_gap_products)}): `{', '.join(roll_gap_products[:40])}{'...' if len(roll_gap_products) > 40 else ''}`",
        "",
        "```bash",
        "PRODUCTS_FILE=data/universe/full_products_90.txt \\",
        f"START_DATE=2020-01-02 END_DATE={audit_end} BAR_PERIODS=1m,1d,1w LAYER=layer2 \\",
        "./scripts/rqdata_full_universe_download.sh",
        "```",
        "",
        "## P4 — Dominant 1m pre-2020 (traffic heavy)",
        "",
        f"Products ({len(minute_products)}): `{', '.join(minute_products)}`",
        "",
        "```bash",
        "uv run --project services/quant-api python scripts/rqdata_1m_pre2020_backfill.py \\",
        "  --traffic-budget-mb 800 --run-write --register",
        "```",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "MODE",
    "RQDATA_EARLIEST_START",
    "RQDATA_MINUTE_EARLIEST_START",
    "TARGET_PERIODS",
    "aggregate_product_period_summary",
    "audit_dominant_main_inventory",
    "audit_roll_segment_inventory",
    "build_inventory_summary",
    "classify_segment_coverage",
    "classify_window_coverage",
    "expected_rqdata_start",
    "load_product_windows",
    "rqdata_start_floor",
    "render_download_queue_commands",
    "run_download_pending_inventory",
    "write_pending_inventory_reports",
]
