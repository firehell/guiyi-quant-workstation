from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.data_center import MarketDataFile
from app.services.rqdata_ingest.parquet import sha256_file


MODE = "source_interval_provenance_repair_dry_run"
APPLY_MODE = "source_interval_provenance_repair_apply"
CONFIRM_FLAG = "--confirm-source-interval-provenance-repair"
DEFAULT_ISSUE_REGISTER = Path("data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/issue_register.csv")
DEFAULT_TRIAGE_REPORT = Path("data/reports/target_coverage_gap_triage_20260711/source_interval_unverified_triage.csv")


@dataclass(frozen=True)
class PathRecord:
    path: Path
    checksum: str
    row_count: int | None


class ApplyBlockedError(RuntimeError):
    pass


def run_source_interval_provenance_repair_dry_run(
    *,
    project_root: Path,
    triage_report: Path = DEFAULT_TRIAGE_REPORT,
    issue_register: Path = DEFAULT_ISSUE_REGISTER,
    output_dir: Path,
    write_outputs: bool = True,
) -> dict[str, Any]:
    triage_rows = _read_csv_records(_resolve_path(project_root, triage_report))
    source_rows = [row for row in triage_rows if _clean_text(row.get("issue_type")) == "source_interval_unverified"]
    issue_rows = _read_csv_records(_resolve_path(project_root, issue_register))

    products = sorted({_clean_text(row.get("product")).lower() for row in source_rows if _clean_text(row.get("product"))})
    manifest_index = _index_manifests(project_root=project_root, products=products)
    processed_index = _index_processed_summaries(project_root=project_root, products=products)

    rows_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        path = _resolve_path(project_root, _clean_text(row.get("standard_path")))
        if path is not None:
            rows_by_path[str(path)] .append(row)

    candidate_rows = []
    affected_rows = []
    for index, (path_text, rows) in enumerate(sorted(rows_by_path.items()), start=1):
        candidate = _candidate_for_path(
            candidate_id=f"source_interval_{index:04d}",
            path=Path(path_text),
            rows=rows,
            manifest_index=manifest_index,
            processed_index=processed_index,
        )
        candidate_rows.append(candidate)
        for row in rows:
            affected_rows.append(_affected_row(candidate, row))

    summary = _render_summary(
        source_rows=source_rows,
        candidate_rows=candidate_rows,
        affected_rows=affected_rows,
        issue_rows=issue_rows,
        output_dir=output_dir,
    )
    outputs = {
        "candidate_files": output_dir / "candidate_files.csv",
        "affected_coverage_rows": output_dir / "affected_coverage_rows.csv",
        "summary": output_dir / "SOURCE_INTERVAL_PROVENANCE_REPAIR_DRY_RUN.md",
    }
    if write_outputs:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(outputs["candidate_files"], candidate_rows)
        _write_csv(outputs["affected_coverage_rows"], affected_rows)
        outputs["summary"].write_text(summary, encoding="utf-8")
    return {
        "mode": MODE,
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "writes_processed_summary": False,
        "calls_rqdata": False,
        "candidate_files": candidate_rows,
        "affected_coverage_rows": affected_rows,
        "summary": summary,
        "outputs": outputs,
    }


def run_source_interval_provenance_repair_apply(
    *,
    project_root: Path,
    session: Session | None,
    candidate_files: Path,
    output_dir: Path,
    apply: bool = False,
    confirm: bool = False,
    candidate_ids: list[str] | None = None,
    limit: int | None = None,
    stop_on_error: bool = True,
    write_outputs: bool = True,
) -> dict[str, Any]:
    candidates = _select_candidates(
        _read_csv_records(_resolve_path(project_root, candidate_files)),
        candidate_ids=candidate_ids,
        limit=limit,
    )
    apply_rows: list[dict[str, Any]] = []
    blocked_reasons: list[str] = []
    writes_parquet = False
    writes_manifest = False
    writes_processed_summary = False
    writes_database = False

    if apply and not confirm:
        blocked_reasons.append("confirmation_required")

    for candidate in candidates:
        if apply and confirm and not blocked_reasons:
            row = _apply_candidate(project_root=project_root, session=session, candidate=candidate, output_dir=output_dir)
        else:
            reason = ",".join(sorted(set(blocked_reasons))) if blocked_reasons else "dry_run"
            row = _apply_row(candidate, applied=False, skipped=not apply, skip_reason=reason)
        apply_rows.append(row)
        if row["applied"] == "True":
            writes_parquet = writes_parquet or row["writes_parquet"] == "True"
            writes_manifest = writes_manifest or row["writes_manifest"] == "True"
            writes_processed_summary = writes_processed_summary or row["writes_processed_summary"] == "True"
            writes_database = writes_database or row["writes_database"] == "True"
        if row["blocked_reason"]:
            blocked_reasons.extend(row["blocked_reason"].split("|"))
            if stop_on_error:
                break

    result = {
        "mode": APPLY_MODE,
        "operation": "apply" if apply else "dry-run",
        "confirm": confirm,
        "confirm_flag": CONFIRM_FLAG,
        "candidate_files_path": str(candidate_files),
        "selected_candidate_count": len(candidates),
        "processed_candidate_count": len(apply_rows),
        "applied_candidate_count": sum(1 for row in apply_rows if row["applied"] == "True"),
        "skipped_candidate_count": sum(1 for row in apply_rows if row["skipped"] == "True"),
        "blocked_candidate_count": sum(1 for row in apply_rows if row["blocked_reason"]),
        "writes_database": writes_database,
        "writes_parquet": writes_parquet,
        "writes_manifest": writes_manifest,
        "writes_processed_summary": writes_processed_summary,
        "calls_rqdata": False,
        "blocked_reasons": sorted({reason for reason in blocked_reasons if reason}),
        "apply_rows": apply_rows,
        "output_dir": output_dir,
    }
    outputs = {
        "apply": output_dir / "source_interval_apply_ledger.csv",
        "summary": output_dir / "SOURCE_INTERVAL_PROVENANCE_REPAIR_APPLY.md",
    }
    summary = _render_apply_summary(result=result, output_dir=output_dir)
    if write_outputs:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(outputs["apply"], apply_rows, fieldnames=_apply_fieldnames())
        outputs["summary"].write_text(summary, encoding="utf-8")
    return {**result, "outputs": outputs, "summary": summary}


def _candidate_for_path(
    *,
    candidate_id: str,
    path: Path,
    rows: list[dict[str, Any]],
    manifest_index: dict[str, list[PathRecord]],
    processed_index: dict[str, list[PathRecord]],
) -> dict[str, Any]:
    first = rows[0]
    summary = _parquet_summary(path)
    manifest_records = manifest_index.get(str(path), [])
    processed_records = processed_index.get(str(path), [])
    source_interval_status = _source_interval_status(summary)
    blocked_reasons = _blocked_reasons(rows=rows, summary=summary, manifest_records=manifest_records, source_interval_status=source_interval_status)
    checksum_before = summary["checksum_before"]
    return {
        "candidate_id": candidate_id,
        "product": _clean_text(first.get("product")).lower(),
        "period": _clean_text(first.get("period")),
        "contract": _clean_text(first.get("symbol_or_contract")),
        "standard_path": str(path),
        "affected_target_rows": len(rows),
        "affected_years": "|".join(sorted({_clean_text(row.get("year")) for row in rows if _clean_text(row.get("year"))})),
        "db_market_data_file_id": _clean_db_id(first.get("db_market_data_file_id")),
        "data_role": _clean_text(first.get("data_role")),
        "quality_status": _clean_text(first.get("quality_status")),
        "row_count": _clean_int(first.get("row_count")),
        "duckdb_row_count": summary["duckdb_row_count"],
        "min_datetime": summary["min_datetime"],
        "max_datetime": summary["max_datetime"],
        "columns_before": "|".join(summary["columns_before"]),
        "source_interval_status": source_interval_status,
        "observed_source_interval_values": "|".join(summary["source_interval_values"]),
        "proposed_source_interval": "1m",
        "checksum_before": checksum_before,
        "file_size_before": summary["file_size_before"],
        "manifest_path": "|".join(str(record.path) for record in manifest_records),
        "processed_summary_path": "|".join(str(record.path) for record in processed_records),
        "manifest_checksum_matches_before": _records_match_checksum(manifest_records, checksum_before),
        "processed_summary_checksum_matches_before": _records_match_checksum(processed_records, checksum_before),
        "db_checksum_sync_required": bool(_clean_db_id(first.get("db_market_data_file_id"))),
        "manifest_checksum_sync_required": bool(manifest_records),
        "processed_summary_checksum_sync_required": bool(processed_records),
        "db_file_size_sync_required": bool(_clean_db_id(first.get("db_market_data_file_id"))),
        "apply_eligible": not blocked_reasons,
        "blocked_reason": "|".join(blocked_reasons),
        "read_error": summary["read_error"],
    }


def _affected_row(candidate: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "product": _clean_text(row.get("product")).lower(),
        "contract_role": _clean_text(row.get("contract_role")),
        "symbol_or_contract": _clean_text(row.get("symbol_or_contract")),
        "period": _clean_text(row.get("period")),
        "year": _clean_text(row.get("year")),
        "status": _clean_text(row.get("status")),
        "issue_type": _clean_text(row.get("issue_type")),
        "expected_start": _clean_text(row.get("expected_start")),
        "expected_end": _clean_text(row.get("expected_end")),
        "quality_status": _clean_text(row.get("quality_status")),
        "row_count": _clean_text(row.get("row_count")),
        "db_market_data_file_id": _clean_db_id(row.get("db_market_data_file_id")),
        "standard_path": _clean_text(row.get("standard_path")),
        "root_cause_bucket": _clean_text(row.get("root_cause_bucket")),
        "candidate_apply_eligible": candidate["apply_eligible"],
        "candidate_blocked_reason": candidate["blocked_reason"],
    }


def _blocked_reasons(
    *,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    manifest_records: list[PathRecord],
    source_interval_status: str,
) -> list[str]:
    reasons: list[str] = []
    if not summary["exists"]:
        reasons.append("missing_physical_file")
    if summary["read_error"]:
        reasons.append("parquet_read_failed")
    if not manifest_records:
        reasons.append("manifest_row_missing")
    if source_interval_status != "source_interval_column_missing":
        reasons.append(source_interval_status)
    if any(_clean_text(row.get("quality_status")) != "passed" for row in rows):
        reasons.append("quality_status_not_passed")
    if any(_clean_text(row.get("data_role")) != "primary" for row in rows):
        reasons.append("data_role_not_primary")
    audit_counts = {_clean_int(row.get("row_count")) for row in rows if _clean_text(row.get("row_count"))}
    if len(audit_counts) > 1:
        reasons.append("inconsistent_audit_row_count")
    if audit_counts and summary["duckdb_row_count"] is not None and summary["duckdb_row_count"] not in audit_counts:
        reasons.append("duckdb_row_count_mismatch")
    return sorted(set(reasons))


def _parquet_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "columns_before": [],
            "source_interval_values": [],
            "duckdb_row_count": None,
            "min_datetime": "",
            "max_datetime": "",
            "checksum_before": "",
            "file_size_before": "",
            "read_error": "missing_physical_file",
        }
    try:
        schema = pq.read_schema(path)
        columns = list(schema.names)
        source_values = _source_interval_values(path, columns)
        stats = _duckdb_summary(path)
        return {
            "exists": True,
            "columns_before": columns,
            "source_interval_values": source_values,
            "duckdb_row_count": stats["row_count"],
            "min_datetime": stats["min_datetime"],
            "max_datetime": stats["max_datetime"],
            "checksum_before": sha256_file(path),
            "file_size_before": path.stat().st_size,
            "read_error": stats["error"],
        }
    except Exception as exc:  # noqa: BLE001 - dry-run report should preserve per-file errors.
        return {
            "exists": True,
            "columns_before": [],
            "source_interval_values": [],
            "duckdb_row_count": None,
            "min_datetime": "",
            "max_datetime": "",
            "checksum_before": "",
            "file_size_before": path.stat().st_size,
            "read_error": f"{type(exc).__name__}: {exc}",
        }


def _source_interval_values(path: Path, columns: list[str]) -> list[str]:
    if "source_interval" not in columns:
        return []
    try:
        frame = pd.read_parquet(path, columns=["source_interval"])
    except Exception:
        return []
    return sorted(str(value) for value in frame["source_interval"].dropna().astype(str).unique())


def _duckdb_summary(path: Path) -> dict[str, Any]:
    try:
        with duckdb.connect(database=":memory:") as connection:
            row = connection.execute(
                "select count(*) as row_count, min(datetime)::varchar as min_datetime, max(datetime)::varchar as max_datetime from read_parquet(?)",
                [str(path)],
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 - preserve the exact file-level read failure.
        return {"row_count": None, "min_datetime": "", "max_datetime": "", "error": f"{type(exc).__name__}: {exc}"}
    return {"row_count": int(row[0]), "min_datetime": row[1] or "", "max_datetime": row[2] or "", "error": ""}


def _source_interval_status(summary: dict[str, Any]) -> str:
    columns = set(summary["columns_before"])
    if "source_interval" not in columns:
        return "source_interval_column_missing"
    values = set(summary["source_interval_values"])
    if values == {"1m"}:
        return "already_source_interval_1m"
    if not values:
        return "source_interval_values_empty"
    return "source_interval_values_unexpected"


def _index_manifests(*, project_root: Path, products: list[str]) -> dict[str, list[PathRecord]]:
    index: dict[str, list[PathRecord]] = defaultdict(list)
    for product in products:
        for manifest_path in sorted((project_root / "data" / "manifests").glob(f"rqdata_{product}_v2_history_*.csv")):
            for row in _read_csv_records(manifest_path):
                standard_path = _resolve_path(project_root, _clean_text(row.get("standard_path")))
                if standard_path is None:
                    continue
                index[str(standard_path)].append(
                    PathRecord(
                        path=manifest_path,
                        checksum=_clean_text(row.get("checksum")),
                        row_count=_clean_int(row.get("row_count")),
                    )
                )
    return index


def _index_processed_summaries(*, project_root: Path, products: list[str]) -> dict[str, list[PathRecord]]:
    index: dict[str, list[PathRecord]] = defaultdict(list)
    for product in products:
        for summary_path in sorted((project_root / "data" / "processed" / "v1b" / product).glob("*.json")):
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for period_summary in (summary.get("periods") or {}).values():
                standard = (period_summary or {}).get("standard") or {}
                standard_path = _resolve_path(project_root, _clean_text(standard.get("path")))
                if standard_path is None:
                    continue
                index[str(standard_path)].append(
                    PathRecord(
                        path=summary_path,
                        checksum=_clean_text(standard.get("checksum")),
                        row_count=_clean_int(standard.get("row_count")),
                    )
                )
    return index


def _render_summary(
    *,
    source_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    affected_rows: list[dict[str, Any]],
    issue_rows: list[dict[str, Any]],
    output_dir: Path,
) -> str:
    period_counts = Counter(row["period"] for row in candidate_rows)
    status_counts = Counter(row["source_interval_status"] for row in candidate_rows)
    eligible_counts = Counter(str(row["apply_eligible"]) for row in candidate_rows)
    issue_count = sum(1 for row in issue_rows if _clean_text(row.get("issue_type")) == "source_interval_unverified")
    lines = [
        "# Source Interval Provenance Repair Dry Run",
        "",
        f"- mode: `{MODE}`",
        f"- output_dir: `{output_dir}`",
        "- writes_database: `False`",
        "- writes_parquet: `False`",
        "- writes_manifest: `False`",
        "- writes_processed_summary: `False`",
        "- calls_rqdata: `False`",
        "",
        "## Executive Result",
        "",
        f"- affected_coverage_rows: `{len(affected_rows)}`",
        f"- unique_candidate_files: `{len(candidate_rows)}`",
        f"- source_interval_issue_register_rows: `{issue_count}`",
        f"- source_interval_triage_rows: `{len(source_rows)}`",
        "",
        "## Candidate File Counts",
        "",
        _markdown_counts(period_counts, "period"),
        "",
        "## Source Interval Status",
        "",
        _markdown_counts(status_counts, "status"),
        "",
        "## Apply Eligibility",
        "",
        _markdown_counts(eligible_counts, "apply_eligible"),
        "",
        "## Synchronization Boundary",
        "",
        "- This run only creates per-file repair candidates.",
        "- If an apply task rewrites Parquet to add `source_interval=1m`, it must refresh the file checksum and file size evidence.",
        "- The same apply task must update manifest checksum rows, processed summary checksum rows when present, and DB `market_data_files.checksum` for rows with `db_market_data_file_id`.",
        "- `quality_status`, `data_role`, `data_version`, row counts and OHLCV values are not changed by this dry-run.",
        "",
        "## Next Gate",
        "",
        "- Open a separate controlled apply task only after reviewing `candidate_files.csv`.",
        "- The apply task must remain file-level, because multiple target years can map to the same Parquet file.",
    ]
    return "\n".join(lines) + "\n"


def _select_candidates(
    rows: list[dict[str, Any]],
    *,
    candidate_ids: list[str] | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    selected = rows
    if candidate_ids:
        wanted = set(candidate_ids)
        selected = [row for row in selected if _clean_text(row.get("candidate_id")) in wanted]
    if limit is not None:
        selected = selected[:limit]
    return selected


def _apply_candidate(*, project_root: Path, session: Session | None, candidate: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    row = _apply_row(candidate, applied=False, skipped=False, skip_reason="")
    path = _resolve_path(project_root, _clean_text(candidate.get("standard_path")))
    if path is None:
        return {**row, "blocked_reason": "missing_standard_path"}

    current = _parquet_summary(path)
    already_applied_reason = _already_applied_reason(project_root=project_root, session=session, candidate=candidate, current=current)
    if already_applied_reason == "already_applied":
        return _apply_row(
            candidate,
            applied=False,
            skipped=True,
            skip_reason="already_applied",
            after_checksum=current["checksum_before"],
            after_file_size=current["file_size_before"],
            after_row_count=current["duckdb_row_count"],
            after_min_datetime=current["min_datetime"],
            after_max_datetime=current["max_datetime"],
        )
    if already_applied_reason:
        return {**row, "blocked_reason": already_applied_reason}

    blockers = _pre_apply_blockers(project_root=project_root, session=session, candidate=candidate, current=current)
    if blockers:
        return {**row, "blocked_reason": "|".join(blockers)}

    backup_records = _backup_candidate_files(project_root=project_root, candidate=candidate, output_dir=output_dir)
    try:
        before_checksum = _clean_text(candidate.get("checksum_before"))
        before_file_size = _clean_int(candidate.get("file_size_before"))
        _rewrite_parquet_with_source_interval(path, _clean_text(candidate.get("proposed_source_interval")) or "1m")
        after = _parquet_summary(path)
        _validate_after_rewrite(candidate=candidate, before=current, after=after)
        after_checksum = after["checksum_before"]
        after_file_size = after["file_size_before"]
        manifest_updates = _update_manifest_files(project_root=project_root, candidate=candidate, checksum_before=before_checksum, checksum_after=after_checksum, file_size_after=after_file_size)
        processed_updates = _update_processed_summaries(project_root=project_root, candidate=candidate, checksum_before=before_checksum, checksum_after=after_checksum, file_size_after=after_file_size)
        db_updated = _update_market_data_file(
            session=session,
            candidate=candidate,
            checksum_before=before_checksum,
            checksum_after=after_checksum,
            file_size_before=before_file_size,
            file_size_after=after_file_size,
        )
        if session is not None:
            session.commit()
        return _apply_row(
            candidate,
            applied=True,
            skipped=False,
            skip_reason="",
            after_checksum=after_checksum,
            after_file_size=after_file_size,
            after_row_count=after["duckdb_row_count"],
            after_min_datetime=after["min_datetime"],
            after_max_datetime=after["max_datetime"],
            manifest_updates=manifest_updates,
            processed_summary_updates=processed_updates,
            db_updates=db_updated,
            backup_paths="|".join(f"{item['source']}=>{item['backup']}" for item in backup_records),
        )
    except Exception as exc:  # noqa: BLE001 - apply ledger must preserve file-level failure detail.
        if session is not None:
            session.rollback()
        _restore_backups(backup_records)
        return {
            **row,
            "blocked_reason": f"apply_failed:{type(exc).__name__}",
            "error_message": str(exc),
            "backup_paths": "|".join(f"{item['source']}=>{item['backup']}" for item in backup_records),
        }


def _pre_apply_blockers(*, project_root: Path, session: Session | None, candidate: dict[str, Any], current: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not _clean_bool(candidate.get("apply_eligible")):
        blockers.append("candidate_not_apply_eligible")
    if current["read_error"]:
        blockers.append("parquet_read_failed")
    if current["source_interval_values"]:
        blockers.append("source_interval_not_missing")
    if _source_interval_status(current) != "source_interval_column_missing":
        blockers.append(_source_interval_status(current))
    if current["checksum_before"] != _clean_text(candidate.get("checksum_before")):
        blockers.append("parquet_checksum_changed")
    if current["file_size_before"] != _clean_int(candidate.get("file_size_before")):
        blockers.append("parquet_file_size_changed")
    if current["duckdb_row_count"] != _clean_int(candidate.get("duckdb_row_count")):
        blockers.append("duckdb_row_count_changed")
    if current["min_datetime"] != _clean_text(candidate.get("min_datetime")):
        blockers.append("min_datetime_changed")
    if current["max_datetime"] != _clean_text(candidate.get("max_datetime")):
        blockers.append("max_datetime_changed")
    blockers.extend(_manifest_sync_blockers(project_root=project_root, candidate=candidate, checksum=_clean_text(candidate.get("checksum_before"))))
    blockers.extend(_processed_sync_blockers(project_root=project_root, candidate=candidate, checksum=_clean_text(candidate.get("checksum_before"))))
    blockers.extend(_db_sync_blockers(session=session, candidate=candidate, checksum=_clean_text(candidate.get("checksum_before")), file_size=_clean_int(candidate.get("file_size_before"))))
    return sorted(set(blockers))


def _already_applied_reason(*, project_root: Path, session: Session | None, candidate: dict[str, Any], current: dict[str, Any]) -> str:
    if _source_interval_status(current) != "already_source_interval_1m":
        return ""
    checksum = current["checksum_before"]
    file_size = current["file_size_before"]
    blockers = []
    blockers.extend(_manifest_sync_blockers(project_root=project_root, candidate=candidate, checksum=checksum))
    blockers.extend(_processed_sync_blockers(project_root=project_root, candidate=candidate, checksum=checksum))
    blockers.extend(_db_sync_blockers(session=session, candidate=candidate, checksum=checksum, file_size=file_size))
    return "already_applied_metadata_mismatch" if blockers else "already_applied"


def _rewrite_parquet_with_source_interval(path: Path, source_interval: str) -> None:
    table = pq.ParquetFile(path).read()
    if "source_interval" in table.column_names:
        raise ApplyBlockedError("source_interval column already exists")
    table = table.append_column("source_interval", pa.array([source_interval] * table.num_rows))
    tmp_path = path.with_name(f"{path.name}.tmp-source-interval")
    pq.write_table(table, tmp_path)
    os.replace(tmp_path, path)


def _validate_after_rewrite(*, candidate: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> None:
    if after["read_error"]:
        raise ApplyBlockedError(after["read_error"])
    if _source_interval_status(after) != "already_source_interval_1m":
        raise ApplyBlockedError("source_interval_after_not_1m")
    for key in ("duckdb_row_count", "min_datetime", "max_datetime"):
        if before[key] != after[key]:
            raise ApplyBlockedError(f"{key}_changed_after_rewrite")
    if after["duckdb_row_count"] != _clean_int(candidate.get("duckdb_row_count")):
        raise ApplyBlockedError("candidate_row_count_changed_after_rewrite")


def _backup_candidate_files(*, project_root: Path, candidate: dict[str, Any], output_dir: Path) -> list[dict[str, str]]:
    backup_root = output_dir / "backups" / _clean_text(candidate.get("candidate_id"))
    backup_root.mkdir(parents=True, exist_ok=True)
    paths = [_resolve_path(project_root, _clean_text(candidate.get("standard_path")))]
    paths.extend(_split_paths(project_root, candidate.get("manifest_path")))
    paths.extend(_split_paths(project_root, candidate.get("processed_summary_path")))
    records: list[dict[str, str]] = []
    for index, source in enumerate((path for path in paths if path is not None and path.exists()), start=1):
        backup = backup_root / f"{index:02d}_{source.name}"
        shutil.copy2(source, backup)
        records.append({"source": str(source), "backup": str(backup)})
    return records


def _restore_backups(records: list[dict[str, str]]) -> None:
    for record in reversed(records):
        shutil.copy2(record["backup"], record["source"])


def _update_manifest_files(*, project_root: Path, candidate: dict[str, Any], checksum_before: str, checksum_after: str, file_size_after: int | None) -> int:
    updates = 0
    standard_path = _resolve_path(project_root, _clean_text(candidate.get("standard_path")))
    for manifest_path in _split_paths(project_root, candidate.get("manifest_path")):
        rows = _read_csv_records(manifest_path)
        fieldnames = list(rows[0].keys()) if rows else []
        file_updates = 0
        for row in rows:
            row_path = _resolve_path(project_root, _clean_text(row.get("standard_path")))
            if row_path == standard_path:
                if _clean_text(row.get("checksum")) != checksum_before:
                    raise ApplyBlockedError(f"manifest_checksum_before_mismatch:{manifest_path}")
                row["checksum"] = checksum_after
                if "file_size_bytes" in row and file_size_after is not None:
                    row["file_size_bytes"] = str(file_size_after)
                if "file_size" in row and file_size_after is not None:
                    row["file_size"] = str(file_size_after)
                file_updates += 1
        if file_updates != 1:
            raise ApplyBlockedError(f"manifest_update_count_not_1:{manifest_path}:{file_updates}")
        _write_csv(manifest_path, rows, fieldnames=fieldnames)
        updates += file_updates
    return updates


def _update_processed_summaries(*, project_root: Path, candidate: dict[str, Any], checksum_before: str, checksum_after: str, file_size_after: int | None) -> int:
    updates = 0
    standard_path = _resolve_path(project_root, _clean_text(candidate.get("standard_path")))
    for summary_path in _split_paths(project_root, candidate.get("processed_summary_path")):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        file_updates = 0
        for period_summary in (summary.get("periods") or {}).values():
            standard = (period_summary or {}).get("standard") or {}
            row_path = _resolve_path(project_root, _clean_text(standard.get("path")))
            if row_path == standard_path:
                if _clean_text(standard.get("checksum")) != checksum_before:
                    raise ApplyBlockedError(f"processed_summary_checksum_before_mismatch:{summary_path}")
                standard["checksum"] = checksum_after
                if "file_size_bytes" in standard and file_size_after is not None:
                    standard["file_size_bytes"] = file_size_after
                if "file_size" in standard and file_size_after is not None:
                    standard["file_size"] = file_size_after
                file_updates += 1
        if file_updates != 1:
            raise ApplyBlockedError(f"processed_summary_update_count_not_1:{summary_path}:{file_updates}")
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updates += file_updates
    return updates


def _update_market_data_file(
    *,
    session: Session | None,
    candidate: dict[str, Any],
    checksum_before: str,
    checksum_after: str,
    file_size_before: int | None,
    file_size_after: int | None,
) -> int:
    if session is None:
        raise ApplyBlockedError("db_session_missing")
    db_id = _clean_int(candidate.get("db_market_data_file_id"))
    if db_id is None:
        raise ApplyBlockedError("db_market_data_file_id_missing")
    statement = (
        update(MarketDataFile)
        .where(
            MarketDataFile.id == db_id,
            MarketDataFile.provider == "rqdata",
            MarketDataFile.data_type == "bars",
            MarketDataFile.file_path == _clean_text(candidate.get("standard_path")),
            MarketDataFile.row_count == _clean_int(candidate.get("row_count")),
            MarketDataFile.file_size_bytes == file_size_before,
            MarketDataFile.checksum == checksum_before,
            MarketDataFile.data_role == "primary",
            MarketDataFile.quality_status == "passed",
        )
        .values(checksum=checksum_after, file_size_bytes=file_size_after)
    )
    result = session.execute(statement)
    if result.rowcount != 1:
        raise ApplyBlockedError(f"conditional_db_update_failed:{db_id}")
    return int(result.rowcount)


def _manifest_sync_blockers(*, project_root: Path, candidate: dict[str, Any], checksum: str) -> list[str]:
    blockers: list[str] = []
    standard_path = _resolve_path(project_root, _clean_text(candidate.get("standard_path")))
    manifest_paths = _split_paths(project_root, candidate.get("manifest_path"))
    if not manifest_paths:
        return ["manifest_row_missing"]
    for manifest_path in manifest_paths:
        matches = _matching_csv_rows(manifest_path, standard_path)
        if len(matches) != 1:
            blockers.append("manifest_row_not_unique")
        elif _clean_text(matches[0].get("checksum")) != checksum:
            blockers.append("manifest_checksum_mismatch")
    return blockers


def _processed_sync_blockers(*, project_root: Path, candidate: dict[str, Any], checksum: str) -> list[str]:
    blockers: list[str] = []
    standard_path = _resolve_path(project_root, _clean_text(candidate.get("standard_path")))
    for summary_path in _split_paths(project_root, candidate.get("processed_summary_path")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blockers.append("processed_summary_read_failed")
            continue
        matches = []
        for period_summary in (summary.get("periods") or {}).values():
            standard = (period_summary or {}).get("standard") or {}
            if _resolve_path(project_root, _clean_text(standard.get("path"))) == standard_path:
                matches.append(standard)
        if len(matches) != 1:
            blockers.append("processed_summary_row_not_unique")
        elif _clean_text(matches[0].get("checksum")) != checksum:
            blockers.append("processed_summary_checksum_mismatch")
    return blockers


def _db_sync_blockers(*, session: Session | None, candidate: dict[str, Any], checksum: str, file_size: int | None) -> list[str]:
    if session is None:
        return ["db_session_missing"]
    db_id = _clean_int(candidate.get("db_market_data_file_id"))
    if db_id is None:
        return ["db_market_data_file_id_missing"]
    try:
        row = session.get(MarketDataFile, db_id)
    except Exception:  # noqa: BLE001 - keep DB gate explicit and non-secret.
        return ["db_unavailable"]
    if row is None:
        return ["db_market_data_file_missing"]
    blockers = []
    if row.file_path != _clean_text(candidate.get("standard_path")):
        blockers.append("db_file_path_mismatch")
    if row.row_count != _clean_int(candidate.get("row_count")):
        blockers.append("db_row_count_mismatch")
    if row.checksum != checksum:
        blockers.append("db_checksum_mismatch")
    if row.file_size_bytes != file_size:
        blockers.append("db_file_size_mismatch")
    if row.data_role != "primary":
        blockers.append("db_data_role_not_primary")
    if row.quality_status != "passed":
        blockers.append("db_quality_status_not_passed")
    return blockers


def _matching_csv_rows(path: Path, standard_path: Path | None) -> list[dict[str, Any]]:
    return [
        row
        for row in _read_csv_records(path)
        if _resolve_path(path.parents[2] if len(path.parents) > 2 else Path.cwd(), _clean_text(row.get("standard_path"))) == standard_path
    ]


def _split_paths(project_root: Path, value: Any) -> list[Path]:
    paths: list[Path] = []
    for item in _clean_text(value).split("|"):
        path = _resolve_path(project_root, item)
        if path is not None:
            paths.append(path)
    return paths


def _apply_row(
    candidate: dict[str, Any],
    *,
    applied: bool,
    skipped: bool,
    skip_reason: str,
    after_checksum: str = "",
    after_file_size: Any = "",
    after_row_count: Any = "",
    after_min_datetime: str = "",
    after_max_datetime: str = "",
    manifest_updates: int = 0,
    processed_summary_updates: int = 0,
    db_updates: int = 0,
    backup_paths: str = "",
) -> dict[str, Any]:
    return {
        "candidate_id": _clean_text(candidate.get("candidate_id")),
        "product": _clean_text(candidate.get("product")),
        "period": _clean_text(candidate.get("period")),
        "contract": _clean_text(candidate.get("contract")),
        "standard_path": _clean_text(candidate.get("standard_path")),
        "db_market_data_file_id": _clean_db_id(candidate.get("db_market_data_file_id")),
        "before_checksum": _clean_text(candidate.get("checksum_before")),
        "after_checksum": after_checksum,
        "before_file_size": _clean_text(candidate.get("file_size_before")),
        "after_file_size": "" if after_file_size is None else str(after_file_size),
        "before_row_count": _clean_text(candidate.get("duckdb_row_count")),
        "after_row_count": "" if after_row_count is None else str(after_row_count),
        "before_min_datetime": _clean_text(candidate.get("min_datetime")),
        "after_min_datetime": after_min_datetime,
        "before_max_datetime": _clean_text(candidate.get("max_datetime")),
        "after_max_datetime": after_max_datetime,
        "manifest_updates": manifest_updates,
        "processed_summary_updates": processed_summary_updates,
        "db_updates": db_updates,
        "writes_parquet": str(applied),
        "writes_manifest": str(applied and manifest_updates > 0),
        "writes_processed_summary": str(applied and processed_summary_updates > 0),
        "writes_database": str(applied and db_updates > 0),
        "applied": str(applied),
        "skipped": str(skipped),
        "skip_reason": skip_reason,
        "blocked_reason": "",
        "error_message": "",
        "backup_paths": backup_paths,
    }


def _apply_fieldnames() -> list[str]:
    return [
        "candidate_id",
        "product",
        "period",
        "contract",
        "standard_path",
        "db_market_data_file_id",
        "before_checksum",
        "after_checksum",
        "before_file_size",
        "after_file_size",
        "before_row_count",
        "after_row_count",
        "before_min_datetime",
        "after_min_datetime",
        "before_max_datetime",
        "after_max_datetime",
        "manifest_updates",
        "processed_summary_updates",
        "db_updates",
        "writes_parquet",
        "writes_manifest",
        "writes_processed_summary",
        "writes_database",
        "applied",
        "skipped",
        "skip_reason",
        "blocked_reason",
        "error_message",
        "backup_paths",
    ]


def _render_apply_summary(*, result: dict[str, Any], output_dir: Path) -> str:
    lines = [
        "# Source Interval Provenance Repair Apply",
        "",
        f"- mode: `{APPLY_MODE}`",
        f"- operation: `{result['operation']}`",
        f"- output_dir: `{output_dir}`",
        f"- selected_candidate_count: `{result['selected_candidate_count']}`",
        f"- processed_candidate_count: `{result['processed_candidate_count']}`",
        f"- applied_candidate_count: `{result['applied_candidate_count']}`",
        f"- skipped_candidate_count: `{result['skipped_candidate_count']}`",
        f"- blocked_candidate_count: `{result['blocked_candidate_count']}`",
        f"- writes_database: `{result['writes_database']}`",
        f"- writes_parquet: `{result['writes_parquet']}`",
        f"- writes_manifest: `{result['writes_manifest']}`",
        f"- writes_processed_summary: `{result['writes_processed_summary']}`",
        "- calls_rqdata: `False`",
        "",
        "## Boundary",
        "",
        "- Only `source_interval=1m` provenance and checksum/file_size synchronization are in scope.",
        "- This task does not change `row_count`, `data_version`, `data_role`, `quality_status`, DB registration scope, failed quality assets, strategy, signal, live runtime, scheduler or trading execution.",
    ]
    if result["blocked_reasons"]:
        lines.extend(["", f"- blocked_reasons: `{','.join(result['blocked_reasons'])}`"])
    lines.extend(
        [
            "",
            "## Candidate Results",
            "",
            "| candidate_id | product | period | applied | skipped | blocked_reason |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in result["apply_rows"]:
        lines.append(
            f"| `{row['candidate_id']}` | `{row['product']}` | `{row['period']}` | `{row['applied']}` | `{row['skipped']}` | `{row['blocked_reason']}` |"
        )
    return "\n".join(lines) + "\n"


def _markdown_counts(counts: Counter[str], label: str) -> str:
    lines = [f"| {label} | count |", "|---|---:|"]
    for key, value in sorted(counts.items()):
        lines.append(f"| `{key}` | {value} |")
    return "\n".join(lines)


def _records_match_checksum(records: list[PathRecord], checksum: str) -> str:
    if not records:
        return "not_found"
    if not checksum:
        return "checksum_unavailable"
    values = {record.checksum for record in records if record.checksum}
    if not values:
        return "checksum_missing"
    return "matched" if values == {checksum} else "mismatch"


def _read_csv_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    fieldnames = fieldnames or (list(rows[0].keys()) if rows else [])
    if not rows:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            if fieldnames:
                writer.writeheader()
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _resolve_path(project_root: Path, value: str | Path) -> Path | None:
    if not value:
        return None
    path = value if isinstance(value, Path) else Path(value)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve(strict=False)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _clean_int(value: Any) -> int | None:
    text = _clean_text(value)
    if not text:
        return None
    return int(float(text))


def _clean_bool(value: Any) -> bool:
    text = _clean_text(value).lower()
    return text in {"true", "1", "yes", "y"}


def _clean_db_id(value: Any) -> str:
    parsed = _clean_int(value)
    return "" if parsed is None else str(parsed)
