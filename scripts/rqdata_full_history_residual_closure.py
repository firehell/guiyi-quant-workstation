from __future__ import annotations

import argparse
import csv
from datetime import date
import json
import os
from pathlib import Path
import sys

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import select, text


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = SCRIPT_PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.models.data_center import DataQualityReport, MarketDataFile  # noqa: E402
from app.services.rqdata_ingest.actual_contract_bars_pilot import (  # noqa: E402
    _validate_reusable_raw,
    plan_actual_contract_bars_pilot,
)
from app.services.rqdata_ingest.full_history_residual_repair import (  # noqa: E402
    build_closure_operation_plan,
    load_frozen_queue,
    write_closure_operation_plan,
)
from app.services.rqdata_ingest.full_history_residual_repair_apply import (  # noqa: E402
    build_stale_retirement_ledger,
)
from app.services.rqdata_ingest.jm_v2_parquet import evaluate_standard_dominant_quality  # noqa: E402
from app.services.rqdata_ingest.parquet import sha256_file  # noqa: E402


LOCAL_QUEUE_SHA256 = "57c1bea01a425fd2acbe1e146ce848d24ae2b94d64542ce3365cc5f1ac29de6e"
RQDATA_QUEUE_SHA256 = "38b0370013f2085843bcede306e8fa58ad6c2246be50a14bc781af8ddc9daf98"
MISSING_CANDIDATE_IDS = {33197, 33198, 33199, 33200}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only planner for the B2-04B residual closure batches.")
    parser.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    parser.add_argument("--inventory-csv", type=Path, required=True)
    parser.add_argument(
        "--classification-root",
        type=Path,
        default=Path("data/reports/full_history_residual_classification_20260710"),
    )
    parser.add_argument(
        "--repair-root",
        type=Path,
        default=Path("data/reports/full_history_residual_repair_20260710"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/full_history_residual_repair_20260710/closure_004b"),
    )
    parser.add_argument("--audit-end", type=date.fromisoformat, default=date(2026, 7, 10))
    parser.add_argument("--tf-source-file-id", type=int, default=82792)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve()
    output_dir = _resolve(root, args.output_dir)
    if output_dir.exists():
        print(json.dumps({"status": "OUTPUT_EXISTS", "output_dir": str(output_dir)}), file=sys.stderr)
        return 3
    classification_root = _resolve(root, args.classification_root)
    repair_root = _resolve(root, args.repair_root)
    inventory_path = _resolve(root, args.inventory_csv)
    load_dotenv(root / ".env", override=False)
    try:
        from app.db.session import SessionLocal  # noqa: PLC0415

        with SessionLocal() as session:
            session.execute(text("select 1"))
            db_operations = _build_db_operations(session, inventory_path)
            tf_operations = _build_tf_operations(
                session,
                root=root,
                classification_root=classification_root,
                audit_end=args.audit_end,
                source_file_id=args.tf_source_file_id,
            )
            rqdata_operations = _build_rqdata_operations(
                session,
                root=root,
                classification_root=classification_root,
                repair_root=repair_root,
            )
        plans = (
            build_closure_operation_plan(
                batch_id="db-stale-retirement-002",
                operations=db_operations,
                requires_rqdata=False,
            ),
            build_closure_operation_plan(
                batch_id="local-rebuild-tf-002",
                operations=tf_operations,
                requires_rqdata=False,
            ),
            build_closure_operation_plan(
                batch_id="rqdata-missing-actual-002",
                operations=rqdata_operations,
                requires_rqdata=True,
            ),
        )
        output_dir.mkdir(parents=True)
        for plan in plans:
            write_closure_operation_plan(plan, output_dir / str(plan["batch_id"]))
        summary = {
            "task_id": "FULL-HISTORY-RESIDUAL-REPAIR-004B",
            "status": "DRY_RUN_APPROVAL_REQUIRED",
            "audit_end": args.audit_end.isoformat(),
            "writes_database": False,
            "writes_parquet": False,
            "writes_manifest": False,
            "calls_rqdata": False,
            "batches": [
                {
                    "batch_id": plan["batch_id"],
                    "operation_count": plan["operation_count"],
                    "ledger_sha256": plan["ledger_sha256"],
                    "required_approval_statement": plan["required_approval_statement"],
                }
                for plan in plans
            ],
            "rqdata_split": {
                "reuse_valid_raw": sum(item["raw_mode"] == "validate_reuse" for item in rqdata_operations),
                "requires_rqdata": sum(item["raw_mode"] == "create_only" for item in rqdata_operations),
            },
        }
        (output_dir / "closure_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - CLI must expose the fail-closed gate.
        secret = os.getenv("DATABASE_URL", "")
        message = str(exc)
        if secret:
            message = message.replace(secret, "[REDACTED_DATABASE_URL]")
        print(
            json.dumps(
                {"status": "CLOSURE_PLAN_BLOCKED", "error_type": type(exc).__name__, "error": message[:1000]},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _build_db_operations(session: object, inventory_path: Path) -> list[dict[str, object]]:
    with inventory_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    selected = [
        row
        for row in rows
        if (row.get("checksum_status") == "mismatch" and row.get("physical_status") == "readable")
        or row.get("checksum_status") == "declared_conflict"
        or _inventory_ids(row) in ({33197}, {33198}, {33199}, {33200})
    ]
    operations = build_stale_retirement_ledger(session, selected)
    if len(operations) != 389:
        raise RuntimeError(f"DB_RETIREMENT_COUNT_DRIFT: expected=389 actual={len(operations)}")
    if sum("replacement_market_data_file_id" in item for item in operations) != 385:
        raise RuntimeError("DB_REPLACEMENT_COUNT_DRIFT")
    return operations


def _build_tf_operations(
    session: object,
    *,
    root: Path,
    classification_root: Path,
    audit_end: date,
    source_file_id: int,
) -> list[dict[str, object]]:
    queue = load_frozen_queue(
        classification_root / "local_data_rebuild_queue.csv",
        expected_sha256=LOCAL_QUEUE_SHA256,
        allowed_action_types={"rebuild_derived_period_from_1m"},
    )
    actions = [action for action in queue.actions if action.product == "tf"]
    if len(actions) != 4 or {action.period for action in actions} != {"5m", "15m", "30m", "60m"}:
        raise RuntimeError("TF_FROZEN_ACTION_SCOPE_DRIFT")
    source = session.get(MarketDataFile, source_file_id)
    if source is None or source.instrument_symbol != "tf" or source.period != "1m":
        raise RuntimeError(f"TF_SOURCE_REGISTRATION_INVALID: {source_file_id}")
    source_path = Path(source.file_path)
    if not source_path.is_file():
        raise RuntimeError(f"TF_SOURCE_PHYSICAL_MISSING: {source_path}")
    frame = pd.read_parquet(source_path)
    datetimes = pd.to_datetime(frame["datetime"], errors="raise")
    frame = frame.loc[datetimes.dt.date <= audit_end].copy()
    if frame.empty:
        raise RuntimeError("TF_SOURCE_EMPTY_AFTER_AUDIT_END")
    quality = evaluate_standard_dominant_quality(frame, "1m")
    if quality.status != "passed":
        raise RuntimeError(f"TF_SOURCE_CORRECTED_QUALITY_NOT_PASSED: {quality.status}")
    start_date = pd.to_datetime(frame["datetime"]).min().date()
    exchange = str(frame["exchange"].dropna().iloc[0])
    periods = ("1m", "5m", "15m", "30m", "60m")
    outputs: list[dict[str, object]] = []
    for period in periods:
        path = (
            root
            / "data/parquet/canonical/bars/provider=rqdata"
            / f"period={period}"
            / f"exchange={exchange}"
            / "symbol=tf/contract=tf.MAIN"
            / f"tf_MAIN_{period}_{start_date:%Y%m%d}_{audit_end:%Y%m%d}_full_history_rebuild_004b_closure.parquet"
        )
        if path.exists():
            raise RuntimeError(f"TF_TARGET_EXISTS: {path}")
        outputs.append(
            {
                "period": period,
                "path": str(path),
                "data_version": f"fh_rebuild004b_closure_tf_{period}_{start_date:%Y%m%d}_{audit_end:%Y%m%d}",
            }
        )
    summary_path = root / f"data/processed/v1b/tf/tf_full_history_rebuild_004b_closure_{start_date:%Y%m%d}_{audit_end:%Y%m%d}.json"
    manifest_path = root / "data/manifests/full_history_residual_repair_004b_closure_tf.csv"
    if summary_path.exists() or manifest_path.exists():
        raise RuntimeError("TF_SUMMARY_OR_MANIFEST_EXISTS")
    report_ids = list(
        session.scalars(select(DataQualityReport.id).where(DataQualityReport.file_id == source_file_id)).all()
    )
    return [
        {
            "source_action_ids": sorted(action.queue_action_id for action in actions),
            "source_market_data_file_id": source_file_id,
            "source_quality_report_ids": report_ids,
            "source_path": str(source_path),
            "source_checksum": sha256_file(source_path),
            "source_row_count_at_audit_end": len(frame),
            "source_min_datetime": pd.to_datetime(frame["datetime"]).min().isoformat(),
            "source_max_datetime": pd.to_datetime(frame["datetime"]).max().isoformat(),
            "corrected_quality_status": quality.status,
            "corrected_abnormal_price_count": quality.abnormal_price_count,
            "data_role": "candidate",
            "outputs": outputs,
            "summary_path": str(summary_path),
            "manifest_path": str(manifest_path),
            "profile_binding_switch": False,
        }
    ]


def _build_rqdata_operations(
    session: object,
    *,
    root: Path,
    classification_root: Path,
    repair_root: Path,
) -> list[dict[str, object]]:
    queue = load_frozen_queue(
        classification_root / "rqdata_download_candidate_queue.csv",
        expected_sha256=RQDATA_QUEUE_SHA256,
        allowed_action_types={"download_missing_actual_rank1_interval"},
    )
    previous = json.loads((repair_root / "rqdata-missing-actual-001/apply_ledger.json").read_text(encoding="utf-8"))
    blocked_ids = {str(item["queue_action_id"]) for item in previous.get("prevalidation_blocked") or ()}
    actions = [action for action in queue.actions if action.queue_action_id in blocked_ids]
    if len(actions) != 71:
        raise RuntimeError(f"RQDATA_BLOCKED_SCOPE_DRIFT: expected=71 actual={len(actions)}")
    operations: list[dict[str, object]] = []
    for action in actions:
        scope = action.target_scope.split(":")
        if len(scope) != 5:
            raise RuntimeError(f"RQDATA_TARGET_SCOPE_INVALID: {action.target_scope}")
        product, contract, period, start_text, end_text = scope
        start_date = date.fromisoformat(start_text)
        end_date = date.fromisoformat(end_text)
        pilot = plan_actual_contract_bars_pilot(
            session=session,
            output_root=root / "data",
            product=product,
            trade_date=end_date,
            start_date=start_date,
            end_date=end_date,
            periods=(period,),
            jm_only=False,
        )
        if pilot["actual_contract"] != contract:
            raise RuntimeError(
                f"RQDATA_MAPPING_DRIFT: action={action.queue_action_id} expected={contract} actual={pilot['actual_contract']}"
            )
        period_plan = pilot["periods"][period]
        canonical_path = Path(period_plan["canonical_path"])
        if canonical_path.exists():
            raise RuntimeError(f"RQDATA_CANONICAL_TARGET_EXISTS: {canonical_path}")
        manifest_path = Path(pilot["manifest_path"])
        if not manifest_path.is_file():
            raise RuntimeError(f"RQDATA_COLLISION_MANIFEST_MISSING: {manifest_path}")
        manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
        existing_periods = sorted(set(manifest["period"].tolist()))
        if period in existing_periods:
            raise RuntimeError(f"RQDATA_TARGET_PERIOD_ALREADY_IN_MANIFEST: {manifest_path} period={period}")
        raw_path = Path(str(period_plan["raw_path"]))
        raw_mode = "create_only"
        raw_checksum = ""
        if raw_path.exists():
            raw = pd.read_parquet(raw_path)
            _validate_reusable_raw(
                raw,
                path=raw_path,
                contract=contract,
                period=period,
                start_date=start_date,
                end_date=end_date,
            )
            raw_mode = "validate_reuse"
            raw_checksum = sha256_file(raw_path)
        operations.append(
            {
                "queue_action_id": action.queue_action_id,
                "product": product,
                "contract": contract,
                "period": period,
                "trade_date": end_text,
                "start_date": start_text,
                "end_date": end_text,
                "exchange": pilot["exchange"],
                "data_role": "candidate",
                "data_version": period_plan["data_version"],
                "raw_mode": raw_mode,
                "raw_path": str(raw_path),
                "raw_checksum_before": raw_checksum,
                "canonical_path": str(canonical_path),
                "manifest_mode": "merge_existing",
                "manifest_path": str(manifest_path),
                "manifest_sha256_before": sha256_file(manifest_path),
                "manifest_existing_periods": existing_periods,
                "profile_binding_switch": False,
            }
        )
    if sum(item["raw_mode"] == "validate_reuse" for item in operations) != 36:
        raise RuntimeError("RQDATA_REUSABLE_RAW_COUNT_DRIFT")
    if sum(item["raw_mode"] == "create_only" for item in operations) != 35:
        raise RuntimeError("RQDATA_REQUIRED_DOWNLOAD_COUNT_DRIFT")
    return operations


def _inventory_ids(row: dict[str, str]) -> set[int]:
    try:
        return {int(item) for item in json.loads(row.get("market_data_file_ids") or "[]")}
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()


def _resolve(root: Path, path: Path) -> Path:
    return (path if path.is_absolute() else root / path).resolve(strict=False)


if __name__ == "__main__":
    raise SystemExit(main())
