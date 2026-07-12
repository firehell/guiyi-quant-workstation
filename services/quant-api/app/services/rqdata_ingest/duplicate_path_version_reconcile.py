from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_center import DataQualityReport, MarketDataFile


CLASSIFICATIONS = ("duplicate_path_versions", "blocked_metadata_mismatch")


def reconcile_duplicate_path_versions(
    *,
    session: Session,
    project_root: Path,
    lpv_ledger: Path,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    ledger_path = _resolve_path(project_root, lpv_ledger)
    rows = [row for row in _read_records(ledger_path) if _clean(row.get("classification")) == "duplicate_path_versions"]
    paths = sorted({_clean(row.get("standard_path")) for row in rows if _clean(row.get("standard_path"))})
    before_counts = _database_counts(session)
    db_rows = list(session.scalars(select(MarketDataFile).where(MarketDataFile.file_path.in_(paths)))) if paths else []
    db_by_path: dict[str, list[MarketDataFile]] = {}
    for row in db_rows:
        db_by_path.setdefault(str(Path(row.file_path)), []).append(row)
    file_ids = [row.id for row in db_rows]
    reports = list(session.scalars(select(DataQualityReport).where(DataQualityReport.file_id.in_(file_ids)))) if file_ids else []
    report_status_by_file = {report.file_id: report.status for report in reports if report.file_id is not None}

    output_rows = []
    for row in rows:
        path_text = _clean(row.get("standard_path"))
        exact_rows = sorted(db_by_path.get(path_text, []), key=lambda item: item.id)
        manifest_version = _clean(row.get("manifest_data_version"))
        current = [item for item in exact_rows if _clean(item.data_version) == manifest_version]
        superseded = [item for item in exact_rows if _clean(item.data_version) != manifest_version]
        issues: list[str] = []
        if len(exact_rows) < 2:
            issues.append("db_duplicate_rows_missing")
        if len(current) != 1:
            issues.append("current_version_not_unique")
        classification = "blocked_metadata_mismatch" if issues else "duplicate_path_versions"
        output_rows.append(
            {
                "classification": classification,
                "product": _clean(row.get("product")),
                "actual_contract": _clean(row.get("actual_contract")),
                "period": _clean(row.get("period")),
                "standard_path": path_text,
                "manifest_data_version": manifest_version,
                "current_market_data_file_id": "|".join(str(item.id) for item in current),
                "current_data_version": "|".join(_clean(item.data_version) for item in current),
                "superseded_market_data_file_ids": "|".join(str(item.id) for item in superseded),
                "superseded_data_versions": "|".join(_clean(item.data_version) for item in superseded),
                "db_exact_path_count": len(exact_rows),
                "db_quality_statuses": "|".join(_clean(item.quality_status) for item in exact_rows),
                "db_quality_report_statuses": "|".join(_clean(report_status_by_file.get(item.id)) for item in exact_rows),
                "recommended_action": "report_only_human_gate_required",
                "issues": "|".join(sorted(set(issues))),
            }
        )

    classifications = Counter(row["classification"] for row in output_rows)
    after_counts = _database_counts(session)
    return {
        "mode": "duplicate_path_version_reconcile",
        "lpv_ledger": str(ledger_path),
        "input_duplicate_rows": len(rows),
        "unique_path_count": len(paths),
        "classification_counts": {name: classifications.get(name, 0) for name in CLASSIFICATIONS},
        "database_counts_before": before_counts,
        "database_counts_after": after_counts,
        "database_counts_unchanged": before_counts == after_counts,
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
        "ledger": output_rows,
    }


def write_duplicate_path_version_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "duplicate_path_version_ledger.csv"
    summary_path = output_dir / "DUPLICATE_PATH_VERSION_RECONCILE.md"
    pd.DataFrame(result["ledger"]).to_csv(ledger_path, index=False, lineterminator="\n")
    summary_path.write_text(_render_summary(result), encoding="utf-8")
    return {"ledger": ledger_path, "summary": summary_path}


def _database_counts(session: Session) -> dict[str, int]:
    return {
        "market_data_files": int(session.scalar(select(func.count(MarketDataFile.id))) or 0),
        "data_quality_reports": int(session.scalar(select(func.count(DataQualityReport.id))) or 0),
    }


def _render_summary(result: dict[str, Any]) -> str:
    before = result["database_counts_before"]
    after = result["database_counts_after"]
    lines = [
        "# Duplicate Path Version Reconcile",
        "",
        "## Result",
        "",
        f"- input_duplicate_rows: {result['input_duplicate_rows']}",
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
        "- No historical DB row is deleted, archived, merged, or modified.",
    ]
    return "\n".join(lines) + "\n"


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=str).fillna("").to_dict("records")


def _resolve_path(project_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (project_root / path).resolve()


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()
