from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

import pandas as pd
from sqlalchemy import select, text


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = SCRIPT_PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.models.data_center import DataQualityReport, MarketDataFile, ProfileActiveBinding  # noqa: E402
from app.services.rqdata_ingest.actual_contract_bars_pilot import run_actual_contract_bars_pilot_write  # noqa: E402
from app.services.rqdata_ingest.bar_aggregation import aggregate_standard_bars  # noqa: E402
from app.services.rqdata_ingest.client import RqDataClient  # noqa: E402
from app.services.rqdata_ingest.dominant_v2_register import register_dominant_v2_quality  # noqa: E402
from app.services.rqdata_ingest.full_history_residual_repair import (  # noqa: E402
    closure_command_accepts_batch,
    load_approved_closure_operation_plan,
)
from app.services.rqdata_ingest.full_history_residual_repair_apply import (  # noqa: E402
    retire_stale_market_data_files,
)
from app.services.rqdata_ingest.jm_v2_parquet import evaluate_standard_dominant_quality  # noqa: E402
from app.services.rqdata_ingest.parquet import sha256_file, write_parquet_atomic  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply one explicitly approved B2-04B closure batch.")
    parser.add_argument("command", choices=("apply-db", "apply-tf", "apply-rqdata"))
    parser.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    parser.add_argument("--plan-dir", type=Path, required=True)
    parser.add_argument("--approval-statement", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve()
    plan_dir = _resolve(root, args.plan_dir)
    try:
        plan = load_approved_closure_operation_plan(
            plan_dir,
            approval_statement=args.approval_statement,
        )
        if not closure_command_accepts_batch(args.command, str(plan["batch_id"])):
            raise RuntimeError(f"COMMAND_BATCH_MISMATCH: command={args.command} batch={plan['batch_id']}")
        if args.command == "apply-db":
            result = _apply_db(root, plan_dir, plan)
        elif args.command == "apply-tf":
            result = _apply_tf(root, plan_dir, plan)
        else:
            result = _apply_rqdata(root, plan_dir, plan)
    except Exception as exc:  # noqa: BLE001 - CLI exposes a redacted fail-closed result.
        secret = os.getenv("DATABASE_URL", "")
        message = str(exc)
        if secret:
            message = message.replace(secret, "[REDACTED_DATABASE_URL]")
        print(
            json.dumps(
                {"status": "CLOSURE_APPLY_BLOCKED", "error_type": type(exc).__name__, "error": message[:1200]},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    return 0


def _apply_db(root: Path, plan_dir: Path, plan: dict[str, object]) -> dict[str, object]:
    operations = list(plan["operations"])
    before_path = plan_dir / "before_snapshot.json"
    ledger_path = plan_dir / "apply_ledger.json"
    rollback_path = plan_dir / "rollback_evidence.json"
    _require_outputs_absent(before_path, ledger_path, rollback_path)
    from app.db.session import SessionLocal  # noqa: PLC0415

    with SessionLocal() as session:
        session.execute(text("select 1"))
        before = []
        for operation in operations:
            file_id = int(operation["market_data_file_id"])
            item = session.get(MarketDataFile, file_id)
            if item is None:
                raise RuntimeError(f"MARKET_DATA_FILE_MISSING: {file_id}")
            reports = session.scalars(select(DataQualityReport).where(DataQualityReport.file_id == file_id)).all()
            bindings = session.scalars(
                select(ProfileActiveBinding).where(ProfileActiveBinding.market_data_file_id == file_id)
            ).all()
            before.append(
                {
                    "market_data_file": _model_snapshot(item),
                    "quality_reports": [_model_snapshot(report) for report in reports],
                    "profile_binding_ids": [binding.id for binding in bindings],
                }
            )
        _write_json_exclusive(before_path, before)
        try:
            applied = retire_stale_market_data_files(session, operations)
            session.commit()
        except Exception:
            session.rollback()
            raise
    with SessionLocal() as verify_session:
        remaining = [
            int(operation["market_data_file_id"])
            for operation in operations
            if verify_session.get(MarketDataFile, int(operation["market_data_file_id"])) is not None
        ]
        remaining_reports = list(
            verify_session.scalars(
                select(DataQualityReport.id).where(
                    DataQualityReport.id.in_(
                        [int(report_id) for operation in operations for report_id in operation["quality_report_ids"]]
                    )
                )
            ).all()
        )
        missing_replacements = [
            int(operation["replacement_market_data_file_id"])
            for operation in operations
            if operation.get("replacement_market_data_file_id") is not None
            and verify_session.get(MarketDataFile, int(operation["replacement_market_data_file_id"])) is None
        ]
    if remaining or remaining_reports or missing_replacements:
        raise RuntimeError(
            f"DB_RETIREMENT_VERIFY_FAILED: remaining={remaining} reports={remaining_reports} replacements={missing_replacements}"
        )
    result = {
        "status": "APPLIED_VERIFIED",
        "batch_id": plan["batch_id"],
        "ledger_sha256": plan["ledger_sha256"],
        "deleted_market_data_files": len(applied),
        "deleted_quality_reports": sum(item["deleted_quality_report_count"] for item in applied),
        "replacement_rows_preserved": sum(item["replacement_market_data_file_id"] is not None for item in applied),
        "profile_binding_changed": False,
        "writes_database": True,
        "writes_parquet": False,
        "calls_rqdata": False,
    }
    _write_json_exclusive(ledger_path, {**result, "results": applied})
    _write_json_exclusive(
        rollback_path,
        {
            "status": "ROLLBACK_SNAPSHOT_READY",
            "before_snapshot": str(before_path),
            "method": "Reinsert only the exact serialized MarketDataFile and DataQualityReport rows in one transaction.",
            "row_count": len(before),
        },
    )
    return result


def _apply_tf(root: Path, plan_dir: Path, plan: dict[str, object]) -> dict[str, object]:
    operations = list(plan["operations"])
    if len(operations) != 1:
        raise RuntimeError("TF_OPERATION_COUNT_INVALID")
    operation = operations[0]
    ledger_path = plan_dir / "apply_ledger.json"
    rollback_path = plan_dir / "rollback_evidence.json"
    _require_outputs_absent(ledger_path, rollback_path)
    output_specs = list(operation["outputs"])
    output_paths = [Path(str(item["path"])) for item in output_specs]
    summary_path = Path(str(operation["summary_path"]))
    manifest_path = Path(str(operation["manifest_path"]))
    _require_outputs_absent(*output_paths, summary_path, manifest_path)
    source_path = Path(str(operation["source_path"]))
    if sha256_file(source_path) != operation["source_checksum"]:
        raise RuntimeError("TF_SOURCE_CHECKSUM_DRIFT")
    source = pd.read_parquet(source_path)
    audit_end = date.fromisoformat(str(operation["source_max_datetime"])[:10])
    source = source.loc[pd.to_datetime(source["datetime"], errors="raise").dt.date <= audit_end].copy()
    if len(source) != int(operation["source_row_count_at_audit_end"]):
        raise RuntimeError("TF_SOURCE_ROW_COUNT_DRIFT")
    spec_by_period = {str(item["period"]): item for item in output_specs}
    frames: dict[str, pd.DataFrame] = {}
    source_spec = spec_by_period["1m"]
    source["period"] = "1m"
    source["interval"] = "1m"
    source["data_role"] = "candidate"
    source["data_version"] = source_spec["data_version"]
    source_quality = evaluate_standard_dominant_quality(source, "1m")
    if source_quality.status != "passed":
        raise RuntimeError(f"TF_CORRECTED_SOURCE_QUALITY_FAILED: {source_quality.status}")
    source["quality_status"] = "passed"
    frames["1m"] = source
    for period in ("5m", "15m", "30m", "60m"):
        frame = aggregate_standard_bars(source, period)
        frame["data_role"] = "candidate"
        frame["data_version"] = spec_by_period[period]["data_version"]
        quality = evaluate_standard_dominant_quality(frame, period)
        if quality.status != "passed":
            raise RuntimeError(f"TF_DERIVED_QUALITY_FAILED: period={period} status={quality.status}")
        frame["quality_status"] = "passed"
        frames[period] = frame
    created: list[Path] = []
    from app.db.session import SessionLocal  # noqa: PLC0415

    try:
        periods_payload: dict[str, Any] = {}
        for period, frame in frames.items():
            path = Path(str(spec_by_period[period]["path"]))
            write_parquet_atomic(frame, path)
            created.append(path)
            timestamps = pd.to_datetime(frame["datetime"], errors="raise")
            periods_payload[period] = {
                "data_version": spec_by_period[period]["data_version"],
                "raw": {"path": str(source_path)},
                "standard": {
                    "path": str(path),
                    "row_count": len(frame),
                    "min_datetime": timestamps.min().isoformat(),
                    "max_datetime": timestamps.max().isoformat(),
                    "checksum": sha256_file(path),
                },
            }
        summary = {
            "symbol": "tf",
            "contract": "tf.MAIN",
            "exchange": str(source["exchange"].dropna().iloc[0]),
            "start_date": pd.to_datetime(source["datetime"]).min().date().isoformat(),
            "end_date": audit_end.isoformat(),
            "data_role": "candidate",
            "periods": periods_payload,
        }
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json_exclusive(summary_path, summary)
        created.append(summary_path)
        with SessionLocal() as session:
            registration = register_dominant_v2_quality(
                session=session,
                summary_path=summary_path,
                manifest_path=manifest_path,
                data_role="candidate",
            )
            session.commit()
        created.append(manifest_path)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    registered = registration["periods"]
    if set(registered) != {"1m", "5m", "15m", "30m", "60m"}:
        raise RuntimeError("TF_REGISTRATION_PERIOD_DRIFT")
    if any(item["quality_status"] != "passed" for item in registered.values()):
        raise RuntimeError("TF_REGISTRATION_QUALITY_NOT_PASSED")
    result = {
        "status": "APPLIED_VERIFIED",
        "batch_id": plan["batch_id"],
        "ledger_sha256": plan["ledger_sha256"],
        "asset_count": len(registered),
        "periods": registered,
        "profile_binding_changed": False,
        "writes_database": True,
        "writes_parquet": True,
        "calls_rqdata": False,
    }
    _write_json_exclusive(ledger_path, result)
    _write_json_exclusive(
        rollback_path,
        {
            "status": "ROLLBACK_SCOPE_RECORDED",
            "market_data_file_ids": [item["market_data_file_id"] for item in registered.values()],
            "quality_report_ids": [item["data_quality_report_id"] for item in registered.values()],
            "files": [str(path) for path in output_paths] + [str(summary_path), str(manifest_path)],
            "profile_binding_changed": False,
        },
    )
    return result


def _apply_rqdata(root: Path, plan_dir: Path, plan: dict[str, object]) -> dict[str, object]:
    operations = list(plan["operations"])
    if len(operations) != 71:
        raise RuntimeError("RQDATA_OPERATION_COUNT_INVALID")
    ledger_path = plan_dir / "apply_ledger.json"
    rollback_path = plan_dir / "rollback_evidence.json"
    _require_outputs_absent(ledger_path, rollback_path)
    backup_root = plan_dir / "before_manifests"
    client = RqDataClient(load_env_file=True)
    from app.db.session import SessionLocal  # noqa: PLC0415

    results: list[dict[str, object]] = []
    for index, operation in enumerate(operations, start=1):
        manifest_path = Path(str(operation["manifest_path"]))
        raw_path = Path(str(operation["raw_path"]))
        canonical_path = Path(str(operation["canonical_path"]))
        if sha256_file(manifest_path) != operation["manifest_sha256_before"]:
            raise RuntimeError(f"RQDATA_MANIFEST_DRIFT: {manifest_path}")
        if canonical_path.exists():
            raise RuntimeError(f"RQDATA_CANONICAL_TARGET_EXISTS: {canonical_path}")
        if operation["raw_mode"] == "validate_reuse":
            if not raw_path.is_file() or sha256_file(raw_path) != operation["raw_checksum_before"]:
                raise RuntimeError(f"RQDATA_REUSABLE_RAW_DRIFT: {raw_path}")
        elif raw_path.exists():
            raise RuntimeError(f"RQDATA_RAW_TARGET_EXISTS: {raw_path}")
        backup_path = backup_root / f"{manifest_path.name}.before-{operation['manifest_sha256_before']}.csv"
        try:
            with SessionLocal() as session:
                result = run_actual_contract_bars_pilot_write(
                    session=session,
                    client=client,
                    output_root=root / "data",
                    product=str(operation["product"]),
                    trade_date=date.fromisoformat(str(operation["trade_date"])),
                    start_date=date.fromisoformat(str(operation["start_date"])),
                    end_date=date.fromisoformat(str(operation["end_date"])),
                    periods=(str(operation["period"]),),
                    jm_only=False,
                    local_daily=bool(operation.get("local_daily", False)),
                    data_role="candidate",
                    raw_mode=str(operation["raw_mode"]),
                    manifest_mode="merge_existing",
                    manifest_backup_root=backup_root,
                    raw_path_override=raw_path if operation.get("original_raw_path") else None,
                )
                period_result = result["periods"][str(operation["period"])]
                if period_result["quality_status"] != "passed" or not canonical_path.is_file():
                    raise RuntimeError(f"RQDATA_ACTION_VERIFY_FAILED: {operation['queue_action_id']}")
                result_record = {
                    "sequence": index,
                    "queue_action_id": operation["queue_action_id"],
                    "raw_mode": operation["raw_mode"],
                    "raw_path": str(raw_path),
                    "canonical_path": str(canonical_path),
                    "manifest_path": str(manifest_path),
                    "manifest_backup_path": str(backup_path),
                    "market_data_file_id": period_result["market_data_file_id"],
                    "quality_report_id": period_result["data_quality_report_id"],
                    "quality_status": period_result["quality_status"],
                    "checksum": period_result["checksum"],
                    "row_count": period_result["row_count"],
                    "data_version": period_result["data_version"],
                }
                session.commit()
        except Exception:
            if backup_path.exists():
                shutil.copy2(backup_path, manifest_path)
            canonical_path.unlink(missing_ok=True)
            if operation["raw_mode"] == "create_only":
                raw_path.unlink(missing_ok=True)
            raise
        results.append(result_record)
    result = {
        "status": "APPLIED_VERIFIED",
        "batch_id": plan["batch_id"],
        "ledger_sha256": plan["ledger_sha256"],
        "applied_count": len(results),
        "reused_raw_count": sum(item["raw_mode"] == "validate_reuse" for item in results),
        "rqdata_download_count": sum(item["raw_mode"] == "create_only" for item in results),
        "profile_binding_changed": False,
        "writes_database": True,
        "writes_parquet": True,
        "calls_rqdata": True,
        "results": results,
    }
    _write_json_exclusive(ledger_path, result)
    _write_json_exclusive(
        rollback_path,
        {
            "status": "ROLLBACK_SCOPE_RECORDED",
            "market_data_file_ids": [item["market_data_file_id"] for item in results],
            "quality_report_ids": [item["quality_report_id"] for item in results],
            "canonical_paths": [item["canonical_path"] for item in results],
            "created_raw_paths": [item["raw_path"] for item in results if item["raw_mode"] == "create_only"],
            "manifest_backups": [item["manifest_backup_path"] for item in results],
            "profile_binding_changed": False,
        },
    )
    return {key: value for key, value in result.items() if key != "results"}


def _model_snapshot(model: object) -> dict[str, object]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


def _write_json_exclusive(path: Path, payload: object) -> None:
    if path.exists():
        raise FileExistsError(f"OUTPUT_EXISTS: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _require_outputs_absent(*paths: Path) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(f"OUTPUT_EXISTS: {existing}")


def _resolve(root: Path, path: Path) -> Path:
    return (path if path.is_absolute() else root / path).resolve(strict=False)


if __name__ == "__main__":
    raise SystemExit(main())
