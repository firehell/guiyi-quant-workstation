from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_center import DataQualityReport, MarketDataFile


CLASSIFICATIONS = (
    "stale_processed_summary_failed",
    "active_failed",
    "warning_original_failed",
    "blocked_metadata_mismatch",
)


def audit_quality_failed_root_causes(
    *,
    session: Session,
    project_root: Path,
    target_coverage_matrix: Path,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    matrix_path = _resolve_path(project_root, target_coverage_matrix)
    rows = _read_records(matrix_path)
    candidates = [row for row in rows if _clean(row.get("issue_type")) == "quality_failed"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        path_text = _clean(row.get("standard_path"))
        if path_text:
            grouped[str(_resolve_path(project_root, Path(path_text)))].append(row)

    paths = sorted(grouped)
    manifest_by_path = _manifest_rows_by_path(project_root)
    processed_by_path = _processed_rows_by_path(project_root)
    before_counts = _database_counts(session)
    db_rows = list(session.scalars(select(MarketDataFile).where(MarketDataFile.file_path.in_(paths)))) if paths else []
    db_by_path: dict[str, list[MarketDataFile]] = defaultdict(list)
    for row in db_rows:
        db_by_path[str(Path(row.file_path))].append(row)
    file_ids = [row.id for row in db_rows]
    reports = list(
        session.scalars(
            select(DataQualityReport)
            .where(DataQualityReport.file_id.in_(file_ids))
            .order_by(DataQualityReport.created_at.desc(), DataQualityReport.id.desc())
        )
    ) if file_ids else []
    reports_by_file: dict[int, list[DataQualityReport]] = defaultdict(list)
    for report in reports:
        if report.file_id is not None:
            reports_by_file[report.file_id].append(report)

    ledger = [
        _audit_one(
            path=Path(path_text),
            target_rows=grouped[path_text],
            manifest_rows=manifest_by_path.get(path_text, []),
            processed_rows=processed_by_path.get(path_text, []),
            db_rows=sorted(db_by_path.get(path_text, []), key=lambda item: item.id),
            reports_by_file=reports_by_file,
        )
        for path_text in paths
    ]
    classifications = Counter(row["classification"] for row in ledger)
    after_counts = _database_counts(session)
    return {
        "mode": "quality_failed_root_cause_audit",
        "target_coverage_matrix": str(matrix_path),
        "candidate_target_row_count": len(candidates),
        "unique_path_count": len(paths),
        "classification_counts": {name: classifications.get(name, 0) for name in CLASSIFICATIONS},
        "database_counts_before": before_counts,
        "database_counts_after": after_counts,
        "database_counts_unchanged": before_counts == after_counts,
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
        "ledger": ledger,
    }


def write_quality_failed_root_cause_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "quality_failed_root_cause_ledger.csv"
    summary_path = output_dir / "QUALITY_FAILED_ROOT_CAUSE_AUDIT.md"
    pd.DataFrame(result["ledger"]).to_csv(ledger_path, index=False, lineterminator="\n")
    summary_path.write_text(_render_summary(result), encoding="utf-8")
    return {"ledger": ledger_path, "summary": summary_path}


def _audit_one(
    *,
    path: Path,
    target_rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]],
    processed_rows: list[dict[str, Any]],
    db_rows: list[MarketDataFile],
    reports_by_file: dict[int, list[DataQualityReport]],
) -> dict[str, Any]:
    physical = _physical_summary(path)
    active_statuses = {_clean(row.quality_status) for row in db_rows if _clean(row.quality_status)}
    manifest_statuses = {_clean(row.get("quality_status")) for row in manifest_rows if _clean(row.get("quality_status"))}
    processed_statuses = {_clean(row.get("quality_status")) for row in processed_rows if _clean(row.get("quality_status"))}
    report_statuses = {
        _clean(report.status)
        for row in db_rows
        for report in reports_by_file.get(row.id, [])
        if _clean(report.status)
    }
    original_statuses = {
        _clean((report.details or {}).get("original_quality_status"))
        for row in db_rows
        for report in reports_by_file.get(row.id, [])
        if _clean((report.details or {}).get("original_quality_status"))
    }
    issues: list[str] = []
    if not physical["exists"]:
        issues.append("physical_file_missing")
    elif physical["error"]:
        issues.append("duckdb_read_failed")
    if len(db_rows) != 1:
        issues.append("db_registration_missing" if not db_rows else "multiple_db_registrations")
    if not manifest_rows:
        issues.append("manifest_row_missing")
    if not processed_rows:
        issues.append("processed_summary_missing")
    if "failed" in active_statuses or "failed" in report_statuses or "failed" in manifest_statuses:
        classification = "active_failed"
    elif "failed" in processed_statuses and (active_statuses | manifest_statuses | report_statuses) & {"warning", "passed"}:
        classification = "stale_processed_summary_failed"
    elif "failed" in original_statuses and (active_statuses | report_statuses | manifest_statuses) & {"warning", "passed"}:
        classification = "warning_original_failed"
    else:
        classification = "blocked_metadata_mismatch"
    if issues and classification != "active_failed":
        classification = "blocked_metadata_mismatch"

    first_target = target_rows[0] if target_rows else {}
    db_row = db_rows[0] if db_rows else None
    return {
        "classification": classification,
        "product": _clean(first_target.get("product")) or _clean(getattr(db_row, "instrument_symbol", "")),
        "symbol_or_contract": _clean(first_target.get("symbol_or_contract")) or _clean(getattr(db_row, "contract_code", "")),
        "period": _clean(first_target.get("period")) or _clean(getattr(db_row, "period", "")),
        "covered_years": "|".join(sorted({_clean(row.get("year")) for row in target_rows if _clean(row.get("year"))})),
        "target_row_count": len(target_rows),
        "standard_path": str(path),
        "physical_exists": physical["exists"],
        "duckdb_row_count": physical["row_count"],
        "duckdb_min_datetime": physical["min_datetime"],
        "duckdb_max_datetime": physical["max_datetime"],
        "physical_error": physical["error"],
        "db_market_data_file_ids": "|".join(str(row.id) for row in db_rows),
        "db_quality_statuses": "|".join(sorted(active_statuses)),
        "data_quality_report_ids": "|".join(str(report.id) for row in db_rows for report in reports_by_file.get(row.id, [])),
        "data_quality_report_statuses": "|".join(sorted(report_statuses)),
        "manifest_quality_statuses": "|".join(sorted(manifest_statuses)),
        "processed_quality_statuses": "|".join(sorted(processed_statuses)),
        "report_original_quality_statuses": "|".join(sorted(original_statuses)),
        "abnormal_price_count": sum(int(report.abnormal_price_count or 0) for row in db_rows for report in reports_by_file.get(row.id, [])),
        "missing_bars": sum(int(report.missing_bars or 0) for row in db_rows for report in reports_by_file.get(row.id, [])),
        "duplicated_bars": sum(int(report.duplicated_bars or 0) for row in db_rows for report in reports_by_file.get(row.id, [])),
        "issues": "|".join(sorted(set(issues))),
    }


def _manifest_rows_by_path(project_root: Path) -> dict[str, list[dict[str, Any]]]:
    rows_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for manifest_path in sorted((project_root / "data" / "manifests").glob("rqdata_*_v2_history_*.csv")):
        for row in _read_records(manifest_path):
            standard_path = _clean(row.get("standard_path"))
            if standard_path:
                rows_by_path[str(_resolve_path(project_root, Path(standard_path)))].append({**row, "manifest_path": str(manifest_path)})
    return rows_by_path


def _processed_rows_by_path(project_root: Path) -> dict[str, list[dict[str, Any]]]:
    rows_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for summary_path in sorted((project_root / "data" / "processed" / "v1b").glob("*/*_v2_parquet_*.json")):
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        product = _clean(data.get("symbol")).lower()
        contract = _clean(data.get("contract")) or f"{product}.MAIN"
        for period, period_summary in (data.get("periods") or {}).items():
            standard = (period_summary or {}).get("standard") or {}
            path_text = _clean(standard.get("path"))
            if not path_text:
                continue
            rows_by_path[str(_resolve_path(project_root, Path(path_text)))].append(
                {
                    "product": product,
                    "contract": contract,
                    "period": period,
                    "quality_status": _clean(period_summary.get("quality_status")),
                    "data_version": _clean(period_summary.get("data_version")),
                    "summary_path": str(summary_path),
                }
            )
    return rows_by_path


def _physical_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "row_count": None, "min_datetime": "", "max_datetime": "", "error": "missing_physical_file"}
    try:
        with duckdb.connect(database=":memory:") as connection:
            row = connection.execute(
                "select count(*), min(datetime), max(datetime) from read_parquet(?)",
                [str(path)],
            ).fetchone()
        return {"exists": True, "row_count": int(row[0]), "min_datetime": _timestamp_text(row[1]), "max_datetime": _timestamp_text(row[2]), "error": ""}
    except Exception as exc:  # noqa: BLE001 - dry-run ledger records the per-file failure.
        return {"exists": True, "row_count": None, "min_datetime": "", "max_datetime": "", "error": f"{type(exc).__name__}: {exc}"}


def _database_counts(session: Session) -> dict[str, int]:
    return {
        "market_data_files": int(session.scalar(select(func.count(MarketDataFile.id))) or 0),
        "data_quality_reports": int(session.scalar(select(func.count(DataQualityReport.id))) or 0),
    }


def _render_summary(result: dict[str, Any]) -> str:
    before = result["database_counts_before"]
    after = result["database_counts_after"]
    lines = [
        "# Quality Failed Root-cause Audit",
        "",
        "## Result",
        "",
        f"- candidate_target_rows: {result['candidate_target_row_count']}",
        f"- unique_paths: {result['unique_path_count']}",
        *(f"- {name}: {result['classification_counts'][name]}" for name in CLASSIFICATIONS),
        f"- database_counts_unchanged: {result['database_counts_unchanged']}",
        f"- market_data_files: {before['market_data_files']} -> {after['market_data_files']}",
        f"- data_quality_reports: {before['data_quality_reports']} -> {after['data_quality_reports']}",
        "",
        "## Safety Boundary",
        "",
        "- writes_database=False",
        "- writes_parquet=False",
        "- writes_manifest=False",
        "- calls_rqdata=False",
        "- This audit does not upgrade warning assets to passed.",
    ]
    return "\n".join(lines) + "\n"


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=str).fillna("").to_dict("records")


def _resolve_path(project_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (project_root / path).resolve()


def _timestamp_text(value: Any) -> str:
    return "" if value is None else pd.Timestamp(value).isoformat()


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()
