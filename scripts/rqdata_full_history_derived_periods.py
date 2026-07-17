from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

import pandas as pd
from dotenv import load_dotenv

SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = SCRIPT_PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

AUDIT_END = date(2026, 7, 10)
HARD_TARGET_START = date(2023, 1, 3)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify and gate local full-history derived periods without RQData.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    verify.add_argument("--audit-end", type=date.fromisoformat, default=AUDIT_END)
    verify.add_argument("--scan-mode", choices=("quick", "full"), default="quick")
    verify.add_argument("--product", action="append", default=[])
    verify.add_argument("--max-workers", type=int, default=4)
    verify.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/full_history_audit_v2_20260710/derived_periods_005"),
    )

    plan = subparsers.add_parser("plan-repair")
    plan.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    plan.add_argument("--verification-dir", type=Path, required=True)
    plan.add_argument("--batch-id", required=True)
    plan.add_argument("--output-dir", type=Path, required=True)

    apply = subparsers.add_parser("apply-repair")
    apply.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    apply.add_argument("--plan-dir", type=Path, required=True)
    apply.add_argument("--approval-statement", required=True)

    session_plan = subparsers.add_parser("plan-session-repair")
    session_plan.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    session_plan.add_argument("--batch-id", default="jm-session-reference-005-001")
    session_plan.add_argument("--audit-start", type=date.fromisoformat, default=HARD_TARGET_START)
    session_plan.add_argument("--audit-end", type=date.fromisoformat, default=AUDIT_END)
    session_plan.add_argument("--output-dir", type=Path, required=True)

    session_apply = subparsers.add_parser("apply-session-repair")
    session_apply.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    session_apply.add_argument("--plan-dir", type=Path, required=True)
    session_apply.add_argument("--approval-statement", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve()
    try:
        if args.command == "plan-repair":
            return _plan_repair(root, args)
        load_dotenv(root / ".env", override=False)
        from app.db.session import SessionLocal  # noqa: PLC0415
        from app.services.rqdata_ingest.full_history_derived_periods import (  # noqa: PLC0415
            DERIVED_PERIOD_TARGETS_VERIFIED,
            DerivedPeriodVerificationConfig,
            apply_derived_period_repair_plan,
            apply_jm_session_repair_plan,
            build_jm_session_repair_plan,
            run_derived_period_verification,
            write_derived_period_reports,
        )

        if args.command == "plan-session-repair":
            output = _resolve(root, args.output_dir)
            if output.exists():
                raise FileExistsError(f"output directory already exists: {output}")
            with SessionLocal() as session:
                plan = build_jm_session_repair_plan(
                    session,
                    batch_id=args.batch_id,
                    audit_start=args.audit_start,
                    audit_end=args.audit_end,
                    enforce_formal_counts=True,
                )
            output.mkdir(parents=True)
            (output / "session_repair_plan.json").write_text(
                json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            pd.DataFrame(plan["operations"]).to_csv(
                output / "session_repair_operations.csv",
                index=False,
            )
            (output / "session_before.json").write_text(
                json.dumps(
                    {
                        "contract_evidence": plan["contract_evidence"],
                        "calendar_evidence": plan["calendar_evidence"],
                        "rows": [item["before"] for item in plan["operations"]],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "status": "DRY_RUN_APPROVAL_REQUIRED",
                        "batch_id": plan["batch_id"],
                        "ledger_sha256": plan["ledger_sha256"],
                        "required_approval_statement": plan["required_approval_statement"],
                        "operation_counts": plan["operation_counts"],
                        "writes_database": False,
                        "writes_parquet": False,
                        "writes_manifest": False,
                        "calls_rqdata": False,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "apply-session-repair":
            plan_dir = _resolve(root, args.plan_dir)
            after_path = plan_dir / "session_after.json"
            rollback_path = plan_dir / "rollback_evidence.json"
            if after_path.exists() or rollback_path.exists():
                raise FileExistsError(f"session apply evidence already exists: {plan_dir}")
            plan = json.loads((plan_dir / "session_repair_plan.json").read_text(encoding="utf-8"))
            with SessionLocal() as session:
                result = apply_jm_session_repair_plan(
                    plan,
                    approval_statement=args.approval_statement,
                    session=session,
                    require_postgresql=True,
                )
            after_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            rollback_path.write_text(
                json.dumps(
                    {
                        "status": "RECORDED",
                        "batch_id": result["batch_id"],
                        "ledger_sha256": result["ledger_sha256"],
                        "method": result["rollback_method"],
                        "before_snapshot": "session_before.json",
                        "profile_binding_changed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0

        if args.command == "apply-repair":
            plan_dir = _resolve(root, args.plan_dir)
            plan = json.loads((plan_dir / "repair_plan.json").read_text(encoding="utf-8"))
            with SessionLocal() as session:
                result = apply_derived_period_repair_plan(
                    plan,
                    approval_statement=args.approval_statement,
                    project_root=root,
                    session=session,
                    require_postgresql=True,
                )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0

        output = _resolve(root, args.output_dir)
        with SessionLocal() as session:
            result = run_derived_period_verification(
                DerivedPeriodVerificationConfig(
                    project_root=root,
                    audit_end=args.audit_end,
                    scan_mode=args.scan_mode,
                    products=tuple(args.product),
                    max_workers=args.max_workers,
                    require_postgresql=True,
                ),
                session,
            )
            paths = write_derived_period_reports(result, output)
        print(
            json.dumps(
                {
                    **result.summary,
                    "outputs": {name: str(path) for name, path in paths.items()},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if result.summary["status"] == DERIVED_PERIOD_TARGETS_VERIFIED else 4
    except FileExistsError as exc:
        print(json.dumps({"status": "OUTPUT_EXISTS", "error": str(exc)[:500]}), file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - CLI must expose a redacted fail-closed gate.
        secret = os.getenv("DATABASE_URL", "")
        message = str(exc)
        if secret:
            message = message.replace(secret, "[REDACTED_DATABASE_URL]")
        status = "ENV_BLOCKED_DB" if "ENV_BLOCKED_DB" in message else "DERIVED_PERIODS_GATE_BLOCKED"
        if type(exc).__name__ == "RepairApprovalError":
            status = "REPAIR_GATE_BLOCKED"
        print(
            json.dumps({"status": status, "error_type": type(exc).__name__, "error": message[:800]}),
            file=sys.stderr,
        )
        return 2


def _plan_repair(root: Path, args: argparse.Namespace) -> int:
    from app.services.rqdata_ingest.full_history_derived_periods import (  # noqa: PLC0415
        build_derived_period_repair_plan,
    )

    verification = _resolve(root, args.verification_dir)
    residual_path = verification / "lineage_residuals.csv"
    residuals = pd.read_csv(residual_path, keep_default_na=False).to_dict("records")
    plan = build_derived_period_repair_plan(residuals, batch_id=args.batch_id)
    output = _resolve(root, args.output_dir)
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    output.mkdir(parents=True)
    (output / "repair_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(plan["operations"]).to_csv(output / "repair_operations.csv", index=False)
    print(
        json.dumps(
            {
                "status": "DRY_RUN_APPROVAL_REQUIRED" if plan["operations"] else "REPAIR_BLOCKED_SESSION_REFERENCE",
                "batch_id": plan["batch_id"],
                "ledger_sha256": plan["ledger_sha256"],
                "required_approval_statement": plan["required_approval_statement"],
                "operation_count": len(plan["operations"]),
                "blocked_residual_count": len(plan["blocked_residuals"]),
                "writes_database": False,
                "writes_parquet": False,
                "writes_manifest": False,
                "calls_rqdata": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _resolve(root: Path, value: Path) -> Path:
    return (value if value.is_absolute() else root / value).resolve(strict=False)


if __name__ == "__main__":
    raise SystemExit(main())
