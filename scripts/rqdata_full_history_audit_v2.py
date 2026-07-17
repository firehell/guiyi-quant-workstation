from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = SCRIPT_PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.full_history_audit_v2 import (  # noqa: E402
    READY,
    AuditV2Config,
    run_full_history_audit_v2,
    write_full_history_audit_v2_reports,
)
from app.services.rqdata_ingest.full_history_contract import V1_AUDIT_END  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only full-history Audit V2 engine.")
    parser.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    parser.add_argument(
        "--inventory-dir",
        type=Path,
        default=Path("data/reports/full_history_audit_v2_20260710"),
    )
    parser.add_argument("--audit-end", type=date.fromisoformat, default=V1_AUDIT_END)
    parser.add_argument("--provider-start-evidence", type=Path)
    parser.add_argument("--legacy-report-dir", type=Path)
    parser.add_argument("--product", action="append", default=[])
    parser.add_argument("--db-fetch-size", type=int, default=10_000)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports/full_history_audit_v2_20260710"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve()
    output_dir = args.output_dir if args.output_dir.is_absolute() else project_root / args.output_dir
    try:
        from app.db.session import SessionLocal  # noqa: PLC0415

        with SessionLocal() as session:
            result = run_full_history_audit_v2(
                AuditV2Config(
                    project_root=project_root,
                    inventory_dir=args.inventory_dir,
                    audit_end=args.audit_end,
                    provider_start_evidence=args.provider_start_evidence,
                    legacy_report_dir=args.legacy_report_dir,
                    products=tuple(args.product),
                    require_postgresql=True,
                    db_fetch_size=args.db_fetch_size,
                ),
                session,
            )
            paths = write_full_history_audit_v2_reports(result, output_dir)
    except FileExistsError as exc:
        print(json.dumps({"status": "OUTPUT_EXISTS", "error": str(exc)[:500]}), file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - CLI exposes a fail-closed audit gate.
        secret = os.getenv("DATABASE_URL", "")
        message = str(exc)
        if secret:
            message = message.replace(secret, "[REDACTED_DATABASE_URL]")
        database_error = type(exc).__name__ in {"OperationalError", "InterfaceError", "DatabaseError"}
        if database_error or "ENV_BLOCKED_DB" in message:
            status = "ENV_BLOCKED_DB"
        elif "AUDIT_V2_BLOCKED_" in message:
            status = message.split(":", 1)[0]
        else:
            status = "AUDIT_V2_FAILED"
        print(
            json.dumps({"status": status, "error_type": type(exc).__name__, "error": message[:500]}),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "status": result.summary["status"],
                "data_gate_status": result.summary["data_gate_status"],
                "writes_database": False,
                "writes_parquet": False,
                "calls_rqdata": False,
                "db_snapshot_source": result.summary["db_snapshot_source"],
                "expected_years_dynamic": True,
                "outputs": {name: str(path) for name, path in paths.items()},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.summary["status"] == READY or args.product else 4


if __name__ == "__main__":
    raise SystemExit(main())
