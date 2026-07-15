from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb

from app.services.rqdata_ingest.parquet import sha256_file
from app.services.rqdata_ingest.weekly_row_count_reconcile import DbMarketFileSnapshot, reconcile_weekly_row_counts

MODE = "residual_root_cause_audit"
QUALITY_WARNING_ACCEPTED = "accepted_warning"
ROW_COUNT_PRODUCTS = ("fb", "lu", "nr", "pf")
CHECKSUM_PRODUCTS = ("ad", "ec", "op")
ORPHAN_PRODUCTS = ("bb", "rs", "wh")


def run_residual_root_cause_audit(
    *,
    project_root: Path,
    sealing_dir: Path,
    output_dir: Path,
    multi_primary_csv: Path | None = None,
    db_rows: list[DbMarketFileSnapshot] | None = None,
    db_status: str = "unavailable",
) -> dict[str, Any]:
    sealing_dir = sealing_dir if sealing_dir.is_absolute() else project_root / sealing_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = output_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    checksum_rows = _read_csv(sealing_dir / "checksum_matrix.csv")
    duplicate_rows = _read_csv(sealing_dir / "duplicate_inventory.csv")
    orphan_rows = _read_csv(sealing_dir / "orphan_inventory.csv")
    inventory_rows = _read_csv(sealing_dir / "asset_physical_inventory.csv")
    issue_rows = _read_csv(sealing_dir / "issue_register.csv")

    root_cause_rows: list[dict[str, Any]] = []
    repair_rows: list[dict[str, Any]] = []
    gate_rows: list[dict[str, Any]] = []

    checksum_evidence = _audit_checksum_mismatches(checksum_rows)
    (evidence_dir / "checksum_ad_ec_op.json").write_text(json.dumps(checksum_evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    root_cause_rows.extend(checksum_evidence["register"])
    repair_rows.extend(checksum_evidence["repairs"])
    gate_rows.extend(checksum_evidence["gates"])

    orphan_evidence = _audit_orphans(project_root=project_root, orphan_rows=orphan_rows, inventory_rows=inventory_rows)
    (evidence_dir / "orphan_bb_rs_wh.json").write_text(json.dumps(orphan_evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    root_cause_rows.extend(orphan_evidence["register"])
    repair_rows.extend(orphan_evidence["repairs"])
    gate_rows.extend(orphan_evidence["gates"])

    duplicate_evidence = _audit_duplicates(duplicate_rows)
    (evidence_dir / "duplicate_breakdown.json").write_text(json.dumps(duplicate_evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    root_cause_rows.extend(duplicate_evidence["register"])
    repair_rows.extend(duplicate_evidence["repairs"])
    gate_rows.extend(duplicate_evidence["gates"])

    jm_evidence = _audit_jm_missing_physical(inventory_rows)
    (evidence_dir / "jm_missing_physical.json").write_text(json.dumps(jm_evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    root_cause_rows.extend(jm_evidence["register"])
    repair_rows.extend(jm_evidence["repairs"])
    gate_rows.extend(jm_evidence["gates"])

    row_count_evidence = _audit_row_count_mismatches(
        project_root=project_root,
        inventory_rows=inventory_rows,
        db_rows=db_rows or [],
        db_status=db_status,
    )
    (evidence_dir / "row_count_fb_lu_nr_pf.json").write_text(json.dumps(row_count_evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    root_cause_rows.extend(row_count_evidence["register"])
    repair_rows.extend(row_count_evidence["repairs"])
    gate_rows.extend(row_count_evidence["gates"])

    quality_evidence = _audit_quality_warnings(issue_rows)
    (evidence_dir / "quality_warning_accepted.json").write_text(json.dumps(quality_evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    root_cause_rows.extend(quality_evidence["register"])
    repair_rows.extend(quality_evidence["repairs"])
    gate_rows.extend(quality_evidence["gates"])

    multi_primary_note = _load_multi_primary_note(multi_primary_csv)
    if multi_primary_note:
        root_cause_rows.append(multi_primary_note["register"])
        repair_rows.append(multi_primary_note["repair"])
        gate_rows.append(multi_primary_note["gate"])

    root_cause_csv = output_dir / "root_cause_register.csv"
    repair_csv = output_dir / "repair_classification.csv"
    gate_csv = output_dir / "gate_register.csv"
    _write_csv(root_cause_csv, root_cause_rows)
    _write_csv(repair_csv, repair_rows)
    _write_csv(gate_csv, gate_rows)

    summary_path = output_dir / "RESIDUAL-ROOT-CAUSE-SUMMARY.md"
    summary_path.write_text(
        _render_summary(
            root_cause_rows=root_cause_rows,
            repair_rows=repair_rows,
            gate_rows=gate_rows,
            output_dir=output_dir,
            multi_primary_csv=multi_primary_csv,
        ),
        encoding="utf-8",
    )
    return {
        "mode": MODE,
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "root_cause_count": len(root_cause_rows),
        "repair_count": len(repair_rows),
        "gate_count": len(gate_rows),
        "outputs": {
            "root_cause_register": root_cause_csv,
            "repair_classification": repair_csv,
            "gate_register": gate_csv,
            "summary": summary_path,
        },
    }


def _audit_checksum_mismatches(checksum_rows: list[dict[str, Any]]) -> dict[str, Any]:
    register: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for row in checksum_rows:
        if _clean_text(row.get("checksum_status")) != "checksum_mismatch":
            continue
        product = _clean_text(row.get("product"))
        if product not in CHECKSUM_PRODUCTS:
            continue
        physical_path = Path(_clean_text(row.get("physical_path")))
        physical_checksum = ""
        physical_readable = physical_path.exists()
        if physical_readable:
            physical_checksum = sha256_file(physical_path)
        manifest_checksum = _clean_text(row.get("manifest_checksum"))
        db_checksum = _clean_text(row.get("db_checksum"))
        processed_checksum = _clean_text(row.get("processed_checksum"))
        layers_match_physical = physical_checksum and all(
            value == physical_checksum for value in (manifest_checksum, db_checksum) if value
        )
        root_cause = "stale_processed_summary" if layers_match_physical and processed_checksum != physical_checksum else "checksum_layer_divergence"
        audit_pass = physical_readable and layers_match_physical
        register.append(
            {
                "anomaly_type": "checksum_mismatch",
                "product": product,
                "period": _clean_text(row.get("period")),
                "physical_path": str(physical_path),
                "root_cause_class": root_cause,
                "audit_result": "pass" if audit_pass else "block",
                "recommended_gate": "DIRECTION-A3-APPLY-METADATA-SYNC",
            }
        )
        repairs.append(
            {
                "anomaly_type": "checksum_mismatch",
                "physical_path": str(physical_path),
                "repair_type": "metadata-only" if audit_pass else "requires_manual_review",
                "needs_new_data_version": "false",
                "followup_task": "DIRECTION-A3-APPLY-METADATA-SYNC",
            }
        )
        gates.append(
            {
                "gate_id": "Gate-A3-APPLY-PROCESSED-SYNC",
                "anomaly_type": "checksum_mismatch",
                "scope": product,
                "precondition": "physical=manifest=db and processed stale",
                "blocked_by": "" if audit_pass else "physical_or_db_divergence",
            }
        )
        details.append(
            {
                "physical_path": str(physical_path),
                "physical_checksum": physical_checksum,
                "manifest_checksum": manifest_checksum,
                "db_checksum": db_checksum,
                "processed_checksum": processed_checksum,
                "root_cause_class": root_cause,
                "audit_pass": audit_pass,
            }
        )
    return {"register": register, "repairs": repairs, "gates": gates, "details": details}


def _audit_orphans(
    *,
    project_root: Path,
    orphan_rows: list[dict[str, Any]],
    inventory_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    register: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    active_by_product = _active_long_window_paths(inventory_rows)
    for row in orphan_rows:
        orphan_path = Path(_clean_text(row.get("physical_path")))
        product = _product_from_path(str(orphan_path))
        active_path = active_by_product.get(product)
        subset_proof = _is_subset_parquet(orphan_path, active_path) if active_path else False
        audit_pass = subset_proof and active_path is not None
        register.append(
            {
                "anomaly_type": "orphan_parquet",
                "product": product,
                "period": "1w",
                "physical_path": str(orphan_path),
                "root_cause_class": "superseded_short_window_file",
                "audit_result": "pass" if audit_pass else "block",
                "recommended_gate": "DIRECTION-A3-APPLY-ORPHAN-ARCHIVE",
            }
        )
        repairs.append(
            {
                "anomaly_type": "orphan_parquet",
                "physical_path": str(orphan_path),
                "repair_type": "archive-only" if audit_pass else "requires_manual_review",
                "needs_new_data_version": "false",
                "followup_task": "DIRECTION-A3-APPLY-ORPHAN-ARCHIVE",
            }
        )
        gates.append(
            {
                "gate_id": "Gate-A3-APPLY-ORPHAN-ARCHIVE",
                "anomaly_type": "orphan_parquet",
                "scope": product,
                "precondition": "short_window_subset_of_active_long_window",
                "blocked_by": "" if audit_pass else "subset_proof_failed",
            }
        )
        details.append(
            {
                "orphan_path": str(orphan_path),
                "active_path": str(active_path) if active_path else "",
                "subset_proof": subset_proof,
                "audit_pass": audit_pass,
            }
        )
    return {"register": register, "repairs": repairs, "gates": gates, "details": details}


def _audit_duplicates(duplicate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    register: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    acb_count = 0
    weekly_count = 0
    for row in duplicate_rows:
        versions = _clean_text(row.get("data_versions"))
        db_ids = [part for part in _clean_text(row.get("db_file_ids")).split(";") if part]
        if "rq_acb_" in versions and "rqdata_actual_contract_bars_" in versions:
            root_cause = "dual_provider_version_key"
            gate_id = "Gate-A3-APPLY-ACB-DUP-SUPERSEDE"
            task = "DIRECTION-A3-APPLY-DUP-SUPERSEDE"
            acb_count += 1
        else:
            root_cause = "duplicate_ingest_batch"
            gate_id = "Gate-A3-APPLY-WEEKLY-DUP-SUPERSEDE"
            task = "DIRECTION-A3-APPLY-DUP-SUPERSEDE"
            weekly_count += 1
        canonical_file_id = max((int(item) for item in db_ids), default=None)
        audit_pass = canonical_file_id is not None and len(db_ids) == 2
        register.append(
            {
                "anomaly_type": "duplicate_path_versions",
                "product": _product_from_path(_clean_text(row.get("physical_path"))),
                "period": _period_from_path(_clean_text(row.get("physical_path"))),
                "physical_path": _clean_text(row.get("physical_path")),
                "root_cause_class": root_cause,
                "audit_result": "pass" if audit_pass else "block",
                "recommended_gate": task,
            }
        )
        repairs.append(
            {
                "anomaly_type": "duplicate_path_versions",
                "physical_path": _clean_text(row.get("physical_path")),
                "repair_type": "supersede",
                "needs_new_data_version": "false",
                "followup_task": task,
                "canonical_file_id": canonical_file_id or "",
            }
        )
        gates.append(
            {
                "gate_id": gate_id,
                "anomaly_type": "duplicate_path_versions",
                "scope": _clean_text(row.get("physical_path")),
                "precondition": "canonical_file_id_selected",
                "blocked_by": "" if audit_pass else "ambiguous_db_rows",
            }
        )
    return {
        "register": register,
        "repairs": repairs,
        "gates": gates,
        "details": {"acb_duplicate_count": acb_count, "weekly_duplicate_count": weekly_count, "total": len(duplicate_rows)},
    }


def _audit_jm_missing_physical(inventory_rows: list[dict[str, Any]]) -> dict[str, Any]:
    register: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    canonical_exists = any(
        _clean_text(row.get("product")) == "jm"
        and _clean_text(row.get("symbol_or_contract")) == "jm.MAIN"
        and _clean_text(row.get("physical_exists")).lower() == "true"
        and "experiments/" not in _clean_text(row.get("physical_path"))
        for row in inventory_rows
    )
    for row in inventory_rows:
        if _clean_text(row.get("checksum_status")) != "missing_physical_file":
            continue
        if _clean_text(row.get("product")) != "jm":
            continue
        physical_path = _clean_text(row.get("physical_path"))
        if "experiments/" not in physical_path:
            continue
        audit_pass = canonical_exists
        register.append(
            {
                "anomaly_type": "missing_physical_file",
                "product": "jm",
                "period": _clean_text(row.get("period")),
                "physical_path": physical_path,
                "root_cause_class": "experiment_path_stale_registration",
                "audit_result": "pass" if audit_pass else "block",
                "recommended_gate": "DIRECTION-A3-APPLY-JM-EXPERIMENT-CLEANUP",
            }
        )
        repairs.append(
            {
                "anomaly_type": "missing_physical_file",
                "physical_path": physical_path,
                "repair_type": "supersede",
                "needs_new_data_version": "false",
                "followup_task": "DIRECTION-A3-APPLY-JM-EXPERIMENT-CLEANUP",
            }
        )
        gates.append(
            {
                "gate_id": "Gate-A3-APPLY-JM-EXPERIMENT-CLEANUP",
                "anomaly_type": "missing_physical_file",
                "scope": "jm",
                "precondition": "canonical_jm_assets_exist",
                "blocked_by": "" if audit_pass else "missing_canonical_replacement",
            }
        )
        details.append({"physical_path": physical_path, "canonical_exists": canonical_exists, "audit_pass": audit_pass})
    return {"register": register, "repairs": repairs, "gates": gates, "details": details}


def _audit_row_count_mismatches(
    *,
    project_root: Path,
    inventory_rows: list[dict[str, Any]],
    db_rows: list[DbMarketFileSnapshot],
    db_status: str,
) -> dict[str, Any]:
    reconcile = reconcile_weekly_row_counts(
        project_root=project_root,
        products=list(ROW_COUNT_PRODUCTS),
        period="1w",
        output_dir=project_root / "data/reports/_residual_row_count_scratch",
        db_status=db_status,
        db_rows=db_rows,
        write_outputs=False,
    )
    register: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    for row in reconcile["rows"]:
        classification = _clean_text(row.get("classification"))
        if classification not in {"db_row_count_stale", "old_version_metadata_stale", "manifest_or_summary_stale"}:
            continue
        duckdb_count = row.get("duckdb_row_count")
        db_count = row.get("db_row_count")
        audit_pass = duckdb_count not in ("", None) and db_count not in ("", None)
        register.append(
            {
                "anomaly_type": "row_count_mismatch",
                "product": _clean_text(row.get("product")),
                "period": "1w",
                "physical_path": _clean_text(row.get("standard_path")),
                "root_cause_class": "stale_db_row_count",
                "audit_result": "pass" if audit_pass else "block",
                "recommended_gate": "DIRECTION-A3-APPLY-METADATA-SYNC",
            }
        )
        repairs.append(
            {
                "anomaly_type": "row_count_mismatch",
                "physical_path": _clean_text(row.get("standard_path")),
                "repair_type": "metadata-only",
                "needs_new_data_version": "false",
                "followup_task": "DIRECTION-A3-APPLY-METADATA-SYNC",
            }
        )
        gates.append(
            {
                "gate_id": "Gate-A3-APPLY-ROWCOUNT",
                "anomaly_type": "row_count_mismatch",
                "scope": _clean_text(row.get("product")),
                "precondition": "parquet_row_count_stable",
                "blocked_by": "" if audit_pass else "parquet_unreadable",
            }
        )
    return {"register": register, "repairs": repairs, "gates": gates, "details": reconcile["rows"]}


def _audit_quality_warnings(issue_rows: list[dict[str, Any]]) -> dict[str, Any]:
    register: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    warning_rows = [row for row in issue_rows if _clean_text(row.get("issue_type")) == "quality_warning"]
    for row in warning_rows:
        register.append(
            {
                "anomaly_type": "quality_warning",
                "product": _clean_text(row.get("product")),
                "period": _clean_text(row.get("period")),
                "physical_path": "",
                "root_cause_class": "low_liquidity_abnormal_price",
                "audit_result": "pass",
                "recommended_gate": "no_action",
            }
        )
        repairs.append(
            {
                "anomaly_type": "quality_warning",
                "physical_path": "",
                "repair_type": "no_action",
                "needs_new_data_version": "false",
                "followup_task": QUALITY_WARNING_ACCEPTED,
            }
        )
    gates.append(
        {
            "gate_id": "Gate-QUALITY-WARNING-NO-UPGRADE",
            "anomaly_type": "quality_warning",
            "scope": f"{len(warning_rows)} rows",
            "precondition": "maintain_accepted_warning",
            "blocked_by": "upgrade_to_passed_forbidden",
        }
    )
    return {
        "register": register,
        "repairs": repairs,
        "gates": gates,
        "details": {"quality_warning_count": len(warning_rows), "upgrade_forbidden": True},
    }


def _load_multi_primary_note(multi_primary_csv: Path | None) -> dict[str, Any] | None:
    if multi_primary_csv is None or not multi_primary_csv.exists():
        return None
    rows = _read_csv(multi_primary_csv)
    return {
        "register": {
            "anomaly_type": "multi_primary_inventory",
            "product": "*",
            "period": "*",
            "physical_path": str(multi_primary_csv),
            "root_cause_class": "multi_primary_registration",
            "audit_result": "pass",
            "recommended_gate": "DIRECTION-A3-APPLY-DUP-SUPERSEDE",
        },
        "repair": {
            "anomaly_type": "multi_primary_inventory",
            "physical_path": str(multi_primary_csv),
            "repair_type": "supersede",
            "needs_new_data_version": "false",
            "followup_task": "DIRECTION-A3-APPLY-DUP-SUPERSEDE",
        },
        "gate": {
            "gate_id": "Gate-MULTI-PRIMARY-RULEBOOK",
            "anomaly_type": "multi_primary_inventory",
            "scope": f"{len(rows)} combinations",
            "precondition": "rulebook_supersede_only",
            "blocked_by": "",
        },
    }


def _active_long_window_paths(inventory_rows: list[dict[str, Any]]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for row in inventory_rows:
        product = _clean_text(row.get("product"))
        if product not in ORPHAN_PRODUCTS:
            continue
        if _clean_text(row.get("contract_role")) != "dominant_main":
            continue
        if _clean_text(row.get("period")) != "1w":
            continue
        path_text = _clean_text(row.get("physical_path"))
        if "20200102_20260711_v2" not in path_text:
            continue
        if _clean_text(row.get("physical_exists")).lower() != "true":
            continue
        result[product] = Path(path_text)
    return result


def _is_subset_parquet(short_path: Path, long_path: Path | None) -> bool:
    if long_path is None or not short_path.exists() or not long_path.exists():
        return False
    try:
        with duckdb.connect(database=":memory:") as connection:
            short_count = connection.execute("select count(*) from read_parquet(?)", [str(short_path)]).fetchone()[0]
            long_count = connection.execute("select count(*) from read_parquet(?)", [str(long_path)]).fetchone()[0]
            if short_count > long_count:
                return False
            overlap = connection.execute(
                """
                select count(*)
                from read_parquet(?) s
                inner join read_parquet(?) l using (datetime)
                """,
                [str(short_path), str(long_path)],
            ).fetchone()[0]
            return int(overlap) == int(short_count)
    except Exception:
        return False


def _render_summary(
    *,
    root_cause_rows: list[dict[str, Any]],
    repair_rows: list[dict[str, Any]],
    gate_rows: list[dict[str, Any]],
    output_dir: Path,
    multi_primary_csv: Path | None,
) -> str:
    anomaly_counts = Counter(row["anomaly_type"] for row in root_cause_rows)
    repair_counts = Counter(row["repair_type"] for row in repair_rows)
    audit_counts = Counter(row["audit_result"] for row in root_cause_rows if row.get("audit_result"))
    return "\n".join(
        [
            "# Residual Root Cause Audit Summary",
            "",
            f"- output_dir: `{output_dir}`",
            f"- root_cause_rows: {len(root_cause_rows)}",
            f"- repair_rows: {len(repair_rows)}",
            f"- gate_rows: {len(gate_rows)}",
            f"- multi_primary_csv: `{multi_primary_csv}`" if multi_primary_csv else "- multi_primary_csv: `(not provided)`",
            "- writes_database: `False`",
            "- writes_parquet: `False`",
            "- calls_rqdata: `False`",
            "",
            "## Anomaly Types",
            "",
            "| anomaly_type | count |",
            "|---|---:|",
            *[f"| `{key}` | {value} |" for key, value in sorted(anomaly_counts.items())],
            "",
            "## Repair Types",
            "",
            "| repair_type | count |",
            "|---|---:|",
            *[f"| `{key}` | {value} |" for key, value in sorted(repair_counts.items())],
            "",
            "## Audit Results",
            "",
            "| audit_result | count |",
            "|---|---:|",
            *[f"| `{key}` | {value} |" for key, value in sorted(audit_counts.items())],
            "",
            "## Hard Constraints",
            "",
            "- `quality_warning` must remain `accepted_warning`; upgrade to `passed` is forbidden.",
            "- This audit is read-only and does not authorize metadata/parquet/db writes.",
            "",
        ]
    )


def _product_from_path(path: str) -> str:
    marker = "/symbol="
    if marker not in path:
        return ""
    return path.split(marker, 1)[1].split("/", 1)[0]


def _period_from_path(path: str) -> str:
    marker = "/period="
    if marker not in path:
        return ""
    return path.split(marker, 1)[1].split("/", 1)[0]


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
