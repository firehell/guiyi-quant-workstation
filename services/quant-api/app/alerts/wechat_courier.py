"""Pinned WeChat-Courier dependency and sanitized child-process runner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

from app.alerts.wechat_group_config import WeChatGroupTarget
from app.core.env import PROJECT_ROOT


VERSIONS_FILE = PROJECT_ROOT / "deploy/wechat-courier/versions.json"
ADAPTER_PATH = PROJECT_ROOT / "services/quant-api/app/alerts/wechat_courier_adapter.py"
_REPOSITORY = "bladydora/WeChat-Courier-macOS"
_TIMEOUT_SECONDS = 45.0


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


RunProcess = Callable[..., subprocess.CompletedProcess[str]]


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
    python_executable = _contained(resolved_root, resolved_root / "venv/bin/python")
    required_directories = (
        _contained(resolved_root, resolved_root / "runtime"),
        _contained(resolved_root, resolved_root / "tmp"),
        _contained(resolved_root, resolved_root / "cache/clang"),
    )
    if (
        not source_root.is_dir()
        or not git_metadata.is_dir()
        or not module_path.is_file()
        or not all(directory.is_dir() for directory in required_directories)
    ):
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
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


class WeChatCourierRunner:
    def __init__(
        self,
        dependency: WeChatCourierDependency,
        *,
        run_process: RunProcess = subprocess.run,
    ) -> None:
        self._dependency = dependency
        self._run_process = run_process

    def verify_target(self, target: WeChatGroupTarget) -> None:
        payload = {
            "action": "verify",
            "target_chat": target.target_chat,
            "upstream_root": str(self._dependency.source_root),
        }
        try:
            result = self._run_process(
                [str(self._dependency.python_executable), str(ADAPTER_PATH)],
                input=json.dumps(payload, separators=(",", ":")),
                capture_output=True,
                text=True,
                check=False,
                timeout=_TIMEOUT_SECONDS,
                env=courier_child_environment(self._dependency.root),
            )
            parsed: Any = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID") from None
        if result.returncode != 0:
            code = parsed.get("error_code") if isinstance(parsed, dict) else None
            if code in {
                "WECHAT_GROUP_TARGET_UNVERIFIED",
                "WECHAT_COURIER_DEPENDENCY_INVALID",
            }:
                raise WeChatCourierError(code)
            raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
        if parsed != {"status": "verified"}:
            raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
