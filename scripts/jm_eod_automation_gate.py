"""S6-07 EOD 自动化 create-only 批准包：prepare / verify / confirm-deploy。

写入边界（本脚本主路径）：
- DB 采集 bound facts 时使用 **READ ONLY** 事务并 rollback
- 批准包文件 **create-only**（禁止覆盖）
- ``--confirm-deploy`` 才会推进受控部署（launchd / runtime），仍受 hash 校验约束

模式互斥：``--prepare-enable-packet`` / ``--prepare-deploy-packet`` /
``--verify-deploy-packet`` / ``--confirm-deploy``。
核心策略在 ``app.services.after_market_automation`` 与 ``after_market_deployment``。
要求源码树干净（``_require_clean_source``）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
from typing import Any
import urllib.request
from datetime import UTC, datetime


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.s607_code_rebind import (  # noqa: E402
    collect_after_market_health as _code_rebind_health,
    collect_launchd_identity as _code_rebind_launchd_identity,
    execute_confirmed_code_rebind as _execute_confirmed_code_rebind,
    launchd_binding as _code_rebind_launchd_binding,
)

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
LAUNCHD_LABEL = "com.guiyi.quant-after-market-scheduler"
API_LAUNCHD_LABEL = "com.guiyi.quant-api"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """互斥模式 + foundation/runtime/approval 路径参数。"""
    parser = argparse.ArgumentParser(description="Prepare or verify create-only S6-07 approval packets")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-enable-packet", action="store_true")
    mode.add_argument("--prepare-deploy-packet", action="store_true")
    mode.add_argument("--verify-deploy-packet", action="store_true")
    mode.add_argument("--confirm-deploy", action="store_true")
    mode.add_argument("--prepare-code-rebind-packet", action="store_true")
    mode.add_argument("--verify-code-rebind-packet", action="store_true")
    mode.add_argument("--confirm-code-rebind", action="store_true")
    parser.add_argument("--foundation-receipt", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--schema-backup", type=Path)
    parser.add_argument("--checkpoint-recovery-receipt", type=Path)
    parser.add_argument("--checkpoint-recovery-outage-snapshot", type=Path)
    parser.add_argument("--checkpoint-recovery-failed-packet", type=Path)
    parser.add_argument("--approval-packet", type=Path)
    parser.add_argument("--approval-hash")
    parser.add_argument("--deployment-receipt-out", type=Path)
    parser.add_argument("--packet-out", type=Path)
    parser.add_argument("--deployment-packet", type=Path)
    parser.add_argument("--target-runtime-commit")
    parser.add_argument("--s6-07-final-receipt", type=Path)
    parser.add_argument("--database-recovery-receipt", type=Path)
    parser.add_argument("--deployment-receipt", type=Path)
    parser.add_argument("--authorization-parent", type=Path)
    parser.add_argument("--rebind-receipt-out", type=Path)
    parser.add_argument(
        "--bind-disabled-precondition",
        action="store_true",
        help=(
            "bind the future fail-closed disabled scheduler state while "
            "leaving the current service unchanged"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """只读绑事实 → 生成/校验批准包；confirm-deploy 时执行受控部署。"""
    args = parse_args(argv)
    try:
        _validate_arguments(args)
        if (
            args.prepare_code_rebind_packet
            or args.verify_code_rebind_packet
            or args.confirm_code_rebind
        ):
            return _run_code_rebind(args)
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
                    checkpoint_recovery_receipt=args.checkpoint_recovery_receipt,
                    checkpoint_recovery_outage_snapshot=args.checkpoint_recovery_outage_snapshot,
                    checkpoint_recovery_failed_packet=args.checkpoint_recovery_failed_packet,
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


def _run_code_rebind(args: argparse.Namespace) -> int:
    """Prepare/verify the no-archive S6-07 code-only rebind packet."""

    from app.services.htdy_s6_08_approval_artifacts import (
        build_s6_07_code_rebind_packet,
        verify_s6_07_code_rebind_packet,
        write_json_create_only,
    )

    deployment = _read_object(args.deployment_packet)
    receipt = {
        "path": str(args.s6_07_final_receipt.resolve(strict=False)),
        "sha256": _sha256_file(args.s6_07_final_receipt),
    }
    recovery_receipt = _database_recovery_receipt_identity(
        args.database_recovery_receipt
    )
    launchd, health = _code_rebind_preconditions(
        launchd=_code_rebind_launchd_binding(
            _code_rebind_launchd_identity(args.runtime_root)
        ),
        health=_code_rebind_health(),
        bind_disabled=(
            args.prepare_code_rebind_packet
            and args.bind_disabled_precondition
        ),
    )
    rebind_receipt = _code_rebind_receipt_identity(
        args.rebind_receipt_out,
        deployment_packet=deployment,
    )
    execution_receipt: dict[str, Any] | None = None
    if args.prepare_code_rebind_packet:
        packet = build_s6_07_code_rebind_packet(
            deployment_packet=deployment,
            target_runtime_commit=str(args.target_runtime_commit),
            s6_07_final_receipt=receipt,
            database_recovery_receipt=recovery_receipt,
            after_market_launchd=launchd,
            after_market_health=health,
            rebind_receipt=rebind_receipt,
        )
        write_json_create_only(args.packet_out, packet)
        status = "approval_required"
        path = args.packet_out
    else:
        packet = _read_object(args.approval_packet)
        verify_s6_07_code_rebind_packet(
            packet,
            approval_hash=str(args.approval_hash),
            deployment_packet=deployment,
            current_s6_07_final_receipt=receipt,
            current_database_recovery_receipt=recovery_receipt,
            current_after_market_launchd=launchd,
            current_after_market_health=health,
            expected_rebind_receipt=rebind_receipt,
        )
        if args.confirm_code_rebind:
            expected_deployment_receipt = Path(
                str(
                    _deployment_output_scope(deployment).get(
                        "deployment_receipt_path"
                    )
                    or _deployment_output_scope(deployment).get(
                        "receipt_path"
                    )
                    or ""
                )
            )
            if (
                args.deployment_receipt.resolve(strict=False)
                != expected_deployment_receipt
            ):
                raise RuntimeError("deployment_receipt_path_mismatch")
            deployment_receipt = _read_object(
                args.deployment_receipt
            )
            authorization_parent = (
                _read_object(args.authorization_parent)
                if args.authorization_parent is not None
                else None
            )
            if deployment.get("packet_type") not in {
                "s6_10_schema_v5_code_only_deployment",
                "s6_10_schema_v6_code_only_deployment",
                "s6_10_schema_v7_code_only_deployment",
            }:
                _load_bound_runtime_environment(deployment)
            execution_receipt = _execute_confirmed_code_rebind(
                packet=packet,
                deployment_receipt=deployment_receipt,
                authorization_parent=authorization_parent,
                runtime_root=args.runtime_root,
                receipt_out=args.rebind_receipt_out,
            )
            status = "completed"
        else:
            status = "verified"
        path = args.approval_packet
    print(
        json.dumps(
            {
                "status": status,
                "packet": str(path.resolve(strict=False)),
                "packet_hash": packet["packet_hash"],
                "writes_authorized": False,
                "reruns_archive": False,
                "receipt": (
                    str(args.rebind_receipt_out.resolve(strict=False))
                    if execution_receipt is not None
                    else None
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _code_rebind_preconditions(
    *,
    launchd: dict[str, Any],
    health: dict[str, Any],
    bind_disabled: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not bind_disabled:
        return launchd, health
    return (
        {**launchd, "loaded": False},
        {"status": "disabled", "enabled": False},
    )


def _load_bound_runtime_environment(
    deployment_packet: dict[str, Any],
) -> None:
    from dotenv import load_dotenv
    from io import StringIO

    binding = (
        deployment_packet.get("bound_facts") or {}
    ).get("runtime_environment")
    if not isinstance(binding, dict):
        raise RuntimeError("runtime_environment_drift")
    path = Path(str(binding.get("path") or ""))
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as exc:
        raise RuntimeError("runtime_environment_drift") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    raw = b"".join(chunks)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or hashlib.sha256(raw).hexdigest()
        != binding.get("file_sha256")
        or int(metadata.st_dev) != binding.get("device")
        or int(metadata.st_ino) != binding.get("inode")
        or int(metadata.st_size) != binding.get("size")
    ):
        raise RuntimeError("runtime_environment_drift")
    try:
        stream = StringIO(raw.decode("utf-8"))
    except UnicodeError as exc:
        raise RuntimeError("runtime_environment_drift") from exc
    load_dotenv(stream=stream, override=True, interpolate=False)
    flags = binding.get("flags")
    if (
        not isinstance(flags, dict)
        or not os.environ.get("DATABASE_URL")
        or {
            name: _runtime_env_flag(name)
            for name in (
                "GUIYI_LIVE_RUNTIME_ENABLED",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
                "GUIYI_WECHAT_AUTOSEND_ENABLED",
            )
        }
        != flags
    ):
        raise RuntimeError("runtime_environment_drift")


def _runtime_env_flag(name: str) -> bool:
    value = os.environ.get(name, "").lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError("runtime_environment_drift")


def _code_rebind_receipt_identity(
    path: Path,
    *,
    deployment_packet: dict[str, Any],
) -> dict[str, Any]:
    output_scope = _deployment_output_scope(deployment_packet)
    if not isinstance(output_scope, dict):
        raise RuntimeError("s6_07_rebind_receipt_invalid")
    output_root = Path(str(output_scope.get("root") or ""))
    resolved = path.resolve(strict=False)
    if (
        not output_root.is_dir()
        or output_root.is_symlink()
        or resolved.parent != output_root.resolve(strict=True)
        or resolved.name != "s6_07_rebind_receipt.json"
        or resolved.exists()
        or resolved.parent.is_symlink()
    ):
        raise RuntimeError("s6_07_rebind_receipt_invalid")
    parent = resolved.parent.stat()
    if int(parent.st_dev) != int(output_scope.get("root_device", -1)):
        raise RuntimeError("s6_07_rebind_receipt_invalid")
    return {
        "path": str(resolved),
        "parent_device": int(parent.st_dev),
        "parent_inode": int(parent.st_ino),
    }


def _deployment_output_scope(
    deployment_packet: dict[str, Any],
) -> dict[str, Any]:
    if deployment_packet.get("packet_type") in {
        "s6_10_schema_v5_code_only_deployment",
        "s6_10_schema_v6_code_only_deployment",
        "s6_10_schema_v7_code_only_deployment",
    }:
        value = deployment_packet.get("output_scope")
    else:
        value = (
            deployment_packet.get("bound_facts") or {}
        ).get("output_scope")
    return value if isinstance(value, dict) else {}


def collect_enable_bound_facts(
    session: Any,
    *,
    source_root: Path,
    runtime_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    """采集 enable 批准包绑定事实：干净 git、uv.lock、DB 身份、runtime/output 路径。"""
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
    checkpoint_recovery_receipt: Path | None = None,
    checkpoint_recovery_outage_snapshot: Path | None = None,
    checkpoint_recovery_failed_packet: Path | None = None,
) -> dict[str, Any]:
    """采集 deploy 批准包绑定事实（schema 备份、行数、migration 修订等）。"""
    from sqlalchemy import text

    from app.services.after_market_deployment import (
        CHECKPOINT_RECOVERY_MODE,
        CHECKPOINT_RECOVERY_ONLY_MODE,
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
    recovery_paths = (
        checkpoint_recovery_receipt,
        checkpoint_recovery_outage_snapshot,
        checkpoint_recovery_failed_packet,
    )
    if any(recovery_paths) and not all(recovery_paths):
        raise RuntimeError("checkpoint_recovery_evidence_incomplete")
    checkpoint_recovery: dict[str, Any] | None = None
    if current_revision == SOURCE_REVISION:
        if all(recovery_paths):
            from app.services.after_market_checkpoint_recovery import (
                collect_checkpoint_recovery_bound_facts,
            )

            deployment_mode = CHECKPOINT_RECOVERY_MODE
            checkpoint_recovery = collect_checkpoint_recovery_bound_facts(
                session,
                receipt_path=checkpoint_recovery_receipt,
                outage_path=checkpoint_recovery_outage_snapshot,
                failed_packet_path=checkpoint_recovery_failed_packet,
            )
        else:
            deployment_mode = SCHEMA_UPGRADE_MODE
        required_migrations = MIGRATION_REVISIONS
        checkpoint_row_count = 0
    elif current_revision == TARGET_REVISION:
        required_migrations = ()
        checkpoint_row_count = int(
            session.execute(text("SELECT count(*) FROM after_market_scheduler_checkpoints")).scalar_one()
        )
        if all(recovery_paths):
            if checkpoint_row_count != 0:
                raise RuntimeError("checkpoint_recovery_checkpoint_not_empty")
            from app.services.after_market_checkpoint_recovery import (
                collect_checkpoint_recovery_bound_facts,
            )

            deployment_mode = CHECKPOINT_RECOVERY_ONLY_MODE
            checkpoint_recovery = collect_checkpoint_recovery_bound_facts(
                session,
                receipt_path=checkpoint_recovery_receipt,
                outage_path=checkpoint_recovery_outage_snapshot,
                failed_packet_path=checkpoint_recovery_failed_packet,
            )
        else:
            deployment_mode = CODE_ONLY_MODE
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
    facts = {
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
        "api_runner": _collect_api_runner_bound_facts(
            source_root=source_root,
            runtime_root=runtime_root,
        ),
    }
    if checkpoint_recovery is not None:
        facts["checkpoint_recovery"] = checkpoint_recovery
    return facts


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
    try:
        result = subprocess.run(
            ("launchctl", "print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("after_market_scheduler_probe_failed") from exc
    if result.returncode == 0:
        return True
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 113 and f'Could not find service "{LAUNCHD_LABEL}"' in output:
        return False
    raise RuntimeError("after_market_scheduler_probe_failed")


def _deployment_command_environment() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def _collect_api_runner_bound_facts(*, source_root: Path, runtime_root: Path) -> dict[str, Any]:
    source_relative_path = Path("scripts/run-local-service.sh")
    source = source_root / source_relative_path
    runtime_dir = Path(
        os.environ.get(
            "GUIYI_RUNTIME_DIR",
            str(Path.home() / "Library" / "Application Support" / "GuiyiQuant"),
        )
    )
    target = runtime_dir / "run-local-service.sh"
    agent_dir = Path(
        os.environ.get(
            "GUIYI_LAUNCH_AGENT_DIR",
            str(Path.home() / "Library" / "LaunchAgents"),
        )
    )
    plist_path = agent_dir / f"{API_LAUNCHD_LABEL}.plist"
    if not source.is_file() or not target.is_file() or not plist_path.is_file():
        raise RuntimeError("api_runner_refresh_failed")
    try:
        with plist_path.open("rb") as handle:
            plist = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise RuntimeError("api_runner_refresh_failed") from exc
    arguments = plist.get("ProgramArguments")
    project_root = (plist.get("EnvironmentVariables") or {}).get("GUIYI_PROJECT_ROOT")
    expected_arguments = ["/bin/bash", str(target.resolve()), "api"]
    if (
        plist.get("Label") != API_LAUNCHD_LABEL
        or arguments != expected_arguments
        or project_root != str(runtime_root.resolve())
    ):
        raise RuntimeError("api_runner_launchd_contract_invalid")
    return {
        "source_relative_path": str(source_relative_path),
        "source_sha256": _sha256_file(source),
        "destination_path": str(target.resolve()),
        "destination_sha256": _sha256_file(target),
        "launchd_plist_path": str(plist_path.resolve()),
        "launchd_plist_sha256": _sha256_file(plist_path),
        "launchd_label": API_LAUNCHD_LABEL,
        "launchd_program_arguments": arguments,
        "launchd_project_root": project_root,
    }


def _refresh_api_runner(runtime_root: Path, bound_facts: dict[str, Any]) -> None:
    source = runtime_root / str(bound_facts.get("source_relative_path") or "")
    target = Path(str(bound_facts.get("destination_path") or ""))
    plist_path = Path(str(bound_facts.get("launchd_plist_path") or ""))
    if (
        not source.is_file()
        or not target.is_file()
        or not plist_path.is_file()
        or _sha256_file(source) != bound_facts.get("source_sha256")
        or _sha256_file(target) != bound_facts.get("destination_sha256")
        or _sha256_file(plist_path) != bound_facts.get("launchd_plist_sha256")
        or bound_facts.get("launchd_label") != API_LAUNCHD_LABEL
        or bound_facts.get("launchd_project_root") != str(runtime_root.resolve())
        or bound_facts.get("launchd_program_arguments")
        != ["/bin/bash", str(target.resolve()), "api"]
    ):
        raise RuntimeError("api_runner_bound_fact_drift")
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(0o700)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    if _sha256_file(target) != bound_facts["source_sha256"]:
        raise RuntimeError("api_runner_refresh_failed")


def _listener_belongs_to_service(service_pid: int) -> bool:
    listeners = subprocess.run(
        ("lsof", "-nP", "-iTCP:8000", "-sTCP:LISTEN", "-t"),
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    if listeners.returncode != 0:
        return False
    process_table = subprocess.run(
        ("ps", "-axo", "pid=,ppid="),
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    if process_table.returncode != 0:
        return False
    parents: dict[int, int] = {}
    for line in process_table.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and all(field.isdigit() for field in fields):
            parents[int(fields[0])] = int(fields[1])
    for value in listeners.stdout.splitlines():
        if not value.strip().isdigit():
            continue
        pid = int(value.strip())
        for _ in range(32):
            if pid == service_pid:
                return True
            pid = parents.get(pid, 0)
            if pid <= 1:
                break
    return False


def _api_service_pid() -> int | None:
    try:
        service = subprocess.run(
            ("launchctl", "print", f"gui/{os.getuid()}/{API_LAUNCHD_LABEL}"),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("api_service_probe_failed") from exc
    if service.returncode != 0:
        return None
    match = re.search(r"^\s*pid = (\d+)\s*$", service.stdout, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def _launchd_service_is_absent(result: Any, label: str) -> bool:
    output = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}"
    return result.returncode == 113 and f'Could not find service "{label}"' in output


def _launchd_bootout_is_absent(result: Any) -> bool:
    output = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}"
    return result.returncode == 3 and "Boot-out failed: 3: No such process" in output


def _reload_bound_api_service(
    bound_facts: dict[str, Any],
    *,
    command_runner: Any = subprocess.run,
) -> None:
    label = str(bound_facts.get("launchd_label") or "")
    plist_path = Path(str(bound_facts.get("launchd_plist_path") or ""))
    runner_path = Path(str(bound_facts.get("destination_path") or ""))
    try:
        with plist_path.open("rb") as handle:
            plist = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise RuntimeError("api_reload_bound_fact_drift") from exc
    if (
        label != API_LAUNCHD_LABEL
        or not plist_path.is_file()
        or not runner_path.is_file()
        or _sha256_file(plist_path) != bound_facts.get("launchd_plist_sha256")
        or _sha256_file(runner_path) != bound_facts.get("source_sha256")
        or plist.get("Label") != API_LAUNCHD_LABEL
        or plist.get("ProgramArguments") != bound_facts.get("launchd_program_arguments")
        or (plist.get("EnvironmentVariables") or {}).get("GUIYI_PROJECT_ROOT")
        != bound_facts.get("launchd_project_root")
    ):
        raise RuntimeError("api_reload_bound_fact_drift")
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{label}"
    bootout = command_runner(
        ("launchctl", "bootout", service),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if bootout.returncode != 0 and not _launchd_bootout_is_absent(bootout):
        raise RuntimeError("api_bootout_failed")
    for attempt in range(5):
        probe = command_runner(
            ("launchctl", "print", service),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if _launchd_service_is_absent(probe, label):
            break
        if probe.returncode != 0:
            raise RuntimeError("api_service_probe_failed")
        if attempt == 4:
            raise RuntimeError("api_bootout_timeout")
        time.sleep(1)
    enable = command_runner(
        ("launchctl", "enable", service),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if enable.returncode != 0:
        raise RuntimeError("api_enable_failed")
    bootstrap = command_runner(
        ("launchctl", "bootstrap", domain, str(plist_path)),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if bootstrap.returncode != 0:
        raise RuntimeError("api_bootstrap_failed")


def _api_health_is_ready(bound_facts: dict[str, Any], *, previous_pid: int | None) -> bool:
    try:
        service = subprocess.run(
            ("launchctl", "print", f"gui/{os.getuid()}/{API_LAUNCHD_LABEL}"),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        match = re.search(r"^\s*pid = (\d+)\s*$", service.stdout, flags=re.MULTILINE)
        current_pid = int(match.group(1)) if match else None
        destination_pattern = rf"^\s*{re.escape(str(bound_facts['destination_path']))}\s*$"
        project_root_pattern = (
            rf"^\s*GUIYI_PROJECT_ROOT => {re.escape(str(bound_facts['launchd_project_root']))}\s*$"
        )
        if (
            service.returncode != 0
            or "state = running" not in service.stdout
            or current_pid is None
            or (previous_pid is not None and current_pid == previous_pid)
            or re.search(destination_pattern, service.stdout, flags=re.MULTILINE) is None
            or re.search(project_root_pattern, service.stdout, flags=re.MULTILINE) is None
            or not _listener_belongs_to_service(current_pid)
        ):
            return False
    except (OSError, subprocess.TimeoutExpired):
        return False
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/runtime/health", timeout=2) as response:
            payload = json.load(response)
    except (OSError, TimeoutError, ValueError):
        return False
    component = (payload.get("components") or {}).get("after_market_scheduler")
    return (
        isinstance(component, dict)
        and component.get("status") == "disabled"
        and component.get("enabled") is False
    )


def _wait_for_api_health(
    bound_facts: dict[str, Any],
    previous_pid: int | None,
    *,
    timeout_seconds: float = 60,
    interval_seconds: float = 1,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _api_health_is_ready(bound_facts, previous_pid=previous_pid):
            return True
        time.sleep(interval_seconds)
    return False


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
    api_runner_refresher: Any = _refresh_api_runner,
    api_pid_probe: Any = _api_service_pid,
    api_service_reloader: Any = _reload_bound_api_service,
    api_readiness_probe: Any = _wait_for_api_health,
    checkpoint_recovery_restorer: Any = None,
    checkpoint_recovery_verifier: Any = None,
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
    recovery_mode = deployment_mode in {
        "schema_upgrade_with_checkpoint_recovery",
        "checkpoint_recovery_only",
    }
    if deployment_mode in {"schema_upgrade", "schema_upgrade_with_checkpoint_recovery"}:
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
    elif deployment_mode not in {"code_only", "checkpoint_recovery_only"}:
        raise RuntimeError("deployment_mode_invalid")

    with session_factory() as session:
        revision = _alembic_revision(session)
        if revision != TARGET_REVISION:
            raise RuntimeError("deployment_post_revision_invalid")
        if recovery_mode:
            if checkpoint_recovery_restorer is None:
                from app.services.after_market_checkpoint_recovery import (
                    restore_checkpoint_from_recovery,
                )

                checkpoint_recovery_restorer = restore_checkpoint_from_recovery
            checkpoint_recovery_restorer(session, facts["checkpoint_recovery"])
            session.commit()
        row_counts = {
            table: int(session.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
            for table in ROW_COUNT_TABLES
        }
        if row_counts != facts["row_counts"]:
            raise RuntimeError("deployment_row_count_drift")
        checkpoint_count = int(
            session.execute(text("SELECT count(*) FROM after_market_scheduler_checkpoints")).scalar_one()
        )
        expected_checkpoint_count = 1 if recovery_mode else facts["checkpoint_row_count"]
        if checkpoint_count != expected_checkpoint_count:
            raise RuntimeError("deployment_checkpoint_row_count_drift")
        if recovery_mode:
            if checkpoint_recovery_verifier is None:
                from app.services.after_market_checkpoint_recovery import (
                    verify_checkpoint_matches_recovery,
                )

                checkpoint_recovery_verifier = verify_checkpoint_matches_recovery
            if not checkpoint_recovery_verifier(session, facts["checkpoint_recovery"]):
                raise RuntimeError("deployment_checkpoint_recovery_verify_failed")
        session.rollback()

    runtime_git = _git_identity(runtime_root)
    if runtime_git != {
        "commit": target_commit,
        "tracked_status_sha256": EMPTY_SHA256,
    } or not runtime_execution_probe(runtime_root):
        raise RuntimeError("deployment_runtime_post_identity_invalid")
    api_runner_facts = facts["api_runner"]
    previous_api_pid = api_pid_probe()
    api_runner_refresher(runtime_root, api_runner_facts)
    api_service_reloader(api_runner_facts)
    if not api_readiness_probe(api_runner_facts, previous_api_pid):
        raise RuntimeError("api_health_check_failed")
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
        "migration_executed": deployment_mode in {
            "schema_upgrade",
            "schema_upgrade_with_checkpoint_recovery",
        },
        "checkpoint_recovery_executed": recovery_mode,
        "runtime_commit": target_commit,
        "database_revision": revision,
        "row_counts": row_counts,
        "checkpoint_row_count": checkpoint_count,
        "shared_python_runner": {
            "destination_path": api_runner_facts["destination_path"],
            "installed_sha256": api_runner_facts["source_sha256"],
            "other_labels_restarted": False,
        },
        "api_restarted": True,
        "api_reload_mode": "bound_plist_bootout_bootstrap",
        "api_health_verified": True,
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
    if args.prepare_code_rebind_packet:
        required = (
            "deployment_packet",
            "target_runtime_commit",
            "s6_07_final_receipt",
            "database_recovery_receipt",
            "runtime_root",
            "rebind_receipt_out",
            "packet_out",
        )
    elif args.verify_code_rebind_packet:
        required = (
            "deployment_packet",
            "s6_07_final_receipt",
            "database_recovery_receipt",
            "runtime_root",
            "rebind_receipt_out",
            "approval_packet",
            "approval_hash",
        )
    elif args.confirm_code_rebind:
        required = (
            "deployment_packet",
            "deployment_receipt",
            "s6_07_final_receipt",
            "database_recovery_receipt",
            "runtime_root",
            "rebind_receipt_out",
            "approval_packet",
            "approval_hash",
        )
    elif args.prepare_enable_packet:
        required = ("foundation_receipt", "runtime_root", "output_root", "packet_out")
    elif args.prepare_deploy_packet:
        required = ("runtime_root", "schema_backup", "packet_out")
    else:
        required = ("runtime_root", "schema_backup", "approval_packet", "approval_hash")
    if any(getattr(args, name) in (None, "") for name in required):
        raise RuntimeError("required_argument_missing")
    recovery_arguments = (
        args.checkpoint_recovery_receipt,
        args.checkpoint_recovery_outage_snapshot,
        args.checkpoint_recovery_failed_packet,
    )
    if any(recovery_arguments) and not all(recovery_arguments):
        raise RuntimeError("checkpoint_recovery_evidence_incomplete")


def _require_clean_source(project_root: Path) -> None:
    """要求工作树干净（含 untracked），否则拒绝生成/校验批准包。"""
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


def _database_recovery_receipt_identity(
    path: Path,
) -> dict[str, Any]:
    if path.name == "recovery_lineage_rebind_receipt.json":
        from app.services.s607_recovery_lineage_rebind import (
            load_recovery_lineage_rebind_identity,
            sha256_file,
        )

        return load_recovery_lineage_rebind_identity(
            path,
            expected_sha256=sha256_file(path),
        )
    from app.services.s607_database_recovery import (
        verify_semantic_recovery_receipt,
    )

    receipt = _read_object(path)
    verify_semantic_recovery_receipt(receipt)
    return {
        "path": str(path.resolve(strict=True)),
        "sha256": _sha256_file(path),
        "receipt_hash": receipt["receipt_hash"],
    }


def _write_create_only(path: Path, payload: dict[str, Any]) -> None:
    """create-only 落盘批准包；已存在则拒绝覆盖。"""
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
        "api_runner_refresh_failed",
        "api_runner_bound_fact_drift",
        "api_runner_launchd_contract_invalid",
        "api_service_probe_failed",
        "api_reload_bound_fact_drift",
        "api_bootout_failed",
        "api_bootout_timeout",
        "api_enable_failed",
        "api_bootstrap_failed",
        "api_health_check_failed",
        "tracked_worktree_not_clean",
        "worktree_not_clean",
    }
    if reason.startswith("foundation_receipt_") or reason in allowed:
        return reason
    return type(exc).__name__


if __name__ == "__main__":
    raise SystemExit(main())
