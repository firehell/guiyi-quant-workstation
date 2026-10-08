"""Read-only installed and loaded identities; never expose launchd environments."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import plistlib
import re

from app.market_data.captured_recovery_runtime import _read_launchd_service, _verify_loaded_service
from app.market_data.closeout_binding import _arguments, _snapshot

SERVICE_LABELS = {
    "live_market": "live", "after_market": "after-market", "alert": "alert",
    "weekly_audit": "weekly-audit", "late_provider_recovery": "late-provider-recovery",
    "reference_worker": "reference-worker",
}


def deployment_identity_health(*, root: Path, commit: str, home: Path | None = None,
                               service_reader: Callable | None = None) -> dict:
    account_home = Path.home() if home is None else home
    reader = _read_launchd_service if service_reader is None else service_reader
    services = {}
    for name, service in SERVICE_LABELS.items():
        label = f"com.guiyi.quant-{service}"
        result = {"status": "unknown", "error_type": "runtime_identity_unavailable"}
        try:
            if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
                raise ValueError
            path = account_home / "Library/LaunchAgents" / f"{label}.plist"
            try:
                path.lstat()
            except FileNotFoundError:
                # Only explicit host absence plus absent real activation is disabled.
                marker = {
                    "live": "market-runtime-enabled", "after-market": "market-runtime-enabled",
                    "late-provider-recovery": "market-runtime-enabled", "alert": "alert-runtime-enabled",
                    "weekly-audit": "weekly-audit-enabled", "reference-worker": "reference-worker-enabled",
                }[service]
                output = reader(label, root=root)
                if output is not None:
                    raise ValueError
                try:
                    (root / ".run" / marker).lstat()
                except FileNotFoundError:
                    result = {"status": "disabled", "error_type": None}
                    services[name] = result
                    continue
                raise ValueError
            content, stamp = _snapshot(path)
            payload = plistlib.loads(content)
            if not isinstance(payload, dict):
                raise ValueError
            environment = payload.get("EnvironmentVariables")
            if not isinstance(environment, dict):
                raise ValueError
            installed_root = Path(environment["GUIYI_PROJECT_ROOT"])
            installed_commit = environment["GUIYI_RUNTIME_COMMIT"]
            arguments = (
                ("/bin/bash", str(installed_root / "scripts/ops/macos/run-local-service.sh"), "weekly-audit-scheduled")
                if service == "weekly-audit" else
                ("/bin/bash", str(account_home / "Library/Application Support/GuiyiQuant/run-local-service.sh"), service)
            )
            if (not installed_root.is_absolute() or installed_root != installed_root.resolve(strict=True)
                    or not isinstance(installed_commit, str)
                    or re.fullmatch(r"[0-9a-f]{40}", installed_commit) is None
                    or payload.get("Label") != label
                    or payload.get("WorkingDirectory") != str(installed_root)
                    or tuple(payload.get("ProgramArguments", ())) != arguments):
                raise ValueError
            output = reader(label, root=root)
            if output is None:
                raise ValueError
            _verify_loaded_service(output, root=installed_root, commit=installed_commit,
                allow_idle=service in {"after-market", "weekly-audit", "late-provider-recovery"})
            if _arguments(output) != arguments or _snapshot(path)[1] != stamp:
                raise ValueError
            matched = installed_root == root and installed_commit == commit
            result = {"status": "matched" if matched else "mismatch",
                "runtime_root": str(installed_root), "runtime_commit": installed_commit,
                "error_type": None if matched else "runtime_identity_mismatch"}
        except (OSError, ValueError, TypeError, KeyError, plistlib.InvalidFileException):
            pass
        services[name] = result
    statuses = {item["status"] for item in services.values()}
    status = "mismatch" if "mismatch" in statuses else "unknown" if "unknown" in statuses else "matched"
    return {"status": status, "services": services}
