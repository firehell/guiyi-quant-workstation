"""Fail-closed discovery and invocation of the private Weixin adapter seam."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Any, TextIO

from app.alerts.recipient_registry import (
    NotificationRecipient,
    RecipientRegistryDocument,
    RecipientRegistryError,
    add_recipient,
    load_recipient_registry,
    write_recipient_registry,
)
from app.core.env import PROJECT_ROOT


VERSIONS_FILE = PROJECT_ROOT / "deploy/openclaw/versions.json"
ADAPTER_PATH = PROJECT_ROOT / "services/quant-api/app/alerts/openclaw_weixin_adapter.mjs"
_INSPECT_PLUGIN_ID = "openclaw-weixin"
_COMMAND_TIMEOUT_SECONDS = 15.0
_ALIAS_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,31}")


class WeixinDependencyError(RuntimeError):
    """The pinned OpenClaw/Weixin dependency is unavailable or incompatible."""


class WeixinRegistrationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class OpenClawWeixinDependency:
    root: Path
    cli_executable: Path
    node_executable: Path
    plugin_root: Path
    openclaw_version: str
    plugin_version: str


RunProcess = Callable[..., subprocess.CompletedProcess[str]]


def _load_versions() -> dict[str, str]:
    try:
        raw = json.loads(VERSIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WeixinDependencyError("WEIXIN_VERSIONS_INVALID") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "openclaw",
        "openclaw_weixin",
        "node",
    }:
        raise WeixinDependencyError("WEIXIN_VERSIONS_INVALID")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise WeixinDependencyError("WEIXIN_VERSIONS_INVALID")
    for key in ("openclaw", "openclaw_weixin", "node"):
        if type(raw[key]) is not str or not raw[key]:
            raise WeixinDependencyError("WEIXIN_VERSIONS_INVALID")
    return {
        "openclaw": raw["openclaw"],
        "openclaw_weixin": raw["openclaw_weixin"],
        "node": raw["node"],
    }


def _contained_path(root: Path, candidate: Path) -> Path:
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise WeixinDependencyError("WEIXIN_DEPENDENCY_PATH_INVALID") from exc
    return resolved


def _fixed_executable(root: Path, relative_path: str) -> Path:
    executable = _contained_path(root, root / relative_path)
    try:
        mode = executable.stat().st_mode
    except OSError as exc:
        raise WeixinDependencyError("WEIXIN_DEPENDENCY_PATH_INVALID") from exc
    if not stat.S_ISREG(mode) or not os.access(executable, os.X_OK):
        raise WeixinDependencyError("WEIXIN_DEPENDENCY_PATH_INVALID")
    return executable


def openclaw_child_environment(root: Path) -> dict[str, str]:
    """Return the complete, intentionally non-inherited OpenClaw child environment."""
    return {
        "GUIYI_OPENCLAW_ROOT": str(root),
        "OPENCLAW_PREFIX": str(root / "runtime"),
        "OPENCLAW_STATE_DIR": str(root / "state"),
        "OPENCLAW_CONFIG_PATH": str(root / "state/openclaw.json"),
        "OPENCLAW_CONFIG": str(root / "state/openclaw.json"),
        "TMPDIR": str(root / "tmp"),
        "OPENCLAW_LOG_LEVEL": "FATAL",
        "npm_config_cache": str(root / "cache/npm"),
    }


def _run_checked_json(
    run_process: RunProcess,
    argv: list[str],
    *,
    environment: dict[str, str],
) -> dict[str, Any]:
    try:
        result = run_process(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            env=environment,
        )
        parsed = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise WeixinDependencyError("WEIXIN_DEPENDENCY_UNAVAILABLE") from exc
    if result.returncode != 0 or not isinstance(parsed, dict):
        raise WeixinDependencyError("WEIXIN_DEPENDENCY_UNAVAILABLE")
    return parsed


def resolve_openclaw_weixin_dependency(
    root: Path,
    *,
    run_process: RunProcess = subprocess.run,
) -> OpenClawWeixinDependency:
    """Resolve only the exact pinned CLI, Node executable, and loaded plugin."""
    versions = _load_versions()
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise WeixinDependencyError("WEIXIN_DEPENDENCY_PATH_INVALID") from exc
    if not resolved_root.is_dir() or not resolved_root.is_absolute():
        raise WeixinDependencyError("WEIXIN_DEPENDENCY_PATH_INVALID")
    cli = _fixed_executable(resolved_root, "runtime/bin/openclaw")
    node = _fixed_executable(resolved_root, "runtime/tools/node/bin/node")
    environment = openclaw_child_environment(resolved_root)

    try:
        version_result = run_process(
            [str(cli), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WeixinDependencyError("WEIXIN_DEPENDENCY_UNAVAILABLE") from exc
    if version_result.returncode != 0 or version_result.stdout.strip() != versions["openclaw"]:
        raise WeixinDependencyError("WEIXIN_OPENCLAW_VERSION_MISMATCH")

    try:
        node_version_result = run_process(
            [str(node), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WeixinDependencyError("WEIXIN_DEPENDENCY_UNAVAILABLE") from exc
    if (
        node_version_result.returncode != 0
        or node_version_result.stdout.strip() != f"v{versions['node']}"
    ):
        raise WeixinDependencyError("WEIXIN_NODE_VERSION_MISMATCH")

    inspect = _run_checked_json(
        run_process,
        [str(cli), "plugins", "inspect", _INSPECT_PLUGIN_ID, "--json"],
        environment=environment,
    )
    plugin = inspect.get("plugin")
    install = inspect.get("install")
    if not isinstance(plugin, dict) or not isinstance(install, dict):
        raise WeixinDependencyError("WEIXIN_PLUGIN_INSPECT_INVALID")
    expected_plugin = versions["openclaw_weixin"]
    if (
        plugin.get("id") != _INSPECT_PLUGIN_ID
        or plugin.get("version") != expected_plugin
        or plugin.get("enabled") is not True
        or plugin.get("activated") is not True
        or plugin.get("status") != "loaded"
        or install.get("version") != expected_plugin
        or install.get("resolvedVersion") != expected_plugin
        or plugin.get("rootDir") != install.get("installPath")
        or type(plugin.get("rootDir")) is not str
    ):
        raise WeixinDependencyError("WEIXIN_PLUGIN_INSPECT_INVALID")
    plugin_root = _contained_path(resolved_root, Path(plugin["rootDir"]))
    if not plugin_root.is_dir():
        raise WeixinDependencyError("WEIXIN_PLUGIN_INSPECT_INVALID")
    return OpenClawWeixinDependency(
        root=resolved_root,
        cli_executable=cli,
        node_executable=node,
        plugin_root=plugin_root,
        openclaw_version=versions["openclaw"],
        plugin_version=expected_plugin,
    )


class OpenClawWeixinAdapterRunner:
    def __init__(
        self,
        dependency: OpenClawWeixinDependency,
        *,
        run_process: RunProcess = subprocess.run,
    ) -> None:
        self._dependency = dependency
        self._run_process = run_process

    def probe(self, registry: RecipientRegistryDocument) -> None:
        payload = {
            "plugin_root": str(self._dependency.plugin_root),
            "account_id": registry.account_id,
            "enabled_recipients": [
                {"alias": recipient.alias, "target": recipient.target}
                for recipient in registry.enabled_recipients
            ],
        }
        try:
            result = self._run_process(
                [
                    str(self._dependency.node_executable),
                    str(ADAPTER_PATH),
                    "probe",
                ],
                input=json.dumps(payload, separators=(",", ":")),
                capture_output=True,
                text=True,
                check=False,
                timeout=_COMMAND_TIMEOUT_SECONDS,
                env=openclaw_child_environment(self._dependency.root),
            )
            parsed = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise RuntimeError("WEIXIN_ADAPTER_UNAVAILABLE") from exc
        if (
            result.returncode != 0
            or not isinstance(parsed, dict)
            or set(parsed) != {"status", "recipient_count"}
            or parsed.get("status") != "ready"
            or type(parsed.get("recipient_count")) is not int
            or parsed["recipient_count"] != len(registry.enabled_recipients)
        ):
            raise RuntimeError("WEIXIN_ADAPTER_UNAVAILABLE")

    def register(
        self,
        *,
        account_id: str | None,
        approved_recipients: tuple[NotificationRecipient, ...],
        challenge: str,
        timeout_seconds: float,
    ) -> tuple[str, str]:
        payload = {
            "plugin_root": str(self._dependency.plugin_root),
            "account_id": account_id,
            "approved_recipients": [
                {"alias": recipient.alias, "target": recipient.target}
                for recipient in approved_recipients
            ],
            "challenge": challenge,
            "timeout_seconds": timeout_seconds,
        }
        try:
            result = self._run_process(
                [
                    str(self._dependency.node_executable),
                    str(ADAPTER_PATH),
                    "register",
                ],
                input=json.dumps(payload, separators=(",", ":")),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds + _COMMAND_TIMEOUT_SECONDS,
                env=openclaw_child_environment(self._dependency.root),
            )
            parsed = json.loads(result.stdout)
        except subprocess.TimeoutExpired as exc:
            raise WeixinRegistrationError("WEIXIN_REGISTRATION_TIMEOUT") from exc
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise WeixinRegistrationError("WEIXIN_ADAPTER_UNAVAILABLE") from exc
        if result.returncode != 0:
            code = parsed.get("error_code") if isinstance(parsed, dict) else None
            if code in {
                "WEIXIN_REGISTRATION_TIMEOUT",
                "WEIXIN_REGISTRATION_AMBIGUOUS",
                "WEIXIN_ACCOUNT_UNAVAILABLE",
            }:
                raise WeixinRegistrationError(code)
            raise WeixinRegistrationError("WEIXIN_ADAPTER_UNAVAILABLE")
        if (
            not isinstance(parsed, dict)
            or set(parsed) != {"status", "account_id", "target"}
            or parsed.get("status") != "registered"
            or not isinstance(parsed.get("account_id"), str)
            or not parsed["account_id"]
            or not isinstance(parsed.get("target"), str)
            or not parsed["target"].endswith("@im.wechat")
        ):
            raise WeixinRegistrationError("WEIXIN_ADAPTER_UNAVAILABLE")
        return parsed["account_id"], parsed["target"]


def generate_registration_challenge() -> str:
    """Generate a URL-safe 128-bit one-time challenge."""
    return secrets.token_urlsafe(16)


def _context_monitor_running() -> bool:
    try:
        result = subprocess.run(
            [
                "/bin/launchctl",
                "print",
                f"gui/{os.getuid()}/com.guiyi.quant-weixin-context",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
            env={},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WeixinRegistrationError("WEIXIN_CONTEXT_MONITOR_STATE_UNKNOWN") from exc
    return result.returncode == 0


def _absolute_environment_path(name: str) -> Path:
    raw = os.getenv(name, "")
    path = Path(raw)
    if not raw or not path.is_absolute():
        raise WeixinRegistrationError("WEIXIN_REGISTRATION_CONFIG_INVALID")
    return path


def register_recipient(
    alias: str,
    *,
    prompt_stream: TextIO,
    timeout_seconds: float = 180.0,
    run_process: RunProcess = subprocess.run,
    monitor_running: Callable[[], bool] = _context_monitor_running,
) -> RecipientRegistryDocument:
    """Register one exact challenge match without exposing its direct target."""
    if _ALIAS_PATTERN.fullmatch(alias) is None:
        raise WeixinRegistrationError("WEIXIN_REGISTRATION_ALIAS_INVALID")
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise WeixinRegistrationError("WEIXIN_REGISTRATION_TIMEOUT_INVALID")
    if monitor_running():
        raise WeixinRegistrationError("WEIXIN_CONTEXT_MONITOR_RUNNING")

    root = _absolute_environment_path("GUIYI_OPENCLAW_ROOT")
    registry_path = _absolute_environment_path("GUIYI_ALERT_RECIPIENTS_PATH")
    try:
        registry_path.lstat()
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise WeixinRegistrationError("RECIPIENT_REGISTRY_INVALID") from exc
    else:
        try:
            existing = load_recipient_registry(registry_path)
        except RecipientRegistryError as exc:
            raise WeixinRegistrationError(str(exc)) from exc
    if existing is not None and any(item.alias == alias for item in existing.recipients):
        raise WeixinRegistrationError("WEIXIN_REGISTRATION_ALIAS_EXISTS")

    try:
        dependency = resolve_openclaw_weixin_dependency(root, run_process=run_process)
    except WeixinDependencyError as exc:
        raise WeixinRegistrationError("WEIXIN_ADAPTER_UNAVAILABLE") from exc
    challenge = generate_registration_challenge()
    prompt_stream.write(f"alias={alias}\nchallenge={challenge}\n")
    prompt_stream.flush()
    account_id, target = OpenClawWeixinAdapterRunner(
        dependency,
        run_process=run_process,
    ).register(
        account_id=existing.account_id if existing is not None else None,
        approved_recipients=existing.recipients if existing is not None else (),
        challenge=challenge,
        timeout_seconds=float(timeout_seconds),
    )
    if existing is not None:
        if account_id != existing.account_id:
            raise WeixinRegistrationError("WEIXIN_ACCOUNT_UNAVAILABLE")
        if any(item.target == target for item in existing.recipients):
            raise WeixinRegistrationError("WEIXIN_REGISTRATION_TARGET_EXISTS")
        try:
            updated = add_recipient(
                existing,
                NotificationRecipient(alias, target, True),
            )
        except RecipientRegistryError as exc:
            raise WeixinRegistrationError(str(exc)) from exc
    else:
        updated = RecipientRegistryDocument(
            1,
            "openclaw-weixin",
            account_id,
            (NotificationRecipient(alias, target, True),),
        )
    try:
        write_recipient_registry(registry_path, updated)
    except RecipientRegistryError as exc:
        raise WeixinRegistrationError(str(exc)) from exc
    return updated
