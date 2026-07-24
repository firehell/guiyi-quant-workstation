"""Hash-bound, code-only Runtime deployment Gate for S6-08.

Prepare and verify only collect read-only facts and create/verify an immutable
approval packet.  Confirm permits exactly one detached Runtime switch, removal
of non-venv Python bytecode, one exact scheduler kickstart, read-only
post-verification, and a create-only receipt.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import subprocess
import sys
from typing import Any
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash  # noqa: E402


TASK_ID = "JM-LIVE-SIGNAL-EVENT-S6-08-DEPLOY"
SCHEMA_VERSION = 1
FOUNDATION_TASK_ID = "JM-EOD-INCREMENTAL-AUTOMATION-S6-07"
FOUNDATION_GATE = "JM_EOD_INCREMENTAL_AUTOMATION_READY"
REQUIRED_DB_REVISION = "20260721_0025"
LAUNCHD_LABEL = "com.guiyi.quant-runtime-scheduler"
UV_LOCK_RELATIVE = Path("services/quant-api/uv.lock")
SAFE_FLAGS = {
    "GUIYI_LIVE_RUNTIME_ENABLED": True,
    "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
    "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
}
FLAG_NAMES = tuple(SAFE_FLAGS)
ALLOWED_OPERATIONS = (
    "runtime_detach_to_approved_commit",
    "purge_non_venv_python_bytecode",
    "kickstart_exact_runtime_scheduler",
    "read_only_post_deployment_verification",
    "create_only_deployment_receipt",
)
FORBIDDEN_OPERATIONS = (
    "database_migration",
    "database_write",
    "runtime_env_write",
    "signal_event_enable",
    "wechat_or_notification",
    "eod_scheduler",
    "api_restart",
    "worker_restart",
    "repo_fetch_or_push",
)


class DeploymentGateError(RuntimeError):
    """A bounded fail-closed deployment error."""

    def __init__(self, error_type: str):
        self.error_type = error_type
        super().__init__(error_type)


@dataclass(frozen=True)
class GateDependencies:
    command_runner: Callable[..., Any]
    source_probe: Callable[[Path], dict[str, Any]]
    runtime_probe: Callable[[Path], dict[str, Any]]
    database_probe: Callable[[], dict[str, Any]]
    runtime_env_probe: Callable[[Path], dict[str, Any]]
    launchd_probe: Callable[[str, Path], dict[str, Any]]
    health_probe: Callable[[], dict[str, Any]]
    runtime_sanitizer: Callable[[Path], None]
    foundation_validator: Callable[[Path, str], dict[str, Any]]
    uid: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="S6-08 code-only Runtime deployment Gate")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-deploy-packet", action="store_true")
    mode.add_argument("--verify-deploy-packet", action="store_true")
    mode.add_argument("--confirm-deploy", action="store_true")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--s6-final-receipt", type=Path)
    parser.add_argument("--s6-final-receipt-sha256")
    parser.add_argument("--runtime-env", type=Path)
    parser.add_argument("--packet-out", type=Path)
    parser.add_argument("--approval-packet", type=Path)
    parser.add_argument("--approval-hash")
    parser.add_argument("--deployment-receipt-out", type=Path)
    return parser.parse_args(argv)


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise DeploymentGateError("required_file_invalid")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command(
    runner: Callable[..., Any],
    argv: tuple[str, ...],
    *,
    cwd: Path,
    error_type: str,
    check: bool = True,
) -> Any:
    try:
        result = runner(
            argv,
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        raise DeploymentGateError(error_type) from exc
    if check and int(getattr(result, "returncode", 0) or 0) != 0:
        raise DeploymentGateError(error_type)
    return result


def _status_entries(status: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for raw in status.split("\0"):
        if not raw:
            continue
        if len(raw) < 4:
            raise DeploymentGateError("git_status_invalid")
        entries.append((raw[:2], raw[3:]))
    return entries


def _relative_status_path(root: Path, raw: str) -> tuple[str, Path]:
    normalized = PurePosixPath(raw)
    if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
        raise DeploymentGateError("git_status_path_invalid")
    relative = normalized.as_posix()
    return relative, root / relative


def _allowed_source_evidence(path: str) -> bool:
    manifest = (
        path.startswith("data/manifests/jm_after_market_archive_s607_")
        and "/" not in path.removeprefix("data/manifests/")
    )
    report = path.startswith("data/reports/jm_eod_incremental_s6_07/")
    return manifest or report


def probe_source_git(
    source_root: Path,
    *,
    command_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    root = source_root.resolve(strict=False)
    status = str(
        _command(
            command_runner,
            ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"),
            cwd=root,
            error_type="source_git_status_unavailable",
        ).stdout
    )
    evidence: list[dict[str, str]] = []
    for state, raw_path in _status_entries(status):
        if state != "??":
            raise DeploymentGateError("source_tracked_not_clean")
        relative, path = _relative_status_path(root, raw_path)
        if path.exists() and path.is_file() and os.access(path, os.X_OK):
            raise DeploymentGateError("source_untracked_executable")
        if not _allowed_source_evidence(relative):
            raise DeploymentGateError("source_untracked_path_invalid")
        if not path.is_file() or path.is_symlink():
            raise DeploymentGateError("source_evidence_invalid")
        evidence.append({"path": relative, "sha256": _sha256_file(path)})
    evidence.sort(key=lambda item: item["path"])
    commit = str(
        _command(
            command_runner,
            ("git", "rev-parse", "HEAD"),
            cwd=root,
            error_type="source_git_identity_unavailable",
        ).stdout
    ).strip()
    tree = str(
        _command(
            command_runner,
            ("git", "rev-parse", "HEAD^{tree}"),
            cwd=root,
            error_type="source_git_identity_unavailable",
        ).stdout
    ).strip()
    lock_path = root / UV_LOCK_RELATIVE
    return {
        "root": str(root),
        "commit": commit,
        "tree": tree,
        "tracked_clean": True,
        "untracked_evidence": {
            "files": evidence,
            "aggregate_sha256": canonical_json_sha256(evidence),
        },
        "uv_lock_sha256": _sha256_file(lock_path),
    }


def _inside_venv(path: str) -> bool:
    return ".venv" in PurePosixPath(path).parts


def probe_runtime_git(
    runtime_root: Path,
    *,
    command_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    root = runtime_root.resolve(strict=False)
    status = str(
        _command(
            command_runner,
            ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"),
            cwd=root,
            error_type="runtime_git_status_unavailable",
        ).stdout
    )
    for state, raw_path in _status_entries(status):
        if state != "??":
            raise DeploymentGateError("runtime_tracked_not_clean")
        relative, path = _relative_status_path(root, raw_path)
        if not _inside_venv(relative) and path.is_file() and os.access(path, os.X_OK):
            raise DeploymentGateError("runtime_untracked_executable")
    commit = str(
        _command(
            command_runner,
            ("git", "rev-parse", "HEAD"),
            cwd=root,
            error_type="runtime_git_identity_unavailable",
        ).stdout
    ).strip()
    tree = str(
        _command(
            command_runner,
            ("git", "rev-parse", "HEAD^{tree}"),
            cwd=root,
            error_type="runtime_git_identity_unavailable",
        ).stdout
    ).strip()
    return {
        "root": str(root),
        "current_commit": commit,
        "tree": tree,
        "tracked_clean": True,
        "untracked_executable_clean": True,
        "uv_lock_sha256": _sha256_file(root / UV_LOCK_RELATIVE),
    }


def collect_database_facts(
    *,
    session_factory: Callable[[], Any] | None = None,
    text_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    owned_engine = None
    if session_factory is None:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from app.db.url import normalize_database_url

        database_url = normalize_database_url(
            os.environ.get(
                "DATABASE_URL",
                "postgresql+psycopg://guiyi@127.0.0.1:5432/guiyi_quant",
            )
        )
        owned_engine = create_engine(database_url, pool_pre_ping=True)
        session_factory = sessionmaker(bind=owned_engine, autoflush=False, autocommit=False)
        text_factory = text
    if text_factory is None:
        from sqlalchemy import text

        text_factory = text
    session = session_factory()
    facts: dict[str, Any] | None = None
    try:
        bind = session.get_bind()
        url = bind.url
        driver = str(url.drivername or "")
        if str(bind.dialect.name or "") != "postgresql" or not driver.startswith("postgresql"):
            raise DeploymentGateError("database_driver_invalid")
        session.execute(text_factory("SET TRANSACTION READ ONLY"))
        read_only = str(
            session.execute(text_factory("SHOW transaction_read_only")).scalar_one()
        ).lower() in {"on", "true", "1"}
        if not read_only:
            raise DeploymentGateError("database_read_only_invalid")
        revision = session.execute(
            text_factory("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
        identity = "|".join(
            (
                driver,
                str(url.host or ""),
                str(url.port or ""),
                str(url.database or ""),
            )
        )
        facts = {
            "driver": driver,
            "identity_sha256": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            "revision": str(revision or ""),
            "read_only": True,
            "rolled_back": True,
        }
    finally:
        try:
            session.rollback()
        finally:
            session.close()
            if owned_engine is not None:
                owned_engine.dispose()
    if facts is None:
        raise DeploymentGateError("database_probe_failed")
    return facts


def _parse_flag_value(value: str) -> bool:
    candidate = value.strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
        candidate = candidate[1:-1].strip()
    normalized = candidate.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise DeploymentGateError("runtime_flag_value_invalid")


def probe_runtime_environment(runtime_env: Path) -> dict[str, Any]:
    path = runtime_env.resolve(strict=False)
    if not path.is_file() or path.is_symlink():
        raise DeploymentGateError("runtime_env_invalid")
    values: dict[str, bool] = {}
    target = set(FLAG_NAMES)
    assignment = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise DeploymentGateError("runtime_env_invalid") from exc
    for line in lines:
        match = assignment.match(line)
        if match is None or match.group(1) not in target:
            continue
        name = match.group(1)
        if name in values:
            raise DeploymentGateError("runtime_flag_duplicate")
        values[name] = _parse_flag_value(match.group(2))
    if set(values) != target:
        raise DeploymentGateError("runtime_flags_missing")
    return {"path": str(path), "flags": values}


def probe_launchd(
    label: str,
    runtime_root: Path,
    *,
    command_runner: Callable[..., Any] = subprocess.run,
    uid: int | None = None,
    plist_path: Path | None = None,
) -> dict[str, Any]:
    if label != LAUNCHD_LABEL:
        raise DeploymentGateError("launchd_identity_invalid")
    resolved_uid = os.getuid() if uid is None else uid
    service = f"gui/{resolved_uid}/{label}"
    output = str(
        _command(
            command_runner,
            ("launchctl", "print", service),
            cwd=runtime_root.resolve(strict=False),
            error_type="launchd_probe_failed",
        ).stdout
    )
    pid_match = re.search(r"(?m)^\s*pid\s*=\s*(\d+)\s*$", output)
    if pid_match is None or int(pid_match.group(1)) <= 0:
        raise DeploymentGateError("launchd_not_loaded")
    selected_plist = (
        plist_path
        if plist_path is not None
        else Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    )
    selected_plist = selected_plist.resolve(strict=False)
    if not selected_plist.is_file() or selected_plist.is_symlink():
        raise DeploymentGateError("launchd_plist_invalid")
    try:
        payload = plistlib.loads(selected_plist.read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise DeploymentGateError("launchd_plist_invalid") from exc
    arguments = payload.get("ProgramArguments")
    environment = payload.get("EnvironmentVariables")
    root = str(runtime_root.resolve(strict=False))
    if (
        payload.get("Label") != label
        or not isinstance(arguments, list)
        or len(arguments) != 3
        or arguments[0] != "/bin/bash"
        or arguments[2] != "scheduler"
        or not isinstance(environment, Mapping)
        or environment.get("GUIYI_PROJECT_ROOT") != root
    ):
        raise DeploymentGateError("launchd_plist_identity_invalid")
    return {
        "label": label,
        "loaded": True,
        "pid": int(pid_match.group(1)),
        "plist_path": str(selected_plist),
        "plist_sha256": _sha256_file(selected_plist),
        "program_arguments": [str(value) for value in arguments],
        "project_root": root,
    }


def probe_runtime_health() -> dict[str, Any]:
    try:
        request = Request("http://127.0.0.1:8000/api/runtime/health", method="GET")
        with urlopen(request, timeout=2.0) as response:
            if not 200 <= int(getattr(response, "status", 200)) < 300:
                raise DeploymentGateError("post_health_failed")
            raw = response.read(1024 * 1024 + 1)
    except DeploymentGateError:
        raise
    except Exception as exc:
        raise DeploymentGateError("post_health_failed") from exc
    if len(raw) > 1024 * 1024:
        raise DeploymentGateError("post_health_failed")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentGateError("post_health_failed") from exc
    if not isinstance(payload, Mapping):
        raise DeploymentGateError("post_health_failed")
    scheduler = (payload.get("components") or {}).get("scheduler") or {}
    return {
        "status": str(payload.get("status") or ""),
        "scheduler_status": str(scheduler.get("status") or ""),
    }


def _validate_foundation_receipt(path: Path, sha256: str) -> dict[str, Any]:
    try:
        from app.services.live_signal_event_gate import validate_s6_final_receipt

        return validate_s6_final_receipt(path, expected_sha256=sha256)
    except Exception as exc:
        raise DeploymentGateError("foundation_receipt_invalid") from exc


def default_dependencies() -> GateDependencies:
    runner = subprocess.run
    uid = os.getuid()
    return GateDependencies(
        command_runner=runner,
        source_probe=lambda root: probe_source_git(root, command_runner=runner),
        runtime_probe=lambda root: probe_runtime_git(root, command_runner=runner),
        database_probe=collect_database_facts,
        runtime_env_probe=probe_runtime_environment,
        launchd_probe=lambda label, root: probe_launchd(
            label,
            root,
            command_runner=runner,
            uid=uid,
        ),
        health_probe=probe_runtime_health,
        runtime_sanitizer=purge_nonvenv_python_artifacts,
        foundation_validator=_validate_foundation_receipt,
        uid=uid,
    )


def collect_deployment_bound_facts(
    *,
    source_root: Path,
    runtime_root: Path,
    s6_final_receipt: Path,
    s6_final_receipt_sha256: str,
    runtime_env: Path,
    dependencies: GateDependencies,
) -> dict[str, Any]:
    source = dependencies.source_probe(source_root)
    runtime = dependencies.runtime_probe(runtime_root)
    try:
        artifact = dependencies.foundation_validator(
            s6_final_receipt,
            s6_final_receipt_sha256,
        )
    except DeploymentGateError:
        raise
    except Exception as exc:
        raise DeploymentGateError("foundation_receipt_invalid") from exc
    receipt = artifact.get("receipt") if isinstance(artifact, Mapping) else None
    if not isinstance(receipt, Mapping):
        raise DeploymentGateError("foundation_receipt_invalid")
    if artifact.get("sha256") != s6_final_receipt_sha256:
        raise DeploymentGateError("foundation_receipt_hash_mismatch")
    foundation = {
        "path": str(artifact.get("path") or ""),
        "sha256": str(artifact.get("sha256") or ""),
        "schema_version": receipt.get("schema_version"),
        "task_id": receipt.get("task_id"),
        "gate": receipt.get("gate"),
        "status": receipt.get("status"),
        "runtime_commit": receipt.get("runtime_commit"),
        "database_revision": receipt.get("database_revision"),
        "authorization_hash": receipt.get("authorization_hash"),
    }
    target_commit = str(source.get("commit") or "")
    current_commit = str(runtime.get("current_commit") or "")
    _command(
        dependencies.command_runner,
        ("git", "cat-file", "-e", f"{target_commit}^{{commit}}"),
        cwd=runtime_root.resolve(strict=False),
        error_type="target_commit_not_local",
    )
    ancestry = _command(
        dependencies.command_runner,
        ("git", "merge-base", "--is-ancestor", current_commit, target_commit),
        cwd=runtime_root.resolve(strict=False),
        error_type="runtime_ancestry_probe_failed",
        check=False,
    )
    if int(getattr(ancestry, "returncode", 0) or 0) != 0:
        raise DeploymentGateError("runtime_not_ancestor")
    facts = {
        "source_git": source,
        "target_commit": target_commit,
        "runtime": runtime,
        "foundation_receipt": foundation,
        "database": dependencies.database_probe(),
        "runtime_environment": dependencies.runtime_env_probe(runtime_env),
        "launchd": dependencies.launchd_probe(LAUNCHD_LABEL, runtime_root),
    }
    validate_bound_facts(facts)
    return facts


def _is_lower_hex(value: Any, length: int) -> bool:
    text = str(value or "")
    return len(text) == length and all(character in "0123456789abcdef" for character in text)


def _validate_safe_flags(value: Any) -> None:
    if not isinstance(value, Mapping) or dict(value) != SAFE_FLAGS:
        raise DeploymentGateError("runtime_flags_unsafe")


def _validate_launchd_facts(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise DeploymentGateError("launchd_identity_invalid")
    if value.get("label") != LAUNCHD_LABEL:
        raise DeploymentGateError("launchd_identity_invalid")
    if value.get("loaded") is not True:
        raise DeploymentGateError("launchd_not_loaded")
    pid = value.get("pid")
    arguments = value.get("program_arguments")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or not Path(str(value.get("plist_path") or "")).is_absolute()
        or not _is_lower_hex(value.get("plist_sha256"), 64)
        or not isinstance(arguments, list)
        or len(arguments) != 3
        or arguments[0] != "/bin/bash"
        or arguments[2] != "scheduler"
        or not Path(str(value.get("project_root") or "")).is_absolute()
    ):
        raise DeploymentGateError("launchd_identity_invalid")


def validate_bound_facts(facts: Mapping[str, Any]) -> None:
    source = facts.get("source_git")
    runtime = facts.get("runtime")
    foundation = facts.get("foundation_receipt")
    database = facts.get("database")
    environment = facts.get("runtime_environment")
    if not all(isinstance(value, Mapping) for value in (source, runtime, foundation, database, environment)):
        raise DeploymentGateError("bound_facts_invalid")
    if (
        not Path(str(source.get("root") or "")).is_absolute()
        or not _is_lower_hex(source.get("commit"), 40)
        or not _is_lower_hex(source.get("tree"), 40)
        or source.get("tracked_clean") is not True
        or not _is_lower_hex(source.get("uv_lock_sha256"), 64)
    ):
        raise DeploymentGateError("source_identity_invalid")
    if source.get("commit") != facts.get("target_commit"):
        raise DeploymentGateError("source_target_mismatch")
    evidence = source.get("untracked_evidence")
    if not isinstance(evidence, Mapping) or not isinstance(evidence.get("files"), list):
        raise DeploymentGateError("source_evidence_invalid")
    files = evidence["files"]
    if evidence.get("aggregate_sha256") != canonical_json_sha256(files):
        raise DeploymentGateError("source_evidence_invalid")
    for item in files:
        if (
            not isinstance(item, Mapping)
            or not _allowed_source_evidence(str(item.get("path") or ""))
            or not _is_lower_hex(item.get("sha256"), 64)
        ):
            raise DeploymentGateError("source_evidence_invalid")
    if (
        not Path(str(runtime.get("root") or "")).is_absolute()
        or not _is_lower_hex(runtime.get("current_commit"), 40)
        or not _is_lower_hex(runtime.get("tree"), 40)
        or runtime.get("tracked_clean") is not True
        or runtime.get("untracked_executable_clean") is not True
        or not _is_lower_hex(runtime.get("uv_lock_sha256"), 64)
    ):
        raise DeploymentGateError("runtime_identity_invalid")
    if runtime.get("uv_lock_sha256") != source.get("uv_lock_sha256"):
        raise DeploymentGateError("dependency_lock_mismatch")
    if (
        foundation.get("schema_version") != 2
        or foundation.get("task_id") != FOUNDATION_TASK_ID
        or foundation.get("gate") != FOUNDATION_GATE
        or foundation.get("status") != "completed"
        or foundation.get("database_revision") != REQUIRED_DB_REVISION
        or not _is_lower_hex(foundation.get("sha256"), 64)
        or not _is_lower_hex(foundation.get("runtime_commit"), 40)
        or not _is_lower_hex(foundation.get("authorization_hash"), 64)
        or not Path(str(foundation.get("path") or "")).is_absolute()
    ):
        raise DeploymentGateError("foundation_receipt_invalid")
    if foundation.get("runtime_commit") != runtime.get("current_commit"):
        raise DeploymentGateError("foundation_runtime_mismatch")
    if (
        not str(database.get("driver") or "").startswith("postgresql")
        or not _is_lower_hex(database.get("identity_sha256"), 64)
        or database.get("read_only") is not True
        or database.get("rolled_back") is not True
    ):
        raise DeploymentGateError("database_identity_invalid")
    if database.get("revision") != REQUIRED_DB_REVISION:
        raise DeploymentGateError("database_revision_invalid")
    if foundation.get("database_revision") != database.get("revision"):
        raise DeploymentGateError("foundation_database_mismatch")
    if not Path(str(environment.get("path") or "")).is_absolute():
        raise DeploymentGateError("runtime_env_invalid")
    _validate_safe_flags(environment.get("flags"))
    launchd = facts.get("launchd")
    _validate_launchd_facts(launchd)
    if launchd.get("project_root") != runtime.get("root"):
        raise DeploymentGateError("launchd_runtime_root_mismatch")


def build_deployment_packet(bound_facts: Mapping[str, Any]) -> dict[str, Any]:
    validate_bound_facts(bound_facts)
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "status": "approval_required",
        "writes_authorized": False,
        "authorization_mode": "exact_packet_hash",
        "bound_facts": dict(bound_facts),
        "allowed_operations": list(ALLOWED_OPERATIONS),
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
        "invalidation_rule": (
            "any source evidence, target, Runtime, foundation receipt, dependency lock, "
            "database, safe flag, launchd, plist, or packet hash drift invalidates approval"
        ),
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def _validate_packet_identity_and_hash(
    packet: Mapping[str, Any],
    approval_hash: str,
) -> None:
    if (
        packet.get("schema_version") != SCHEMA_VERSION
        or packet.get("task_id") != TASK_ID
        or packet.get("status") != "approval_required"
        or packet.get("writes_authorized") is not False
        or packet.get("authorization_mode") != "exact_packet_hash"
        or packet.get("allowed_operations") != list(ALLOWED_OPERATIONS)
        or packet.get("forbidden_operations") != list(FORBIDDEN_OPERATIONS)
    ):
        raise DeploymentGateError("packet_identity_invalid")
    packet_hash = str(packet.get("packet_hash") or "")
    if (
        not _is_lower_hex(approval_hash, 64)
        or approval_hash != packet_hash
        or canonical_packet_hash(packet) != packet_hash
    ):
        raise DeploymentGateError("approval_hash_invalid")


def verify_deployment_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
) -> None:
    _validate_packet_identity_and_hash(packet, approval_hash)
    if packet.get("bound_facts") != current_facts:
        raise DeploymentGateError("bound_fact_drift")
    validate_bound_facts(current_facts)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DeploymentGateError("approval_packet_missing") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeploymentGateError("approval_packet_invalid") from exc
    if not isinstance(payload, dict):
        raise DeploymentGateError("approval_packet_invalid")
    return payload


def write_json_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    output = path.resolve(strict=False)
    if output.exists():
        raise DeploymentGateError("output_already_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            json.dump(
                dict(payload),
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            )
            handle.write("\n")
    except FileExistsError as exc:
        raise DeploymentGateError("output_already_exists") from exc
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        try:
            output.unlink()
        except FileNotFoundError:
            pass
        raise


def purge_nonvenv_python_artifacts(runtime_root: Path) -> None:
    root = runtime_root.resolve(strict=False)
    if not root.is_dir():
        raise DeploymentGateError("runtime_root_unavailable")
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        directories[:] = [name for name in directories if name != ".venv"]
        current_path = Path(current)
        for directory in list(directories):
            if directory == "__pycache__":
                shutil.rmtree(current_path / directory)
                directories.remove(directory)
        for filename in files:
            if filename.endswith((".pyc", ".pyo")):
                (current_path / filename).unlink()


def _kickstart_command(uid: int) -> tuple[str, ...]:
    return (
        "launchctl",
        "kickstart",
        "-k",
        f"gui/{uid}/{LAUNCHD_LABEL}",
    )


def _run_mutation(
    dependencies: GateDependencies,
    argv: tuple[str, ...],
    *,
    runtime_root: Path,
    error_type: str,
) -> None:
    _command(
        dependencies.command_runner,
        argv,
        cwd=runtime_root,
        error_type=error_type,
    )


def _validate_post_runtime(
    runtime: Mapping[str, Any],
    *,
    expected_commit: str,
    expected_tree: str,
    expected_uv: str,
) -> None:
    if (
        runtime.get("current_commit") != expected_commit
        or runtime.get("tree") != expected_tree
        or runtime.get("tracked_clean") is not True
        or runtime.get("untracked_executable_clean") is not True
        or runtime.get("uv_lock_sha256") != expected_uv
    ):
        raise DeploymentGateError("post_runtime_identity_invalid")


def _validate_post_launchd(
    launchd: Mapping[str, Any],
    *,
    previous: Mapping[str, Any],
    require_new_pid: bool,
) -> None:
    _validate_launchd_facts(launchd)
    for key in (
        "label",
        "plist_path",
        "plist_sha256",
        "program_arguments",
        "project_root",
    ):
        if launchd.get(key) != previous.get(key):
            raise DeploymentGateError("post_launchd_drift")
    if require_new_pid and launchd.get("pid") == previous.get("pid"):
        raise DeploymentGateError("scheduler_pid_not_restarted")


def _validate_health(health: Mapping[str, Any]) -> None:
    if health.get("status") != "ok" or health.get("scheduler_status") != "ok":
        raise DeploymentGateError("post_health_failed")


def _post_deployment_verification(
    *,
    facts: Mapping[str, Any],
    dependencies: GateDependencies,
    runtime_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    runtime = dependencies.runtime_probe(runtime_root)
    source = facts["source_git"]
    _validate_post_runtime(
        runtime,
        expected_commit=str(facts["target_commit"]),
        expected_tree=str(source["tree"]),
        expected_uv=str(source["uv_lock_sha256"]),
    )
    database = dependencies.database_probe()
    if database != facts["database"]:
        raise DeploymentGateError("post_database_drift")
    environment = dependencies.runtime_env_probe(Path(str(facts["runtime_environment"]["path"])))
    _validate_safe_flags(environment.get("flags"))
    if environment != facts["runtime_environment"]:
        raise DeploymentGateError("post_runtime_env_drift")
    launchd = dependencies.launchd_probe(LAUNCHD_LABEL, runtime_root)
    _validate_post_launchd(launchd, previous=facts["launchd"], require_new_pid=True)
    health = dependencies.health_probe()
    _validate_health(health)
    return runtime, database, environment, launchd, health


def _verify_rollback(
    *,
    facts: Mapping[str, Any],
    dependencies: GateDependencies,
    runtime_root: Path,
) -> None:
    previous_runtime = facts["runtime"]
    runtime = dependencies.runtime_probe(runtime_root)
    _validate_post_runtime(
        runtime,
        expected_commit=str(previous_runtime["current_commit"]),
        expected_tree=str(previous_runtime["tree"]),
        expected_uv=str(previous_runtime["uv_lock_sha256"]),
    )
    if dependencies.database_probe() != facts["database"]:
        raise DeploymentGateError("rollback_database_drift")
    environment = dependencies.runtime_env_probe(Path(str(facts["runtime_environment"]["path"])))
    _validate_safe_flags(environment.get("flags"))
    if environment != facts["runtime_environment"]:
        raise DeploymentGateError("rollback_runtime_env_drift")
    launchd = dependencies.launchd_probe(LAUNCHD_LABEL, runtime_root)
    _validate_post_launchd(launchd, previous=facts["launchd"], require_new_pid=False)
    _validate_health(dependencies.health_probe())


def _error_code(exc: Exception) -> str:
    if isinstance(exc, DeploymentGateError):
        return exc.error_type
    return "unexpected_error"


def _write_failure_receipt(
    path: Path,
    *,
    packet_hash: str,
    previous_commit: str,
    target_commit: str,
    error_type: str,
    trigger_error_type: str,
    rollback_attempted: bool,
    rollback_succeeded: bool,
) -> None:
    write_json_create_only(
        path,
        {
            "schema_version": 1,
            "task_id": TASK_ID,
            "status": "failed",
            "approval_packet_hash": packet_hash,
            "previous_commit": previous_commit,
            "target_commit": target_commit,
            "error_type": error_type,
            "trigger_error_type": trigger_error_type,
            "rollback": {
                "attempted": rollback_attempted,
                "succeeded": rollback_succeeded,
            },
            "scope_note": "code-only Runtime deployment; no database, env, notification, EOD, API, or worker write",
        },
    )


def execute_confirmed_deployment(
    *,
    packet: Mapping[str, Any],
    approval_hash: str,
    current_facts: Mapping[str, Any],
    receipt_out: Path,
    dependencies: GateDependencies,
) -> dict[str, Any]:
    verify_deployment_packet(
        packet,
        approval_hash=approval_hash,
        current_facts=current_facts,
    )
    if receipt_out.resolve(strict=False).exists():
        raise DeploymentGateError("output_already_exists")
    facts = current_facts
    runtime_root = Path(str(facts["runtime"]["root"]))
    previous_commit = str(facts["runtime"]["current_commit"])
    target_commit = str(facts["target_commit"])
    packet_hash = str(packet["packet_hash"])
    switch_attempted = False
    try:
        switch_attempted = True
        _run_mutation(
            dependencies,
            ("git", "switch", "--detach", target_commit),
            runtime_root=runtime_root,
            error_type="runtime_switch_failed",
        )
        try:
            dependencies.runtime_sanitizer(runtime_root)
        except Exception as exc:
            raise DeploymentGateError("python_artifact_purge_failed") from exc
        _run_mutation(
            dependencies,
            _kickstart_command(dependencies.uid),
            runtime_root=runtime_root,
            error_type="scheduler_kickstart_failed",
        )
        _, database, environment, launchd, _ = _post_deployment_verification(
            facts=facts,
            dependencies=dependencies,
            runtime_root=runtime_root,
        )
        receipt = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "status": "completed",
            "approval_packet_hash": packet_hash,
            "previous_commit": previous_commit,
            "target_commit": target_commit,
            "scheduler_restart": {
                "label": LAUNCHD_LABEL,
                "previous_pid": facts["launchd"]["pid"],
                "new_pid": launchd["pid"],
                "loaded": True,
                "other_labels_restarted": False,
            },
            "database_revision_before": facts["database"]["revision"],
            "database_revision_after": database["revision"],
            "database_unchanged": database == facts["database"],
            "feature_flags": dict(environment["flags"]),
            "flags_safe": environment["flags"] == SAFE_FLAGS,
            "health_verified": True,
            "rollback": False,
            "completed_at": datetime.now(UTC).isoformat(),
            "scope_note": "research observation only; no notification, order, or automatic trading authorization",
        }
        write_json_create_only(receipt_out, receipt)
        return receipt
    except Exception as exc:
        trigger_error = _error_code(exc)
        rollback_succeeded = False
        if switch_attempted:
            try:
                _run_mutation(
                    dependencies,
                    ("git", "switch", "--detach", previous_commit),
                    runtime_root=runtime_root,
                    error_type="rollback_runtime_switch_failed",
                )
                _run_mutation(
                    dependencies,
                    _kickstart_command(dependencies.uid),
                    runtime_root=runtime_root,
                    error_type="rollback_scheduler_kickstart_failed",
                )
                _verify_rollback(
                    facts=facts,
                    dependencies=dependencies,
                    runtime_root=runtime_root,
                )
                rollback_succeeded = True
            except Exception:
                rollback_succeeded = False
        final_error = trigger_error if rollback_succeeded else "rollback_failed"
        try:
            _write_failure_receipt(
                receipt_out,
                packet_hash=packet_hash,
                previous_commit=previous_commit,
                target_commit=target_commit,
                error_type=final_error,
                trigger_error_type=trigger_error,
                rollback_attempted=switch_attempted,
                rollback_succeeded=rollback_succeeded,
            )
        except DeploymentGateError as receipt_error:
            if receipt_error.error_type != "output_already_exists":
                raise DeploymentGateError("failure_receipt_write_failed") from None
        raise DeploymentGateError(final_error) from None


def _validate_cli_arguments(args: argparse.Namespace) -> None:
    common = (
        args.runtime_root,
        args.s6_final_receipt,
        args.s6_final_receipt_sha256,
        args.runtime_env,
    )
    if any(value in (None, "") for value in common):
        raise DeploymentGateError("required_argument_missing")
    if not _is_lower_hex(args.s6_final_receipt_sha256, 64):
        raise DeploymentGateError("sha256_invalid")
    if args.prepare_deploy_packet:
        if args.packet_out is None:
            raise DeploymentGateError("required_argument_missing")
        return
    if args.approval_packet is None or args.approval_hash is None:
        raise DeploymentGateError("required_argument_missing")
    if not _is_lower_hex(args.approval_hash, 64):
        raise DeploymentGateError("sha256_invalid")
    if args.confirm_deploy and args.deployment_receipt_out is None:
        raise DeploymentGateError("required_argument_missing")


def _collect_from_args(
    args: argparse.Namespace,
    *,
    dependencies: GateDependencies,
    fact_collector: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return fact_collector(
        source_root=PROJECT_ROOT,
        runtime_root=args.runtime_root,
        s6_final_receipt=args.s6_final_receipt,
        s6_final_receipt_sha256=args.s6_final_receipt_sha256,
        runtime_env=args.runtime_env,
        dependencies=dependencies,
    )


def _preexecution_failure_receipt(args: argparse.Namespace, error_type: str) -> None:
    if (
        not args.confirm_deploy
        or args.deployment_receipt_out is None
        or args.deployment_receipt_out.resolve(strict=False).exists()
    ):
        return
    _write_failure_receipt(
        args.deployment_receipt_out,
        packet_hash=str(args.approval_hash or ""),
        previous_commit="",
        target_commit="",
        error_type=error_type,
        trigger_error_type=error_type,
        rollback_attempted=False,
        rollback_succeeded=False,
    )


def main(
    argv: list[str] | None = None,
    *,
    dependencies: GateDependencies | None = None,
    fact_collector: Callable[..., dict[str, Any]] | None = None,
) -> int:
    args = parse_args(argv)
    deps = dependencies or default_dependencies()
    collector = fact_collector or collect_deployment_bound_facts
    try:
        _validate_cli_arguments(args)
        if args.prepare_deploy_packet:
            if args.packet_out.resolve(strict=False).exists():
                raise DeploymentGateError("output_already_exists")
            facts = _collect_from_args(args, dependencies=deps, fact_collector=collector)
            packet = build_deployment_packet(facts)
            write_json_create_only(args.packet_out, packet)
            status = "approval_required"
        else:
            packet = _read_json_object(args.approval_packet)
            _validate_packet_identity_and_hash(packet, str(args.approval_hash))
            facts = _collect_from_args(args, dependencies=deps, fact_collector=collector)
            verify_deployment_packet(
                packet,
                approval_hash=str(args.approval_hash),
                current_facts=facts,
            )
            if args.verify_deploy_packet:
                status = "verified"
            else:
                execute_confirmed_deployment(
                    packet=packet,
                    approval_hash=str(args.approval_hash),
                    current_facts=facts,
                    receipt_out=args.deployment_receipt_out,
                    dependencies=deps,
                )
                status = "deployed"
        print(
            json.dumps(
                {
                    "status": status,
                    "task_id": TASK_ID,
                    "packet_hash": packet["packet_hash"],
                    "writes_authorized": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        error_type = _error_code(exc)
        try:
            _preexecution_failure_receipt(args, error_type)
        except Exception:
            error_type = "failure_receipt_write_failed"
        print(
            json.dumps(
                {"status": "blocked", "error_type": error_type},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
