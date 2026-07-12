from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.rqdata_ingest.parquet import sha256_file


CLASSIFICATIONS = (
    "already_registered",
    "eligible_for_registration",
    "duplicate_path_versions",
    "blocked_metadata_mismatch",
)
REQUIRED_COLUMNS = {"datetime", "open", "high", "low", "close", "volume", "open_interest"}


def reconcile_actual_contract_registrations(
    *,
    session: Session,
    project_root: Path,
    candidate_file: Path,
    manifest_root: Path | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    candidate_file = _resolve_path(project_root, candidate_file)
    manifest_root = (manifest_root or project_root / "data" / "manifests").resolve()
    candidates = _read_records(candidate_file)
    if not candidates:
        raise ValueError(f"candidate file has no rows: {candidate_file}")

    grouped_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        standard_path = _clean(row.get("standard_path"))
        if not standard_path:
            raise ValueError("candidate row is missing standard_path")
        grouped_candidates[str(_resolve_path(project_root, Path(standard_path)))].append(row)

    paths = sorted(grouped_candidates)
    manifests_by_path = _manifest_rows_by_path(project_root=project_root, manifest_root=manifest_root)
    before_counts = _database_counts(session)
    db_rows = list(session.scalars(select(MarketDataFile).where(MarketDataFile.file_path.in_(paths))))
    db_by_path: dict[str, list[MarketDataFile]] = defaultdict(list)
    for row in db_rows:
        db_by_path[str(Path(row.file_path))].append(row)
    db_file_ids = [row.id for row in db_rows]
    quality_reports = list(
        session.scalars(select(DataQualityReport).where(DataQualityReport.file_id.in_(db_file_ids)))
    ) if db_file_ids else []
    quality_reports_by_file_id: dict[int, list[DataQualityReport]] = defaultdict(list)
    for report in quality_reports:
        if report.file_id is not None:
            quality_reports_by_file_id[report.file_id].append(report)

    contracts = sorted({_clean(row.get("symbol_or_contract")) for row in candidates if _clean(row.get("symbol_or_contract"))})
    identity_rows = list(
        session.scalars(
            select(MarketDataFile).where(
                MarketDataFile.provider == "rqdata",
                MarketDataFile.data_type == "bars",
                MarketDataFile.contract_code.in_(contracts),
            )
        )
    )
    identity_index: dict[tuple[str, str, str, str], list[MarketDataFile]] = defaultdict(list)
    for row in identity_rows:
        identity_index[_identity_key(row.instrument_symbol, row.contract_code, row.period, row.data_version)].append(row)

    ledger: list[dict[str, Any]] = []
    for path_text in paths:
        candidate_rows = grouped_candidates[path_text]
        path = Path(path_text)
        manifest_rows = manifests_by_path.get(path_text, [])
        exact_db_rows = sorted(db_by_path.get(path_text, []), key=lambda row: row.id)
        ledger.append(
            _reconcile_one(
                path=path,
                candidate_rows=candidate_rows,
                manifest_rows=manifest_rows,
                exact_db_rows=exact_db_rows,
                identity_index=identity_index,
                quality_reports_by_file_id=quality_reports_by_file_id,
            )
        )

    after_counts = _database_counts(session)
    classifications = Counter(row["classification"] for row in ledger)
    return {
        "mode": "lpv_actual_contract_registration_dry_run",
        "candidate_file": str(candidate_file),
        "candidate_target_row_count": len(candidates),
        "unique_path_count": len(paths),
        "classification_counts": {name: classifications.get(name, 0) for name in CLASSIFICATIONS},
        "eligible_for_registration_count": classifications.get("eligible_for_registration", 0),
        "database_counts_before": before_counts,
        "database_counts_after": after_counts,
        "database_counts_unchanged": before_counts == after_counts,
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
        "ledger": ledger,
    }


def write_actual_contract_registration_reconcile_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "registration_reconcile_ledger.csv"
    summary_path = output_dir / "LPV_ACTUAL_CONTRACT_REGISTRATION_DRY_RUN.md"
    pd.DataFrame(result["ledger"]).to_csv(ledger_path, index=False, lineterminator="\n")
    summary_path.write_text(_render_summary(result), encoding="utf-8")
    return {"ledger": ledger_path, "summary": summary_path}


def _reconcile_one(
    *,
    path: Path,
    candidate_rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]],
    exact_db_rows: list[MarketDataFile],
    identity_index: dict[tuple[str, str, str, str], list[MarketDataFile]],
    quality_reports_by_file_id: dict[int, list[DataQualityReport]],
) -> dict[str, Any]:
    issues: list[str] = []
    physical = _physical_summary(path)
    if not physical["exists"]:
        issues.append("physical_file_missing")
    elif physical["error"]:
        issues.append("duckdb_read_failed")
    if len(manifest_rows) != 1:
        issues.append("manifest_row_missing" if not manifest_rows else "multiple_manifest_rows")

    manifest = manifest_rows[0] if len(manifest_rows) == 1 else {}
    candidate_products = sorted({_clean(row.get("product")) for row in candidate_rows if _clean(row.get("product"))})
    candidate_contracts = sorted({_clean(row.get("symbol_or_contract")) for row in candidate_rows if _clean(row.get("symbol_or_contract"))})
    candidate_periods = sorted({_clean(row.get("period")) for row in candidate_rows if _clean(row.get("period"))})
    candidate_years = sorted({_clean(row.get("year")) for row in candidate_rows if _clean(row.get("year"))})
    candidate_row_counts = sorted({_to_int(row.get("row_count")) for row in candidate_rows if _to_int(row.get("row_count")) is not None})
    if len(candidate_contracts) != 1 or len(candidate_periods) != 1 or len(candidate_row_counts) > 1:
        issues.append("candidate_metadata_inconsistent")

    manifest_product = _clean(manifest.get("product")).lower()
    manifest_contract = _clean(manifest.get("actual_contract"))
    manifest_period = _clean(manifest.get("period"))
    manifest_version = _clean(manifest.get("data_version"))
    manifest_checksum = _clean(manifest.get("checksum"))
    manifest_row_count = _to_int(manifest.get("row_count"))
    if manifest:
        if _clean(manifest.get("provider")) != "rqdata":
            issues.append("manifest_provider_not_rqdata")
        if _clean(manifest.get("data_role")) != "primary":
            issues.append("manifest_data_role_not_primary")
        if _clean(manifest.get("quality_status")) != "passed":
            issues.append("manifest_quality_not_passed")
        if _clean(manifest.get("status")) != "success":
            issues.append("manifest_status_not_success")
        if candidate_contracts and manifest_contract != candidate_contracts[0]:
            issues.append("manifest_contract_mismatch")
        if candidate_periods and manifest_period != candidate_periods[0]:
            issues.append("manifest_period_mismatch")
        if physical["exists"] and not physical["error"]:
            if manifest_row_count != physical["row_count"]:
                issues.append("manifest_row_count_mismatch")
            if manifest_checksum != physical["checksum"]:
                issues.append("manifest_checksum_mismatch")
            if not _same_timestamp(manifest.get("min_datetime"), physical["min_datetime"]):
                issues.append("manifest_min_datetime_mismatch")
            if not _same_timestamp(manifest.get("max_datetime"), physical["max_datetime"]):
                issues.append("manifest_max_datetime_mismatch")
            missing_columns = sorted(REQUIRED_COLUMNS - set(physical["columns"]))
            if missing_columns:
                issues.append("physical_required_columns_missing")

    identity_matches = identity_index.get(
        _identity_key(manifest_product, manifest_contract, manifest_period, manifest_version),
        [],
    )
    db_issues = _db_metadata_issues(
        exact_db_rows,
        manifest_product=manifest_product,
        manifest_contract=manifest_contract,
        manifest_period=manifest_period,
        manifest_version=manifest_version,
        physical=physical,
        quality_reports_by_file_id=quality_reports_by_file_id,
    )
    if issues:
        classification = "blocked_metadata_mismatch"
    elif len(exact_db_rows) > 1:
        classification = "duplicate_path_versions"
    elif len(exact_db_rows) == 1:
        classification = "blocked_metadata_mismatch" if db_issues else "already_registered"
    elif identity_matches:
        classification = "blocked_metadata_mismatch"
        db_issues.append("registration_identity_exists_at_different_path")
    else:
        classification = "eligible_for_registration"

    all_issues = sorted(set(issues + db_issues))
    return {
        "classification": classification,
        "product": manifest_product or "|".join(candidate_products),
        "actual_contract": manifest_contract or "|".join(candidate_contracts),
        "period": manifest_period or "|".join(candidate_periods),
        "covered_years": "|".join(candidate_years),
        "target_row_count": len(candidate_rows),
        "standard_path": str(path),
        "physical_exists": physical["exists"],
        "duckdb_row_count": physical["row_count"],
        "duckdb_min_datetime": physical["min_datetime"],
        "duckdb_max_datetime": physical["max_datetime"],
        "physical_checksum": physical["checksum"],
        "physical_file_size_bytes": physical["file_size_bytes"],
        "physical_error": physical["error"],
        "manifest_row_count": len(manifest_rows),
        "manifest_data_version": manifest_version,
        "manifest_quality_status": _clean(manifest.get("quality_status")),
        "manifest_checksum": manifest_checksum,
        "db_exact_path_count": len(exact_db_rows),
        "db_market_data_file_ids": "|".join(str(row.id) for row in exact_db_rows),
        "db_data_versions": "|".join(_clean(row.data_version) for row in exact_db_rows),
        "db_quality_report_ids": "|".join(
            str(report.id) for row in exact_db_rows for report in quality_reports_by_file_id.get(row.id, [])
        ),
        "db_quality_report_statuses": "|".join(
            _clean(report.status) for row in exact_db_rows for report in quality_reports_by_file_id.get(row.id, [])
        ),
        "db_identity_match_count": len(identity_matches),
        "issues": "|".join(all_issues),
    }


def _manifest_rows_by_path(*, project_root: Path, manifest_root: Path) -> dict[str, list[dict[str, Any]]]:
    rows_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for manifest_path in sorted(manifest_root.glob("rqdata_actual_contract_bars_*.csv")):
        if manifest_path.name == "rqdata_actual_contract_bars_batch.csv":
            continue
        for row in _read_records(manifest_path):
            standard_path = _clean(row.get("standard_path"))
            if not standard_path:
                continue
            resolved = str(_resolve_path(project_root, Path(standard_path)))
            rows_by_path[resolved].append({**row, "manifest_path": str(manifest_path)})
    return rows_by_path


def _physical_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "row_count": None,
            "min_datetime": "",
            "max_datetime": "",
            "columns": [],
            "checksum": "",
            "file_size_bytes": None,
            "error": "missing_physical_file",
        }
    try:
        with duckdb.connect(database=":memory:") as connection:
            row = connection.execute(
                "select count(*), min(datetime), max(datetime) from read_parquet(?)",
                [str(path)],
            ).fetchone()
            columns = [item[0] for item in connection.execute("describe select * from read_parquet(?)", [str(path)]).fetchall()]
        return {
            "exists": True,
            "row_count": int(row[0]),
            "min_datetime": _timestamp_text(row[1]),
            "max_datetime": _timestamp_text(row[2]),
            "columns": columns,
            "checksum": sha256_file(path),
            "file_size_bytes": path.stat().st_size,
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - dry-run must preserve per-file errors in its ledger.
        return {
            "exists": True,
            "row_count": None,
            "min_datetime": "",
            "max_datetime": "",
            "columns": [],
            "checksum": "",
            "file_size_bytes": path.stat().st_size,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _db_metadata_issues(
    rows: list[MarketDataFile],
    *,
    manifest_product: str,
    manifest_contract: str,
    manifest_period: str,
    manifest_version: str,
    physical: dict[str, Any],
    quality_reports_by_file_id: dict[int, list[DataQualityReport]],
) -> list[str]:
    issues: list[str] = []
    if len(rows) != 1:
        return issues
    row = rows[0]
    if row.provider != "rqdata" or row.data_type != "bars":
        issues.append("db_provider_or_data_type_mismatch")
    if row.instrument_symbol != manifest_product or row.contract_code != manifest_contract or row.period != manifest_period:
        issues.append("db_registration_identity_mismatch")
    if row.data_version != manifest_version:
        issues.append("db_data_version_mismatch")
    if row.data_role != "primary" or row.quality_status != "passed":
        issues.append("db_active_metadata_mismatch")
    reports = quality_reports_by_file_id.get(row.id, [])
    if len(reports) != 1:
        issues.append("db_quality_report_missing" if not reports else "multiple_db_quality_reports")
    elif reports[0].status != "passed":
        issues.append("db_quality_report_not_passed")
    if not physical["error"]:
        if row.row_count != physical["row_count"]:
            issues.append("db_row_count_mismatch")
        if row.checksum != physical["checksum"]:
            issues.append("db_checksum_mismatch")
        if row.file_size_bytes != physical["file_size_bytes"]:
            issues.append("db_file_size_mismatch")
    return issues


def _database_counts(session: Session) -> dict[str, int]:
    return {
        "market_data_files": int(session.scalar(select(func.count(MarketDataFile.id))) or 0),
        "data_quality_reports": int(session.scalar(select(func.count(DataQualityReport.id))) or 0),
    }


def _render_summary(result: dict[str, Any]) -> str:
    counts = result["classification_counts"]
    before = result["database_counts_before"]
    after = result["database_counts_after"]
    lines = [
        "# LPV Actual Contract Registration Dry-run",
        "",
        "## Result",
        "",
        f"- candidate_target_rows: {result['candidate_target_row_count']}",
        f"- unique_paths: {result['unique_path_count']}",
        *(f"- {name}: {counts[name]}" for name in CLASSIFICATIONS),
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
        "- Duplicate path versions are reported only; no historical DB row is deleted, merged, archived or changed.",
        "",
        "## Human Gate",
        "",
    ]
    if result["eligible_for_registration_count"]:
        lines.append("- True registration candidates remain. Stop and request explicit authorization before designing any DB write path.")
    else:
        lines.append("- No registration candidate remains. Controlled DB registration is not authorized or required by this dry-run.")
    return "\n".join(lines) + "\n"


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=str).fillna("").to_dict("records")


def _resolve_path(project_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (project_root / path).resolve()


def _identity_key(product: Any, contract: Any, period: Any, data_version: Any) -> tuple[str, str, str, str]:
    return (_clean(product).lower(), _clean(contract), _clean(period), _clean(data_version))


def _same_timestamp(left: Any, right: Any) -> bool:
    if not _clean(left) or not _clean(right):
        return False
    return pd.Timestamp(left) == pd.Timestamp(right)


def _timestamp_text(value: Any) -> str:
    return "" if value is None else pd.Timestamp(value).isoformat()


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _to_int(value: Any) -> int | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None
