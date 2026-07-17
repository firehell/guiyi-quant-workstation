from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from sqlalchemy import text

SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = SCRIPT_PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.full_history_physical_inventory import (  # noqa: E402
    AUDIT_END,
    READY,
    InventoryConfig,
    run_full_history_physical_inventory,
    write_inventory_reports,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only inventory of canonical Parquet, manifests, processed summaries, and direct PostgreSQL.",
    )
    parser.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    parser.add_argument("--audit-end", type=date.fromisoformat, default=AUDIT_END)
    parser.add_argument("--scan-mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--product", action="append", default=[])
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SCRIPT_PROJECT_ROOT / "data/reports/full_history_audit_v2_20260710",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve()
    output_dir = args.output_dir.resolve(strict=False)
    if output_dir.exists():
        print(f"OUTPUT_EXISTS: {output_dir}", file=sys.stderr)
        return 3

    # Load only the selected data environment. Values are never printed.
    load_dotenv(project_root / ".env", override=False)
    try:
        from app.db.session import SessionLocal  # noqa: PLC0415

        with SessionLocal() as session:
            session.execute(text("select 1"))
            result = run_full_history_physical_inventory(
                InventoryConfig(
                    project_root=project_root,
                    audit_end=args.audit_end,
                    scan_mode=args.scan_mode,
                    products=tuple(args.product),
                    max_workers=args.max_workers,
                    require_postgresql=True,
                ),
                session,
            )
    except Exception as exc:  # noqa: BLE001 - CLI must expose a fail-closed environment gate.
        message = str(exc).replace(os.getenv("DATABASE_URL", "__not_set__"), "[REDACTED_DATABASE_URL]")
        database_error = type(exc).__name__ in {"OperationalError", "InterfaceError", "DatabaseError"}
        status = (
            "ENV_BLOCKED_DB"
            if database_error or "DB" in message.upper() or "POSTGRES" in message.upper()
            else "INVENTORY_FAILED"
        )
        print(json.dumps({"status": status, "error_type": type(exc).__name__, "error": message[:500]}), file=sys.stderr)
        return 2

    paths = write_inventory_reports(result, output_dir)
    print(
        json.dumps(
            {
                "status": result.summary["status"],
                "writes_database": False,
                "writes_parquet": False,
                "calls_rqdata": False,
                "db_snapshot_source": result.summary["db_snapshot_source"],
                "expected_matrix_generated": False,
                "outputs": {name: str(path) for name, path in paths.items()},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.summary["status"] == READY or args.product else 4


if __name__ == "__main__":
    raise SystemExit(main())
