#!/usr/bin/env python3
"""Create the read-only B2-00 preflight and canonical B2-04B closure evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError


AUDIT_END = "2026-07-10"
READY = "FULL_HISTORY_AUDIT_ENV_READY"
TASK_ID = "FULL-HISTORY-AUDIT-V2-PREFLIGHT-000"
DISABLED_SWITCHES = (
    "GUIYI_LIVE_RUNTIME_ENABLED",
    "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
    "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _git_evidence(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    commands = [
        _run(["git", "branch", "--show-current"], cwd=root),
        _run(["git", "rev-parse", "HEAD"], cwd=root),
        _run(["git", "rev-parse", "origin/main"], cwd=root),
        _run(["git", "status", "--short"], cwd=root),
        _run(["git", "rev-list", "--left-right", "--count", "origin/main...HEAD"], cwd=root),
    ]
    branch, head, origin, status, divergence = commands
    counts = divergence["stdout"].split()
    return (
        {
            "branch": branch["stdout"],
            "head": head["stdout"],
            "origin_main": origin["stdout"],
            "worktree_clean": status["stdout"] == "",
            "status_short": status["stdout"].splitlines(),
            "behind_origin_main": int(counts[0]) if len(counts) == 2 else None,
            "ahead_of_origin_main": int(counts[1]) if len(counts) == 2 else None,
        },
        commands,
    )


def _manifest_ranges(manifest_root: Path) -> dict[str, list[dict[str, Any]]]:
    evidence: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(manifest_root.rglob("*.csv")):
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                for line_number, row in enumerate(csv.DictReader(handle), start=2):
                    product = str(row.get("product") or "").strip().lower()
                    if product not in {"a", "al", "ag", "jm"}:
                        continue
                    contract = str(row.get("continuous_contract") or row.get("contract") or "").strip()
                    if contract and not contract.upper().endswith(".MAIN"):
                        continue
                    period = str(row.get("period") or "").strip()
                    minimum = str(row.get("min_datetime") or row.get("start_time") or "").strip()
                    maximum = str(row.get("max_datetime") or row.get("end_time") or "").strip()
                    if not period or not minimum or not maximum:
                        continue
                    key = (product, period)
                    item = evidence.setdefault(
                        key,
                        {"product": product, "period": period, "start": minimum, "end": maximum, "sources": []},
                    )
                    item["start"] = min(item["start"], minimum)
                    item["end"] = max(item["end"], maximum)
                    item["sources"].append(f"{path.relative_to(manifest_root.parent)}#{line_number}")
        except (OSError, UnicodeError, csv.Error):
            continue
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (product, _period), item in sorted(evidence.items()):
        item["manifest_record_count"] = len(item.pop("sources"))
        result[product].append(item)
    return dict(result)


def _empty_directories(roots: list[Path]) -> list[str]:
    rows: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for directory, child_dirs, child_files in os.walk(root):
            if not child_dirs and not child_files:
                rows.append(str(Path(directory)))
    return sorted(rows)


def _mounted_volume(path: Path) -> tuple[bool, str]:
    resolved = path.resolve(strict=False)
    for candidate in (resolved, *resolved.parents):
        if os.path.ismount(candidate):
            return candidate != Path("/"), str(candidate)
    return False, ""


def _alembic_heads(code_root: Path, session: Any) -> dict[str, Any]:
    current = [str(row[0]) for row in session.execute(text("SELECT version_num FROM alembic_version")).all()]
    config = Config(str(code_root / "services/quant-api/alembic.ini"))
    config.set_main_option("script_location", str(code_root / "services/quant-api/alembic"))
    heads = list(ScriptDirectory.from_config(config).get_heads())
    return {"current": current, "heads": heads, "at_head": sorted(current) == sorted(heads)}


def run_preflight(*, code_root: Path, data_root: Path, output_dir: Path) -> dict[str, Any]:
    api_root = code_root / "services/quant-api"
    sys.path.insert(0, str(api_root))
    from app.db.session import SessionLocal  # noqa: PLC0415
    from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding  # noqa: PLC0415

    git, commands = _git_evidence(code_root)
    data_git, data_commands = _git_evidence(data_root)
    commands.extend(data_commands)
    canonical = data_root / "data/parquet/canonical/bars"
    parquet_files = sorted(canonical.rglob("*.parquet")) if canonical.is_dir() else []
    duckdb_sample: dict[str, Any] = {"path": "", "readable": False, "row_count": None, "error": "no sample"}
    if parquet_files:
        sample = parquet_files[0]
        try:
            with duckdb.connect(database=":memory:") as connection:
                count = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(sample)]).fetchone()[0]
            duckdb_sample = {"path": str(sample), "readable": True, "row_count": count, "error": ""}
        except (duckdb.Error, OSError) as exc:
            duckdb_sample = {"path": str(sample), "readable": False, "row_count": None, "error": str(exc)}

    db: dict[str, Any]
    profile_counts: dict[str, Any]
    path_drift: dict[str, int]
    alembic: dict[str, Any]
    try:
        with SessionLocal() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SELECT 1"))
            profile_counts = {
                "profiles_total": session.scalar(select(func.count()).select_from(DataProfile)),
                "profiles_active": session.scalar(
                    select(func.count()).select_from(DataProfile).where(DataProfile.is_active.is_(True))
                ),
                "bindings_total": session.scalar(select(func.count()).select_from(ProfileActiveBinding)),
                "bindings_active": session.scalar(
                    select(func.count()).select_from(ProfileActiveBinding).where(
                        ProfileActiveBinding.binding_status == "active"
                    )
                ),
            }
            missing = outside = missing_bars = 0
            for data_type, file_path in session.execute(select(MarketDataFile.data_type, MarketDataFile.file_path)):
                path = Path(file_path)
                resolved = path.resolve(strict=False) if path.is_absolute() else (data_root / path).resolve(strict=False)
                if not resolved.is_file():
                    missing += 1
                    if data_type == "bars":
                        missing_bars += 1
                try:
                    resolved.relative_to(data_root.resolve())
                except ValueError:
                    outside += 1
            path_drift = {
                "missing_market_data_paths_all_data_types": missing,
                "missing_bars_paths": missing_bars,
                "outside_data_root_paths": outside,
                "bars_path_gate_passed": missing_bars == 0,
            }
            alembic = _alembic_heads(code_root, session)
            db = {"available": True, "snapshot_source": "direct_postgresql", "error": ""}
            session.rollback()
    except (OSError, RuntimeError, SQLAlchemyError) as exc:
        db = {"available": False, "snapshot_source": "direct_postgresql", "error": type(exc).__name__}
        profile_counts = {}
        path_drift = {}
        alembic = {"current": [], "heads": [], "at_head": False}

    mounted, mount_point = _mounted_volume(data_root)
    mounted = data_root.exists() and mounted
    switch_evidence = {
        key: {"configured": key in os.environ, "enabled": os.environ.get(key, "").strip().lower() in {"1", "true", "yes", "on"}}
        for key in DISABLED_SWITCHES
    }
    empty_dirs = _empty_directories(
        [canonical, data_root / "data/manifests", data_root / "data/processed/v1b"]
    )
    blockers: list[str] = []
    if not git["head"]:
        blockers.append("ENV_BLOCKED_GIT")
    if not git["worktree_clean"]:
        blockers.append("ENV_BLOCKED_GIT")
    if not data_root.exists() or not mounted:
        blockers.append("ENV_BLOCKED_DATA_ROOT")
    if not db["available"]:
        blockers.append("ENV_BLOCKED_DB")
    if not parquet_files or not duckdb_sample["readable"] or not alembic["at_head"]:
        blockers.append("ENV_BLOCKED_DATA_ROOT")
    if path_drift.get("missing_bars_paths", 0):
        blockers.append("ENV_BLOCKED_DATA_ROOT")
    if any(item["enabled"] for item in switch_evidence.values()):
        blockers.append("ENV_BLOCKED_RUNTIME_SWITCH")
    status = READY if not blockers else blockers[0]
    evidence = {
        "task_id": TASK_ID,
        "status": status,
        "audit_end": AUDIT_END,
        "generated_at": datetime.now(UTC).isoformat(),
        "code_git": git,
        "data_git": data_git,
        "data_root": str(data_root.resolve(strict=False)),
        "data_root_mounted": mounted,
        "data_mount_point": mount_point,
        "canonical_bars_root": str(canonical),
        "canonical_exists": canonical.is_dir(),
        "canonical_parquet_count": len(parquet_files),
        "manifest_root": str(data_root / "data/manifests"),
        "processed_summary_root": str(data_root / "data/processed/v1b"),
        "reports_root": str(data_root / "data/reports"),
        "database": db,
        "alembic": alembic,
        "duckdb_sample": duckdb_sample,
        "runtime_switches": switch_evidence,
        "calls_rqdata": False,
        "archive_runtime_started": False,
        "live_runtime_started": False,
        "notifications_sent": False,
        "representative_manifest_ranges": _manifest_ranges(data_root / "data/manifests"),
        "profile_counts": profile_counts,
        "path_drift": path_drift,
        "empty_directory_count": len(empty_dirs),
        "empty_directories": empty_dirs,
        "commands": commands,
        "redaction": "No environment values, database URL, credentials, tokens, cookies, or webhook values were emitted.",
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
    }
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite preflight output: {output_dir}")
    output_dir.mkdir(parents=True)
    (output_dir / "environment_evidence.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    markdown = [
        f"# {TASK_ID}",
        "",
        f"- status: `{status}`",
        f"- audit_end: `{AUDIT_END}`",
        f"- code commit: `{git['head']}`",
        f"- data worktree commit: `{data_git['head']}`",
        f"- direct PostgreSQL: `{db['available']}`",
        f"- Alembic at head: `{alembic['at_head']}`",
        f"- canonical parquet count: `{len(parquet_files)}`",
        f"- DuckDB sample readable: `{duckdb_sample['readable']}`",
        "- writes_database / writes_parquet / writes_manifest: `false / false / false`",
        "- calls_rqdata: `false`",
        "",
        "Sensitive information was redacted: no secret environment values or connection strings were printed.",
        "",
        status,
    ]
    (output_dir / "PREFLIGHT.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return evidence


def finalize_b204b(*, data_root: Path) -> dict[str, Any]:
    repair_root = data_root / "data/reports/full_history_residual_repair_20260710"
    closure = repair_root / "closure_004b"
    historical = closure / "closure_summary.json"
    frozen = closure / "closure_summary_dry_run_historical.json"
    canonical = closure / "closure_summary_final.json"
    if canonical.exists() or frozen.exists():
        raise FileExistsError("refusing to overwrite B2-04B closure summaries")
    historical_payload = json.loads(historical.read_text(encoding="utf-8"))
    frozen.write_text(json.dumps(historical_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    inventory_path = closure / "post_repair_inventory_full/inventory_summary.json"
    audit_path = closure / "post_repair_audit_v2_full/audit_v2_summary.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    batch_paths = sorted(path for path in repair_root.rglob("apply_ledger.json") if path.is_file())
    payload = {
        "task_id": "FULL-HISTORY-RESIDUAL-REPAIR-004B",
        "status": "FULL_HISTORY_RESIDUAL_REPAIR_004B",
        "historical_dry_run_summary": str(frozen.relative_to(data_root)),
        "audit_end": AUDIT_END,
        "inventory": {
            "status": inventory.get("status"),
            "rows": inventory.get("physical_inventory_rows"),
            "checksum_status_counts": inventory.get("checksum_status_counts"),
            "physical_status_counts": inventory.get("physical_status_counts"),
            "schema_status_counts": inventory.get("schema_status_counts"),
            "path_drift": inventory.get("path_drift"),
            "sha256": _sha256(inventory_path),
        },
        "audit_v2": {
            "status": audit.get("status"),
            "expected_window_count": audit.get("expected_window_count"),
            "gap_count": audit.get("gap_count"),
            "quality": audit.get("layer_status_counts", {}).get("quality", {}),
            "warnings_promoted_to_passed": audit.get("warnings_promoted_to_passed"),
            "sha256": _sha256(audit_path),
        },
        "closure_ledgers": [
            {"path": str(path.relative_to(data_root)), "sha256": _sha256(path)} for path in batch_paths
        ],
        "db_snapshot_source": "direct_postgresql",
        "calls_rqdata_during_final_verification": False,
        "profile_binding_changed_by_b204b": False,
        "data_layer_status": "DATA_LAYER_REAUDIT_REQUIRED",
    }
    if not (
        payload["inventory"]["rows"] == 27837
        and payload["inventory"]["checksum_status_counts"] == {"matched": 27837}
        and payload["inventory"]["physical_status_counts"] == {"readable": 27837}
        and payload["inventory"]["schema_status_counts"] == {"schema_ok": 27837}
        and payload["audit_v2"]["gap_count"] == 0
        and payload["audit_v2"]["quality"] == {"passed": 693, "warning": 27}
        and payload["audit_v2"]["warnings_promoted_to_passed"] is False
    ):
        raise RuntimeError("B2-04B final evidence drifted; canonical summary not written")
    canonical.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    historical.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["preflight", "finalize-b204b"])
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.mode == "preflight":
        if args.output_dir is None:
            parser.error("--output-dir is required for preflight")
        result = run_preflight(
            code_root=args.code_root.resolve(), data_root=args.data_root.resolve(), output_dir=args.output_dir.resolve()
        )
    else:
        result = finalize_b204b(data_root=args.data_root.resolve())
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
