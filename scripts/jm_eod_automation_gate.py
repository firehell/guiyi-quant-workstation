from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from datetime import UTC, datetime


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
LAUNCHD_LABEL = "com.guiyi.quant-after-market-scheduler"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare or verify create-only S6-07 approval packets")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-enable-packet", action="store_true")
    mode.add_argument("--prepare-deploy-packet", action="store_true")
    mode.add_argument("--verify-deploy-packet", action="store_true")
    mode.add_argument("--confirm-deploy", action="store_true")
    parser.add_argument("--foundation-receipt", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--schema-backup", type=Path)
    parser.add_argument("--approval-packet", type=Path)
    parser.add_argument("--approval-hash")
    parser.add_argument("--deployment-receipt-out", type=Path)
    parser.add_argument("--packet-out", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        _validate_arguments(args)
        _require_clean_source(PROJECT_ROOT)
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from app.db.url import normalize_database_url
        from app.services.after_market_automation import AutomationPolicy, build_enable_approval_packet
        from app.services.after_market_deployment import (
            build_deployment_approval_packet,
            validate_deployment_approval_packet,
        )

        database_url = normalize_database_url(
            os.environ.get("DATABASE_URL", "postgresql+psycopg://guiyi@127.0.0.1:5432/guiyi_quant")
        )
        engine = create_engine(database_url, pool_pre_ping=True)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        with SessionLocal() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
            if args.prepare_enable_packet:
                bound_facts = collect_enable_bound_facts(
                    session,
                    source_root=PROJECT_ROOT,
                    runtime_root=args.runtime_root,
                    output_root=args.output_root,
                )
            else:
                bound_facts = collect_deployment_bound_facts(
                    session,
                    source_root=PROJECT_ROOT,
                    runtime_root=args.runtime_root,
                    schema_backup=args.schema_backup,
                )
            session.rollback()
        if args.prepare_enable_packet:
            foundation = _read_object(args.foundation_receipt)
            packet = build_enable_approval_packet(
                bound_facts=bound_facts,
                foundation_receipt=foundation,
                foundation_receipt_path=args.foundation_receipt,
                policy=AutomationPolicy(),
            )
            _write_create_only(args.packet_out, packet)
            status = "approval_required"
        elif args.prepare_deploy_packet:
            packet = build_deployment_approval_packet(bound_facts=bound_facts)
            _write_create_only(args.packet_out, packet)
            status = "approval_required"
        else:
            packet = _read_object(args.approval_packet)
            validate_deployment_approval_packet(
                packet,
                approval_hash=str(args.approval_hash),
                current_bound_facts=bound_facts,
            )
            if args.confirm_deploy:
                receipt_out = args.deployment_receipt_out or (
                    args.runtime_root
                    / ".run"
                    / "approvals"
                    / "s607"
                    / str(packet["bound_facts"]["runtime"]["target_commit"])[:8]
                    / "deployment_receipt.json"
                )
                _execute_confirmed_deployment(
                    packet=packet,
                    session_factory=SessionLocal,
                    receipt_out=receipt_out,
                )
                status = "deployed"
            else:
                status = "verified"
    except Exception as exc:  # noqa: BLE001 - approval preparation emits only a bounded type/reason.
        print(
            json.dumps(
                {"status": "blocked", "error_type": _safe_error_type(exc)},
                ensure_ascii=False,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": status,
                "packet": str((args.packet_out or args.approval_packet).resolve(strict=False)),
                "packet_hash": packet["packet_hash"],
                "writes_authorized": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


def collect_enable_bound_facts(
    session: Any,
    *,
    source_root: Path,
    runtime_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    if not runtime_root.is_dir():
        raise RuntimeError("runtime_root_unavailable")
    if not output_root.is_dir():
        raise RuntimeError("output_root_unavailable")
    _require_clean_source(source_root)
    git = _git_identity(source_root)
    if git["tracked_status_sha256"] != EMPTY_SHA256:
        raise RuntimeError("tracked_worktree_not_clean")
    lock_path = source_root / "services" / "quant-api" / "uv.lock"
    if not lock_path.is_file():
        raise RuntimeError("dependency_lock_missing")
    url = session.get_bind().url
    return {
        "git": git,
        "dependency_lock_sha256": _sha256_file(lock_path),
        "database": {
            "driver": url.drivername,
            "host": url.host,
            "port": url.port,
            "database": url.database,
            "alembic_revision": _alembic_revision(session),
        },
        "runtime_root": str(runtime_root.resolve(strict=False)),
        "output_root": str(output_root.resolve(strict=False)),
        "output_device": output_root.stat().st_dev,
        "launchd_label": LAUNCHD_LABEL,
    }


def _git_identity(project_root: Path) -> dict[str, str]:
    status = _git_value(project_root, "status", "--porcelain=v1", "--untracked-files=no")
    return {
        "commit": _git_value(project_root, "rev-parse", "HEAD"),
        "tracked_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
    }


def collect_deployment_bound_facts(
    session: Any,
    *,
    source_root: Path,
    runtime_root: Path,
    schema_backup: Path,
) -> dict[str, Any]:
    from sqlalchemy import text

    from app.services.after_market_deployment import MIGRATION_REVISIONS, ROW_COUNT_TABLES

    if not runtime_root.is_dir():
        raise RuntimeError("runtime_root_unavailable")
    if not schema_backup.is_file():
        raise RuntimeError("schema_backup_missing")
    source_git = _git_identity(source_root)
    runtime_git = _git_identity(runtime_root)
    migrations: list[dict[str, str]] = []
    versions = source_root / "services" / "quant-api" / "alembic" / "versions"
    for revision in MIGRATION_REVISIONS:
        matches = sorted(versions.glob(f"{revision}_*.py"))
        if len(matches) != 1:
            raise RuntimeError("deployment_migration_missing")
        path = matches[0]
        migrations.append({"revision": revision, "path": str(path.resolve()), "sha256": _sha256_file(path)})
    url = session.get_bind().url
    return {
        "source_git": source_git,
        "runtime": {
            "root": str(runtime_root.resolve(strict=False)),
            "current_commit": runtime_git["commit"],
            "target_commit": source_git["commit"],
            "tracked_status_sha256": runtime_git["tracked_status_sha256"],
        },
        "database": {
            "driver": url.drivername,
            "host": url.host,
            "port": url.port,
            "database": url.database,
            "alembic_revision": _alembic_revision(session),
        },
        "migration_chain": migrations,
        "schema_backup": {
            "path": str(schema_backup.resolve(strict=False)),
            "sha256": _sha256_file(schema_backup),
        },
        "row_counts": {
            table: int(session.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
            for table in ROW_COUNT_TABLES
        },
    }


def _execute_confirmed_deployment(
    *,
    packet: dict[str, Any],
    session_factory: Any,
    receipt_out: Path,
    command_runner: Any = subprocess.run,
) -> dict[str, Any]:
    from sqlalchemy import text

    from app.services.after_market_deployment import ROW_COUNT_TABLES, TARGET_REVISION

    facts = packet["bound_facts"]
    runtime_root = Path(facts["runtime"]["root"])
    target_commit = str(facts["runtime"]["target_commit"])
    api_root = runtime_root / "services" / "quant-api"
    commands = (
        ("git", "fetch", "origin", "main"),
        ("git", "switch", "--detach", target_commit),
        ("uv", "sync", "--frozen", "--project", str(api_root)),
        (
            "uv",
            "run",
            "--frozen",
            "--project",
            str(api_root),
            "alembic",
            "upgrade",
            TARGET_REVISION,
        ),
    )
    for command in commands:
        command_runner(command, cwd=runtime_root if command[0] == "git" else api_root, check=True)

    with session_factory() as session:
        revision = _alembic_revision(session)
        if revision != TARGET_REVISION:
            raise RuntimeError("deployment_post_revision_invalid")
        row_counts = {
            table: int(session.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
            for table in ROW_COUNT_TABLES
        }
        if row_counts != facts["row_counts"]:
            raise RuntimeError("deployment_row_count_drift")
        checkpoint_count = int(
            session.execute(text("SELECT count(*) FROM after_market_scheduler_checkpoints")).scalar_one()
        )
        if checkpoint_count != 0:
            raise RuntimeError("deployment_checkpoint_not_empty")
        session.rollback()

    runtime_git = _git_identity(runtime_root)
    if runtime_git != {"commit": target_commit, "tracked_status_sha256": EMPTY_SHA256}:
        raise RuntimeError("deployment_runtime_post_identity_invalid")
    command_runner(
        ("launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.guiyi.quant-api"),
        cwd=runtime_root,
        check=True,
    )
    receipt = {
        "schema_version": 1,
        "task_id": packet["task_id"],
        "status": "completed",
        "gate": "JM_EOD_AUTOMATION_DEPLOYMENT_PASSED",
        "approval_packet_hash": packet["packet_hash"],
        "runtime_commit": target_commit,
        "database_revision": revision,
        "row_counts": row_counts,
        "checkpoint_row_count": checkpoint_count,
        "api_restarted": True,
        "after_market_scheduler_loaded": False,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    _write_create_only(receipt_out, receipt)
    return receipt


def _alembic_revision(session: Any) -> str:
    from sqlalchemy import text

    revisions = session.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars().all()
    if len(revisions) != 1:
        raise RuntimeError("database_revision_invalid")
    return str(revisions[0])


def _validate_arguments(args: argparse.Namespace) -> None:
    required: tuple[str, ...]
    if args.prepare_enable_packet:
        required = ("foundation_receipt", "runtime_root", "output_root", "packet_out")
    elif args.prepare_deploy_packet:
        required = ("runtime_root", "schema_backup", "packet_out")
    else:
        required = ("runtime_root", "schema_backup", "approval_packet", "approval_hash")
    if any(getattr(args, name) in (None, "") for name in required):
        raise RuntimeError("required_argument_missing")


def _require_clean_source(project_root: Path) -> None:
    if _git_value(project_root, "status", "--porcelain=v1", "--untracked-files=normal"):
        raise RuntimeError("worktree_not_clean")


def _git_value(project_root: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError("foundation_receipt_missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("foundation_receipt_invalid")
    return payload


def _write_create_only(path: Path, payload: dict[str, Any]) -> None:
    output = path.resolve(strict=False)
    if output.exists():
        raise FileExistsError("approval_packet_already_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _safe_error_type(exc: Exception) -> str:
    reason = str(exc).split(":", 1)[0]
    allowed = {
        "approval_packet_already_exists",
        "dependency_lock_missing",
        "foundation_receipt_incomplete",
        "foundation_receipt_invalid",
        "foundation_receipt_missing",
        "jm_archive_passed_receipt_required",
        "output_root_unavailable",
        "runtime_root_unavailable",
        "tracked_worktree_not_clean",
        "worktree_not_clean",
    }
    if reason.startswith("foundation_receipt_") or reason in allowed:
        return reason
    return type(exc).__name__


if __name__ == "__main__":
    raise SystemExit(main())
