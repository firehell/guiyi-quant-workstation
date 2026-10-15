"""Read-only Runtime identity primitives; no recovery or deployment policy."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import NoReturn

from app.core.env import PROJECT_ROOT

class RuntimeIdentityError(ValueError):
    """Bounded identity failure, adapted by the calling workflow."""
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

def _reject(code: str) -> NoReturn:
    raise RuntimeIdentityError(code) from None

def runtime_heartbeat_identity() -> dict[str, object]:
    """Code-root identity plus the launcher's whitelisted commit declaration."""
    commit = os.environ.get("GUIYI_RUNTIME_COMMIT", "")
    identity: dict[str, object] = {
        "runtime_root": str(PROJECT_ROOT),
        "runtime_commit": commit if re.fullmatch(r"[0-9a-f]{40}", commit) else None,
    }
    generation = os.environ.get("GUIYI_RUNTIME_GENERATION", "")
    tag = os.environ.get("GUIYI_RUNTIME_TAG", "")
    if re.fullmatch(r"[1-9][0-9]*", generation) and re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        identity.update(runtime_generation=int(generation), runtime_tag=tag)
    return identity

def command_result(
    arguments: list[str], *, root: Path, capture_stderr: bool = False
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            arguments, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if capture_stderr else subprocess.DEVNULL,
            text=True, timeout=5, check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        _reject("IDENTITY_UNAVAILABLE")
    if not isinstance(result.stdout, str) or (
        capture_stderr and not isinstance(result.stderr, str)
    ):
        _reject("IDENTITY_UNAVAILABLE")
    return result

def read_command(arguments: list[str], *, root: Path) -> str:
    result = command_result(arguments, root=root)
    if result.returncode != 0:
        _reject("IDENTITY_UNAVAILABLE")
    return result.stdout.strip()

def read_launchd_service(label: str, *, root: Path) -> str | None:
    """Return one loaded definition, or None only for an explicit label absence."""
    if re.fullmatch(
        r"com\.guiyi\.quant-(?:api|web|live|alert|after-market|late-provider-recovery|log-rotate|weekly-audit|reference-worker|market-feed)(?:-candidate-[0-9a-f]{32})?",
        label,
    ) is None:
        _reject("IDENTITY_UNAVAILABLE")
    domain = f"gui/{os.getuid()}"
    read_command(["/bin/launchctl", "print", domain], root=root)
    result = command_result(
        ["/bin/launchctl", "print", f"{domain}/{label}"],
        root=root,
        capture_stderr=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    unavailable = result.stdout + result.stderr
    explicit_absence = (
        f'Could not find service "{label}" in domain for user gui: {os.getuid()}'
    )
    if result.returncode == 113 and unavailable in {
        explicit_absence,
        f"{explicit_absence}\n",
        f"Bad request.\n{explicit_absence}",
        f"Bad request.\n{explicit_absence}\n",
    }:
        return None
    _reject("IDENTITY_UNAVAILABLE")

def verify_loaded_service(
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

@contextmanager
def safe_directory(path: Path) -> Iterator[int]:
    """Pin an absolute directory without following any ancestor alias."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError
        yield fd
    finally:
        os.close(fd)

def file_snapshot(path: Path, *, private: bool = False, limit: int = 1024 * 1024) -> tuple[bytes, tuple[int, ...]]:
    with safe_directory(path.parent) as directory:
        if private and stat.S_IMODE(os.fstat(directory).st_mode) != 0o700:
            raise ValueError
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                    or info.st_mode & 0o022 or info.st_size > limit
                    or private and stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError
            content = os.read(fd, limit + 1)
            def identity(item):
                return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
            after = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            if len(content) != info.st_size or identity(info) != identity(os.fstat(fd)) or identity(info) != identity(after):
                raise ValueError
            return content, identity(after)
        finally:
            os.close(fd)

def launchd_arguments(output: str) -> tuple[str, ...]:
    scopes: list[str] = []
    values: list[str] = []
    seen = False
    for raw in output.splitlines():
        line = raw.strip()
        if line.endswith((" = {", " => {")):
            name = line.rsplit(" ", 2)[0]
            scopes.append(name)
            if len(scopes) == 2 and name == "arguments":
                if seen:
                    raise ValueError
                seen = True
        elif line == "}":
            if not scopes:
                raise ValueError
            scopes.pop()
        elif len(scopes) == 2 and scopes[-1] == "arguments":
            values.append(line)
    if scopes or not seen:
        raise ValueError
    return tuple(values)

def launchd_environments(output: str) -> tuple[dict[str, str], ...]:
    """Read only direct launchd environment scopes, never event descriptors."""
    names = {"environment", "inherited environment", "default environment"}
    scopes: list[tuple[str, str]] = []
    result: dict[str, dict[str, str]] = {}
    for raw in output.splitlines():
        line = raw.strip()
        if line.endswith((" = {", " => {")):
            name, operator, _ = line.rsplit(" ", 2)
            if not scopes and operator != "=":
                raise ValueError
            if len(scopes) == 2 and scopes[-1][0] in names:
                raise ValueError
            if name in names:
                if len(scopes) != 1 or operator != "=" or name in result:
                    raise ValueError
                result[name] = {}
            scopes.append((name, operator))
        elif line == "}":
            if not scopes:
                raise ValueError
            scopes.pop()
        elif len(scopes) == 2 and scopes[-1][0] in names:
            match = re.fullmatch(r"([^\s]+) => (.*)", line)
            if match is None or match[1] in result[scopes[-1][0]]:
                raise ValueError
            result[scopes[-1][0]][match[1]] = match[2]
    if scopes or "environment" not in result:
        raise ValueError
    return tuple(result.values())
