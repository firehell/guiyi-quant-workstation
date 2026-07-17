from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = SCRIPT_PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.full_history_residual_repair import (  # noqa: E402
    ApprovalRequiredError,
    BatchApproval,
    FrozenQueueError,
    build_repair_plan,
    load_frozen_queue,
    validate_batch_approval,
    write_repair_plan,
)


QUEUE_SPECS = {
    "code": {
        "file": "code_fix_queue.csv",
        "sha256": "7a2ce118c94ec560d0542a8b89025531ddecb0dbd9bca556e0d6aa198e557e8e",
        "actions": {
            "clip_actual_rank1_to_supported_boundary",
            "deduplicate_actual_rank1_targets",
            "remove_static_annual_session_requirement",
        },
    },
    "metadata": {
        "file": "metadata_repair_queue.csv",
        "sha256": "672dcfee33fa7151688157fab30694a0cbd3dafca727d7fdf9cf9491c1876f15",
        "actions": {
            "create_missing_registration_metadata",
            "reconcile_db_registration",
            "regenerate_processed_summary",
            "repair_manifest_checksum",
            "repair_trading_calendar_boundary",
        },
    },
    "local-rebuild": {
        "file": "local_data_rebuild_queue.csv",
        "sha256": "57c1bea01a425fd2acbe1e146ce848d24ae2b94d64542ce3365cc5f1ac29de6e",
        "actions": {"rebuild_derived_period_from_1m"},
    },
    "rqdata": {
        "file": "rqdata_download_candidate_queue.csv",
        "sha256": "38b0370013f2085843bcede306e8fa58ad6c2246be50a14bc781af8ddc9daf98",
        "actions": {"download_missing_actual_rank1_interval"},
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed planner for frozen B2-04A residual repair queues.")
    parser.add_argument("command", choices=("plan", "verify-approval"))
    parser.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    parser.add_argument(
        "--queue-root",
        type=Path,
        default=Path("data/reports/full_history_residual_classification_20260710"),
    )
    parser.add_argument("--queue", choices=tuple(QUEUE_SPECS), required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--action-id", action="append", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--approval-json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve()
    queue_root = args.queue_root if args.queue_root.is_absolute() else root / args.queue_root
    spec = QUEUE_SPECS[args.queue]
    try:
        queue = load_frozen_queue(
            queue_root / str(spec["file"]),
            expected_sha256=str(spec["sha256"]),
            allowed_action_types=set(spec["actions"]),
        )
        plan = build_repair_plan(queue, batch_id=args.batch_id, selected_action_ids=tuple(args.action_id))
        if args.command == "plan":
            if args.output_dir is None:
                raise FrozenQueueError("OUTPUT_DIR_REQUIRED")
            output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
            paths = write_repair_plan(plan, output_dir)
            print(
                json.dumps(
                    {
                        "status": "DRY_RUN_APPROVAL_REQUIRED",
                        "batch_id": plan.batch_id,
                        "ledger_sha256": plan.ledger_sha256,
                        "required_approval_statement": plan.required_approval_statement,
                        "writes_database": False,
                        "writes_parquet": False,
                        "writes_manifest": False,
                        "calls_rqdata": False,
                        "outputs": {name: str(path) for name, path in paths.items()},
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.approval_json is None:
            raise ApprovalRequiredError("APPROVAL_JSON_REQUIRED")
        payload = json.loads(args.approval_json.read_text(encoding="utf-8"))
        approval = BatchApproval(
            task_id=str(payload.get("task_id", "")),
            batch_id=str(payload.get("batch_id", "")),
            queue_sha256=str(payload.get("queue_sha256", "")),
            ledger_sha256=str(payload.get("ledger_sha256", "")),
            approved_action_ids=tuple(payload.get("approved_action_ids") or ()),
            approval_statement=str(payload.get("approval_statement", "")),
            rqdata_allowed=payload.get("rqdata_allowed") is True,
        )
        validate_batch_approval(plan, approval)
        print(json.dumps({"status": "APPROVAL_VALID", "batch_id": plan.batch_id}, sort_keys=True))
        return 0
    except FileExistsError as exc:
        print(json.dumps({"status": "OUTPUT_EXISTS", "error": str(exc)}), file=sys.stderr)
        return 3
    except (FrozenQueueError, ApprovalRequiredError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps({"status": "REPAIR_GATE_BLOCKED", "error_type": type(exc).__name__, "error": str(exc)[:500]}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
