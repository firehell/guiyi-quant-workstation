"""Explicit local administration. No trading endpoint is exposed over HTTP."""

import argparse
from pathlib import Path
from datetime import datetime, UTC
import json
import os
import plistlib
import subprocess
import re
from .runtime import (
    directory,
    private_folder,
    write_private,
    read_private,
    write_private_bytes,
    launcher_path,
    verify_launcher,
)
from .credentials import CredentialStore, setup_dialog
from .worker import verify_config

LABEL = "com.guiyi.quant-tqkq-simulation"


def launch_state():
    p = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        if (
            "Could not find service" in p.stderr
            or "Could not find specified service" in p.stderr
        ):
            return None
        raise ValueError("TQ_LAUNCHD_STATE_UNKNOWN")
    match = re.search(r"^\s*pid = ([0-9]+)$", p.stdout, re.M)
    return {"pid": int(match.group(1)) if match else None}


def config(root, tag, account):
    root = Path(root).resolve(strict=True)
    commit = subprocess.run(
        [
            "/usr/bin/git",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(root),
            "rev-parse",
            tag + "^{commit}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    result = {
        "schema": 1,
        "provider": "TQKQ",
        "account_id": account,
        "root": str(root),
        "commit": commit,
        "tag": tag,
    }
    verify_config(result)
    bindings = read_private(
        Path.home() / "Library/Application Support/GuiyiQuant/service-bindings.json"
    )
    if bindings["services"]["api"]["root"] != str(root):
        raise ValueError("TQ_FORMAL_API_ROOT_MISMATCH")
    return result


def service_environment(root):
    # Match the launchd job for preflight; terminal proxy variables must not
    # make a successful probe conceal a missing service-side dependency.
    import pwd

    user = pwd.getpwuid(os.getuid()).pw_name
    return {
        "HOME": str(Path.home()),
        "USER": user,
        "LOGNAME": user,
        "GUIYI_PROJECT_ROOT": str(root),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    }


def service_command(root, *, inspect=False):
    return ["/bin/bash", str(launcher_path()), *(["--inspect"] if inspect else [])]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "credentials",
            "configure",
            "probe",
            "install",
            "start",
            "status",
            "pause",
            "stop",
        ),
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--trade", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "credentials":
            account = setup_dialog(replace=args.replace)
            print(
                json.dumps(
                    {"status": "TQ_CREDENTIAL_STORED", "account_fingerprint": account}
                )
            )
            return 0
        base = private_folder(directory())
        path = base / "config.json"
        if args.action == "configure":
            if not args.root or not args.tag:
                raise ValueError("TQ_RELEASE_ARGUMENTS_REQUIRED")
            state = launch_state()
            if state and state["pid"]:
                raise ValueError("TQ_STOP_BEFORE_RECONFIGURE")
            current = config(args.root, args.tag, CredentialStore().load().account_id)
            write_private(path, current)
            write_private(base / "control.json", {"mode": "observe"})
            print(
                json.dumps({"status": "TQ_CONFIGURED_DISABLED", "tag": current["tag"]})
            )
            return 0
        if args.action == "status":
            value = (
                read_private(base / "monitor.json")
                if (base / "monitor.json").exists()
                else None
            )
            print(
                json.dumps(
                    {
                        "status": "NOT_STARTED"
                        if value is None
                        else value["overview"]["status"],
                        "observer": None
                        if value is None
                        else value["overview"]["observer"],
                        "block_code": None
                        if value is None
                        else value["overview"].get("block_code"),
                        "runtime_tag": None
                        if value is None
                        else value.get("runtime_tag"),
                        "launchd": launch_state(),
                    }
                )
            )
            return 0
        current = read_private(path, limit=8192)
        root = verify_config(current)
        if args.action in {"pause", "stop"}:
            write_private(base / "control.json", {"mode": args.action})
            print(
                json.dumps(
                    {
                        "status": "TQ_" + args.action.upper() + "_REQUESTED",
                        "automatic_flatten": False,
                    }
                )
            )
            return 0
        if CredentialStore().load().account_id != current["account_id"]:
            raise ValueError("TQ_CREDENTIAL_ACCOUNT_MISMATCH")
        if args.action == "probe":
            verify_launcher(root)
            if launch_state() and launch_state()["pid"]:
                raise ValueError("TQ_STOP_BEFORE_PROBE")
            return subprocess.run(
                service_command(root, inspect=True),
                cwd=Path.home(),
                env=service_environment(root),
                check=False,
            ).returncode
        if args.action == "install":
            state = launch_state()
            if state and state["pid"]:
                raise ValueError("TQ_STOP_BEFORE_INSTALL")
            if state:
                subprocess.run(
                    ["/bin/launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"],
                    check=True,
                    capture_output=True,
                )
                if launch_state() is not None:
                    raise ValueError("TQ_BOOTOUT_UNKNOWN")
            write_private_bytes(
                launcher_path(),
                (root / "scripts/ops/macos/run-tq-simulation.sh").read_bytes(),
            )
            verify_launcher(root)
            payload = {
                "Label": LABEL,
                "ProgramArguments": service_command(root),
                "WorkingDirectory": str(Path.home()),
                "EnvironmentVariables": service_environment(root),
                "RunAtLoad": True,
                "KeepAlive": False,
                "Umask": 0o077,
                "StandardOutPath": str(base / "runtime.log"),
                "StandardErrorPath": str(base / "runtime.log"),
            }
            installed = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
            raw = plistlib.dumps(payload, sort_keys=True)
            if installed.is_symlink():
                raise ValueError("TQ_PLIST_PATH_INVALID")
            write_private_bytes(installed, raw)
            print(
                json.dumps(
                    {"status": "TQ_INSTALLED_NOT_STARTED", "tag": current["tag"]}
                )
            )
            return 0
        if args.action == "start":
            verify_launcher(root)
            if (base / "hold.json").exists():
                raise ValueError("TQ_PERSISTED_HOLD_REQUIRES_RECONCILIATION")
            if args.trade:
                proof = read_private(base / "preflight.json")
                if (
                    proof.get("config") != current
                    or proof.get("ready_for_start") is not True
                    or not 0
                    <= (
                        datetime.now(UTC) - datetime.fromisoformat(proof["at"])
                    ).total_seconds()
                    <= 300
                ):
                    raise ValueError("TQ_FRESH_PREFLIGHT_REQUIRED")
            write_private(
                base / "control.json", {"mode": "trade" if args.trade else "observe"}
            )
            state = launch_state()
            if state is None:
                installed = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
                if installed.is_symlink() or not installed.is_file():
                    raise ValueError("TQ_INSTALL_REQUIRED")
                observed = plistlib.loads(installed.read_bytes())
                if (
                    observed.get("WorkingDirectory") != str(Path.home())
                    or observed.get("ProgramArguments") != service_command(root)
                    or observed.get("EnvironmentVariables") != service_environment(root)
                ):
                    raise ValueError("TQ_INSTALLED_ROOT_MISMATCH")
                subprocess.run(
                    [
                        "/bin/launchctl",
                        "bootstrap",
                        f"gui/{os.getuid()}",
                        str(installed),
                    ],
                    capture_output=True,
                    check=True,
                )
            elif state["pid"] is None:
                # A completed/failed job never earns an automatic retry. Explicit
                # start requires full fresh preflight and a clean replacement install.
                raise ValueError("TQ_EXPLICIT_REINSTALL_REQUIRED")
            print(
                json.dumps(
                    {
                        "status": "TQ_START_REQUESTED",
                        "mode": "trade" if args.trade else "observe",
                    }
                )
            )
            return 0
        return 1
    except Exception as error:
        code = str(error) if type(error) is ValueError else "TQ_ADMINISTRATION_BLOCKED"
        if not re.fullmatch("TQ_[A-Z0-9_]{1,100}", code):
            code = "TQ_ADMINISTRATION_BLOCKED"
        print(json.dumps({"status": "BLOCKED", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
