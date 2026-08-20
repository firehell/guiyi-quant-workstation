"""Pinned Clawbot dependency, one-child runner and Alert sender."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import stat
import subprocess
from typing import Any
import unicodedata

from app.alerts.clawbot_owner import (
    CLAWBOT_OWNER_ALIAS,
    ClawbotOwnerError,
    validate_clawbot_owner_ids,
)
from app.alerts.notification import ALERT_CANARY_TEXT, AlertNotificationMessage, format_alert_message
from app.alerts.recipients import (
    ClawbotRecipient,
    ClawbotRecipientError,
    RecipientDirectory,
    load_recipient_directory,
    validate_clawbot_recipient_ids,
)
from app.core.env import PROJECT_ROOT


VERSIONS_PATH = PROJECT_ROOT / "deploy/clawbot/versions.json"
SINGLE_SHOT_PATH = PROJECT_ROOT / "services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs"
CHILD_TIMEOUT_SECONDS = 15.0
VERSION_TIMEOUT_SECONDS = 10.0
CLAWBOT_PATH_ENV_NAMES = (
    "GUIYI_OPENCLAW_BIN",
    "GUIYI_OPENCLAW_NODE_BIN",
    "GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT",
    "GUIYI_OPENCLAW_STATE_DIR",
    "GUIYI_OPENCLAW_CONFIG_PATH",
    "GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH",
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
    openclaw_bin: Path = field(repr=False)
    node_bin: Path = field(repr=False)
    plugin_root: Path = field(repr=False)
    state_dir: Path = field(repr=False)
    config_path: Path = field(repr=False)
    recipients_path: Path = field(repr=False)
    versions_path: Path = field(repr=False)


@dataclass(frozen=True, slots=True)
class ClawbotOwnerCandidate:
    account_id: str = field(repr=False)
    target_user_id: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ClawbotContext:
    user_id: str = field(repr=False)
    context_token: str = field(repr=False)


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
            or not isinstance(payload["plugin_modules"], dict)
            or set(payload["plugin_modules"]) != {"accounts", "inbound", "send"}
        ):
            raise ValueError
        for value in payload["plugin_modules"].values():
            _module_relative_path(value)
        return payload
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, ClawbotError):
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None


def _module_relative_path(value: object) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\\" in value
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError
    relative = PurePosixPath(value)
    if relative.is_absolute() or str(relative) != value or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError
    return Path(*relative.parts)


def resolve_clawbot_dependency(
    *,
    openclaw_bin: Path,
    node_bin: Path,
    plugin_root: Path,
    state_dir: Path,
    config_path: Path,
    recipients_path: Path,
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
        for relative_value in manifest["plugin_modules"].values():
            relative = _module_relative_path(relative_value)
            module = _regular(resolved_plugin / relative)
            module.relative_to(resolved_plugin)
            if module != resolved_plugin / relative:
                raise ValueError
        package_path = _regular(resolved_plugin / "package.json")
        if package_path != resolved_plugin / "package.json":
            raise ValueError
        package = json.loads(package_path.read_text(encoding="utf-8"))
        if (
            not isinstance(package, dict)
            or package.get("version") != manifest["openclaw_weixin_version"]
        ):
            raise ValueError
    except (
        KeyError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ClawbotError,
    ):
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None
    try:
        if not recipients_path.is_absolute():
            raise ValueError
        recipients_parent = _directory(recipients_path.parent)
        parent_metadata = recipients_parent.stat()
        if stat.S_IMODE(parent_metadata.st_mode) != 0o700 or parent_metadata.st_uid != os.getuid():
            raise ValueError
        resolved_recipients = recipients_parent / recipients_path.name
    except (OSError, ValueError, ClawbotError):
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None
    dependency = ClawbotDependency(
        resolved_openclaw,
        resolved_node,
        resolved_plugin,
        resolved_state,
        resolved_config,
        resolved_recipients,
        _regular(versions_path),
    )
    if not verify_versions:
        return dependency
    commands = (
        [str(dependency.openclaw_bin), "--version"],
        [str(dependency.node_bin), "--version"],
        [str(dependency.openclaw_bin), "plugins", "inspect", "openclaw-weixin", "--runtime", "--json"],
    )
    command_environment = {
        "OPENCLAW_STATE_DIR": str(dependency.state_dir),
        "OPENCLAW_CONFIG": str(dependency.config_path),
        "OPENCLAW_CONFIG_PATH": str(dependency.config_path),
        "OPENCLAW_LOG_LEVEL": "FATAL",
        "PATH": (
            f"{dependency.openclaw_bin.parent}:{dependency.node_bin.parent}"
            ":/usr/bin:/bin:/usr/sbin:/sbin"
        ),
    }
    try:
        results = [
            run_process(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=VERSION_TIMEOUT_SECONDS,
                env=command_environment,
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
    def __init__(
        self,
        dependency: ClawbotDependency,
        *,
        recipient_directory: RecipientDirectory,
        run_process: RunProcess = subprocess.run,
    ) -> None:
        self.dependency = dependency
        self._active_recipients = frozenset(recipient_directory.recipients)
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
            validate_clawbot_owner_ids(account_id, target_user_id)
            return ClawbotOwnerCandidate(account_id, target_user_id)
        except (ClawbotOwnerError, KeyError, TypeError, ValueError):
            raise ClawbotError("CLAWBOT_CHILD_FAILED") from None

    def snapshot_contexts(self) -> tuple[str, tuple[ClawbotContext, ...]]:
        payload = self._invoke({"action": "snapshot_contexts"}, expected_status="ready")
        try:
            if set(payload) != {"status", "action", "account_id", "contexts"}:
                raise ValueError
            if payload["action"] != "snapshot_contexts" or not isinstance(payload["contexts"], list):
                raise ValueError
            account_id = payload["account_id"]
            contexts = tuple(
                self._parse_context(account_id, item) for item in payload["contexts"]
            )
            if len(contexts) > 64 or tuple(item.user_id for item in contexts) != tuple(
                sorted(item.user_id for item in contexts)
            ) or len({item.user_id for item in contexts}) != len(contexts):
                raise ValueError
            if not isinstance(account_id, str):
                raise ValueError
            validate_clawbot_recipient_ids(account_id, "validation-only@im.wechat")
            return account_id, contexts
        except (ClawbotRecipientError, KeyError, TypeError, ValueError):
            raise ClawbotError("CLAWBOT_CHILD_FAILED") from None

    @staticmethod
    def _parse_context(account_id: object, value: object) -> ClawbotContext:
        if not isinstance(value, dict) or set(value) != {"user_id", "context_token"}:
            raise ValueError
        user_id = value["user_id"]
        context_token = value["context_token"]
        validate_clawbot_recipient_ids(account_id, user_id)
        if (
            not isinstance(user_id, str)
            or not isinstance(context_token, str)
            or not context_token
            or context_token.strip() != context_token
            or any(unicodedata.category(character).startswith("C") for character in context_token)
        ):
            raise ValueError
        return ClawbotContext(user_id, context_token)

    def probe(self, recipient: ClawbotRecipient) -> None:
        self._require_active_recipient(recipient)
        payload = self._invoke(
            {"action": "probe", "account_id": recipient.account_id, "target_user_id": recipient.target_user_id},
            expected_status="ready",
        )
        if payload != {"status": "ready", "action": "probe", "account_configured": True, "context_available": True}:
            raise ClawbotError("CLAWBOT_CHILD_FAILED")

    def send_text(self, recipient: ClawbotRecipient, text: str) -> None:
        self._require_active_recipient(recipient)
        payload = self._invoke(
            {"action": "send", "account_id": recipient.account_id, "target_user_id": recipient.target_user_id, "text": text},
            expected_status="accepted",
        )
        if payload != {"status": "accepted", "action": "send"}:
            raise ClawbotError("CLAWBOT_CHILD_FAILED")

    def _require_active_recipient(self, recipient: ClawbotRecipient) -> None:
        if recipient not in self._active_recipients:
            raise ClawbotError("CLAWBOT_RECIPIENT_INVALID")

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
    def __init__(self, recipient: ClawbotRecipient, runner: ClawbotRunner) -> None:
        self._recipient = recipient
        self._runner = runner

    def send(self, message: AlertNotificationMessage) -> None:
        self._runner.send_text(self._recipient, format_alert_message(message))

    def send_canary(self) -> ClawbotSendSummary:
        try:
            self._runner.send_text(self._recipient, ALERT_CANARY_TEXT)
        except ClawbotError:
            return ClawbotSendSummary(1, 0, 1, (CLAWBOT_OWNER_ALIAS,))
        return ClawbotSendSummary(1, 1, 0, ())


def build_clawbot_dependency_from_env(*, verify_versions: bool) -> ClawbotDependency:
    values = [os.getenv(name, "") for name in CLAWBOT_PATH_ENV_NAMES]
    if any(not value for value in values):
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY")
    return resolve_clawbot_dependency(
        openclaw_bin=Path(values[0]),
        node_bin=Path(values[1]),
        plugin_root=Path(values[2]),
        state_dir=Path(values[3]),
        config_path=Path(values[4]),
        recipients_path=Path(values[5]),
        verify_versions=verify_versions,
    )


def build_clawbot_runner_from_env(*, verify_versions: bool = True) -> ClawbotRunner:
    dependency = build_clawbot_dependency_from_env(verify_versions=verify_versions)
    try:
        directory = load_recipient_directory(dependency.recipients_path)
    except ClawbotRecipientError:
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None
    return ClawbotRunner(dependency, recipient_directory=directory)


def build_clawbot_sender_from_env(*, live_probe: bool = True) -> ClawbotAlertSender:
    runner = build_clawbot_runner_from_env(verify_versions=True)
    try:
        recipient = load_recipient_directory(runner.dependency.recipients_path).recipients_for(
            "subing_entry_signal_v1"
        )[0]
        if live_probe:
            runner.probe(recipient)
    except Exception as exc:
        if isinstance(exc, ClawbotError):
            raise
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY") from None
    return ClawbotAlertSender(recipient, runner)


def clawbot_transport_configured_from_env() -> bool:
    """Validate local Clawbot structure without spawning or contacting the provider."""
    try:
        dependency = build_clawbot_dependency_from_env(verify_versions=False)
        load_recipient_directory(dependency.recipients_path)
    except (ClawbotError, ClawbotOwnerError, ClawbotRecipientError, OSError, ValueError):
        return False
    return True
