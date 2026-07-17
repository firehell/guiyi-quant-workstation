from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = SCRIPT_PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.actual_contract_bars_pilot import _evaluate_actual_contract_bar_quality  # noqa: E402
from app.services.rqdata_ingest.bar_sample import normalize_bar_frame  # noqa: E402
from app.services.rqdata_ingest.full_history_residual_repair import (  # noqa: E402
    build_closure_operation_plan,
    write_closure_operation_plan,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replan quality-failed RQData daily bars with a local 1m-to-1d source.")
    parser.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    parser.add_argument(
        "--source-plan-dir",
        type=Path,
        default=Path("data/reports/full_history_residual_repair_20260710/closure_004b/rqdata-missing-actual-003"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/full_history_residual_repair_20260710/closure_004b/rqdata-missing-actual-004"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve()
    source_dir = _resolve(root, args.source_plan_dir)
    output_dir = _resolve(root, args.output_dir)
    operations = json.loads((source_dir / "operations.json").read_text(encoding="utf-8"))
    if len(operations) != 71:
        raise RuntimeError(f"SOURCE_OPERATION_COUNT_DRIFT: {len(operations)}")
    local_daily = 0
    reused = 0
    missing = 0
    revised: list[dict[str, object]] = []
    for original in operations:
        operation = dict(original)
        if operation.get("original_raw_quality_status") == "failed":
            original_raw_path = Path(str(operation["original_raw_path"]))
            minute_root = original_raw_path.parents[1] / "frequency=1m"
            minute_path = minute_root / (
                f"{operation['contract']}_1m_raw_{operation['start_date'].replace('-', '')}_"
                f"{operation['end_date'].replace('-', '')}_repair004b_local_daily.parquet"
            )
            if minute_path.exists():
                raise RuntimeError(f"LOCAL_DAILY_RAW_TARGET_EXISTS: {minute_path}")
            operation.update(
                {
                    "raw_mode": "create_only",
                    "raw_path": str(minute_path),
                    "raw_checksum_before": "",
                    "source_period": "1m",
                    "local_daily": True,
                    "raw_refresh_reason": "rqdata_daily_close_settlement_ohlc_mismatch_use_1m_local_daily",
                }
            )
            local_daily += 1
        elif operation["raw_mode"] == "validate_reuse":
            raw_path = Path(str(operation["raw_path"]))
            raw = pd.read_parquet(raw_path)
            frame = normalize_bar_frame(
                raw,
                symbol=str(operation["product"]),
                contract=str(operation["contract"]),
                source_contract=str(operation["contract"]),
                exchange=str(operation["exchange"]),
                frequency=str(operation["period"]),
                data_version=str(operation["data_version"]),
            )
            quality = _evaluate_actual_contract_bar_quality(frame, str(operation["period"]))
            if quality.status == "passed":
                operation["raw_quality_precheck"] = "passed"
                reused += 1
            else:
                raise RuntimeError(f"REUSABLE_RAW_QUALITY_DRIFT: {raw_path} status={quality.status}")
        else:
            operation["source_period"] = str(operation["period"])
            operation["local_daily"] = False
            missing += 1
        revised.append(operation)
    if (reused, local_daily, missing) != (4, 32, 35):
        raise RuntimeError(f"RQDATA_REPLAN_COUNT_DRIFT: reuse={reused} local_daily={local_daily} missing={missing}")
    plan = build_closure_operation_plan(
        batch_id="rqdata-missing-actual-004",
        operations=revised,
        requires_rqdata=True,
    )
    write_closure_operation_plan(plan, output_dir)
    summary = {
        "status": "DRY_RUN_APPROVAL_REQUIRED",
        "batch_id": plan["batch_id"],
        "ledger_sha256": plan["ledger_sha256"],
        "required_approval_statement": plan["required_approval_statement"],
        "operation_count": len(revised),
        "reuse_valid_raw": reused,
        "rebuild_daily_from_new_1m_raw": local_daily,
        "download_missing_raw": missing,
        "rqdata_call_count": local_daily + missing,
        "overwrites_existing_raw": False,
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
    }
    (output_dir / "replan_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _resolve(root: Path, path: Path) -> Path:
    return (path if path.is_absolute() else root / path).resolve(strict=False)


if __name__ == "__main__":
    raise SystemExit(main())
