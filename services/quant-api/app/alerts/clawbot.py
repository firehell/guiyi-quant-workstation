"""Pinned Clawbot dependency, one-child runner and Alert sender."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

from app.alerts.clawbot_owner import CLAWBOT_OWNER_ALIAS, ClawbotOwner, load_clawbot_owner
from app.alerts.notification import ALERT_CANARY_TEXT, AlertNotificationMessage, format_alert_message
from app.core.env import PROJECT_ROOT


VERSIONS_PATH = PROJECT_ROOT / "deploy/clawbot/versions.json"
SINGLE_SHOT_PATH = PROJECT_ROOT / "services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs"
CHILD_TIMEOUT_SECONDS = 15.0
VERSION_TIMEOUT_SECONDS = 10.0
_ENV_PATHS = (
    "GUIYI_OPENCLAW_BIN",
    "GUIYI_OPENCLAW_NODE_BIN",
    "GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT",
    "GUIYI_OPENCLAW_STATE_DIR",
    "GUIYI_OPENCLAW_CONFIG_PATH",
    "GUIYI_ALERT_CLAWBOT_OWNER_PATH",
)
_PUBLIC_CHILD_ERRORS = {
    "CLAWBOT_CONTEXT_UNAVAILABLE",
    "CLAWBOT_DEPENDENCY_INVALID",
    "CLAWBOT_INPUT_INVALID",
    "CLAWBOT_OWNER_INVALID",
    "CLAWBOT_OWNER_UNAVAILABLE",
    "CLAWBOT_SEND_FAILED",
}


class ClawbotError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ClawbotDependency:
    openclaw_bin: Path
    node_bin: Path
    plugin_root: Path
    state_dir: Path
    config_path: Path
    owner_path: Path
    versions_path: Path


@dataclass(frozen=True, slots=True)
class ClawbotOwnerCandidate:
    account_id: str
    target_user_id: str


@dataclass(frozen=True, slots=True)
class ClawbotSendSummary:
    attempted: int
    provider_accepted: int
    failed: int
    failed_aliases: tuple[str, ...]


RunProcess = Callable[..., subprocess.CompletedProcess[str]]


def _regular(path: Path, *, executable: bool = False) -> Path:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
        if not path.is_absolute() or not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise ValueError
        if executable and not os.access(resolved, os.X_OK):
            raise ValueError
        return resolved
    except (OSError, ValueError):
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None


def _directory(path: Path) -> Path:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
        if not path.is_absolute() or not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
            raise ValueError
        return resolved
    except (OSError, ValueError):
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None


def _manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(_regular(path).read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {"schema_version", "openclaw_version", "openclaw_weixin_version", "node_version", "plugin_modules"}
            or payload["schema_version"] != 1
            or type(payload["schema_version"]) is not int
            or not all(
                isinstance(payload[key], str) and bool(payload[key])
                for key in ("openclaw_version", "openclaw_weixin_version", "node_version")
            )
            or payload["plugin_modules"]
            != {
                "accounts": "dist/src/auth/accounts.js",
                "inbound": "dist/src/messaging/inbound.js",
                "send": "dist/src/messaging/send.js",
            }
        ):
            raise ValueError
        return payload
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, ClawbotError):
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None


def resolve_clawbot_dependency(
    *,
    openclaw_bin: Path,
    node_bin: Path,
    plugin_root: Path,
    state_dir: Path,
    config_path: Path,
    owner_path: Path,
    versions_path: Path = VERSIONS_PATH,
    verify_versions: bool = True,
    run_process: RunProcess = subprocess.run,
) -> ClawbotDependency:
    manifest = _manifest(versions_path)
    resolved_openclaw = _regular(openclaw_bin, executable=True)
    resolved_node = _regular(node_bin, executable=True)
    resolved_plugin = _directory(plugin_root)
    resolved_state = _directory(state_dir)
    resolved_config = _regular(config_path)
    try:
        if not owner_path.is_absolute():
            raise ValueError
        owner_parent = _directory(owner_path.parent)
        parent_metadata = owner_parent.stat()
        if stat.S_IMODE(parent_metadata.st_mode) != 0o700 or parent_metadata.st_uid != os.getuid():
            raise ValueError
        resolved_owner = owner_parent / owner_path.name
    except (OSError, ValueError, ClawbotError):
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None
    dependency = ClawbotDependency(
        resolved_openclaw,
        resolved_node,
        resolved_plugin,
        resolved_state,
        resolved_config,
        resolved_owner,
        _regular(versions_path),
    )
    if not verify_versions:
        return dependency
    commands = (
        [str(dependency.openclaw_bin), "--version"],
        [str(dependency.node_bin), "--version"],
        [str(dependency.openclaw_bin), "plugins", "inspect", "openclaw-weixin", "--runtime", "--json"],
    )
    try:
        results = [
            run_process(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=VERSION_TIMEOUT_SECONDS,
                env={"PATH": f"{dependency.openclaw_bin.parent}:{dependency.node_bin.parent}:/usr/bin:/bin"},
            )
            for command in commands
        ]
        plugin_payload = json.loads(results[2].stdout)
        plugin = plugin_payload["plugin"]
        install = plugin_payload["install"]
        if (
            any(result.returncode != 0 for result in results)
            or results[0].stdout.strip() != manifest["openclaw_version"]
            or results[1].stdout.strip() != manifest["node_version"]
            or plugin.get("id") != "openclaw-weixin"
            or plugin.get("version") != manifest["openclaw_weixin_version"]
            or plugin.get("status") != "loaded"
            or plugin.get("activated") is not True
            or install.get("version") != manifest["openclaw_weixin_version"]
            or Path(install.get("installPath", "")).resolve(strict=True) != dependency.plugin_root
        ):
            raise ValueError
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None
    return dependency


def _child_environment(dependency: ClawbotDependency) -> dict[str, str]:
    return {
        "OPENCLAW_STATE_DIR": str(dependency.state_dir),
        "OPENCLAW_CONFIG": str(dependency.config_path),
        "OPENCLAW_CONFIG_PATH": str(dependency.config_path),
        "OPENCLAW_LOG_LEVEL": "FATAL",
        "GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT": str(dependency.plugin_root),
        "GUIYI_CLAWBOT_VERSIONS_PATH": str(dependency.versions_path),
        "PATH": f"{dependency.node_bin.parent}:/usr/bin:/bin:/usr/sbin:/sbin",
    }


class ClawbotRunner:
    def __init__(self, dependency: ClawbotDependency, *, run_process: RunProcess = subprocess.run) -> None:
        self.dependency = dependency
        self._run_process = run_process

    def discover_owner(self) -> ClawbotOwnerCandidate:
        payload = self._invoke({"action": "discover_owner"}, expected_status="ready")
        try:
            if set(payload) != {
                "status", "action", "account_count", "owner_candidate_count", "context_available", "account_id", "target_user_id"
            } or payload["action"] != "discover_owner" or payload["account_count"] != 1 or payload["owner_candidate_count"] != 1 or payload["context_available"] is not True:
                raise ValueError
            account_id = payload["account_id"]
            target_user_id = payload["target_user_id"]
            if not isinstance(account_id, str) or not account_id or not isinstance(target_user_id, str) or not target_user_id.endswith("@im.wechat"):
                raise ValueError
            return ClawbotOwnerCandidate(account_id, target_user_id)
        except (KeyError, TypeError, ValueError):
            raise ClawbotError("CLAWBOT_CHILD_FAILED") from None

    def probe(self, owner: ClawbotOwner) -> None:
        payload = self._invoke(
            {"action": "probe", "account_id": owner.account_id, "target_user_id": owner.target_user_id},
            expected_status="ready",
        )
        if payload != {"status": "ready", "action": "probe", "account_configured": True, "context_available": True}:
            raise ClawbotError("CLAWBOT_CHILD_FAILED")

    def send_text(self, owner: ClawbotOwner, text: str) -> None:
        payload = self._invoke(
            {"action": "send", "account_id": owner.account_id, "target_user_id": owner.target_user_id, "text": text},
            expected_status="accepted",
        )
        if payload != {"status": "accepted", "action": "send"}:
            raise ClawbotError("CLAWBOT_CHILD_FAILED")

    def _invoke(self, payload: dict[str, object], *, expected_status: str) -> dict[str, Any]:
        argv = [str(self.dependency.node_bin), str(SINGLE_SHOT_PATH)]
        try:
            result = self._run_process(
                argv,
                input=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                capture_output=True,
                text=True,
                check=False,
                timeout=CHILD_TIMEOUT_SECONDS,
                env=_child_environment(self.dependency),
            )
            decoded = json.loads(result.stdout)
            if not isinstance(decoded, dict):
                raise ValueError
            if result.returncode != 0:
                code = decoded.get("error")
                if decoded.get("status") == "error" and code in _PUBLIC_CHILD_ERRORS:
                    raise ClawbotError(str(code))
                raise ValueError
            if decoded.get("status") != expected_status:
                raise ValueError
            return decoded
        except ClawbotError:
            raise
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, ValueError):
            raise ClawbotError("CLAWBOT_CHILD_FAILED") from None


class ClawbotAlertSender:
    def __init__(self, owner: ClawbotOwner, runner: ClawbotRunner) -> None:
        self._owner = owner
        self._runner = runner

    def send(self, message: AlertNotificationMessage) -> None:
        self._runner.send_text(self._owner, format_alert_message(message))

    def send_canary(self) -> ClawbotSendSummary:
        try:
            self._runner.send_text(self._owner, ALERT_CANARY_TEXT)
        except ClawbotError:
            return ClawbotSendSummary(1, 0, 1, (CLAWBOT_OWNER_ALIAS,))
        return ClawbotSendSummary(1, 1, 0, ())


def build_clawbot_dependency_from_env(*, verify_versions: bool) -> ClawbotDependency:
    values = [os.getenv(name, "") for name in _ENV_PATHS]
    if any(not value for value in values):
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY")
    return resolve_clawbot_dependency(
        openclaw_bin=Path(values[0]),
        node_bin=Path(values[1]),
        plugin_root=Path(values[2]),
        state_dir=Path(values[3]),
        config_path=Path(values[4]),
        owner_path=Path(values[5]),
        verify_versions=verify_versions,
    )


def build_clawbot_runner_from_env(*, verify_versions: bool = True) -> ClawbotRunner:
    return ClawbotRunner(build_clawbot_dependency_from_env(verify_versions=verify_versions))


def build_clawbot_sender_from_env(*, live_probe: bool = True) -> ClawbotAlertSender:
    runner = build_clawbot_runner_from_env(verify_versions=True)
    try:
        owner = load_clawbot_owner(runner.dependency.owner_path)
        if live_probe:
            runner.probe(owner)
    except Exception as exc:
        if isinstance(exc, ClawbotError):
            raise
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None
    return ClawbotAlertSender(owner, runner)
