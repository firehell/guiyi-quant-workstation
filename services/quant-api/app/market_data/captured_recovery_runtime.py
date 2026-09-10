"""Read-only identity gate for captured recovery; never starts a service or provider."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
from typing import NoReturn

from app.core.env import PROJECT_ROOT


class CapturedRecoveryRuntimeError(ValueError):
    """Only a bounded public code crosses the preflight boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _reject(suffix: str) -> NoReturn:
    raise CapturedRecoveryRuntimeError(f"CAPTURED_RECOVERY_RUNTIME_{suffix}") from None


def runtime_heartbeat_identity() -> dict[str, object]:
    """Code-root identity plus the launcher's whitelisted commit declaration."""
    commit = os.environ.get("GUIYI_RUNTIME_COMMIT", "")
    return {
        "runtime_root": str(PROJECT_ROOT),
        "runtime_commit": commit if re.fullmatch(r"[0-9a-f]{40}", commit) else None,
    }


def _read_command(arguments: list[str], *, root: Path) -> str:
    try:
        result = subprocess.run(
            arguments, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=5, check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        _reject("IDENTITY_UNAVAILABLE")
    if result.returncode != 0 or not isinstance(result.stdout, str):
        _reject("IDENTITY_UNAVAILABLE")
    return result.stdout.strip()


def _verify_markers(root: Path) -> None:
    try:
        directory = os.open(root / ".run", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(directory)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
                _reject("MARKER_INVALID")
            for name in ("market-runtime-enabled", "alert-runtime-enabled"):
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                     dir_fd=directory)
                try:
                    info = os.fstat(descriptor)
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                            or stat.S_IMODE(info.st_mode) != 0o600
                            or info.st_nlink != 1 or info.st_size != 8
                            or os.read(descriptor, 9) != b"enabled\n"):
                        _reject("MARKER_INVALID")
                finally:
                    os.close(descriptor)
        finally:
            os.close(directory)
    except OSError:
        _reject("MARKER_INVALID")


def _verify_loaded_service(
    output: str, *, root: Path, commit: str, allow_idle: bool = False, require_idle: bool = False,
    require_guard: bool = False,
    working_directory: Path | None = None,
) -> dict[str, str]:
    # Never retain or report unrelated launchd environment keys or raw output.
    patterns = {
        "state": r"state = (.*)", "pid": r"pid = (.*)",
        "directory": r"working directory = (.*)",
        "root": r"GUIYI_PROJECT_ROOT => (.*)",
        "commit": r"GUIYI_RUNTIME_COMMIT => (.*)",
        "guard": r"GUIYI_LIVE_RECOVERY_ENABLED => (.*)",
    }
    fields: dict[str, str] = {}
    scopes: list[tuple[str, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if line.endswith((" = {", " => {")):
            name, operator, _brace = line.rsplit(" ", 2)
            if not scopes and operator != "=":
                _reject("SERVICE_IDENTITY_INVALID")
            scopes.append((name, operator))
            continue
        if line == "}":
            if not scopes:
                _reject("SERVICE_IDENTITY_INVALID")
            scopes.pop()
            continue
        for key, pattern in patterns.items():
            # Only the service's direct `environment = {` block is authoritative.
            in_environment = len(scopes) == 2 and scopes[-1] == ("environment", "=")
            if (key in {"root", "commit", "guard"} and not in_environment
                    or key not in {"root", "commit", "guard"} and len(scopes) != 1):
                continue
            match = re.fullmatch(pattern, line)
            if match is not None:
                if key in fields:
                    _reject("SERVICE_IDENTITY_INVALID")
                fields[key] = match.group(1)
    state = fields.get("state")
    allowed_states = {"running", "waiting", "not running"} if allow_idle else {"running"}
    if (scopes or state not in allowed_states
            or require_idle and (state != "not running" or "pid" in fields)
            or require_guard and fields.get("guard") != "1"
            or state == "running" and re.fullmatch(r"[1-9][0-9]{0,9}", fields.get("pid", "")) is None
            or fields.get("directory") != str(working_directory or root) or fields.get("root") != str(root)
            or fields.get("commit") != commit):
        _reject("SERVICE_IDENTITY_INVALID")
    return fields


def _verify_after_market_plist(*, root: Path, commit: str,
                               label: str = "com.guiyi.quant-after-market") -> None:
    """Require the installed schedule to retain the same guarded after-market code root."""
    if label not in {f"com.guiyi.quant-{name}" for name in ("api", "web", "live", "alert", "after-market")}:
        _reject("SERVICE_CONFIGURATION_INVALID")
    path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    try:
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(parent)
            if info.st_uid != os.getuid() or info.st_mode & 0o022:
                _reject("SERVICE_CONFIGURATION_INVALID")
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                info = os.fstat(descriptor)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o022 or not 0 < info.st_size <= 65536):
                    _reject("SERVICE_CONFIGURATION_INVALID")
                payload = plistlib.loads(os.read(descriptor, 65537))
            finally:
                os.close(descriptor)
        finally:
            os.close(parent)
    except (OSError, ValueError, plistlib.InvalidFileException):
        _reject("SERVICE_CONFIGURATION_INVALID")
    if not isinstance(payload, dict):
        _reject("SERVICE_CONFIGURATION_INVALID")
    environment = payload.get("EnvironmentVariables")
    if (payload.get("Label") != label
            or payload.get("WorkingDirectory") != str(Path.home() if label in {"com.guiyi.quant-api", "com.guiyi.quant-web"} else root)
            or not isinstance(environment, dict)
            or environment.get("GUIYI_PROJECT_ROOT") != str(root)
            or environment.get("GUIYI_RUNTIME_COMMIT") != commit):
        _reject("SERVICE_CONFIGURATION_INVALID")


def _verify_heartbeat(payload: dict | None, *, now: datetime, root: Path, commit: str) -> None:
    if (not isinstance(payload, dict) or payload.get("recovery_guard_enabled") is not True
            or payload.get("runtime_root") != str(root)
            or payload.get("runtime_commit") != commit):
        _reject("HEARTBEAT_INVALID")
    try:
        generated = datetime.fromisoformat(payload["generated_at"])
        if generated.tzinfo is None or generated.utcoffset() is None:
            _reject("HEARTBEAT_INVALID")
        if not timedelta(0) <= now - generated <= timedelta(seconds=30):
            _reject("HEARTBEAT_INVALID")
    except (KeyError, TypeError, ValueError, OverflowError):
        _reject("HEARTBEAT_INVALID")


def verify_captured_recovery_runtime(
    *, now: datetime, live_heartbeat: dict | None, alert_heartbeat: dict | None,
    root: Path = PROJECT_ROOT,
) -> str:
    """Require an exact clean detached release and fresh shared-guard evidence.

    ``root`` is a test seam; the public CLI must always use the code-root default.
    Heartbeats are supplied by the caller so this module never connects to Redis.
    """
    if os.environ.get("GUIYI_LIVE_RECOVERY_ENABLED") != "1":
        _reject("DISABLED")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        _reject("CLOCK_INVALID")
    try:
        if not root.is_absolute() or root != root.resolve(strict=True) or not root.is_dir():
            _reject("ROOT_INVALID")
    except (OSError, RuntimeError):
        _reject("ROOT_INVALID")
    git = ["/usr/bin/git", "-c", "core.fsmonitor=false"]
    if _read_command([*git, "rev-parse", "--show-toplevel"], root=root) != str(root):
        _reject("ROOT_INVALID")
    if _read_command([*git, "rev-parse", "--abbrev-ref", "HEAD"], root=root) != "HEAD":
        _reject("CODE_IDENTITY_INVALID")
    commit = _read_command([*git, "rev-parse", "HEAD"], root=root)
    tag = _read_command([*git, "describe", "--exact-match", "--tags", "HEAD"], root=root)
    if (re.fullmatch(r"[0-9a-f]{40}", commit) is None
            or re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) is None
            or _read_command([*git, "status", "--porcelain=v1", "--untracked-files=all"], root=root)):
        _reject("CODE_IDENTITY_INVALID")
    tag_ref = f"refs/tags/{tag}"
    if (_read_command([*git, "cat-file", "-t", tag_ref], root=root) != "tag"
            or _read_command([*git, "rev-parse", f"{tag_ref}^{{commit}}"], root=root) != commit):
        _reject("CODE_IDENTITY_INVALID")
    _verify_markers(root)
    for label in ("com.guiyi.quant-live", "com.guiyi.quant-alert"):
        output = _read_command(["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"], root=root)
        _verify_loaded_service(output, root=root, commit=commit)
    _verify_after_market_plist(root=root, commit=commit)
    output = _read_command(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/com.guiyi.quant-after-market"], root=root,
    )
    _verify_loaded_service(output, root=root, commit=commit, allow_idle=True)
    for heartbeat in (live_heartbeat, alert_heartbeat):
        _verify_heartbeat(heartbeat, now=now, root=root, commit=commit)
    return json.dumps({"root": str(root), "commit": commit, "tag": tag},
                      sort_keys=True, separators=(",", ":"))
