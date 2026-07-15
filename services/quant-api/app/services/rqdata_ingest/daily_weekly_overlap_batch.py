from __future__ import annotations

import csv
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.rqdata_ingest.schema_contract import (
    CANONICAL_BAR_SCHEMA_VERSION,
    compare_overlap_from_1m_source,
    validate_canonical_bar_contract,
)

MODE = "daily_weekly_overlap_batch"
TARGET_PERIODS = ("1d", "1w")


@dataclass(frozen=True)
class AssetPaths:
    product: str
    contract: str
    contract_role: str
    period: str
    source_1m_path: Path | None
    stored_path: Path | None


def run_contract_audit(
    *,
    sealing_dir: Path,
    output_dir: Path,
    limit_rows: int | None = None,
) -> dict[str, Any]:
    inventory_path = sealing_dir / "asset_physical_inventory.csv"
    rows = _read_csv(inventory_path)
    if limit_rows is not None:
        rows = rows[:limit_rows]

    matrix_rows: list[dict[str, Any]] = []
    for item in rows:
        physical_path = _clean_text(item.get("physical_path"))
        if not physical_path:
            continue
        path = Path(physical_path)
        period = _clean_text(item.get("period"))
        contract_role = _clean_text(item.get("contract_role"))
        result = validate_canonical_bar_contract(path, period=period, contract_role=contract_role)
        matrix_rows.append(
            {
                "physical_path": physical_path,
                "product": _clean_text(item.get("product")),
                "symbol_or_contract": _clean_text(item.get("symbol_or_contract")),
                "period": period,
                "contract_role": contract_role,
                "schema_version": result.get("schema_version", CANONICAL_BAR_SCHEMA_VERSION),
                "schema_fingerprint": result.get("fingerprint", ""),
                "embedded_status": result.get("embedded_status", ""),
                "sidecar_status": result.get("sidecar_status", ""),
                "schema_status": result.get("status", ""),
                "missing_embedded": ";".join(result.get("missing_embedded", [])),
                "missing_sidecar": ";".join(result.get("missing_sidecar", [])),
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    matrix_csv = output_dir / "schema_contract_matrix.csv"
    _write_csv(matrix_csv, matrix_rows)
    summary = _render_contract_summary(matrix_rows, output_dir=output_dir)
    summary_path = output_dir / "CONTRACT-AUDIT-SUMMARY.md"
    summary_path.write_text(summary, encoding="utf-8")
    return {
        "mode": "contract-audit",
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "rows": matrix_rows,
        "outputs": {"schema_contract_matrix": matrix_csv, "summary": summary_path},
    }


def run_jm_pilot_overlap(*, sealing_dir: Path, output_dir: Path, product: str = "jm", contract: str = "jm.MAIN") -> dict[str, Any]:
    inventory = _load_inventory(sealing_dir / "asset_physical_inventory.csv")
    paths = _resolve_product_paths(inventory, product=product, contract=contract, contract_role="dominant_main")
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "mode": "jm-pilot",
        "product": product,
        "contract": contract,
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "periods": {},
        "outputs": {},
    }
    for period in TARGET_PERIODS:
        stored_path = paths.get(period)
        source_1m_path = paths.get("1m")
        if stored_path is None:
            results["periods"][period] = {"status": "not_applicable", "issue_type": "missing_stored_path"}
            continue
        if source_1m_path is None:
            results["periods"][period] = {"status": "failed", "issue_type": "missing_source_1m"}
            continue
        overlap = compare_overlap_from_1m_source(source_1m_path=source_1m_path, stored_path=stored_path, period=period)
        period_dir = output_dir / period
        period_dir.mkdir(parents=True, exist_ok=True)
        mismatch_csv = period_dir / "mismatch_rows.csv"
        _write_csv(mismatch_csv, overlap.get("mismatches", []))
        result_json = period_dir / "overlap_result.json"
        payload = {
            "source_1m_path": str(source_1m_path),
            "stored_path": str(stored_path),
            **overlap,
            "mismatches": overlap.get("mismatches", []),
        }
        result_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        results["periods"][period] = {
            "status": overlap.get("status"),
            "issue_type": overlap.get("issue_type", ""),
            "overlap_rows": overlap.get("overlap_rows", 0),
            "block_mismatches": overlap.get("block_mismatches", 0),
            "warning_mismatches": overlap.get("warning_mismatches", 0),
            "source_1m_path": str(source_1m_path),
            "stored_path": str(stored_path),
            "output": str(result_json),
        }
        results["outputs"][period] = {"overlap_result": result_json, "mismatch_rows": mismatch_csv}

    summary_path = output_dir / "JM-PILOT-OVERLAP-SUMMARY.md"
    summary_path.write_text(_render_jm_summary(results, output_dir=output_dir), encoding="utf-8")
    results["outputs"]["summary"] = summary_path
    return results


def run_batch_overlap(
    *,
    sealing_dir: Path,
    output_dir: Path,
    products: list[str],
    max_workers: int = 4,
    limit_products: int | None = None,
) -> dict[str, Any]:
    inventory = _load_inventory(sealing_dir / "asset_physical_inventory.csv")
    coverage = _load_coverage_targets(sealing_dir / "target_coverage_matrix.csv")
    selected_products = [product.lower() for product in products]
    if limit_products is not None:
        selected_products = selected_products[:limit_products]

    tasks: list[AssetPaths] = []
    for product in selected_products:
        for period in TARGET_PERIODS:
            if not _is_batch_target(coverage, product=product, period=period):
                continue
            paths = _resolve_product_paths(
                inventory,
                product=product,
                contract=f"{product}.MAIN",
                contract_role="dominant_main",
            )
            tasks.append(
                AssetPaths(
                    product=product,
                    contract=f"{product}.MAIN",
                    contract_role="dominant_main",
                    period=period,
                    source_1m_path=paths.get("1m"),
                    stored_path=paths.get(period),
                )
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = {executor.submit(_run_single_overlap, task): task for task in tasks}
        for future in as_completed(futures):
            rows.append(future.result())

    rows.sort(key=lambda item: (item["product"], item["period"]))
    summary_rows = rows
    issue_csv = output_dir / "batch_overlap_summary.csv"
    _write_csv(issue_csv, summary_rows)
    mismatch_dir = output_dir / "products"
    mismatch_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        product_dir = mismatch_dir / row["product"] / row["period"]
        product_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(product_dir / "mismatch_rows.csv", row.pop("mismatch_rows", []))

    summary_path = output_dir / "BATCH-OVERLAP-SUMMARY.md"
    summary_path.write_text(_render_batch_summary(summary_rows, output_dir=output_dir, target_count=len(tasks)), encoding="utf-8")
    return {
        "mode": MODE,
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "target_count": len(tasks),
        "completed_count": len(rows),
        "rows": summary_rows,
        "outputs": {"batch_overlap_summary": issue_csv, "summary": summary_path},
    }


def _run_single_overlap(task: AssetPaths) -> dict[str, Any]:
    if task.source_1m_path is None or task.stored_path is None:
        return {
            "product": task.product,
            "contract": task.contract,
            "contract_role": task.contract_role,
            "period": task.period,
            "status": "failed",
            "issue_type": "missing_paths",
            "overlap_rows": 0,
            "block_mismatches": 0,
            "warning_mismatches": 0,
            "source_1m_path": "" if task.source_1m_path is None else str(task.source_1m_path),
            "stored_path": "" if task.stored_path is None else str(task.stored_path),
            "mismatch_rows": [],
        }
    overlap = compare_overlap_from_1m_source(
        source_1m_path=task.source_1m_path,
        stored_path=task.stored_path,
        period=task.period,
    )
    return {
        "product": task.product,
        "contract": task.contract,
        "contract_role": task.contract_role,
        "period": task.period,
        "status": overlap.get("status"),
        "issue_type": overlap.get("issue_type", ""),
        "comparison_mode": overlap.get("comparison_mode", ""),
        "overlap_rows": overlap.get("overlap_rows", 0),
        "block_mismatches": overlap.get("block_mismatches", 0),
        "warning_mismatches": overlap.get("warning_mismatches", 0),
        "source_1m_path": str(task.source_1m_path),
        "stored_path": str(task.stored_path),
        "mismatch_rows": overlap.get("mismatches", []),
    }


def _load_inventory(path: Path) -> list[dict[str, Any]]:
    return _read_csv(path)


def _load_coverage_targets(path: Path) -> list[dict[str, Any]]:
    return _read_csv(path)


def _is_batch_target(coverage: list[dict[str, Any]], *, product: str, period: str) -> bool:
    for item in coverage:
        if _clean_text(item.get("product")) != product:
            continue
        if _clean_text(item.get("contract_role")) != "dominant_main":
            continue
        if _clean_text(item.get("period")) != period:
            continue
        if _clean_text(item.get("status")) == "covered_passed":
            return True
    return False


def _resolve_product_paths(
    inventory: list[dict[str, Any]],
    *,
    product: str,
    contract: str,
    contract_role: str,
) -> dict[str, Path]:
    candidates: dict[str, list[dict[str, Any]]] = {period: [] for period in ("1m", "1d", "1w")}
    for item in inventory:
        if _clean_text(item.get("product")) != product:
            continue
        if _clean_text(item.get("symbol_or_contract")) != contract:
            continue
        if _clean_text(item.get("contract_role")) != contract_role:
            continue
        period = _clean_text(item.get("period"))
        if period not in candidates:
            continue
        if _clean_text(item.get("physical_exists")).lower() not in {"true", "1", "yes"}:
            continue
        if "experiments/" in _clean_text(item.get("physical_path")):
            continue
        candidates[period].append(item)

    resolved: dict[str, Path] = {}
    for period, items in candidates.items():
        if not items:
            continue
        preferred = sorted(
            items,
            key=lambda row: (
                "processed_summary" in _clean_text(row.get("evidence_source")),
                _clean_text(row.get("quality_status")) == "passed",
                _clean_text(row.get("end_date")),
                _clean_text(row.get("data_version")),
            ),
            reverse=True,
        )
        physical_path = _clean_text(preferred[0].get("physical_path"))
        if physical_path:
            resolved[period] = Path(physical_path)

    anchor_token = _date_token_from_path(str(resolved.get("1m", "")))
    if anchor_token:
        for period in ("1d", "1w"):
            period_candidates = candidates.get(period, [])
            matched = [
                item
                for item in period_candidates
                if _date_token_from_path(_clean_text(item.get("physical_path"))) == anchor_token
            ]
            if matched:
                preferred = sorted(
                    matched,
                    key=lambda row: (
                        "processed_summary" in _clean_text(row.get("evidence_source")),
                        _clean_text(row.get("quality_status")) == "passed",
                    ),
                    reverse=True,
                )
                physical_path = _clean_text(preferred[0].get("physical_path"))
                if physical_path:
                    resolved[period] = Path(physical_path)
    return resolved


def _date_token_from_path(path: str) -> str:
    import re

    if not path:
        return ""
    match = re.search(r"_(20\d{6})_(20\d{6})_v\d+\.parquet$", Path(path).name)
    return f"{match.group(1)}_{match.group(2)}" if match else ""


def _render_contract_summary(rows: list[dict[str, Any]], *, output_dir: Path) -> str:
    counts = Counter(row["schema_status"] for row in rows)
    embedded_counts = Counter(row["embedded_status"] for row in rows)
    return "\n".join(
        [
            "# Canonical Bar Contract Audit",
            "",
            f"- output_dir: `{output_dir}`",
            f"- schema_version: `{CANONICAL_BAR_SCHEMA_VERSION}`",
            f"- rows: {len(rows)}",
            "- writes_database: `False`",
            "- writes_parquet: `False`",
            "",
            "## Status Counts",
            "",
            "| status | count |",
            "|---|---:|",
            *[f"| `{key}` | {value} |" for key, value in sorted(counts.items())],
            "",
            "## Embedded Status",
            "",
            "| embedded_status | count |",
            "|---|---:|",
            *[f"| `{key}` | {value} |" for key, value in sorted(embedded_counts.items())],
            "",
        ]
    )


def _render_jm_summary(result: dict[str, Any], *, output_dir: Path) -> str:
    lines = [
        "# JM Pilot Daily/Weekly Overlap Summary",
        "",
        f"- output_dir: `{output_dir}`",
        f"- product: `{result['product']}`",
        f"- contract: `{result['contract']}`",
        "- writes_database: `False`",
        "- writes_parquet: `False`",
        "- calls_rqdata: `False`",
        "",
        "## Period Results",
        "",
        "| period | status | overlap_rows | block | warning | stored_path |",
        "|---|---|---:|---:|---:|---|",
    ]
    for period, payload in sorted(result["periods"].items()):
        lines.append(
            f"| `{period}` | `{payload.get('status', '')}` | {payload.get('overlap_rows', 0)} | "
            f"{payload.get('block_mismatches', 0)} | {payload.get('warning_mismatches', 0)} | "
            f"`{Path(str(payload.get('stored_path', ''))).name}` |"
        )
    return "\n".join(lines) + "\n"


def _render_batch_summary(rows: list[dict[str, Any]], *, output_dir: Path, target_count: int) -> str:
    status_counts = Counter(row["status"] for row in rows)
    block_total = sum(int(row.get("block_mismatches", 0) or 0) for row in rows)
    return "\n".join(
        [
            "# Daily/Weekly Overlap Batch Summary",
            "",
            f"- output_dir: `{output_dir}`",
            f"- target_count: {target_count}",
            f"- completed_count: {len(rows)}",
            f"- block_mismatches_total: {block_total}",
            "- writes_database: `False`",
            "- writes_parquet: `False`",
            "- calls_rqdata: `False`",
            "",
            "## Status Counts",
            "",
            "| status | count |",
            "|---|---:|",
            *[f"| `{key}` | {value} |" for key, value in sorted(status_counts.items())],
            "",
        ]
    )


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
