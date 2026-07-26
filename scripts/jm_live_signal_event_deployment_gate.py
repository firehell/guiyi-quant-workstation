"""Hash-bound, code-only Runtime deployment Gate for S6-08.

Prepare and verify only collect read-only facts and create/verify an immutable
approval packet.  Confirm permits exactly one detached Runtime switch, removal
of non-venv Python bytecode, one exact scheduler kickstart, read-only
post-verification, and a create-only receipt.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
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
HTDY_STEP4_SOURCE_BRANCH = "codex/v1-htdy-approval-a-rebind"
ALLOWED_SOURCE_BRANCHES = {"main", HTDY_STEP4_SOURCE_BRANCH}
UV_LOCK_RELATIVE = Path("services/quant-api/uv.lock")
RUNNER_RELATIVE = Path("scripts/run-local-service.sh")
RUNTIME_SUPPORT_RELATIVE = Path("Library/Application Support/GuiyiQuant")
LAUNCHD_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
REQUIRED_LAUNCHD_ENVIRONMENT = {"PATH", "GUIYI_PROJECT_ROOT"}
OPTIONAL_LAUNCHD_ENVIRONMENT = {"GUIYI_RUNTIME_DIR", "GUIYI_RUNTIME_ENV"}
SYSTEM_INJECTED_LAUNCHD_ENVIRONMENT = {
    "XPC_SERVICE_NAME": LAUNCHD_LABEL,
    "OSLogRateLimit": "64",
}
LAUNCHD_IDENTITY_FIELDS = (
    "label",
    "loaded",
    "plist_path",
    "plist_sha256",
    "loaded_program",
    "program_arguments",
    "environment",
    "working_directory",
    "project_root",
    "runner_path",
    "runner_sha256",
)
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


def _unavailable_recovery_validator(
    _path: Path,
    _sha256: str,
) -> dict[str, Any]:
    raise DeploymentGateError("database_recovery_receipt_invalid")


@dataclass(frozen=True)
class RuntimeEnvironmentResult:
    facts: dict[str, Any]
    database_url: str


@dataclass(frozen=True)
class GateDependencies:
    command_runner: Callable[..., Any]
    source_probe: Callable[[Path, Mapping[str, Any]], dict[str, Any]]
    runtime_probe: Callable[[Path], dict[str, Any]]
    database_probe: Callable[[str], dict[str, Any]]
    runtime_env_probe: Callable[[Path], RuntimeEnvironmentResult]
    launchd_probe: Callable[[str, Path], dict[str, Any]]
    health_probe: Callable[[], dict[str, Any]]
    runtime_sanitizer: Callable[[Path], None]
    foundation_validator: Callable[[Path, str], dict[str, Any]]
    uid: int
    recovery_validator: Callable[
        [Path, str],
        dict[str, Any],
    ] = _unavailable_recovery_validator


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="S6-08 code-only Runtime deployment Gate")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-deploy-packet", action="store_true")
    mode.add_argument("--verify-deploy-packet", action="store_true")
    mode.add_argument("--confirm-deploy", action="store_true")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--s6-final-receipt", type=Path)
    parser.add_argument("--s6-final-receipt-sha256")
    parser.add_argument("--database-recovery-receipt", type=Path)
    parser.add_argument("--database-recovery-receipt-sha256")
    parser.add_argument("--runtime-env", type=Path)
    parser.add_argument("--output-root", type=Path)
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


_MANIFEST_EVIDENCE = re.compile(
    r"^data/manifests/jm_after_market_archive_s607_(\d{8})_([0-9a-f]{8})\.csv$"
)
_REPORT_EVIDENCE = re.compile(
    r"^data/reports/jm_eod_incremental_s6_07/"
    r"(s607_(\d{8})_([0-9a-f]{8}))/"
    r"(completion_receipt|execution_packet|final_audit|quality_gate)\.json$"
)
_D2_REPORT_FILES = {
    "completion_receipt",
    "execution_packet",
    "final_audit",
    "quality_gate",
}
_HTDY_SCHEMA_V3_OUTPUT_ROOT = re.compile(
    r"^data/reports/jm_live_signal_event_s6_08/htdy_schema_v3/"
    r"\d{8}-[0-9a-f]{12}$"
)
_HTDY_SCHEMA_V3_EVIDENCE = re.compile(
    r"^data/reports/jm_live_signal_event_s6_08/htdy_schema_v3/"
    r"\d{8}-[0-9a-f]{12}/"
    r"(?:(?:deployment_packet|deployment_receipt|s6_07_rebind_packet|"
    r"s6_07_rebind_receipt|service_parent_packet|approval_bundle)\.json|"
    r"daily/\d{4}-\d{2}-\d{2}/(?:child_packet|accepted_event|"
    r"authorization_consumed|completion_receipt)\.json)$"
)


def _allowed_source_evidence(path: str) -> bool:
    return (
        _MANIFEST_EVIDENCE.fullmatch(path) is not None
        or _REPORT_EVIDENCE.fullmatch(path) is not None
        or _HTDY_SCHEMA_V3_EVIDENCE.fullmatch(path) is not None
    )


def exclude_htdy_output_evidence(
    source: Mapping[str, Any],
    *,
    output_root: Path,
) -> dict[str, Any]:
    source_root = Path(str(source.get("root") or ""))
    if not _is_htdy_schema_v3_output_root(
        output_root,
        source_root=source_root,
    ):
        return dict(source)
    relative_root = output_root.resolve(strict=True).relative_to(
        source_root.resolve(strict=True)
    )
    prefix = f"{relative_root.as_posix()}/"
    normalized = dict(source)
    for key in ("untracked_evidence", "source_evidence"):
        section = source.get(key)
        if not isinstance(section, Mapping):
            raise DeploymentGateError("source_evidence_invalid")
        files = section.get("files")
        if not isinstance(files, list):
            raise DeploymentGateError("source_evidence_invalid")
        retained = [
            dict(item)
            for item in files
            if isinstance(item, Mapping)
            and not str(item.get("path") or "").startswith(prefix)
        ]
        normalized[key] = {
            "files": retained,
            "aggregate_sha256": canonical_json_sha256(retained),
        }
    return normalized


def _foundation_evidence_scope(receipt: Mapping[str, Any]) -> tuple[date, date, set[str], str]:
    try:
        d1_day = date.fromisoformat(str((receipt.get("d1") or {})["trading_day"]))
        d2 = receipt.get("d2") or {}
        d2_day = date.fromisoformat(str(d2["trading_day"]))
        d2_batch = str(d2["batch_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DeploymentGateError("foundation_evidence_scope_invalid") from exc
    if d2_day < d1_day or _REPORT_EVIDENCE.fullmatch(
        f"data/reports/jm_eod_incremental_s6_07/{d2_batch}/execution_packet.json"
    ) is None:
        raise DeploymentGateError("foundation_evidence_scope_invalid")
    lineage = receipt.get("deployment_lineage")
    if not isinstance(lineage, Mapping):
        raise DeploymentGateError("foundation_evidence_scope_invalid")
    commits = {
        str(value)
        for key, value in lineage.items()
        if key.endswith("_commit") and _is_lower_hex(value, 40)
    }
    d1_commit = (receipt.get("d1") or {}).get("runtime_commit")
    runtime_commit = receipt.get("runtime_commit")
    for value in (d1_commit, runtime_commit):
        if _is_lower_hex(value, 40):
            commits.add(str(value))
    if not commits:
        raise DeploymentGateError("foundation_evidence_scope_invalid")
    return d1_day, d2_day, {commit[:8] for commit in commits}, d2_batch


def _validate_source_evidence(
    files: list[dict[str, str]],
    *,
    foundation_receipt: Mapping[str, Any],
) -> None:
    d1_day, d2_day, lineage_prefixes, d2_batch = _foundation_evidence_scope(foundation_receipt)
    report_files: dict[str, set[str]] = {}
    for item in files:
        relative = item["path"]
        if _HTDY_SCHEMA_V3_EVIDENCE.fullmatch(relative) is not None:
            continue
        match = _MANIFEST_EVIDENCE.fullmatch(relative)
        if match is not None:
            day_text, commit_prefix = match.groups()
        else:
            report_match = _REPORT_EVIDENCE.fullmatch(relative)
            if report_match is None:
                raise DeploymentGateError("source_evidence_name_invalid")
            batch, day_text, commit_prefix, file_type = report_match.groups()
            report_files.setdefault(batch, set()).add(file_type)
        try:
            evidence_day = datetime.strptime(day_text, "%Y%m%d").date()
        except ValueError as exc:
            raise DeploymentGateError("source_evidence_date_invalid") from exc
        if not d1_day <= evidence_day <= d2_day:
            raise DeploymentGateError("source_evidence_date_invalid")
        if commit_prefix not in lineage_prefixes:
            raise DeploymentGateError("source_evidence_lineage_invalid")
    if report_files.get(d2_batch, set()) != _D2_REPORT_FILES:
        raise DeploymentGateError("source_d2_evidence_incomplete")


def _collect_tracked_source_evidence(
    root: Path,
    *,
    commit: str,
    command_runner: Callable[..., Any],
) -> list[dict[str, str]]:
    output = str(
        _command(
            command_runner,
            (
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                "-z",
                commit,
                "--",
                "data/manifests",
                "data/reports/jm_eod_incremental_s6_07",
            ),
            cwd=root,
            error_type="source_tracked_evidence_unavailable",
        ).stdout
    )
    evidence: list[dict[str, str]] = []
    for relative in sorted(path for path in output.split("\0") if path):
        if not _allowed_source_evidence(relative):
            if relative.startswith(
                ("data/manifests/jm_after_market_archive_s607_", "data/reports/jm_eod_incremental_s6_07/")
            ):
                raise DeploymentGateError("source_evidence_name_invalid")
            continue
        _, path = _relative_status_path(root, relative)
        if not path.is_file() or path.is_symlink() or os.access(path, os.X_OK):
            raise DeploymentGateError("source_tracked_evidence_invalid")
        blob = str(
            _command(
                command_runner,
                ("git", "show", f"{commit}:{relative}"),
                cwd=root,
                error_type="source_tracked_evidence_unavailable",
            ).stdout
        ).encode("utf-8")
        file_sha256 = _sha256_file(path)
        if hashlib.sha256(blob).hexdigest() != file_sha256:
            raise DeploymentGateError("source_tracked_evidence_blob_mismatch")
        evidence.append({"path": relative, "sha256": file_sha256})
    return evidence


def probe_source_git(
    source_root: Path,
    *,
    foundation_receipt: Mapping[str, Any],
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
            if relative.startswith(
                ("data/manifests/jm_after_market_archive_s607_", "data/reports/jm_eod_incremental_s6_07/")
            ):
                raise DeploymentGateError("source_evidence_name_invalid")
            raise DeploymentGateError("source_untracked_path_invalid")
        if not path.is_file() or path.is_symlink():
            raise DeploymentGateError("source_evidence_invalid")
        evidence.append({"path": relative, "sha256": _sha256_file(path)})
    evidence.sort(key=lambda item: item["path"])
    branch = str(
        _command(
            command_runner,
            ("git", "branch", "--show-current"),
            cwd=root,
            error_type="source_git_identity_unavailable",
        ).stdout
    ).strip()
    if branch not in ALLOWED_SOURCE_BRANCHES:
        raise DeploymentGateError("source_branch_invalid")
    commit = str(
        _command(
            command_runner,
            ("git", "rev-parse", "HEAD"),
            cwd=root,
            error_type="source_git_identity_unavailable",
        ).stdout
    ).strip()
    source_ref = (
        "refs/heads/main"
        if branch == "main"
        else f"refs/heads/{HTDY_STEP4_SOURCE_BRANCH}"
    )
    local_main = str(
        _command(
            command_runner,
            ("git", "rev-parse", source_ref),
            cwd=root,
            error_type="source_main_unavailable",
        ).stdout
    ).strip()
    if commit != local_main:
        raise DeploymentGateError("source_main_head_mismatch")
    tracked_evidence = _collect_tracked_source_evidence(
        root,
        commit=commit,
        command_runner=command_runner,
    )
    combined_evidence = [
        {**item, "tracking": "tracked"}
        for item in tracked_evidence
    ] + [
        {**item, "tracking": "untracked"}
        for item in evidence
    ]
    combined_evidence.sort(key=lambda item: item["path"])
    if len({item["path"] for item in combined_evidence}) != len(combined_evidence):
        raise DeploymentGateError("source_evidence_duplicate")
    _validate_source_evidence(combined_evidence, foundation_receipt=foundation_receipt)
    origin_main = str(
        _command(
            command_runner,
            ("git", "rev-parse", "refs/remotes/origin/main"),
            cwd=root,
            error_type="source_origin_main_unavailable",
        ).stdout
    ).strip()
    origin_ancestor = _command(
        command_runner,
        ("git", "merge-base", "--is-ancestor", origin_main, local_main),
        cwd=root,
        error_type="source_origin_ancestry_probe_failed",
        check=False,
    )
    if int(getattr(origin_ancestor, "returncode", 0) or 0) != 0:
        raise DeploymentGateError("source_main_diverged")
    ahead_text = str(
        _command(
            command_runner,
            ("git", "rev-list", "--count", f"{origin_main}..{local_main}"),
            cwd=root,
            error_type="source_origin_ancestry_probe_failed",
        ).stdout
    ).strip()
    try:
        ahead = int(ahead_text)
    except ValueError as exc:
        raise DeploymentGateError("source_origin_ancestry_probe_failed") from exc
    tree = str(
        _command(
            command_runner,
            ("git", "rev-parse", "HEAD^{tree}"),
            cwd=root,
            error_type="source_git_identity_unavailable",
        ).stdout
    ).strip()
    git_dir_text = str(
        _command(
            command_runner,
            ("git", "rev-parse", "--git-dir"),
            cwd=root,
            error_type="source_git_identity_unavailable",
        ).stdout
    ).strip()
    git_common_text = str(
        _command(
            command_runner,
            ("git", "rev-parse", "--git-common-dir"),
            cwd=root,
            error_type="source_git_identity_unavailable",
        ).stdout
    ).strip()
    git_dir = Path(git_dir_text)
    git_common = Path(git_common_text)
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    if not git_common.is_absolute():
        git_common = root / git_common
    runner_path = root / RUNNER_RELATIVE
    runner_blob = str(
        _command(
            command_runner,
            ("git", "show", f"{commit}:{RUNNER_RELATIVE.as_posix()}"),
            cwd=root,
            error_type="source_runner_blob_unavailable",
        ).stdout
    ).encode("utf-8")
    runner_worktree_sha = _sha256_file(runner_path)
    runner_blob_sha = hashlib.sha256(runner_blob).hexdigest()
    if runner_worktree_sha != runner_blob_sha:
        raise DeploymentGateError("source_runner_blob_mismatch")
    lock_path = root / UV_LOCK_RELATIVE
    return {
        "root": str(root),
        "branch": branch,
        "commit": commit,
        "local_main": local_main,
        "origin_main": origin_main,
        "ahead_of_origin": ahead,
        "tree": tree,
        "tracked_clean": True,
        "git_dir": str(git_dir.resolve(strict=False)),
        "git_common_dir": str(git_common.resolve(strict=False)),
        "runner_relative_path": RUNNER_RELATIVE.as_posix(),
        "runner_worktree_sha256": runner_worktree_sha,
        "runner_target_blob_sha256": runner_blob_sha,
        "untracked_evidence": {
            "files": evidence,
            "aggregate_sha256": canonical_json_sha256(evidence),
        },
        "tracked_evidence": {
            "files": tracked_evidence,
            "aggregate_sha256": canonical_json_sha256(tracked_evidence),
        },
        "source_evidence": {
            "files": combined_evidence,
            "aggregate_sha256": canonical_json_sha256(combined_evidence),
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
    git_dir_text = str(
        _command(
            command_runner,
            ("git", "rev-parse", "--git-dir"),
            cwd=root,
            error_type="runtime_git_identity_unavailable",
        ).stdout
    ).strip()
    git_common_text = str(
        _command(
            command_runner,
            ("git", "rev-parse", "--git-common-dir"),
            cwd=root,
            error_type="runtime_git_identity_unavailable",
        ).stdout
    ).strip()
    git_dir = Path(git_dir_text)
    git_common = Path(git_common_text)
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    if not git_common.is_absolute():
        git_common = root / git_common
    return {
        "root": str(root),
        "current_commit": commit,
        "tree": tree,
        "tracked_clean": True,
        "untracked_executable_clean": True,
        "git_dir": str(git_dir.resolve(strict=False)),
        "git_common_dir": str(git_common.resolve(strict=False)),
        "uv_lock_sha256": _sha256_file(root / UV_LOCK_RELATIVE),
    }


def collect_database_facts(
    database_url: str,
    *,
    session_factory: Callable[[str], Any] | None = None,
    text_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(database_url, str) or not database_url.strip():
        raise DeploymentGateError("database_url_missing")
    owned_engine = None
    if session_factory is None:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from app.db.url import normalize_database_url

        normalized_url = normalize_database_url(database_url)
        owned_engine = create_engine(normalized_url, pool_pre_ping=True)
        factory = sessionmaker(bind=owned_engine, autoflush=False, autocommit=False)

        def create_session(_database_url: str) -> Any:
            return factory()

        session_factory = create_session
        text_factory = text
    if text_factory is None:
        from sqlalchemy import text

        text_factory = text
    session = session_factory(database_url)
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
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise DeploymentGateError("runtime_flag_value_invalid")


def _parse_runtime_env_value(raw: str) -> str:
    if raw == "":
        return ""
    if raw != raw.strip() or "\x00" in raw:
        raise DeploymentGateError("runtime_env_syntax_invalid")
    inline_comment = re.fullmatch(r"([^ \t]+)[ \t]+#.*", raw)
    if inline_comment is not None:
        raw = inline_comment.group(1)
    if "$(" in raw or "`" in raw:
        raise DeploymentGateError("runtime_env_syntax_invalid")
    if raw[0] in {"'", '"'}:
        quote = raw[0]
        if len(raw) < 2 or raw[-1] != quote:
            raise DeploymentGateError("runtime_env_syntax_invalid")
        value = raw[1:-1]
        if (
            quote in value
            or (quote == '"' and ("\\" in value or "$" in value))
        ):
            raise DeploymentGateError("runtime_env_syntax_invalid")
        return value
    if (
        any(character.isspace() for character in raw)
        or any(
            token in raw
            for token in ("#", ";", "&&", "||", "<(", ">(", "$", "\\")
        )
        or "'" in raw
        or '"' in raw
    ):
        raise DeploymentGateError("runtime_env_syntax_invalid")
    return raw


def _read_regular_file_once(
    path: Path,
    *,
    error_type: str,
) -> tuple[bytes, os.stat_result]:
    descriptor: int | None = None
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise DeploymentGateError(error_type)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), metadata
    except DeploymentGateError:
        raise
    except OSError as exc:
        raise DeploymentGateError(error_type) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def probe_runtime_environment(runtime_env: Path) -> RuntimeEnvironmentResult:
    path = Path(os.path.abspath(runtime_env))
    values: dict[str, str] = {}
    assignment = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
    try:
        raw_bytes, metadata = _read_regular_file_once(
            path,
            error_type="runtime_env_invalid",
        )
        lines = raw_bytes.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise DeploymentGateError("runtime_env_invalid") from exc
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw_line != stripped:
            raise DeploymentGateError("runtime_env_syntax_invalid")
        line = raw_line
        match = assignment.fullmatch(line)
        if match is None:
            raise DeploymentGateError("runtime_env_syntax_invalid")
        name = match.group(1)
        value = _parse_runtime_env_value(match.group(2))
        if name in values:
            raise DeploymentGateError("runtime_env_duplicate_key")
        values[name] = value
    target = set(FLAG_NAMES)
    if not target.issubset(values):
        raise DeploymentGateError("runtime_flags_missing")
    database_url = values.get("DATABASE_URL")
    if not database_url:
        raise DeploymentGateError("database_url_missing")
    flags = {name: _parse_flag_value(values[name]) for name in FLAG_NAMES}
    return RuntimeEnvironmentResult(
        facts={
            "path": str(path),
            "file_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "device": int(metadata.st_dev),
            "inode": int(metadata.st_ino),
            "size": int(metadata.st_size),
            "flags": flags,
        },
        database_url=database_url,
    )


def resolve_runtime_environment_path(
    launchd: Mapping[str, Any],
    *,
    home: Path | None = None,
) -> Path:
    environment = launchd.get("environment")
    if not isinstance(environment, Mapping):
        raise DeploymentGateError("launchd_environment_invalid")
    home_root = (home if home is not None else Path.home()).resolve(strict=False)
    explicit_env = environment.get("GUIYI_RUNTIME_ENV")
    explicit_dir = environment.get("GUIYI_RUNTIME_DIR")
    if explicit_env:
        resolved = Path(str(explicit_env))
    elif explicit_dir:
        resolved = Path(str(explicit_dir)) / "project.env"
    else:
        resolved = home_root / RUNTIME_SUPPORT_RELATIVE / "project.env"
    if not resolved.is_absolute():
        raise DeploymentGateError("runtime_env_path_invalid")
    return resolved.resolve(strict=False)


def validate_runtime_environment_cli_path(
    runtime_env: Path,
    launchd: Mapping[str, Any],
    *,
    home: Path | None = None,
) -> Path:
    resolved = resolve_runtime_environment_path(launchd, home=home)
    if runtime_env.is_symlink() or runtime_env.resolve(strict=False) != resolved:
        raise DeploymentGateError("runtime_env_path_mismatch")
    return resolved


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _validate_managed_output_path(root: Path, path: Path) -> tuple[Path, int, int]:
    absolute = Path(os.path.abspath(path))
    try:
        raw_relative = absolute.relative_to(root)
    except ValueError as exc:
        raise DeploymentGateError("output_path_outside_root") from exc
    current = root
    for part in raw_relative.parts[:-1]:
        current = current / part
        if not current.is_dir() or current.is_symlink():
            raise DeploymentGateError("output_parent_invalid")
    if absolute.exists() and absolute.is_symlink():
        raise DeploymentGateError("output_path_invalid")
    resolved = absolute.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise DeploymentGateError("output_path_outside_root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise DeploymentGateError("output_path_invalid")
    parent = resolved.parent
    if not parent.is_dir() or parent.is_symlink():
        raise DeploymentGateError("output_parent_invalid")
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if not current.is_dir() or current.is_symlink():
            raise DeploymentGateError("output_parent_invalid")
    if resolved.exists() and resolved.is_symlink():
        raise DeploymentGateError("output_path_invalid")
    parent_metadata = parent.stat()
    return resolved, int(parent_metadata.st_dev), int(parent_metadata.st_ino)


def collect_output_scope(
    *,
    output_root: Path,
    packet_path: Path,
    receipt_path: Path,
    protected_paths: list[Path],
) -> dict[str, Any]:
    if output_root.is_symlink():
        raise DeploymentGateError("output_root_invalid")
    try:
        root = output_root.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise DeploymentGateError("output_root_invalid") from exc
    if not root.is_dir():
        raise DeploymentGateError("output_root_invalid")
    for protected in protected_paths:
        candidate = protected.resolve(strict=False)
        if _paths_overlap(root, candidate):
            raise DeploymentGateError("output_scope_overlap")
    packet, packet_device, packet_parent_inode = _validate_managed_output_path(
        root,
        packet_path,
    )
    receipt, receipt_device, receipt_parent_inode = _validate_managed_output_path(
        root,
        receipt_path,
    )
    if packet == receipt:
        raise DeploymentGateError("output_path_collision")
    root_device = int(root.stat().st_dev)
    if packet_device != root_device or receipt_device != root_device:
        raise DeploymentGateError("output_device_mismatch")
    return {
        "root": str(root),
        "root_device": root_device,
        "packet_path": str(packet),
        "packet_device": packet_device,
        "packet_parent_inode": packet_parent_inode,
        "receipt_path": str(receipt),
        "receipt_device": receipt_device,
        "receipt_parent_inode": receipt_parent_inode,
    }


def _runtime_lock_identity(runtime_root: Path, label: str) -> str:
    return canonical_json_sha256(
        {
            "runtime_root": str(Path(os.path.abspath(runtime_root))),
            "launchd_label": label,
        }
    )


def _runtime_lock_path(runtime_root: Path, launchd: Mapping[str, Any]) -> Path:
    runner = Path(str(launchd.get("runner_path") or ""))
    identity = _runtime_lock_identity(runtime_root, str(launchd.get("label") or ""))
    return runner.parent / f".s6-08-runtime-deploy-{identity[:24]}.lock"


def collect_runtime_lock_scope(
    *,
    runtime_root: Path,
    launchd: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(os.path.abspath(runtime_root))
    if (
        not root.is_absolute()
        or launchd.get("label") != LAUNCHD_LABEL
        or Path(str(launchd.get("project_root") or "")) != root
    ):
        raise DeploymentGateError("deployment_lock_identity_invalid")
    runner = Path(str(launchd.get("runner_path") or ""))
    parent = runner.parent
    if (
        not runner.is_absolute()
        or not parent.is_dir()
        or parent.is_symlink()
        or parent.resolve(strict=True) != parent
    ):
        raise DeploymentGateError("deployment_lock_parent_invalid")
    path = _runtime_lock_path(root, launchd)
    if path.exists() and path.is_symlink():
        raise DeploymentGateError("deployment_lock_invalid")
    metadata = parent.stat()
    identity = _runtime_lock_identity(root, LAUNCHD_LABEL)
    return {
        "path": str(path),
        "parent_path": str(parent),
        "parent_device": int(metadata.st_dev),
        "parent_inode": int(metadata.st_ino),
        "runtime_root": str(root),
        "launchd_label": LAUNCHD_LABEL,
        "identity_sha256": identity,
    }


def _validate_runtime_lock_scope(
    value: Any,
    *,
    runtime_root: Path,
    launchd: Mapping[str, Any],
) -> None:
    if not isinstance(value, Mapping):
        raise DeploymentGateError("deployment_lock_identity_invalid")
    expected_identity = _runtime_lock_identity(runtime_root, LAUNCHD_LABEL)
    expected_path = _runtime_lock_path(runtime_root, launchd)
    parent = expected_path.parent
    if (
        value.get("path") != str(expected_path)
        or value.get("parent_path") != str(parent)
        or value.get("runtime_root") != str(Path(os.path.abspath(runtime_root)))
        or value.get("launchd_label") != LAUNCHD_LABEL
        or value.get("identity_sha256") != expected_identity
        or isinstance(value.get("parent_device"), bool)
        or not isinstance(value.get("parent_device"), int)
        or value.get("parent_device") < 0
        or isinstance(value.get("parent_inode"), bool)
        or not isinstance(value.get("parent_inode"), int)
        or value.get("parent_inode") <= 0
    ):
        raise DeploymentGateError("deployment_lock_identity_invalid")


@contextmanager
def deployment_lock(lock_scope: Mapping[str, Any]):
    _validate_runtime_lock_scope(
        lock_scope,
        runtime_root=Path(str(lock_scope.get("runtime_root") or "")),
        launchd={
            "label": lock_scope.get("launchd_label"),
            "runner_path": str(
                Path(str(lock_scope.get("parent_path") or "")) / "run-local-service.sh"
            ),
        },
    )
    parent_descriptor: int | None = None
    descriptor: int | None = None
    path = Path(str(lock_scope["path"]))
    parent = Path(str(lock_scope["parent_path"]))
    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    lock_flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        try:
            parent_descriptor = os.open(parent, parent_flags)
            parent_metadata = os.fstat(parent_descriptor)
            if (
                not stat.S_ISDIR(parent_metadata.st_mode)
                or int(parent_metadata.st_dev) != lock_scope.get("parent_device")
                or int(parent_metadata.st_ino) != lock_scope.get("parent_inode")
            ):
                raise DeploymentGateError("deployment_lock_parent_drift")
            descriptor = os.open(
                path.name,
                lock_flags,
                0o600,
                dir_fd=parent_descriptor,
            )
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise DeploymentGateError("deployment_lock_invalid")
        except DeploymentGateError:
            raise
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EINVAL, errno.ENOTDIR}:
                raise DeploymentGateError("deployment_lock_invalid") from exc
            raise DeploymentGateError("deployment_lock_unavailable") from exc
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeploymentGateError("deployment_lock_busy") from exc
        yield
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _launchctl_scalar(output: str, field: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(field)}\s*=\s*(.+?)\s*$", output)
    if match is None:
        raise DeploymentGateError("launchd_loaded_identity_invalid")
    return match.group(1)


def _launchctl_block(output: str, field: str) -> list[str]:
    lines = output.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if re.fullmatch(rf"\s*{re.escape(field)}\s*=\s*\{{\s*", line):
            start = index + 1
            break
    if start is None:
        raise DeploymentGateError("launchd_loaded_identity_invalid")
    values: list[str] = []
    for line in lines[start:]:
        if re.fullmatch(r"\s*}\s*", line):
            return values
        stripped = line.strip()
        if stripped:
            values.append(stripped)
    raise DeploymentGateError("launchd_loaded_identity_invalid")


def _launchctl_environment(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _launchctl_block(output, "environment"):
        if " => " not in line:
            raise DeploymentGateError("launchd_loaded_identity_invalid")
        key, value = line.split(" => ", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in values:
            raise DeploymentGateError("launchd_loaded_identity_invalid")
        values[key] = value
    return values


def probe_launchd(
    label: str,
    runtime_root: Path,
    *,
    command_runner: Callable[..., Any] = subprocess.run,
    uid: int | None = None,
    plist_path: Path | None = None,
    runner_path: Path | None = None,
    working_directory: Path | None = None,
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
    expected_runner = (
        runner_path
        if runner_path is not None
        else Path.home() / RUNTIME_SUPPORT_RELATIVE / "run-local-service.sh"
    ).resolve(strict=False)
    expected_working_directory = (
        working_directory if working_directory is not None else Path.home()
    ).resolve(strict=False)
    if not isinstance(environment, Mapping):
        raise DeploymentGateError("launchd_environment_invalid")
    environment_dict = {str(key): str(value) for key, value in environment.items()}
    environment_keys = set(environment_dict)
    if (
        not REQUIRED_LAUNCHD_ENVIRONMENT.issubset(environment_keys)
        or not environment_keys.issubset(
            REQUIRED_LAUNCHD_ENVIRONMENT | OPTIONAL_LAUNCHD_ENVIRONMENT
        )
        or environment_dict.get("PATH") != LAUNCHD_PATH
        or environment_dict.get("GUIYI_PROJECT_ROOT") != root
    ):
        raise DeploymentGateError("launchd_environment_invalid")
    for optional_path in OPTIONAL_LAUNCHD_ENVIRONMENT & environment_keys:
        if not Path(environment_dict[optional_path]).is_absolute():
            raise DeploymentGateError("launchd_environment_invalid")
    expected_arguments = ["/bin/bash", str(expected_runner), "scheduler"]
    if (
        payload.get("Label") != label
        or not isinstance(arguments, list)
        or arguments != expected_arguments
        or payload.get("WorkingDirectory") != str(expected_working_directory)
    ):
        raise DeploymentGateError("launchd_plist_identity_invalid")
    loaded_program = _launchctl_scalar(output, "program")
    loaded_arguments = _launchctl_block(output, "arguments")
    loaded_environment = _launchctl_environment(output)
    accepted_loaded_environments = (
        environment_dict,
        {**environment_dict, **SYSTEM_INJECTED_LAUNCHD_ENVIRONMENT},
    )
    loaded_working_directory = _launchctl_scalar(output, "working directory")
    loaded_plist_path = Path(_launchctl_scalar(output, "path")).resolve(strict=False)
    if (
        loaded_program != "/bin/bash"
        or loaded_arguments != expected_arguments
        or loaded_environment not in accepted_loaded_environments
        or loaded_working_directory != str(expected_working_directory)
        or loaded_plist_path != selected_plist
    ):
        raise DeploymentGateError("launchd_loaded_identity_mismatch")
    runner_sha256 = _sha256_file(expected_runner)
    return {
        "label": label,
        "loaded": True,
        "pid": int(pid_match.group(1)),
        "plist_path": str(selected_plist),
        "plist_sha256": _sha256_file(selected_plist),
        "loaded_program": loaded_program,
        "program_arguments": loaded_arguments,
        "environment": environment_dict,
        "working_directory": loaded_working_directory,
        "project_root": root,
        "runner_path": str(expected_runner),
        "runner_sha256": runner_sha256,
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
        "heartbeat_at": scheduler.get("heartbeat_at"),
        "last_cycle_status": str(scheduler.get("last_cycle_status") or ""),
        "signal_events_enabled": scheduler.get("signal_events_enabled") is True,
        "signal_event_authorization_hash": scheduler.get("signal_event_authorization_hash"),
    }


def _validate_foundation_receipt(path: Path, sha256: str) -> dict[str, Any]:
    try:
        from app.services.live_signal_event_gate import validate_s6_final_receipt

        return validate_s6_final_receipt(path, expected_sha256=sha256)
    except Exception as exc:
        raise DeploymentGateError("foundation_receipt_invalid") from exc


def _validate_database_recovery_receipt(
    path: Path,
    sha256: str,
) -> dict[str, Any]:
    try:
        from app.services.s607_database_recovery import (
            verify_semantic_recovery_receipt,
        )

        if _sha256_file(path) != sha256:
            raise DeploymentGateError(
                "database_recovery_receipt_hash_mismatch"
            )
        receipt = _read_json_object(path)
        verify_semantic_recovery_receipt(receipt)
        return {
            "path": str(path.resolve(strict=True)),
            "sha256": sha256,
            "receipt_hash": receipt["receipt_hash"],
            "packet_hash": receipt["packet_hash"],
        }
    except DeploymentGateError:
        raise
    except Exception as exc:
        raise DeploymentGateError(
            "database_recovery_receipt_invalid"
        ) from exc


def default_dependencies() -> GateDependencies:
    runner = subprocess.run
    uid = os.getuid()
    return GateDependencies(
        command_runner=runner,
        source_probe=lambda root, receipt: probe_source_git(
            root,
            foundation_receipt=receipt,
            command_runner=runner,
        ),
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
        recovery_validator=_validate_database_recovery_receipt,
    )


def collect_deployment_bound_facts(
    *,
    source_root: Path,
    runtime_root: Path,
    s6_final_receipt: Path,
    s6_final_receipt_sha256: str,
    database_recovery_receipt: Path,
    database_recovery_receipt_sha256: str,
    runtime_env: Path,
    output_root: Path,
    packet_path: Path,
    deployment_receipt_path: Path,
    dependencies: GateDependencies,
) -> dict[str, Any]:
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
    recovery_receipt = dependencies.recovery_validator(
        database_recovery_receipt,
        database_recovery_receipt_sha256,
    )
    d1_day, d2_day, lineage_prefixes, d2_batch = _foundation_evidence_scope(receipt)
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
        "evidence_scope": {
            "d1_trading_day": d1_day.isoformat(),
            "d2_trading_day": d2_day.isoformat(),
            "lineage_commit_prefixes": sorted(lineage_prefixes),
            "d2_batch_id": d2_batch,
        },
    }
    source = exclude_htdy_output_evidence(
        dependencies.source_probe(source_root, receipt),
        output_root=output_root,
    )
    runtime = dependencies.runtime_probe(runtime_root)
    target_commit = str(source.get("commit") or "")
    current_commit = str(runtime.get("current_commit") or "")
    foundation_commit = str(foundation.get("runtime_commit") or "")
    _command(
        dependencies.command_runner,
        ("git", "cat-file", "-e", f"{target_commit}^{{commit}}"),
        cwd=runtime_root.resolve(strict=False),
        error_type="target_commit_not_local",
    )
    foundation_ancestry = _command(
        dependencies.command_runner,
        ("git", "merge-base", "--is-ancestor", foundation_commit, current_commit),
        cwd=runtime_root.resolve(strict=False),
        error_type="foundation_runtime_ancestry_probe_failed",
        check=False,
    )
    if int(getattr(foundation_ancestry, "returncode", 0) or 0) != 0:
        raise DeploymentGateError("foundation_runtime_not_ancestor")
    ancestry = _command(
        dependencies.command_runner,
        ("git", "merge-base", "--is-ancestor", current_commit, target_commit),
        cwd=runtime_root.resolve(strict=False),
        error_type="runtime_ancestry_probe_failed",
        check=False,
    )
    if int(getattr(ancestry, "returncode", 0) or 0) != 0:
        raise DeploymentGateError("runtime_not_ancestor")
    launchd = dependencies.launchd_probe(LAUNCHD_LABEL, runtime_root)
    resolved_runtime_env = validate_runtime_environment_cli_path(runtime_env, launchd)
    environment_result = dependencies.runtime_env_probe(resolved_runtime_env)
    if not isinstance(environment_result, RuntimeEnvironmentResult):
        raise DeploymentGateError("runtime_env_probe_invalid")
    environment = environment_result.facts
    database = dependencies.database_probe(environment_result.database_url)
    health = dependencies.health_probe()
    runtime_lock = collect_runtime_lock_scope(
        runtime_root=Path(str(runtime["root"])),
        launchd=launchd,
    )
    output_scope = collect_output_scope(
        output_root=output_root,
        packet_path=packet_path,
        receipt_path=deployment_receipt_path,
        protected_paths=[
            *(
                []
                if _is_htdy_schema_v3_output_root(
                    output_root,
                    source_root=Path(str(source["root"])),
                )
                else [Path(str(source["root"]))]
            ),
            Path(str(runtime["root"])),
            Path(str(environment["path"])),
            Path(str(launchd["plist_path"])),
            Path(str(launchd["runner_path"])),
            Path(str(source["git_dir"])),
            Path(str(source["git_common_dir"])),
            Path(str(runtime["git_dir"])),
            Path(str(runtime["git_common_dir"])),
            Path(str(runtime_lock["parent_path"])),
        ],
    )
    facts = {
        "source_git": source,
        "target_commit": target_commit,
        "runtime": runtime,
        "foundation_receipt": foundation,
        "database_recovery_receipt": recovery_receipt,
        "database": database,
        "runtime_environment": environment,
        "launchd": launchd,
        "runtime_health": health,
        "runtime_lock": runtime_lock,
        "output_scope": output_scope,
    }
    validate_bound_facts(facts)
    return facts


def _is_htdy_schema_v3_output_root(
    output_root: Path,
    *,
    source_root: Path,
) -> bool:
    try:
        relative = output_root.resolve(strict=True).relative_to(
            source_root.resolve(strict=True)
        )
    except (FileNotFoundError, OSError, ValueError):
        return False
    return (
        _HTDY_SCHEMA_V3_OUTPUT_ROOT.fullmatch(relative.as_posix())
        is not None
    )


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
    environment = value.get("environment")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or not Path(str(value.get("plist_path") or "")).is_absolute()
        or not _is_lower_hex(value.get("plist_sha256"), 64)
        or value.get("loaded_program") != "/bin/bash"
        or not isinstance(arguments, list)
        or len(arguments) != 3
        or arguments[0] != "/bin/bash"
        or arguments[2] != "scheduler"
        or not isinstance(environment, Mapping)
        or not REQUIRED_LAUNCHD_ENVIRONMENT.issubset(environment)
        or not set(environment).issubset(
            REQUIRED_LAUNCHD_ENVIRONMENT | OPTIONAL_LAUNCHD_ENVIRONMENT
        )
        or environment.get("PATH") != LAUNCHD_PATH
        or environment.get("GUIYI_PROJECT_ROOT") != value.get("project_root")
        or not Path(str(value.get("working_directory") or "")).is_absolute()
        or not Path(str(value.get("project_root") or "")).is_absolute()
        or not Path(str(value.get("runner_path") or "")).is_absolute()
        or arguments[1] != value.get("runner_path")
        or not _is_lower_hex(value.get("runner_sha256"), 64)
    ):
        raise DeploymentGateError("launchd_identity_invalid")


def _health_datetime(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise DeploymentGateError("post_health_failed") from exc
    if parsed.tzinfo is None:
        raise DeploymentGateError("post_health_failed")
    return parsed.astimezone(UTC)


def validate_post_health(
    health: Mapping[str, Any],
    *,
    pre_health: Mapping[str, Any],
) -> None:
    if (
        health.get("status") != "ok"
        or health.get("scheduler_status") != "ok"
        or health.get("last_cycle_status") not in {"idle", "running", "success"}
        or health.get("signal_events_enabled") is not False
        or health.get("signal_event_authorization_hash") not in {None, ""}
        or _health_datetime(health.get("heartbeat_at"))
        <= _health_datetime(pre_health.get("heartbeat_at"))
    ):
        raise DeploymentGateError("post_health_failed")


def _validate_pre_health(health: Any) -> None:
    try:
        if (
            not isinstance(health, Mapping)
            or health.get("status") != "ok"
            or health.get("scheduler_status") != "ok"
            or health.get("last_cycle_status") not in {"idle", "running", "success"}
            or health.get("signal_events_enabled") is not False
            or health.get("signal_event_authorization_hash") not in {None, ""}
        ):
            raise DeploymentGateError("runtime_health_invalid")
        _health_datetime(health.get("heartbeat_at"))
    except (DeploymentGateError, TypeError, ValueError) as exc:
        raise DeploymentGateError("runtime_health_invalid") from exc


def _validate_restart_baseline_health(health: Any) -> None:
    if not isinstance(health, Mapping):
        raise DeploymentGateError("rollback_health_baseline_invalid")
    try:
        _health_datetime(health.get("heartbeat_at"))
    except DeploymentGateError as exc:
        raise DeploymentGateError("rollback_health_baseline_invalid") from exc


def _validate_output_scope(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise DeploymentGateError("output_scope_invalid")
    root = Path(str(value.get("root") or ""))
    packet = Path(str(value.get("packet_path") or ""))
    receipt = Path(str(value.get("receipt_path") or ""))
    devices = (
        value.get("root_device"),
        value.get("packet_device"),
        value.get("receipt_device"),
    )
    parent_inodes = (
        value.get("packet_parent_inode"),
        value.get("receipt_parent_inode"),
    )
    if (
        not root.is_absolute()
        or not packet.is_absolute()
        or not receipt.is_absolute()
        or packet == receipt
        or not packet.is_relative_to(root)
        or not receipt.is_relative_to(root)
        or any(isinstance(device, bool) or not isinstance(device, int) or device < 0 for device in devices)
        or any(
            isinstance(inode, bool) or not isinstance(inode, int) or inode <= 0
            for inode in parent_inodes
        )
        or len(set(devices)) != 1
    ):
        raise DeploymentGateError("output_scope_invalid")


def validate_bound_facts(facts: Mapping[str, Any]) -> None:
    source = facts.get("source_git")
    runtime = facts.get("runtime")
    foundation = facts.get("foundation_receipt")
    recovery_receipt = facts.get("database_recovery_receipt")
    database = facts.get("database")
    environment = facts.get("runtime_environment")
    if not all(
        isinstance(value, Mapping)
        for value in (
            source,
            runtime,
            foundation,
            recovery_receipt,
            database,
            environment,
        )
    ):
        raise DeploymentGateError("bound_facts_invalid")
    if (
        not Path(str(source.get("root") or "")).is_absolute()
        or source.get("branch") not in ALLOWED_SOURCE_BRANCHES
        or not _is_lower_hex(source.get("commit"), 40)
        or source.get("commit") != source.get("local_main")
        or not _is_lower_hex(source.get("origin_main"), 40)
        or isinstance(source.get("ahead_of_origin"), bool)
        or not isinstance(source.get("ahead_of_origin"), int)
        or source.get("ahead_of_origin") < 0
        or not _is_lower_hex(source.get("tree"), 40)
        or source.get("tracked_clean") is not True
        or not Path(str(source.get("git_dir") or "")).is_absolute()
        or not Path(str(source.get("git_common_dir") or "")).is_absolute()
        or source.get("runner_relative_path") != RUNNER_RELATIVE.as_posix()
        or not _is_lower_hex(source.get("runner_worktree_sha256"), 64)
        or source.get("runner_worktree_sha256") != source.get("runner_target_blob_sha256")
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
        or not Path(str(runtime.get("git_dir") or "")).is_absolute()
        or not Path(str(runtime.get("git_common_dir") or "")).is_absolute()
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
    if (
        not str(database.get("driver") or "").startswith("postgresql")
        or not _is_lower_hex(database.get("identity_sha256"), 64)
        or database.get("read_only") is not True
        or database.get("rolled_back") is not True
    ):
        raise DeploymentGateError("database_identity_invalid")
    if (
        not str(recovery_receipt.get("path") or "").endswith(
            "recovery_receipt.json"
        )
        or not _is_lower_hex(recovery_receipt.get("sha256"), 64)
        or not _is_lower_hex(
            recovery_receipt.get("receipt_hash"),
            64,
        )
        or recovery_receipt.get("packet_hash")
        != "443adda6d2b3f0e82edaeff1d72e9ff4"
        "a6d194b0f1d78928a034f175f513c2f3"
    ):
        raise DeploymentGateError(
            "database_recovery_receipt_invalid"
        )
    if database.get("revision") != REQUIRED_DB_REVISION:
        raise DeploymentGateError("database_revision_invalid")
    if foundation.get("database_revision") != database.get("revision"):
        raise DeploymentGateError("foundation_database_mismatch")
    if (
        not Path(str(environment.get("path") or "")).is_absolute()
        or not _is_lower_hex(environment.get("file_sha256"), 64)
        or isinstance(environment.get("device"), bool)
        or not isinstance(environment.get("device"), int)
        or environment.get("device") < 0
        or isinstance(environment.get("inode"), bool)
        or not isinstance(environment.get("inode"), int)
        or environment.get("inode") <= 0
        or isinstance(environment.get("size"), bool)
        or not isinstance(environment.get("size"), int)
        or environment.get("size") < 0
    ):
        raise DeploymentGateError("runtime_env_invalid")
    _validate_safe_flags(environment.get("flags"))
    launchd = facts.get("launchd")
    _validate_launchd_facts(launchd)
    if launchd.get("project_root") != runtime.get("root"):
        raise DeploymentGateError("launchd_runtime_root_mismatch")
    if launchd.get("runner_sha256") != source.get("runner_target_blob_sha256"):
        raise DeploymentGateError("installed_runner_hash_mismatch")
    if Path(str(environment.get("path"))) != resolve_runtime_environment_path(launchd):
        raise DeploymentGateError("runtime_env_path_mismatch")
    _validate_pre_health(facts.get("runtime_health"))
    _validate_runtime_lock_scope(
        facts.get("runtime_lock"),
        runtime_root=Path(str(runtime.get("root"))),
        launchd=launchd,
    )
    _validate_output_scope(facts.get("output_scope"))


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
            "database, safe flag, launchd, plist, or packet hash drift invalidates approval; "
            "runtime heartbeat may only advance monotonically"
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
    bound_facts = packet.get("bound_facts")
    if not isinstance(bound_facts, Mapping):
        raise DeploymentGateError("bound_facts_invalid")
    validate_bound_facts(bound_facts)


def verify_deployment_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
) -> None:
    _validate_packet_identity_and_hash(packet, approval_hash)
    bound_facts = packet.get("bound_facts")
    if not isinstance(bound_facts, Mapping):
        raise DeploymentGateError("bound_fact_drift")
    if set(bound_facts) != set(current_facts):
        raise DeploymentGateError("bound_fact_drift")
    for key in bound_facts:
        if key != "runtime_health" and bound_facts[key] != current_facts[key]:
            raise DeploymentGateError("bound_fact_drift")
    bound_health = bound_facts.get("runtime_health")
    current_health = current_facts.get("runtime_health")
    if not isinstance(bound_health, Mapping) or not isinstance(current_health, Mapping):
        raise DeploymentGateError("bound_fact_drift")
    if set(bound_health) != set(current_health):
        raise DeploymentGateError("bound_fact_drift")
    for key in bound_health:
        if key not in {"heartbeat_at", "last_cycle_status"} and bound_health[key] != current_health[key]:
            raise DeploymentGateError("bound_fact_drift")
    try:
        if _health_datetime(current_health.get("heartbeat_at")) < _health_datetime(
            bound_health.get("heartbeat_at")
        ):
            raise DeploymentGateError("bound_fact_drift")
    except DeploymentGateError as exc:
        raise DeploymentGateError("bound_fact_drift") from exc
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


def write_json_create_only(
    path: Path,
    payload: Mapping[str, Any],
    *,
    parent_device: int,
    parent_inode: int,
) -> None:
    output = Path(os.path.abspath(path))
    parent = output.parent
    parent_descriptor: int | None = None
    descriptor: int | None = None
    created_identity: tuple[int, int] | None = None
    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    output_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        try:
            parent_descriptor = os.open(parent, parent_flags)
        except FileNotFoundError as exc:
            raise DeploymentGateError("output_parent_invalid") from exc
        except OSError as exc:
            raise DeploymentGateError("output_parent_drift") from exc
        parent_metadata = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or int(parent_metadata.st_dev) != parent_device
            or int(parent_metadata.st_ino) != parent_inode
        ):
            raise DeploymentGateError("output_parent_drift")
        descriptor = os.open(
            output.name,
            output_flags,
            0o600,
            dir_fd=parent_descriptor,
        )
        created_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(created_metadata.st_mode):
            raise DeploymentGateError("output_target_invalid")
        created_identity = (
            int(created_metadata.st_dev),
            int(created_metadata.st_ino),
        )
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
        if parent_descriptor is not None and created_identity is not None:
            try:
                current = os.stat(
                    output.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if (
                    int(current.st_dev),
                    int(current.st_ino),
                ) == created_identity:
                    os.unlink(output.name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        raise
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)


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
    try:
        _validate_launchd_facts(launchd)
    except DeploymentGateError as exc:
        raise DeploymentGateError("post_launchd_drift") from exc
    for key in LAUNCHD_IDENTITY_FIELDS:
        if launchd.get(key) != previous.get(key):
            raise DeploymentGateError("post_launchd_drift")
    if require_new_pid and launchd.get("pid") == previous.get("pid"):
        raise DeploymentGateError("scheduler_pid_not_restarted")


POST_VERIFY_ATTEMPTS = 60
POST_VERIFY_INTERVAL_SECONDS = 1.0


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
    last_error: DeploymentGateError | None = None
    launchd: dict[str, Any] | None = None
    health: dict[str, Any] | None = None
    for attempt in range(POST_VERIFY_ATTEMPTS):
        try:
            launchd = dependencies.launchd_probe(LAUNCHD_LABEL, runtime_root)
            _validate_post_launchd(launchd, previous=facts["launchd"], require_new_pid=True)
            health = dependencies.health_probe()
            validate_post_health(health, pre_health=facts["runtime_health"])
            break
        except DeploymentGateError as exc:
            last_error = exc
            if attempt + 1 < POST_VERIFY_ATTEMPTS:
                time.sleep(POST_VERIFY_INTERVAL_SECONDS)
    else:
        raise DeploymentGateError(
            last_error.error_type if last_error is not None else "post_health_failed"
        )
    runtime = dependencies.runtime_probe(runtime_root)
    _validate_post_runtime(
        runtime,
        expected_commit=str(facts["target_commit"]),
        expected_tree=str(source["tree"]),
        expected_uv=str(source["uv_lock_sha256"]),
    )
    environment_result = dependencies.runtime_env_probe(
        Path(str(facts["runtime_environment"]["path"]))
    )
    if not isinstance(environment_result, RuntimeEnvironmentResult):
        raise DeploymentGateError("runtime_env_probe_invalid")
    environment = environment_result.facts
    _validate_safe_flags(environment.get("flags"))
    if environment != facts["runtime_environment"]:
        raise DeploymentGateError("post_runtime_env_drift")
    database = dependencies.database_probe(environment_result.database_url)
    if database != facts["database"]:
        raise DeploymentGateError("post_database_drift")
    assert launchd is not None and health is not None
    return runtime, database, environment, launchd, health


def _verify_rollback(
    *,
    facts: Mapping[str, Any],
    dependencies: GateDependencies,
    runtime_root: Path,
    restart_launchd: Mapping[str, Any],
    restart_health: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    _validate_post_launchd(
        restart_launchd,
        previous=facts["launchd"],
        require_new_pid=False,
    )
    _validate_restart_baseline_health(restart_health)
    last_error: DeploymentGateError | None = None
    launchd: dict[str, Any] | None = None
    health: dict[str, Any] | None = None
    for attempt in range(POST_VERIFY_ATTEMPTS):
        try:
            launchd = dependencies.launchd_probe(LAUNCHD_LABEL, runtime_root)
            _validate_post_launchd(
                launchd,
                previous=restart_launchd,
                require_new_pid=True,
            )
            health = dependencies.health_probe()
            validate_post_health(health, pre_health=restart_health)
            break
        except DeploymentGateError as exc:
            last_error = exc
            if attempt + 1 < POST_VERIFY_ATTEMPTS:
                time.sleep(POST_VERIFY_INTERVAL_SECONDS)
    else:
        raise DeploymentGateError(
            last_error.error_type if last_error is not None else "rollback_health_failed"
        )
    previous_runtime = facts["runtime"]
    runtime = dependencies.runtime_probe(runtime_root)
    _validate_post_runtime(
        runtime,
        expected_commit=str(previous_runtime["current_commit"]),
        expected_tree=str(previous_runtime["tree"]),
        expected_uv=str(previous_runtime["uv_lock_sha256"]),
    )
    environment_result = dependencies.runtime_env_probe(
        Path(str(facts["runtime_environment"]["path"]))
    )
    if not isinstance(environment_result, RuntimeEnvironmentResult):
        raise DeploymentGateError("runtime_env_probe_invalid")
    environment = environment_result.facts
    _validate_safe_flags(environment.get("flags"))
    if environment != facts["runtime_environment"]:
        raise DeploymentGateError("rollback_runtime_env_drift")
    if dependencies.database_probe(environment_result.database_url) != facts["database"]:
        raise DeploymentGateError("rollback_database_drift")
    assert launchd is not None and health is not None
    return launchd, health


def _error_code(exc: Exception) -> str:
    if isinstance(exc, DeploymentGateError):
        return exc.error_type
    return "unexpected_error"


def _write_failure_receipt(
    path: Path,
    *,
    output_scope: Mapping[str, Any],
    packet_hash: str,
    previous_commit: str,
    target_commit: str,
    error_type: str,
    trigger_error_type: str,
    rollback_attempted: bool,
    rollback_succeeded: bool,
    rollback_restart: Mapping[str, Any] | None = None,
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
                "restart": dict(rollback_restart or {}),
            },
            "scope_note": "code-only Runtime deployment; no database, env, notification, EOD, API, or worker write",
        },
        parent_device=int(output_scope["receipt_device"]),
        parent_inode=int(output_scope["receipt_parent_inode"]),
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
    bound_receipt = Path(str(current_facts["output_scope"]["receipt_path"]))
    if receipt_out.resolve(strict=False) != bound_receipt:
        raise DeploymentGateError("deployment_receipt_path_mismatch")
    if bound_receipt.exists():
        raise DeploymentGateError("output_already_exists")
    facts = current_facts
    runtime_root = Path(str(facts["runtime"]["root"]))
    previous_commit = str(facts["runtime"]["current_commit"])
    target_commit = str(facts["target_commit"])
    packet_hash = str(packet["packet_hash"])
    target_owned = False
    restart_attempted = False
    rollback_restart: dict[str, Any] = {}
    try:
        switch_error: DeploymentGateError | None = None
        try:
            _run_mutation(
                dependencies,
                ("git", "switch", "--detach", target_commit),
                runtime_root=runtime_root,
                error_type="runtime_switch_failed",
            )
        except DeploymentGateError as exc:
            switch_error = exc
        switched_runtime = dependencies.runtime_probe(runtime_root)
        switched_head = str(switched_runtime.get("current_commit") or "")
        if switched_head == target_commit:
            target_owned = True
        elif switched_head == previous_commit:
            raise switch_error or DeploymentGateError("runtime_switch_failed")
        else:
            raise DeploymentGateError("runtime_switch_concurrent_drift")
        _validate_post_runtime(
            switched_runtime,
            expected_commit=target_commit,
            expected_tree=str(facts["source_git"]["tree"]),
            expected_uv=str(facts["source_git"]["uv_lock_sha256"]),
        )
        if switch_error is not None:
            raise switch_error
        try:
            dependencies.runtime_sanitizer(runtime_root)
        except Exception as exc:
            raise DeploymentGateError("python_artifact_purge_failed") from exc
        restart_attempted = True
        _run_mutation(
            dependencies,
            _kickstart_command(dependencies.uid),
            runtime_root=runtime_root,
            error_type="scheduler_kickstart_failed",
        )
        _, database, environment, launchd, health = _post_deployment_verification(
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
            "health": {
                "status": health["status"],
                "scheduler_status": health["scheduler_status"],
                "heartbeat_at": health["heartbeat_at"],
                "last_cycle_status": health["last_cycle_status"],
                "signal_events_enabled": health["signal_events_enabled"],
                "signal_event_authorization_hash": health[
                    "signal_event_authorization_hash"
                ],
            },
            "health_verified": True,
            "rollback": False,
            "completed_at": datetime.now(UTC).isoformat(),
            "scope_note": "research observation only; no notification, order, or automatic trading authorization",
        }
        write_json_create_only(
            receipt_out,
            receipt,
            parent_device=int(facts["output_scope"]["receipt_device"]),
            parent_inode=int(facts["output_scope"]["receipt_parent_inode"]),
        )
        return receipt
    except Exception as exc:
        trigger_error = _error_code(exc)
        rollback_attempted = False
        rollback_succeeded = False
        if target_owned:
            try:
                current_runtime = dependencies.runtime_probe(runtime_root)
                current_head = str(current_runtime.get("current_commit") or "")
                if current_head == target_commit:
                    rollback_attempted = True
                    _run_mutation(
                        dependencies,
                        ("git", "switch", "--detach", previous_commit),
                        runtime_root=runtime_root,
                        error_type="rollback_runtime_switch_failed",
                    )
                    restored = dependencies.runtime_probe(runtime_root)
                    _validate_post_runtime(
                        restored,
                        expected_commit=previous_commit,
                        expected_tree=str(facts["runtime"]["tree"]),
                        expected_uv=str(facts["runtime"]["uv_lock_sha256"]),
                    )
                    if restart_attempted:
                        restart_launchd = dependencies.launchd_probe(
                            LAUNCHD_LABEL,
                            runtime_root,
                        )
                        _validate_post_launchd(
                            restart_launchd,
                            previous=facts["launchd"],
                            require_new_pid=False,
                        )
                        restart_health = dependencies.health_probe()
                        _validate_restart_baseline_health(restart_health)
                        rollback_restart = {
                            "previous_pid": restart_launchd["pid"],
                            "previous_heartbeat_at": restart_health["heartbeat_at"],
                        }
                        _run_mutation(
                            dependencies,
                            _kickstart_command(dependencies.uid),
                            runtime_root=runtime_root,
                            error_type="rollback_scheduler_kickstart_failed",
                        )
                        rollback_launchd, rollback_health = _verify_rollback(
                            facts=facts,
                            dependencies=dependencies,
                            runtime_root=runtime_root,
                            restart_launchd=restart_launchd,
                            restart_health=restart_health,
                        )
                        rollback_restart.update(
                            new_pid=rollback_launchd["pid"],
                            new_heartbeat_at=rollback_health["heartbeat_at"],
                        )
                    rollback_succeeded = True
                elif current_head not in {previous_commit, target_commit}:
                    trigger_error = "runtime_switch_concurrent_drift"
            except Exception:
                rollback_succeeded = False
        if rollback_attempted and not rollback_succeeded:
            final_error = "rollback_failed"
        else:
            final_error = trigger_error
        try:
            _write_failure_receipt(
                receipt_out,
                output_scope=facts["output_scope"],
                packet_hash=packet_hash,
                previous_commit=previous_commit,
                target_commit=target_commit,
                error_type=final_error,
                trigger_error_type=trigger_error,
                rollback_attempted=rollback_attempted,
                rollback_succeeded=rollback_succeeded,
                rollback_restart=rollback_restart,
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
        args.output_root,
    )
    if any(value in (None, "") for value in common):
        raise DeploymentGateError("required_argument_missing")
    if not _is_lower_hex(args.s6_final_receipt_sha256, 64):
        raise DeploymentGateError("sha256_invalid")
    if (
        args.database_recovery_receipt is None
        or args.database_recovery_receipt_sha256 is None
    ):
        raise DeploymentGateError("required_argument_missing")
    if not _is_lower_hex(
        args.database_recovery_receipt_sha256,
        64,
    ):
        raise DeploymentGateError("sha256_invalid")
    if args.prepare_deploy_packet:
        if args.packet_out is None or args.deployment_receipt_out is None:
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
    packet_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    return fact_collector(
        source_root=PROJECT_ROOT,
        runtime_root=args.runtime_root,
        s6_final_receipt=args.s6_final_receipt,
        s6_final_receipt_sha256=args.s6_final_receipt_sha256,
        database_recovery_receipt=args.database_recovery_receipt,
        database_recovery_receipt_sha256=(
            args.database_recovery_receipt_sha256
        ),
        runtime_env=args.runtime_env,
        output_root=args.output_root,
        packet_path=packet_path,
        deployment_receipt_path=receipt_path,
        dependencies=dependencies,
    )


def _validate_packet_cli_paths(
    packet: Mapping[str, Any],
    args: argparse.Namespace,
) -> tuple[Path, Path, Path]:
    output_scope = (packet.get("bound_facts") or {}).get("output_scope")
    if not isinstance(output_scope, Mapping):
        raise DeploymentGateError("output_scope_invalid")
    root = Path(str(output_scope.get("root") or ""))
    packet_path = Path(str(output_scope.get("packet_path") or ""))
    receipt_path = Path(str(output_scope.get("receipt_path") or ""))
    if (
        args.output_root.resolve(strict=False) != root
        or args.approval_packet.resolve(strict=False) != packet_path
    ):
        raise DeploymentGateError("output_scope_cli_mismatch")
    if (
        args.confirm_deploy
        and args.deployment_receipt_out.resolve(strict=False) != receipt_path
    ):
        raise DeploymentGateError("deployment_receipt_path_mismatch")
    if (
        args.deployment_receipt_out is not None
        and args.deployment_receipt_out.resolve(strict=False) != receipt_path
    ):
        raise DeploymentGateError("deployment_receipt_path_mismatch")
    return root, packet_path, receipt_path


def _preexecution_failure_receipt(
    args: argparse.Namespace,
    error_type: str,
    *,
    output_scope: Mapping[str, Any],
) -> None:
    if (
        not args.confirm_deploy
        or args.deployment_receipt_out is None
        or error_type in {"deployment_lock_busy", "output_already_exists"}
        or args.deployment_receipt_out.resolve(strict=False).exists()
    ):
        return
    _write_failure_receipt(
        args.deployment_receipt_out,
        output_scope=output_scope,
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
    receipt_authorized = False
    authorized_output_scope: Mapping[str, Any] | None = None
    try:
        _validate_cli_arguments(args)
        if (
            args.confirm_deploy
            and args.deployment_receipt_out.resolve(strict=False).exists()
        ):
            raise DeploymentGateError("output_already_exists")
        if args.prepare_deploy_packet:
            if args.packet_out.resolve(strict=False).exists():
                raise DeploymentGateError("output_already_exists")
            if args.deployment_receipt_out.resolve(strict=False).exists():
                raise DeploymentGateError("output_already_exists")
            facts = _collect_from_args(
                args,
                dependencies=deps,
                fact_collector=collector,
                packet_path=args.packet_out,
                receipt_path=args.deployment_receipt_out,
            )
            packet = build_deployment_packet(facts)
            write_json_create_only(
                args.packet_out,
                packet,
                parent_device=int(facts["output_scope"]["packet_device"]),
                parent_inode=int(facts["output_scope"]["packet_parent_inode"]),
            )
            status = "approval_required"
        else:
            packet = _read_json_object(args.approval_packet)
            _validate_packet_identity_and_hash(packet, str(args.approval_hash))
            _, packet_path, receipt_path = _validate_packet_cli_paths(packet, args)
            receipt_authorized = True
            authorized_output_scope = packet["bound_facts"]["output_scope"]
            if args.verify_deploy_packet:
                facts = _collect_from_args(
                    args,
                    dependencies=deps,
                    fact_collector=collector,
                    packet_path=packet_path,
                    receipt_path=receipt_path,
                )
                verify_deployment_packet(
                    packet,
                    approval_hash=str(args.approval_hash),
                    current_facts=facts,
                )
                status = "verified"
            else:
                lock_scope = packet["bound_facts"]["runtime_lock"]
                with deployment_lock(lock_scope):
                    if receipt_path.exists():
                        raise DeploymentGateError("output_already_exists")
                    facts = _collect_from_args(
                        args,
                        dependencies=deps,
                        fact_collector=collector,
                        packet_path=packet_path,
                        receipt_path=receipt_path,
                    )
                    verify_deployment_packet(
                        packet,
                        approval_hash=str(args.approval_hash),
                        current_facts=facts,
                    )
                    execute_confirmed_deployment(
                        packet=packet,
                        approval_hash=str(args.approval_hash),
                        current_facts=facts,
                        receipt_out=receipt_path,
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
        if receipt_authorized:
            try:
                assert authorized_output_scope is not None
                _preexecution_failure_receipt(
                    args,
                    error_type,
                    output_scope=authorized_output_scope,
                )
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
