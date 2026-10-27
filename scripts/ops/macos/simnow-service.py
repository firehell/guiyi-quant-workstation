"""Render or explicitly install an isolated observe-only SimNow LaunchAgent.

No launchctl command is run. An installed agent starts at the next login; the
private config remains the source of mode and account identity.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import stat
import sys
import tempfile


LABEL = "com.guiyi.quant-simnow"


def _absolute(path, *, allow_symlink: bool = False) -> Path:
    value = Path(path)
    if not value.is_absolute() or (value.is_symlink() and not allow_symlink):
        raise ValueError("SERVICE_PATH_INVALID")
    return value


def render_launch_agent(settings, config_path, *, home: Path | None = None) -> bytes:
    """Return a deterministic, password-free LaunchAgent plist."""
    if settings.mode != "observe":
        raise ValueError("OBSERVE_ONLY")
    if type(settings.enabled) is not bool:
        raise ValueError("SERVICE_ENABLED_INVALID")
    if (
        type(settings.account_id) is not str
        or len(settings.account_id) != 64
        or any(c not in "0123456789abcdef" for c in settings.account_id)
    ):
        raise ValueError("SERVICE_ACCOUNT_INVALID")
    project_root = _absolute(settings.project_root)
    _absolute(settings.state_root)
    # Isolated venv interpreters normally link bin/python to the installed binary.
    sdk_python = _absolute(settings.sdk_python, allow_symlink=True)
    config_path = _absolute(config_path)
    if not config_path.is_file() or not sdk_python.is_file():
        raise ValueError("SERVICE_SOURCE_MISSING")
    runner = project_root / "scripts/broker/simnow_supervisor.py"
    if not runner.is_file():
        raise ValueError("SERVICE_RUNNER_MISSING")
    # launchd opens stdout/stderr before spawning the interpreter. Keep these
    # ordinary logs in the user's standard log root, not a protected volume.
    logs = (
        _absolute(home if home is not None else Path.home())
        / "Library/Logs/GuiyiQuant/SimNow"
    )
    value = {
        "Label": LABEL,
        "ProgramArguments": [
            str(sdk_python),
            "-I",
            str(runner),
            "--config",
            str(config_path),
            "--observe-only",
        ],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 60,
        "StandardOutPath": str(logs / "supervisor.out.log"),
        "StandardErrorPath": str(logs / "supervisor.err.log"),
    }
    return plistlib.dumps(value, fmt=plistlib.FMT_XML, sort_keys=True)


def _private_regular(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("PRIVATE_PATH_REQUIRED")
    info = path.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("PRIVATE_PATH_REQUIRED")


def _private_dir(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("PRIVATE_PATH_REQUIRED")
    info = path.stat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("PRIVATE_PATH_REQUIRED")


def install_observe(settings, config_path: Path, *, home: Path | None = None) -> Path:
    """Install only the observe plist, without loading or starting it."""
    if settings.mode != "observe" or settings.enabled is not True:
        raise ValueError("OBSERVE_ENABLED_REQUIRED")
    config_path = _absolute(config_path)
    _private_regular(config_path)
    state_root = _absolute(settings.state_root)
    _private_dir(state_root)
    user_home = _absolute(home if home is not None else Path.home())
    data = render_launch_agent(settings, config_path, home=user_home)
    logs = user_home / "Library/Logs/GuiyiQuant/SimNow"
    logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_dir(logs)
    base = user_home / "Library/LaunchAgents"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if base.is_symlink() or base.stat().st_uid != os.getuid():
        raise ValueError("SERVICE_TARGET_INVALID")
    target = base / f"{LABEL}.plist"
    if target.exists() or target.is_symlink():
        raise ValueError("SERVICE_ALREADY_EXISTS")
    fd, name = tempfile.mkstemp(prefix=f".{LABEL}.", dir=base)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Exclusive link prevents overwriting an existing user agent.
        os.link(name, target, follow_symlinks=False)
    finally:
        Path(name).unlink(missing_ok=True)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="SimNow observe LaunchAgent (默认只读计划)"
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--install-observe", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "packages" / "quant-core"))
    from guiyi_quant.simnow_execution.settings import load_settings

    try:
        settings = load_settings(args.config)
        if args.install_observe:
            target = install_observe(settings, args.config)
            print(f"OBSERVE_AGENT_INSTALLED path={target}")
        else:
            render_launch_agent(settings, args.config)
            print(f"OBSERVE_AGENT_PLAN_READY label={LABEL} enabled={settings.enabled}")
        return 0
    except Exception:
        print("SERVICE_PLAN_FAILED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
