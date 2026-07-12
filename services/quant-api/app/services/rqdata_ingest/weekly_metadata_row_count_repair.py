from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.data_center import MarketDataFile
from app.services.rqdata_ingest.weekly_row_count_reconcile import (
    DbMarketFileSnapshot,
    reconcile_weekly_row_counts,
)


MODE = "weekly_metadata_row_count_repair"
CONFIRM_FLAG = "--confirm-ad-ec-op-weekly-row-count-repair"


@dataclass(frozen=True)
class ExpectedWeeklyRepair:
    product: str
    db_file_id: int
    old_row_count: int
    target_row_count: int
    file_name: str


EXPECTED_REPAIRS: tuple[ExpectedWeeklyRepair, ...] = (
    ExpectedWeeklyRepair("ad", 44115, 47, 55, "ad_MAIN_1w_20230103_20260707_v2.parquet"),
    ExpectedWeeklyRepair("ec", 44133, 134, 148, "ec_MAIN_1w_20230103_20260707_v2.parquet"),
    ExpectedWeeklyRepair("op", 44159, 36, 42, "op_MAIN_1w_20230103_20260707_v2.parquet"),
)


def build_weekly_metadata_row_count_repair_plan(
    *,
    project_root: Path,
    output_dir: Path,
    db_status: str,
    db_error_type: str = "",
    db_rows: list[DbMarketFileSnapshot] | None = None,
    apply: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    db_rows = db_rows or []
    reconcile = reconcile_weekly_row_counts(
        project_root=project_root,
        products=[item.product for item in EXPECTED_REPAIRS],
        period="1w",
        output_dir=output_dir / "_reconcile_input",
        db_status=db_status,
        db_error_type=db_error_type,
        db_rows=db_rows,
        write_outputs=False,
    )
    reconcile_rows = reconcile["rows"]
    candidates = [_candidate_for(expected, reconcile_rows) for expected in EXPECTED_REPAIRS]

    plan_blockers: list[str] = []
    if db_status != "available":
        plan_blockers.append("db_unavailable")
    matched_candidate_count = sum(1 for candidate in candidates if candidate["matched_reconcile_rows"] == 1)
    if matched_candidate_count != len(EXPECTED_REPAIRS):
        plan_blockers.append("candidate_count_not_3")
    if apply and not confirm:
        plan_blockers.append("confirmation_required")

    for candidate in candidates:
        candidate_blockers = _candidate_blockers(candidate)
        candidate["blocked_reasons"] = "|".join(candidate_blockers)
        candidate["decision"] = "ready" if not candidate_blockers else "blocked"
        plan_blockers.extend(candidate_blockers)

    unique_blockers = sorted(set(plan_blockers))
    ready_to_apply = not unique_blockers
    apply_rows = [_apply_placeholder(row, apply=apply) for row in candidates]
    return {
        "mode": MODE,
        "operation": "apply" if apply else "dry-run",
        "confirm": confirm,
        "confirm_flag": CONFIRM_FLAG,
        "db_status": db_status,
        "db_error_type": db_error_type,
        "writes_database": bool(apply and ready_to_apply),
        "writes_parquet": False,
        "calls_rqdata": False,
        "ready_to_apply": ready_to_apply,
        "blocked_reasons": unique_blockers,
        "candidates": candidates,
        "apply_rows": apply_rows,
        "output_dir": output_dir,
        "reconcile_classification_counts": dict(Counter(row["classification"] for row in reconcile_rows)),
    }


def apply_weekly_metadata_row_count_repair(*, session: Session, plan: dict[str, Any]) -> dict[str, Any]:
    if not plan["ready_to_apply"]:
        return {**plan, "writes_database": False}

    apply_rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for candidate in plan["candidates"]:
        statement = (
            update(MarketDataFile)
            .where(
                MarketDataFile.id == candidate["db_file_id"],
                MarketDataFile.provider == "rqdata",
                MarketDataFile.data_type == "bars",
                MarketDataFile.period == "1w",
                MarketDataFile.instrument_symbol == candidate["product"],
                MarketDataFile.file_path == candidate["standard_path"],
                MarketDataFile.row_count == candidate["old_row_count"],
            )
            .values(row_count=candidate["target_row_count"])
        )
        result = session.execute(statement)
        if result.rowcount != 1:
            failures.append(f"conditional_update_failed:{candidate['product']}:{candidate['db_file_id']}")
            apply_rows.append(_apply_row(candidate, applied=False, after_row_count="", skip_reason="conditional_update_failed"))
            continue
        after = session.get(MarketDataFile, candidate["db_file_id"])
        apply_rows.append(
            _apply_row(
                candidate,
                applied=True,
                after_row_count="" if after is None else after.row_count,
                skip_reason="",
            )
        )

    if failures:
        session.rollback()
        return {
            **plan,
            "writes_database": False,
            "ready_to_apply": False,
            "blocked_reasons": sorted(set([*plan["blocked_reasons"], *failures])),
            "apply_rows": apply_rows,
        }

    session.flush()
    return {**plan, "writes_database": True, "apply_rows": apply_rows}


def write_weekly_metadata_row_count_repair_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "metadata_repair_candidates.csv"
    apply_path = output_dir / "metadata_repair_apply.csv"
    summary_path = output_dir / "METADATA_REPAIR_SUMMARY.md"
    _write_csv(candidate_path, _candidate_fieldnames(), result["candidates"])
    _write_csv(apply_path, _apply_fieldnames(), result["apply_rows"])
    summary_path.write_text(_render_summary(result=result, output_dir=output_dir), encoding="utf-8")
    return {
        "summary": summary_path,
        "candidates": candidate_path,
        "apply": apply_path,
    }


def _candidate_for(expected: ExpectedWeeklyRepair, rows: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        row
        for row in rows
        if row["product"] == expected.product
        and Path(row["standard_path"]).name == expected.file_name
    ]
    row = matches[0] if len(matches) == 1 else {}
    return {
        "product": expected.product,
        "file_name": expected.file_name,
        "standard_path": row.get("standard_path", ""),
        "db_file_id": _to_int(row.get("db_file_id")),
        "expected_db_file_id": expected.db_file_id,
        "old_row_count": expected.old_row_count,
        "target_row_count": expected.target_row_count,
        "db_row_count": _to_int(row.get("db_row_count")),
        "manifest_row_count": _to_int(row.get("manifest_row_count")),
        "processed_summary_row_count": _to_int(row.get("processed_summary_row_count")),
        "duckdb_row_count": _to_int(row.get("duckdb_row_count")),
        "distinct_datetime_count": _to_int(row.get("distinct_datetime_count")),
        "duplicate_datetime_count": _to_int(row.get("duplicate_datetime_count")),
        "classification": row.get("classification", "missing_reconcile_row"),
        "db_data_role": row.get("db_data_role", ""),
        "db_quality_status": row.get("db_quality_status", ""),
        "db_data_version": row.get("db_data_version", ""),
        "matched_reconcile_rows": len(matches),
        "decision": "",
        "blocked_reasons": "",
    }


def _candidate_blockers(candidate: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if candidate["matched_reconcile_rows"] != 1:
        blockers.append("expected_file_not_unique")
    if candidate["classification"] != "old_version_metadata_stale":
        blockers.append("classification_not_old_version_metadata_stale")
    if candidate["db_file_id"] != candidate["expected_db_file_id"]:
        blockers.append("db_file_id_mismatch")
    if candidate["db_row_count"] != candidate["old_row_count"]:
        blockers.append("old_row_count_mismatch")
    if candidate["manifest_row_count"] != candidate["target_row_count"]:
        blockers.append("manifest_row_count_mismatch")
    if candidate["processed_summary_row_count"] != candidate["target_row_count"]:
        blockers.append("processed_summary_row_count_mismatch")
    if candidate["duckdb_row_count"] != candidate["target_row_count"]:
        blockers.append("duckdb_row_count_mismatch")
    if candidate["distinct_datetime_count"] != candidate["duckdb_row_count"]:
        blockers.append("distinct_datetime_mismatch")
    if candidate["duplicate_datetime_count"] != 0:
        blockers.append("duplicate_datetime_found")
    if candidate["db_data_role"] != "primary":
        blockers.append("data_role_not_primary")
    if candidate["db_quality_status"] == "failed":
        blockers.append("quality_failed_blocked")
    if not candidate["standard_path"]:
        blockers.append("missing_standard_path")
    return blockers


def _apply_placeholder(candidate: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    return _apply_row(
        candidate,
        applied=False,
        after_row_count="",
        skip_reason="" if apply and candidate["decision"] == "ready" else candidate["blocked_reasons"] or "dry_run",
    )


def _apply_row(candidate: dict[str, Any], *, applied: bool, after_row_count: Any, skip_reason: str) -> dict[str, Any]:
    return {
        "product": candidate["product"],
        "db_file_id": candidate["db_file_id"],
        "file_name": candidate["file_name"],
        "standard_path": candidate["standard_path"],
        "before_row_count": candidate["db_row_count"],
        "target_row_count": candidate["target_row_count"],
        "after_row_count": after_row_count,
        "applied": applied,
        "skip_reason": skip_reason,
    }


def _render_summary(*, result: dict[str, Any], output_dir: Path) -> str:
    lines = [
        "# AD/EC/OP Weekly Metadata Row Count Repair Summary",
        "",
        f"- mode: `{MODE}`",
        f"- operation: `{result['operation']}`",
        f"- output_dir: `{output_dir}`",
        f"- db_status: `{result['db_status']}`",
        f"- writes_database: `{result['writes_database']}`",
        "- writes_parquet: `False`",
        "- calls_rqdata: `False`",
        f"- ready_to_apply: `{result['ready_to_apply']}`",
    ]
    if result["db_error_type"]:
        lines.append(f"- db_error_type: `{result['db_error_type']}`")
    if result["blocked_reasons"]:
        lines.append(f"- blocked_reasons: `{','.join(result['blocked_reasons'])}`")
    lines.extend(
        [
            "",
            "## Candidates",
            "",
            "| product | db_file_id | file | before | target | manifest | processed | duckdb | duplicate_datetime | classification | decision | blocked_reasons |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for row in result["candidates"]:
        lines.append(
            "| {product} | {db_file_id} | `{file_name}` | {before} | {target} | {manifest} | {processed} | {duckdb} | {duplicate} | `{classification}` | `{decision}` | `{blocked}` |".format(
                product=row["product"],
                db_file_id=_cell(row["db_file_id"]),
                file_name=row["file_name"],
                before=_cell(row["db_row_count"]),
                target=_cell(row["target_row_count"]),
                manifest=_cell(row["manifest_row_count"]),
                processed=_cell(row["processed_summary_row_count"]),
                duckdb=_cell(row["duckdb_row_count"]),
                duplicate=_cell(row["duplicate_datetime_count"]),
                classification=row["classification"],
                decision=row["decision"],
                blocked=row["blocked_reasons"],
            )
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This repair may update only `market_data_files.row_count` for the three fixed 20260707 weekly metadata rows.",
            "- It does not write Parquet, manifest, checksum, data_version, data_role, quality_status, RQData downloads, strategy, signal, live runtime, scheduler or trading execution state.",
        ]
    )
    return "\n".join(lines) + "\n"


def _candidate_fieldnames() -> list[str]:
    return [
        "product",
        "file_name",
        "standard_path",
        "db_file_id",
        "expected_db_file_id",
        "old_row_count",
        "target_row_count",
        "db_row_count",
        "manifest_row_count",
        "processed_summary_row_count",
        "duckdb_row_count",
        "distinct_datetime_count",
        "duplicate_datetime_count",
        "classification",
        "db_data_role",
        "db_quality_status",
        "db_data_version",
        "matched_reconcile_rows",
        "decision",
        "blocked_reasons",
    ]


def _apply_fieldnames() -> list[str]:
    return [
        "product",
        "db_file_id",
        "file_name",
        "standard_path",
        "before_row_count",
        "target_row_count",
        "after_row_count",
        "applied",
        "skip_reason",
    ]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))


def _cell(value: Any) -> str:
    return "" if value in (None, "") else str(value)
