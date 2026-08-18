"""Pinned WeChat-Courier dependency and sanitized child-process runner."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

from app.alerts.notification import (
    ALERT_CANARY_TEXT,
    AlertNotificationMessage,
    format_alert_message,
)
from app.alerts.wechat_group_config import WeChatGroupTarget
from app.core.env import PROJECT_ROOT


VERSIONS_FILE = PROJECT_ROOT / "deploy/wechat-courier/versions.json"
ADAPTER_PATH = PROJECT_ROOT / "services/quant-api/app/alerts/wechat_courier_adapter.py"
_REPOSITORY = "bladydora/WeChat-Courier-macOS"
_TIMEOUT_SECONDS = 45.0
_PUBLIC_ERROR_CODES = {
    "WECHAT_COURIER_BUSY",
    "WECHAT_GROUP_TARGET_UNVERIFIED",
    "WECHAT_COURIER_DEPENDENCY_INVALID",
    "WECHAT_COURIER_SEND_FAILED",
}


class WeChatCourierError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class WeChatCourierDependency:
    root: Path
    source_root: Path
    python_executable: Path
    upstream_commit: str


@dataclass(frozen=True, slots=True)
class WeChatGroupSendSummary:
    attempted: int
    automation_completed: int
    failed: int
    failed_aliases: tuple[str, ...]


RunProcess = Callable[..., subprocess.CompletedProcess[str]]
DependencyResolver = Callable[[Path], WeChatCourierDependency]


def _is_private_directory(path: Path) -> bool:
    try:
        metadata = path.stat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == 0o700
        and metadata.st_uid == os.getuid()
    )


def _load_versions() -> str:
    try:
        payload = json.loads(VERSIONS_FILE.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "repository", "commit"}
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
            or payload["repository"] != _REPOSITORY
            or not isinstance(payload["commit"], str)
            or len(payload["commit"]) != 40
            or any(character not in "0123456789abcdef" for character in payload["commit"])
        ):
            raise ValueError
        return payload["commit"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError):
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID") from None


def _contained(root: Path, path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        return resolved
    except (OSError, ValueError):
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID") from None


def _contained_executable_entry(root: Path, path: Path) -> Path:
    """Contain the venv entry while allowing its standard interpreter symlink."""
    try:
        resolved_parent = path.parent.resolve(strict=True)
        resolved_parent.relative_to(root)
        return resolved_parent / path.name
    except (OSError, ValueError):
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID") from None


def resolve_wechat_courier_dependency(
    root: Path,
    *,
    run_process: RunProcess = subprocess.run,
) -> WeChatCourierDependency:
    """Resolve only the exact clean detached source and dedicated Python."""
    commit = _load_versions()
    if not root.is_absolute():
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID") from None
    if not resolved_root.is_dir():
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")

    source_root = _contained(resolved_root, resolved_root / "source")
    git_metadata = _contained(resolved_root, source_root / ".git")
    module_path = _contained(resolved_root, source_root / "wechat_courier.py")
    python_executable = _contained_executable_entry(
        resolved_root,
        resolved_root / "venv/bin/python",
    )
    required_directories = (
        _contained(resolved_root, resolved_root / "runtime"),
        _contained(resolved_root, resolved_root / "tmp"),
        _contained(resolved_root, resolved_root / "cache/clang"),
    )
    if (
        not _is_private_directory(resolved_root)
        or not source_root.is_dir()
        or not git_metadata.is_dir()
        or not module_path.is_file()
        or not all(_is_private_directory(directory) for directory in required_directories)
    ):
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
    try:
        unresolved_git_head = git_metadata / "HEAD"
        if unresolved_git_head.is_symlink():
            raise ValueError
        git_head = _contained(resolved_root, unresolved_git_head)
        if (
            not git_head.is_file()
            or git_head.read_text(encoding="ascii").strip() != commit
        ):
            raise ValueError
    except (OSError, UnicodeError, ValueError):
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID") from None
    try:
        python_mode = python_executable.stat().st_mode
    except OSError:
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID") from None
    if not stat.S_ISREG(python_mode) or not os.access(python_executable, os.X_OK):
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")

    commands = (
        ["/usr/bin/git", "-C", str(source_root), "rev-parse", "HEAD"],
        ["/usr/bin/git", "-C", str(source_root), "status", "--porcelain"],
    )
    results: list[subprocess.CompletedProcess[str]] = []
    try:
        for command in commands:
            results.append(
                run_process(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10.0,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                )
            )
    except (OSError, subprocess.SubprocessError):
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID") from None
    if (
        any(result.returncode != 0 for result in results)
        or results[0].stdout.strip() != commit
        or results[1].stdout.strip()
    ):
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
    return WeChatCourierDependency(
        root=resolved_root,
        source_root=source_root,
        python_executable=python_executable,
        upstream_commit=commit,
    )


def courier_child_environment(root: Path) -> dict[str, str]:
    return {
        "PATH": f"{root}/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": str(root / "tmp"),
        "CLANG_MODULE_CACHE_PATH": str(root / "cache/clang"),
        "PYTHONUNBUFFERED": "1",
    }


@contextmanager
def _nonblocking_gui_lock(dependency: WeChatCourierDependency):
    lock_path = dependency.root / "runtime/guiyi-wechat-courier.lock"
    descriptor: int | None = None
    try:
        if not _is_private_directory(lock_path.parent):
            raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WeChatCourierError("WECHAT_COURIER_BUSY") from None
        yield
    except WeChatCourierError:
        raise
    except OSError:
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID") from None
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(descriptor)


class WeChatCourierRunner:
    def __init__(
        self,
        dependency: WeChatCourierDependency,
        *,
        run_process: RunProcess = subprocess.run,
        resolve_dependency: DependencyResolver = resolve_wechat_courier_dependency,
    ) -> None:
        self._dependency = dependency
        self._run_process = run_process
        self._resolve_dependency = resolve_dependency

    def verify_target(self, target: WeChatGroupTarget) -> None:
        payload = {
            "action": "verify",
            "target_chat": target.target_chat,
            "upstream_root": str(self._dependency.source_root),
            "upstream_commit": self._dependency.upstream_commit,
        }
        self._run_child(payload, {"status": "verified"})

    def send_text(self, target: WeChatGroupTarget, text: str) -> None:
        payload = {
            "action": "send",
            "target_chat": target.target_chat,
            "text": text,
            "upstream_root": str(self._dependency.source_root),
            "upstream_commit": self._dependency.upstream_commit,
        }
        self._run_child(payload, {"status": "sent"})

    def _run_child(self, payload: dict[str, str], expected: dict[str, str]) -> None:
        try:
            with _nonblocking_gui_lock(self._dependency):
                refreshed = self._resolve_dependency(self._dependency.root)
                if refreshed != self._dependency:
                    raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
                result = self._run_process(
                    [str(self._dependency.python_executable), str(ADAPTER_PATH)],
                    input=json.dumps(payload, separators=(",", ":")),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=_TIMEOUT_SECONDS,
                    env=courier_child_environment(self._dependency.root),
                    cwd=str(self._dependency.root / "runtime"),
                )
            parsed: Any = json.loads(result.stdout)
        except WeChatCourierError:
            raise
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID") from None
        if result.returncode != 0:
            code = parsed.get("error_code") if isinstance(parsed, dict) else None
            if code in _PUBLIC_ERROR_CODES:
                raise WeChatCourierError(code)
            raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
        if parsed != expected:
            raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")


class WeChatGroupAlertSender:
    def __init__(
        self,
        *,
        target: WeChatGroupTarget,
        runner: WeChatCourierRunner,
    ) -> None:
        self._target = target
        self._runner = runner

    def send(self, message: AlertNotificationMessage) -> None:
        text = format_alert_message(message)
        self._runner.send_text(self._target, text)

    def verify_target(self) -> None:
        self._runner.verify_target(self._target)

    def send_canary(self) -> WeChatGroupSendSummary:
        try:
            self._runner.send_text(self._target, ALERT_CANARY_TEXT)
        except WeChatCourierError:
            return WeChatGroupSendSummary(
                attempted=1,
                automation_completed=0,
                failed=1,
                failed_aliases=(self._target.group_alias,),
            )
        return WeChatGroupSendSummary(
            attempted=1,
            automation_completed=1,
            failed=0,
            failed_aliases=(),
        )
