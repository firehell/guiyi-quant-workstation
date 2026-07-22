from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
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

    from app.services.after_market_deployment import (
        CODE_ONLY_MODE,
        MIGRATION_REVISIONS,
        ROW_COUNT_TABLES,
        SCHEMA_UPGRADE_MODE,
        SOURCE_REVISION,
        TARGET_REVISION,
    )

    if not runtime_root.is_dir():
        raise RuntimeError("runtime_root_unavailable")
    if not schema_backup.is_file():
        raise RuntimeError("schema_backup_missing")
    if not _runtime_tree_is_preparable(runtime_root):
        raise RuntimeError("runtime_worktree_not_clean")
    source_git = _git_identity(source_root)
    runtime_git = _git_identity(runtime_root)
    current_revision = _alembic_revision(session)
    if current_revision == SOURCE_REVISION:
        deployment_mode = SCHEMA_UPGRADE_MODE
        required_migrations = MIGRATION_REVISIONS
        checkpoint_row_count = 0
    elif current_revision == TARGET_REVISION:
        deployment_mode = CODE_ONLY_MODE
        required_migrations = ()
        checkpoint_row_count = int(
            session.execute(text("SELECT count(*) FROM after_market_scheduler_checkpoints")).scalar_one()
        )
    else:
        raise RuntimeError("deployment_database_revision_unsupported")
    migrations: list[dict[str, str]] = []
    versions = source_root / "services" / "quant-api" / "alembic" / "versions"
    for revision in required_migrations:
        matches = sorted(versions.glob(f"{revision}_*.py"))
        if len(matches) != 1:
            raise RuntimeError("deployment_migration_missing")
        path = matches[0]
        migrations.append(
            {
                "revision": revision,
                "path": str(path.resolve()),
                "sha256": _sha256_file(path),
            }
        )
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
            "alembic_revision": current_revision,
        },
        "deployment_mode": deployment_mode,
        "migration_chain": migrations,
        "schema_backup": {
            "path": str(schema_backup.resolve(strict=False)),
            "sha256": _sha256_file(schema_backup),
        },
        "row_counts": {
            table: int(session.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
            for table in ROW_COUNT_TABLES
        },
        "checkpoint_row_count": checkpoint_row_count,
    }


def _runtime_tree_is_preparable(runtime_root: Path) -> bool:
    return _runtime_tree_matches_policy(runtime_root, allow_python_artifacts=True)


def _runtime_tree_is_execution_clean(runtime_root: Path) -> bool:
    return _runtime_tree_matches_policy(runtime_root, allow_python_artifacts=False)


def _runtime_tree_matches_policy(runtime_root: Path, *, allow_python_artifacts: bool) -> bool:
    tracked_status = _git_value(runtime_root, "status", "--porcelain=v1", "--untracked-files=no")
    untracked_executable = _git_value(
        runtime_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        "services",
        "packages",
        "scripts",
        "deploy",
    )
    ignored_executable = _git_value(
        runtime_root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--",
        "services",
        "packages",
        "scripts",
        "deploy",
    )
    unexpected_ignored = [
        path
        for path in ignored_executable.splitlines()
        if path and not _allowed_runtime_generated_path(path, allow_python_artifacts=allow_python_artifacts)
    ]
    return not tracked_status and not untracked_executable and not unexpected_ignored


def _allowed_runtime_generated_path(path: str, *, allow_python_artifacts: bool) -> bool:
    if path.startswith("services/quant-api/.venv/") or path.endswith("/.DS_Store"):
        return True
    return allow_python_artifacts and ("/__pycache__/" in path or path.endswith(".pyc"))


def _purge_runtime_python_artifacts(runtime_root: Path) -> None:
    managed_venv = runtime_root / "services" / "quant-api" / ".venv"
    for relative_root in ("services", "packages", "scripts", "deploy"):
        root = runtime_root / relative_root
        if not root.is_dir():
            continue
        for directory in sorted(root.rglob("__pycache__"), key=lambda path: len(path.parts), reverse=True):
            if not directory.is_relative_to(managed_venv):
                shutil.rmtree(directory)
        for bytecode in root.rglob("*.pyc"):
            if not bytecode.is_relative_to(managed_venv):
                bytecode.unlink()


def _after_market_scheduler_is_loaded() -> bool:
    result = subprocess.run(
        ("launchctl", "print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 113 and f'Could not find service "{LAUNCHD_LABEL}"' in output:
        return False
    raise RuntimeError("after_market_scheduler_probe_failed")


def _deployment_command_environment() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def _execute_confirmed_deployment(
    *,
    packet: dict[str, Any],
    session_factory: Any,
    receipt_out: Path,
    command_runner: Any = subprocess.run,
    runtime_preflight_probe: Any = _runtime_tree_is_preparable,
    runtime_execution_probe: Any = _runtime_tree_is_execution_clean,
    runtime_sanitizer: Any = _purge_runtime_python_artifacts,
    launchd_probe: Any = _after_market_scheduler_is_loaded,
) -> dict[str, Any]:
    from sqlalchemy import text

    from app.services.after_market_deployment import ROW_COUNT_TABLES, TARGET_REVISION

    facts = packet["bound_facts"]
    runtime_root = Path(facts["runtime"]["root"])
    target_commit = str(facts["runtime"]["target_commit"])
    api_root = runtime_root / "services" / "quant-api"
    if not runtime_preflight_probe(runtime_root):
        raise RuntimeError("runtime_worktree_not_clean")
    if launchd_probe():
        raise RuntimeError("after_market_scheduler_already_loaded")
    runtime_sanitizer(runtime_root)
    if not runtime_execution_probe(runtime_root):
        raise RuntimeError("runtime_python_artifact_cleanup_failed")
    bootstrap_commands = [
        ("git", "fetch", "origin", "main"),
        ("git", "switch", "--detach", target_commit),
        ("uv", "venv", "--clear", str(api_root / ".venv")),
        ("uv", "sync", "--frozen", "--project", str(api_root)),
    ]
    for command in bootstrap_commands:
        command_runner(command, cwd=runtime_root if command[0] == "git" else api_root, check=True)
    if not runtime_execution_probe(runtime_root):
        raise RuntimeError("deployment_runtime_post_sync_identity_invalid")
    deployment_mode = str(facts["deployment_mode"])
    if deployment_mode == "schema_upgrade":
        command_runner(
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
            cwd=api_root,
            check=True,
            env=_deployment_command_environment(),
        )
    elif deployment_mode != "code_only":
        raise RuntimeError("deployment_mode_invalid")

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
        if checkpoint_count != facts["checkpoint_row_count"]:
            raise RuntimeError("deployment_checkpoint_row_count_drift")
        session.rollback()

    runtime_git = _git_identity(runtime_root)
    if runtime_git != {
        "commit": target_commit,
        "tracked_status_sha256": EMPTY_SHA256,
    } or not runtime_execution_probe(runtime_root):
        raise RuntimeError("deployment_runtime_post_identity_invalid")
    command_runner(
        ("launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.guiyi.quant-api"),
        cwd=runtime_root,
        check=True,
    )
    after_market_scheduler_loaded = launchd_probe()
    if after_market_scheduler_loaded:
        raise RuntimeError("after_market_scheduler_loaded_during_deployment")
    receipt = {
        "schema_version": 1,
        "task_id": packet["task_id"],
        "status": "completed",
        "gate": "JM_EOD_AUTOMATION_DEPLOYMENT_PASSED",
        "approval_packet_hash": packet["packet_hash"],
        "deployment_mode": deployment_mode,
        "migration_executed": deployment_mode == "schema_upgrade",
        "runtime_commit": target_commit,
        "database_revision": revision,
        "row_counts": row_counts,
        "checkpoint_row_count": checkpoint_count,
        "api_restarted": True,
        "after_market_scheduler_loaded": after_market_scheduler_loaded,
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
        "runtime_worktree_not_clean",
        "after_market_scheduler_already_loaded",
        "after_market_scheduler_loaded_during_deployment",
        "after_market_scheduler_probe_failed",
        "runtime_python_artifact_cleanup_failed",
        "deployment_runtime_post_sync_identity_invalid",
        "tracked_worktree_not_clean",
        "worktree_not_clean",
    }
    if reason.startswith("foundation_receipt_") or reason in allowed:
        return reason
    return type(exc).__name__


if __name__ == "__main__":
    raise SystemExit(main())
