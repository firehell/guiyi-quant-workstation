"""Read-only installed and loaded identities; never expose launchd environments."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import plistlib
import re
from typing import Any

from app.market_data.captured_recovery_runtime import _read_launchd_service, _verify_loaded_service
from app.market_data.closeout_binding import _arguments, _environments, _snapshot
from app.runtime_bindings import RuntimeBindingError, authorized_program_arguments, bindings_sha256, read_bindings, verify_release

SERVICE_LABELS = {
    "live_market": "live", "after_market": "after-market", "alert": "alert",
    "weekly_audit": "weekly-audit", "late_provider_recovery": "late-provider-recovery",
    "reference_worker": "reference-worker",
}


def deployment_identity_health(*, root: Path, commit: str, home: Path | None = None,
                               service_reader: Callable | None = None) -> dict:
    account_home = Path.home() if home is None else home
    reader = _read_launchd_service if service_reader is None else service_reader
    services: dict[str, dict[str, Any]] = {}
    try:
        registry = read_bindings(home=account_home)
        registry_digest = bindings_sha256(home=account_home) if registry is not None else None
    except RuntimeBindingError:
        return {"status": "unknown", "services": {name: {
            "status": "unknown", "error_type": "runtime_binding_registry_invalid"
        } for name in SERVICE_LABELS}}
    labels = SERVICE_LABELS if registry is None else {
        next((key for key, value in SERVICE_LABELS.items() if value == service), service): service
        for service in registry.services
    }
    for name, service in labels.items():
        label = f"com.guiyi.quant-{service}"
        result: dict[str, Any] = {"status": "unknown", "error_type": "runtime_identity_unavailable"}
        try:
            if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
                raise ValueError
            binding = None if registry is None else registry.services[service]
            if binding is not None:
                label = binding.label
            expected_root = root if binding is None else Path(binding.root)
            expected_commit = commit if binding is None else binding.commit
            if binding is not None:
                verify_release(expected_root, binding.tag, binding.commit)
            path = account_home / "Library/LaunchAgents" / f"{label}.plist"
            try:
                path.lstat()
            except FileNotFoundError:
                if binding is not None:
                    if binding.enabled or reader(label, root=expected_root) is not None:
                        raise ValueError
                    services[name] = {"status": "disabled", "error_type": None,
                        "runtime_root": binding.root, "runtime_commit": binding.commit,
                        "runtime_generation": binding.generation, "runtime_tag": binding.tag}
                    continue
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
            arguments: tuple[str, ...] = (
                ("/bin/bash", str(installed_root / "scripts/ops/macos/run-local-service.sh"), "weekly-audit-scheduled")
                if service == "weekly-audit" and binding is None else
                ("/bin/bash", str(account_home / "Library/Application Support/GuiyiQuant/run-local-service.sh"), service)
            )
            if binding is not None:
                arguments = authorized_program_arguments(binding, account_home)
            if (not installed_root.is_absolute() or installed_root != installed_root.resolve(strict=True)
                    or not isinstance(installed_commit, str)
                    or re.fullmatch(r"[0-9a-f]{40}", installed_commit) is None
                    or payload.get("Label") != label
                    or (binding is None and payload.get("WorkingDirectory") != str(installed_root))
                    or tuple(payload.get("ProgramArguments", ())) != arguments):
                raise ValueError
            if binding is not None and not binding.enabled:
                if reader(label, root=expected_root) is not None:
                    raise ValueError
                result = {"status": "disabled", "error_type": None,
                          "runtime_root": binding.root, "runtime_commit": binding.commit,
                          "runtime_generation": binding.generation, "runtime_tag": binding.tag}
                services[name] = result
                continue
            output = reader(label, root=expected_root)
            if output is None:
                raise ValueError
            working_directory = account_home if binding is not None and service in {"api", "web"} else installed_root
            if payload.get("WorkingDirectory") != str(working_directory):
                raise ValueError
            _verify_loaded_service(output, root=installed_root, commit=installed_commit,
                allow_idle=service in {"after-market", "weekly-audit", "late-provider-recovery"},
                working_directory=working_directory)
            if _arguments(output) != arguments or _snapshot(path)[1] != stamp:
                raise ValueError
            if binding is not None:
                declarations = {"GUIYI_RUNTIME_GENERATION": str(binding.generation), "GUIYI_RUNTIME_TAG": binding.tag}
                if any(environment.get(key) != value for key, value in declarations.items()):
                    raise ValueError
                loaded = [item for item in _environments(output)
                          if item.get("GUIYI_PROJECT_ROOT") == binding.root
                          and item.get("GUIYI_RUNTIME_COMMIT") == binding.commit]
                if len(loaded) != 1 or any(loaded[0].get(key) != value for key, value in declarations.items()):
                    raise ValueError
            matched = installed_root == expected_root and installed_commit == expected_commit
            result = {"status": "matched" if matched else "mismatch",
                "runtime_root": str(installed_root), "runtime_commit": installed_commit,
                "error_type": None if matched else "runtime_identity_mismatch"}
            if binding is not None:
                result.update(runtime_generation=binding.generation, runtime_tag=binding.tag)
        except (OSError, ValueError, TypeError, KeyError, plistlib.InvalidFileException):
            pass
        services[name] = result
    if registry is not None:
        try:
            if bindings_sha256(home=account_home) != registry_digest:
                raise RuntimeBindingError("REGISTRY_DRIFT")
        except RuntimeBindingError:
            return {"status": "unknown", "services": {name: {
                "status": "unknown", "error_type": "runtime_binding_registry_drift"
            } for name in labels}}
    statuses = {item["status"] for item in services.values()}
    status = "mismatch" if "mismatch" in statuses else "unknown" if "unknown" in statuses else "matched"
    return {"status": status, "services": services}
