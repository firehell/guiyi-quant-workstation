from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from pathlib import Path
import sys

from sqlalchemy.exc import SQLAlchemyError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.direct_db_baseline_audit import (  # noqa: E402
    AUDIT_FAILED_GATE,
    ENVIRONMENT_FAILED_GATE,
    AuditEnvironmentGateError,
    BLOCKED_GATE,
    DirectDatabaseGateError,
    build_source_lineage,
    collect_direct_database_evidence,
    run_direct_db_audit,
    sanitize_error,
    validate_full_universe_scope,
    write_blocked_environment_package,
    write_success_reports,
)
from app.services.rqdata_ingest.target_coverage_audit import (  # noqa: E402
    DEFAULT_AUDIT_END,
    load_product_windows,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only direct PostgreSQL data-layer baseline audit (no fallback).")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--data-project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--products-file", type=Path)
    parser.add_argument("--product-windows", type=Path)
    parser.add_argument("--audit-end", type=date.fromisoformat, default=DEFAULT_AUDIT_END)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    output_dir = args.output_dir or (
        args.project_root
        / "data"
        / "reports"
        / f"data_layer_direct_db_baseline_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    if output_dir.exists():
        parser.error(f"output directory already exists; refusing to overwrite: {output_dir}")

    source_lineage = build_source_lineage(
        args.project_root,
        [
            "scripts/rqdata_direct_db_baseline_audit.py",
            "services/quant-api/app/services/rqdata_ingest/direct_db_baseline_audit.py",
            "docs/tasks/B-01-DIRECT-DB-FINAL-BASELINE-AUDIT.md",
        ],
    )
    commit = str(source_lineage["git_commit"])
    branch = str(source_lineage["branch"])
    worktree = str(source_lineage["worktree"])
    base_evidence = {
        "gate": BLOCKED_GATE,
        "db_snapshot_source": "unavailable",
        "git_commit": commit,
        "branch": branch,
        "worktree": worktree,
        "project_root": str(args.project_root),
        "code_project_root": str(args.project_root),
        "data_project_root": str(args.data_project_root),
        "git_status_short": source_lineage["git_status_short"],
        "source_fingerprints_sha256": source_lineage["source_fingerprints_sha256"],
        "audit_end": args.audit_end.isoformat(),
        "captured_at": datetime.now(UTC).isoformat(),
        "uses_api_fallback": False,
        "uses_manifest_only": False,
        "write_flags_present": False,
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "writes_quality": False,
        "writes_profile_binding": False,
        "calls_rqdata": False,
    }

    session = None
    database_gate_passed = False
    try:
        if args.project_root.resolve() != PROJECT_ROOT.resolve() or Path(worktree).resolve() != PROJECT_ROOT.resolve():
            raise AuditEnvironmentGateError(
                f"code root mismatch imported={PROJECT_ROOT} requested={args.project_root} git_worktree={worktree}"
            )
        if branch != "codex/b-01-direct-db-baseline":
            raise AuditEnvironmentGateError(f"unexpected B-01 branch: {branch}")

        from app.db.session import SessionLocal  # noqa: PLC0415

        session = SessionLocal()
        environment = collect_direct_database_evidence(
            session,
            project_root=args.project_root,
            data_project_root=args.data_project_root,
            audit_end=args.audit_end,
            git_commit=commit,
            branch=branch,
            worktree=worktree,
        )
        environment.update(
            {
                "git_status_short": source_lineage["git_status_short"],
                "source_fingerprints_sha256": source_lineage["source_fingerprints_sha256"],
            }
        )
        database_gate_passed = True
        products_file = args.products_file or args.data_project_root / "data" / "universe" / "active_products.txt"
        product_windows_file = args.product_windows or args.data_project_root / "data" / "universe" / "product_1d_start_from_2020.csv"
        products = [
            line.strip().lower()
            for line in products_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        canonical_products_file = args.data_project_root / "data" / "universe" / "active_products.txt"
        canonical_products = [
            line.strip().lower()
            for line in canonical_products_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        windows = load_product_windows(product_windows_file, products=products)
        validate_full_universe_scope(
            products=products,
            canonical_products=canonical_products,
            window_products=set(windows),
        )
        environment["scope"] = {
            "products_file": str(products_file),
            "product_windows": str(product_windows_file),
            "product_count": len(products),
        }
        payload = run_direct_db_audit(
            session=session,
            project_root=args.data_project_root,
            products=products,
            product_windows=windows,
            audit_end=args.audit_end,
            environment=environment,
        )
        paths = write_success_reports(output_dir, payload=payload, audit_end=args.audit_end)
    except AuditEnvironmentGateError as exc:
        error = sanitize_error(exc)
        evidence = {**base_evidence, "gate": ENVIRONMENT_FAILED_GATE, "error_type": type(exc).__name__, "db_error": error}
        write_blocked_environment_package(output_dir, evidence=evidence)
        print(ENVIRONMENT_FAILED_GATE)
        print(f"reason={error}")
        print(f"output_dir={output_dir}")
        return 4
    except (DirectDatabaseGateError, SQLAlchemyError) as exc:
        error = sanitize_error(exc)
        gate = AUDIT_FAILED_GATE if database_gate_passed else BLOCKED_GATE
        evidence = {
            **base_evidence,
            "gate": gate,
            "db_snapshot_source": "database" if database_gate_passed else "unavailable",
            "error_type": type(exc).__name__,
            "db_error": error,
        }
        write_blocked_environment_package(output_dir, evidence=evidence)
        print(gate)
        print(f"reason={error}")
        print(f"output_dir={output_dir}")
        return 3 if database_gate_passed else 2
    except Exception as exc:  # noqa: BLE001
        error = sanitize_error(exc)
        evidence = {
            **base_evidence,
            "gate": AUDIT_FAILED_GATE,
            "db_snapshot_source": "database" if database_gate_passed else "unavailable",
            "error_type": type(exc).__name__,
            "db_error": error,
        }
        write_blocked_environment_package(output_dir, evidence=evidence)
        print(AUDIT_FAILED_GATE)
        print(f"reason={error}")
        print(f"output_dir={output_dir}")
        return 3
    finally:
        if session is not None:
            session.rollback()
            session.close()

    print("DIRECT_DB_BASELINE_READY")
    print("db_snapshot_source=database")
    print("writes_database=False writes_parquet=False calls_rqdata=False")
    print(f"output_dir={output_dir}")
    for name, path in paths.items():
        print(f"{name}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
