from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

import duckdb


MODE = "weekly_row_count_reconcile"
DEFAULT_SOURCE_REPORT = Path("data/reports/target_coverage_audit_20260711")
DEFAULT_TRIAGE_REPORT = Path("data/reports/target_coverage_gap_triage_20260711/row_count_mismatch_triage.csv")


@dataclass(frozen=True)
class DbMarketFileSnapshot:
    id: int | None
    file_path: str
    row_count: int | None
    start_time: str
    end_time: str
    checksum: str
    data_role: str
    quality_status: str
    data_version: str


def reconcile_weekly_row_counts(
    *,
    project_root: Path,
    products: list[str],
    period: str,
    output_dir: Path,
    db_status: str,
    db_error_type: str = "",
    db_rows: list[DbMarketFileSnapshot] | None = None,
    write_outputs: bool = True,
) -> dict[str, Any]:
    products = [product.lower() for product in products]
    db_rows = db_rows or []
    manifest_by_path = _load_manifest_rows(project_root=project_root, products=products, period=period)
    processed_by_path = _load_processed_summary_rows(project_root=project_root, products=products, period=period)
    inventory_by_path = _load_asset_inventory(
        project_root / DEFAULT_SOURCE_REPORT / "asset_physical_inventory.csv",
        products=products,
        period=period,
    )
    target_paths = _load_target_paths(project_root / DEFAULT_TRIAGE_REPORT, products=products, period=period)
    db_by_path = _index_db_rows(db_rows, project_root=project_root)

    paths = sorted(set(manifest_by_path) | set(processed_by_path) | set(inventory_by_path) | target_paths)
    rows: list[dict[str, Any]] = []
    for path in paths:
        manifest = manifest_by_path.get(path, {})
        processed = processed_by_path.get(path, {})
        inventory = inventory_by_path.get(path, {})
        db = db_by_path.get(path)
        duckdb_summary = _duckdb_summary(Path(path))
        row = {
            "product": _first_text(manifest.get("product"), processed.get("product"), inventory.get("product"), _product_from_path(path)),
            "contract": _first_text(manifest.get("contract"), processed.get("contract"), inventory.get("contract"), _contract_from_path(path)),
            "period": _first_text(manifest.get("period"), processed.get("period"), inventory.get("period"), period),
            "standard_path": path,
            "db_file_id": "" if db is None else _clean_int(db.id),
            "db_row_count": "" if db is None else _clean_int(db.row_count),
            "db_data_role": "" if db is None else _clean_text(db.data_role),
            "db_quality_status": "" if db is None else _clean_text(db.quality_status),
            "db_data_version": "" if db is None else _clean_text(db.data_version),
            "manifest_row_count": _clean_int(manifest.get("row_count")),
            "processed_summary_row_count": _clean_int(processed.get("row_count")),
            "duckdb_row_count": _clean_int(duckdb_summary.get("row_count")),
            "distinct_datetime_count": _clean_int(duckdb_summary.get("distinct_datetime_count")),
            "duplicate_datetime_count": _clean_int(duckdb_summary.get("duplicate_datetime_count")),
            "min_datetime": _clean_text(duckdb_summary.get("min_datetime")),
            "max_datetime": _clean_text(duckdb_summary.get("max_datetime")),
            "audit_metadata_row_count": _clean_int(inventory.get("manifest_or_db_row_count")),
            "audit_row_count_status": _clean_text(inventory.get("row_count_status")),
            "newer_matched_sibling": False,
            "classification": "",
            "read_error": _clean_text(duckdb_summary.get("error")),
        }
        rows.append(row)

    for row in rows:
        row["newer_matched_sibling"] = _has_newer_matched_sibling(row, rows)
        row["classification"] = _classify(row=row, db_status=db_status)

    csv_path = output_dir / "row_count_reconcile.csv"
    summary_path = output_dir / "ROW_COUNT_RECONCILE_SUMMARY.md"
    outputs = {"row_count_reconcile": csv_path, "summary": summary_path}
    if write_outputs:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(csv_path, rows)
        summary = _render_summary(rows=rows, db_status=db_status, db_error_type=db_error_type, output_dir=output_dir)
        summary_path.write_text(summary, encoding="utf-8")
    return {
        "mode": MODE,
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "db_status": db_status,
        "db_error_type": db_error_type,
        "rows": rows,
        "outputs": outputs,
    }


def _load_manifest_rows(*, project_root: Path, products: list[str], period: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for product in products:
        for manifest in sorted((project_root / "data" / "manifests").glob(f"rqdata_{product}_v2_history_*.csv")):
            for item in _read_csv(manifest):
                if _clean_text(item.get("period")) != period:
                    continue
                path = _resolve_path(project_root, _clean_text(item.get("standard_path")))
                if not path:
                    continue
                rows[str(path)] = {
                    "product": product,
                    "contract": _clean_text(item.get("actual_contract")) or f"{product}.MAIN",
                    "period": period,
                    "row_count": _to_int(item.get("row_count")),
                }
    return rows


def _load_processed_summary_rows(*, project_root: Path, products: list[str], period: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for product in products:
        for summary_path in sorted((project_root / "data" / "processed" / "v1b" / product).glob("*.json")):
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            period_summary = (summary.get("periods") or {}).get(period) or {}
            standard = period_summary.get("standard") or {}
            path = _resolve_path(project_root, _clean_text(standard.get("path")))
            if not path:
                continue
            rows[str(path)] = {
                "product": _clean_text(summary.get("symbol")) or product,
                "contract": _clean_text(summary.get("contract")) or f"{product}.MAIN",
                "period": period,
                "row_count": _to_int(standard.get("row_count")),
            }
    return rows


def _load_asset_inventory(path: Path, *, products: list[str], period: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in _read_csv(path):
        if _clean_text(item.get("product")) not in products or _clean_text(item.get("period")) != period:
            continue
        if _clean_text(item.get("contract_role")) != "dominant_main":
            continue
        physical_path = _clean_text(item.get("physical_path"))
        if not physical_path:
            continue
        rows[physical_path] = {
            "product": _clean_text(item.get("product")),
            "contract": _clean_text(item.get("symbol_or_contract")),
            "period": period,
            "manifest_or_db_row_count": _to_int(item.get("manifest_or_db_row_count")),
            "row_count_status": _clean_text(item.get("row_count_status")),
        }
    return rows


def _load_target_paths(path: Path, *, products: list[str], period: str) -> set[str]:
    paths = set()
    for item in _read_csv(path):
        if _clean_text(item.get("product")) not in products or _clean_text(item.get("period")) != period:
            continue
        standard_path = _clean_text(item.get("standard_path"))
        if standard_path:
            paths.add(standard_path)
    return paths


def _index_db_rows(rows: list[DbMarketFileSnapshot], *, project_root: Path) -> dict[str, DbMarketFileSnapshot]:
    indexed: dict[str, DbMarketFileSnapshot] = {}
    for row in rows:
        path = _resolve_path(project_root, row.file_path)
        if path is not None:
            indexed[str(path)] = row
    return indexed


def _duckdb_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "row_count": None,
            "distinct_datetime_count": None,
            "duplicate_datetime_count": None,
            "min_datetime": "",
            "max_datetime": "",
            "error": "missing_physical_file",
        }
    try:
        with duckdb.connect(database=":memory:") as connection:
            row = connection.execute(
                """
                select
                    count(*) as row_count,
                    count(distinct datetime) as distinct_datetime_count,
                    count(*) - count(distinct datetime) as duplicate_datetime_count,
                    min(datetime) as min_datetime,
                    max(datetime) as max_datetime
                from read_parquet(?)
                """,
                [str(path)],
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 - report read failure without stopping other files.
        return {
            "row_count": None,
            "distinct_datetime_count": None,
            "duplicate_datetime_count": None,
            "min_datetime": "",
            "max_datetime": "",
            "error": type(exc).__name__,
        }
    return {
        "row_count": int(row[0]),
        "distinct_datetime_count": int(row[1]),
        "duplicate_datetime_count": int(row[2]),
        "min_datetime": _format_datetime(row[3]),
        "max_datetime": _format_datetime(row[4]),
        "error": "",
    }


def _classify(*, row: dict[str, Any], db_status: str) -> str:
    duckdb_row_count = _to_int(row.get("duckdb_row_count"))
    distinct_count = _to_int(row.get("distinct_datetime_count"))
    duplicate_count = _to_int(row.get("duplicate_datetime_count"))
    manifest_row_count = _to_int(row.get("manifest_row_count"))
    processed_row_count = _to_int(row.get("processed_summary_row_count"))
    db_row_count = _to_int(row.get("db_row_count"))

    if row.get("read_error") or duckdb_row_count is None:
        return "parquet_row_issue"
    if duplicate_count not in (None, 0) or distinct_count != duckdb_row_count:
        return "parquet_row_issue"
    if manifest_row_count is not None and manifest_row_count != duckdb_row_count:
        return "manifest_or_summary_stale"
    if processed_row_count is not None and processed_row_count != duckdb_row_count:
        return "manifest_or_summary_stale"
    if db_status != "available":
        return "db_unavailable_partial"
    if db_row_count is None:
        return "missing_db_record"
    if db_row_count != duckdb_row_count:
        return "old_version_metadata_stale" if row.get("newer_matched_sibling") else "db_row_count_stale"
    return "matched"


def _has_newer_matched_sibling(row: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    product = row["product"]
    period = row["period"]
    current_token = _date_token(row["standard_path"])
    if current_token is None:
        return False
    for sibling in rows:
        if sibling is row or sibling["product"] != product or sibling["period"] != period:
            continue
        sibling_token = _date_token(sibling["standard_path"])
        if sibling_token is None or sibling_token <= current_token:
            continue
        duckdb_row_count = _to_int(sibling.get("duckdb_row_count"))
        manifest_row_count = _to_int(sibling.get("manifest_row_count"))
        processed_row_count = _to_int(sibling.get("processed_summary_row_count"))
        db_row_count = _to_int(sibling.get("db_row_count"))
        audit_status = _clean_text(sibling.get("audit_row_count_status"))
        local_matched = duckdb_row_count is not None and manifest_row_count == duckdb_row_count and processed_row_count in (None, duckdb_row_count)
        db_or_audit_matched = db_row_count == duckdb_row_count or audit_status == "matched"
        if local_matched and db_or_audit_matched:
            return True
    return False


def _render_summary(*, rows: list[dict[str, Any]], db_status: str, db_error_type: str, output_dir: Path) -> str:
    counts = Counter(row["classification"] for row in rows)
    mismatch_rows = [row for row in rows if row["classification"] in {"old_version_metadata_stale", "db_row_count_stale", "db_unavailable_partial"}]
    lines = [
        "# AD/EC/OP Weekly Row Count Reconcile Summary",
        "",
        f"- mode: `{MODE}`",
        f"- output_dir: `{output_dir}`",
        f"- db_status: `{db_status}`",
        "- writes_database: `False`",
        "- writes_parquet: `False`",
        "- calls_rqdata: `False`",
    ]
    if db_error_type:
        lines.append(f"- db_error_type: `{db_error_type}`")
    lines.extend(
        [
            "",
            "## Classification Counts",
            "",
            _markdown_counts(counts),
            "",
            "## Reconcile Rows",
            "",
            "| product | file | db_row_count | manifest_row_count | processed_summary_row_count | duckdb_row_count | duplicate_datetime_count | newer_matched_sibling | classification |",
            "|---|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| {product} | `{file}` | {db} | {manifest} | {processed} | {duckdb} | {duplicate} | {sibling} | `{classification}` |".format(
                product=row["product"],
                file=Path(row["standard_path"]).name,
                db=_cell(row["db_row_count"]),
                manifest=_cell(row["manifest_row_count"]),
                processed=_cell(row["processed_summary_row_count"]),
                duckdb=_cell(row["duckdb_row_count"]),
                duplicate=_cell(row["duplicate_datetime_count"]),
                sibling=str(row["newer_matched_sibling"]),
                classification=row["classification"],
            )
        )
    lines.extend(
        [
            "",
            "## Conclusion Boundary",
            "",
            "- This task reconciles row-count evidence only; it does not repair metadata.",
            "- `source_interval` provenance metadata is out of scope for this run.",
            "- No PostgreSQL, Parquet, manifest, checksum, RQData, strategy, signal, live runtime or trading execution writes are authorized by this report.",
        ]
    )
    if db_status != "available":
        lines.append("- DB was unavailable in this run, so DB-layer reconciliation remains partial.")
    elif mismatch_rows:
        lines.append("- The mismatched historical files have local manifest/summary/DuckDB agreement and newer matched siblings; treat this as metadata staleness before considering Parquet regeneration.")
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "product",
        "contract",
        "period",
        "standard_path",
        "db_file_id",
        "db_row_count",
        "db_data_role",
        "db_quality_status",
        "db_data_version",
        "manifest_row_count",
        "processed_summary_row_count",
        "duckdb_row_count",
        "distinct_datetime_count",
        "duplicate_datetime_count",
        "min_datetime",
        "max_datetime",
        "audit_metadata_row_count",
        "audit_row_count_status",
        "newer_matched_sibling",
        "classification",
        "read_error",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _resolve_path(project_root: Path, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _date_token(path: str) -> int | None:
    matches = re.findall(r"_(20\d{6})(?:_v\d+)?(?:\.parquet)?", Path(path).name)
    if not matches:
        return None
    return int(matches[-1])


def _product_from_path(path: str) -> str:
    match = re.search(r"/symbol=([^/]+)/", path)
    return match.group(1) if match else ""


def _contract_from_path(path: str) -> str:
    match = re.search(r"/contract=([^/]+)/", path)
    return match.group(1) if match else ""


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_int(value: Any) -> int | str:
    parsed = _to_int(value)
    return "" if parsed is None else parsed


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))


def _format_datetime(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _cell(value: Any) -> str:
    return str(value) if value not in (None, "") else ""


def _markdown_counts(counts: Counter[str]) -> str:
    if not counts:
        return "_No rows._"
    lines = ["| classification | count |", "|---|---:|"]
    for key, count in sorted(counts.items()):
        lines.append(f"| `{key}` | {count} |")
    return "\n".join(lines)
