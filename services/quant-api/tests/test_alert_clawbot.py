from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess

import pytest

import app.alerts.clawbot as clawbot
from app.alerts.clawbot import (
    ClawbotAlertSender,
    ClawbotDependency,
    ClawbotError,
    ClawbotOwnerCandidate,
    ClawbotRunner,
    clawbot_transport_configured_from_env,
    resolve_clawbot_dependency,
)
from app.alerts.notification import ALERT_CANARY_TEXT, AlertNotificationMessage, format_alert_message
from app.alerts.recipients import ClawbotRecipient


def _tree(tmp_path: Path) -> tuple[ClawbotDependency, Path]:
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps({"version": "2.4.6"}),
        encoding="utf-8",
    )
    for relative in (
        "dist/src/auth/accounts.js",
        "dist/src/messaging/inbound.js",
        "dist/src/messaging/send.js",
    ):
        module = root / relative
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("export {};\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    config = state / "openclaw.json"
    config.write_text("{}", encoding="utf-8")
    recipients_parent = tmp_path / "private"
    recipients_parent.mkdir(mode=0o700)
    recipients_parent.chmod(0o700)
    recipients = recipients_parent / "recipients.json"
    openclaw = tmp_path / "openclaw"
    node = tmp_path / "node"
    for executable in (openclaw, node):
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o700)
    manifest = tmp_path / "versions.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "openclaw_version": "OpenClaw fixture",
                "openclaw_weixin_version": "2.4.6",
                "node_version": "v24.15.0",
                "plugin_modules": {
                    "accounts": "dist/src/auth/accounts.js",
                    "inbound": "dist/src/messaging/inbound.js",
                    "send": "dist/src/messaging/send.js",
                },
            }
        ),
        encoding="utf-8",
    )
    dependency = ClawbotDependency(openclaw, node, root, state, config, recipients, manifest)
    return dependency, manifest


def _recipient() -> ClawbotRecipient:
    return ClawbotRecipient("owner", "fixture-account", "fixture-owner@im.wechat")


def _write_recipients(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "channel": "openclaw-weixin",
                "account_id": "fixture-account",
                "active_recipients": [
                    {"alias": "owner", "target_user_id": "fixture-owner@im.wechat"}
                ],
                "retired_aliases": [],
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _message() -> AlertNotificationMessage:
    return AlertNotificationMessage(
        rule_code="htdy_original_15m",
        symbol="ag",
        product_name="白银",
        contract="AG2610",
        frequency="15m",
        bar_end=datetime(2026, 8, 13, 2, 45, tzinfo=UTC),
        result_codes=("buy",),
    )


def test_dependency_resolver_validates_exact_live_versions_and_plugin_root(tmp_path: Path) -> None:
    expected, manifest = _tree(tmp_path)
    calls: list[list[str]] = []
    environments: list[object] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        environments.append(kwargs["env"])
        if argv == [str(expected.openclaw_bin), "--version"]:
            stdout = "OpenClaw fixture\n"
        elif argv == [str(expected.node_bin), "--version"]:
            stdout = "v24.15.0\n"
        else:
            stdout = json.dumps(
                {
                    "plugin": {"id": "openclaw-weixin", "version": "2.4.6", "status": "loaded", "activated": True},
                    "install": {"installPath": str(expected.plugin_root), "version": "2.4.6"},
                }
            )
        return subprocess.CompletedProcess(argv, 0, stdout, "private stderr")

    result = resolve_clawbot_dependency(
        openclaw_bin=expected.openclaw_bin,
        node_bin=expected.node_bin,
        plugin_root=expected.plugin_root,
        state_dir=expected.state_dir,
        config_path=expected.config_path,
        recipients_path=expected.recipients_path,
        versions_path=manifest,
        verify_versions=True,
        run_process=run,
    )

    assert result == expected
    assert calls == [
        [str(expected.openclaw_bin), "--version"],
        [str(expected.node_bin), "--version"],
        [str(expected.openclaw_bin), "plugins", "inspect", "openclaw-weixin", "--runtime", "--json"],
    ]
    assert environments == [
        {
            "OPENCLAW_STATE_DIR": str(expected.state_dir),
            "OPENCLAW_CONFIG": str(expected.config_path),
            "OPENCLAW_CONFIG_PATH": str(expected.config_path),
            "OPENCLAW_LOG_LEVEL": "FATAL",
            "PATH": f"{expected.openclaw_bin.parent}:{expected.node_bin.parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        }
    ] * 3


@pytest.mark.parametrize(
    "problem",
    [
        "relative",
        "missing_node",
        "config_dir",
        "missing_parent",
        "version_mismatch",
        "missing_package",
        "package_version",
        "package_symlink",
    ],
)
def test_dependency_resolver_fails_closed(tmp_path: Path, problem: str) -> None:
    expected, manifest = _tree(tmp_path)
    values = {
        "openclaw_bin": expected.openclaw_bin,
        "node_bin": expected.node_bin,
        "plugin_root": expected.plugin_root,
        "state_dir": expected.state_dir,
        "config_path": expected.config_path,
        "recipients_path": expected.recipients_path,
        "versions_path": manifest,
    }
    if problem == "relative":
        values["plugin_root"] = Path("relative")
    elif problem == "missing_node":
        expected.node_bin.unlink()
    elif problem == "config_dir":
        expected.config_path.unlink()
        expected.config_path.mkdir()
    elif problem == "missing_parent":
        values["recipients_path"] = tmp_path / "missing/recipients.json"
    elif problem == "missing_package":
        (expected.plugin_root / "package.json").unlink()
    elif problem == "package_version":
        (expected.plugin_root / "package.json").write_text(
            json.dumps({"version": "9.9.9"}),
            encoding="utf-8",
        )
    elif problem == "package_symlink":
        package = expected.plugin_root / "package.json"
        outside = tmp_path / "package.json"
        package.replace(outside)
        package.symlink_to(outside)

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[-1] == "--version":
            stdout = "wrong\n" if problem == "version_mismatch" else (
                "OpenClaw fixture\n" if argv[0] == str(expected.openclaw_bin) else "v24.15.0\n"
            )
        else:
            stdout = json.dumps({"plugin": {"id": "openclaw-weixin", "version": "2.4.6", "status": "loaded", "activated": True}, "install": {"installPath": str(expected.plugin_root), "version": "2.4.6"}})
        return subprocess.CompletedProcess(argv, 0, stdout, "private")

    with pytest.raises(ClawbotError, match="^ALERT_NOTIFICATION_TRANSPORT_NOT_READY$"):
        resolve_clawbot_dependency(**values, verify_versions=True, run_process=run)


def test_python_resolver_uses_manifest_module_paths_without_private_path_knowledge(
    tmp_path: Path,
) -> None:
    expected, manifest = _tree(tmp_path)
    custom_modules = {
        "accounts": "compiled/account-entry.js",
        "inbound": "compiled/context-entry.js",
        "send": "compiled/send-entry.js",
    }
    for relative in custom_modules.values():
        module = expected.plugin_root / relative
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("export {};\n", encoding="utf-8")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["plugin_modules"] = custom_modules
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = resolve_clawbot_dependency(
        openclaw_bin=expected.openclaw_bin,
        node_bin=expected.node_bin,
        plugin_root=expected.plugin_root,
        state_dir=expected.state_dir,
        config_path=expected.config_path,
        recipients_path=expected.recipients_path,
        versions_path=manifest,
        verify_versions=False,
    )

    assert result == expected


def test_runner_uses_fixed_argv_stdin_and_allowlisted_environment(tmp_path: Path) -> None:
    dependency, _ = _tree(tmp_path)
    observed: dict[str, object] = {}

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps({
                "status": "ready",
                "action": "discover_owner",
                "account_count": 1,
                "owner_candidate_count": 1,
                "context_available": True,
                "account_id": "fixture-account",
                "target_user_id": "fixture-owner@im.wechat",
            }),
            "private raw stderr",
        )

    candidate = ClawbotRunner(dependency, run_process=run).discover_owner()

    assert candidate == ClawbotOwnerCandidate("fixture-account", "fixture-owner@im.wechat")
    assert observed["argv"] == [str(dependency.node_bin), str(clawbot.SINGLE_SHOT_PATH)]
    kwargs = observed["kwargs"]
    assert json.loads(kwargs["input"]) == {"action": "discover_owner"}
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is False
    assert kwargs["timeout"] == clawbot.CHILD_TIMEOUT_SECONDS
    assert kwargs["env"] == {
        "OPENCLAW_STATE_DIR": str(dependency.state_dir),
        "OPENCLAW_CONFIG": str(dependency.config_path),
        "OPENCLAW_CONFIG_PATH": str(dependency.config_path),
        "OPENCLAW_LOG_LEVEL": "FATAL",
        "GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT": str(dependency.plugin_root),
        "GUIYI_CLAWBOT_VERSIONS_PATH": str(dependency.versions_path),
        "PATH": f"{dependency.node_bin.parent}:/usr/bin:/bin:/usr/sbin:/sbin",
    }


@pytest.mark.parametrize(
    ("account_id", "target_user_id"),
    [
        (" fixture-account", "fixture-owner@im.wechat"),
        ("fixture-account", "fixture-owner\n@im.wechat"),
    ],
)
def test_runner_discovery_rejects_ids_that_owner_schema_cannot_persist(
    tmp_path: Path,
    account_id: str,
    target_user_id: str,
) -> None:
    dependency, _ = _tree(tmp_path)

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "status": "ready",
                    "action": "discover_owner",
                    "account_count": 1,
                    "owner_candidate_count": 1,
                    "context_available": True,
                    "account_id": account_id,
                    "target_user_id": target_user_id,
                }
            ),
            "",
        )

    with pytest.raises(ClawbotError, match="^CLAWBOT_CHILD_FAILED$"):
        ClawbotRunner(dependency, run_process=run).discover_owner()


@pytest.mark.parametrize("failure", ["timeout", "crash", "malformed", "private_error"])
def test_runner_failure_never_respawns_or_leaks_raw_child_output(tmp_path: Path, failure: str) -> None:
    dependency, _ = _tree(tmp_path)
    calls = 0

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 15, output="private target", stderr="private token")
        if failure == "crash":
            return subprocess.CompletedProcess(argv, -9, "", "private target")
        if failure == "malformed":
            return subprocess.CompletedProcess(argv, 0, "private malformed", "private token")
        return subprocess.CompletedProcess(argv, 1, '{"status":"error","error":"CLAWBOT_CONTEXT_UNAVAILABLE"}', "private token")

    with pytest.raises(ClawbotError) as captured:
        ClawbotRunner(dependency, run_process=run).probe(_recipient())

    assert calls == 1
    assert "private" not in str(captured.value)


def test_sender_formats_once_and_canary_reports_provider_acceptance(tmp_path: Path) -> None:
    dependency, _ = _tree(tmp_path)
    payloads: list[dict[str, object]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        payloads.append(json.loads(str(kwargs["input"])))
        return subprocess.CompletedProcess(argv, 0, '{"status":"accepted","action":"send"}', "")

    sender = ClawbotAlertSender(_recipient(), ClawbotRunner(dependency, run_process=run))
    sender.send(_message())
    summary = sender.send_canary()

    assert payloads == [
        {"action": "send", "account_id": "fixture-account", "target_user_id": "fixture-owner@im.wechat", "text": format_alert_message(_message())},
        {"action": "send", "account_id": "fixture-account", "target_user_id": "fixture-owner@im.wechat", "text": ALERT_CANARY_TEXT},
    ]
    assert summary.attempted == 1
    assert summary.provider_accepted == 1
    assert summary.failed == 0
    assert summary.failed_aliases == ()


def test_canary_failure_is_one_attempt_and_sanitized(tmp_path: Path) -> None:
    dependency, _ = _tree(tmp_path)
    calls = 0

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 1, '{"status":"error","error":"CLAWBOT_SEND_FAILED"}', "private")

    summary = ClawbotAlertSender(_recipient(), ClawbotRunner(dependency, run_process=run)).send_canary()

    assert calls == 1
    assert summary.attempted == 1
    assert summary.provider_accepted == 0
    assert summary.failed == 1
    assert summary.failed_aliases == ("owner",)


def test_structural_transport_check_reads_files_without_version_probe_or_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dependency, manifest = _tree(tmp_path)
    _write_recipients(dependency.recipients_path)
    monkeypatch.setattr(clawbot, "VERSIONS_PATH", manifest)
    for name, value in zip(clawbot.CLAWBOT_PATH_ENV_NAMES, (
        dependency.openclaw_bin,
        dependency.node_bin,
        dependency.plugin_root,
        dependency.state_dir,
        dependency.config_path,
        dependency.recipients_path,
    ), strict=True):
        monkeypatch.setenv(name, str(value))
    monkeypatch.setattr(
        clawbot.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural health must not spawn a child")
        ),
    )

    assert clawbot_transport_configured_from_env() is True

    (dependency.plugin_root / "package.json").write_text(
        json.dumps({"version": "9.9.9"}),
        encoding="utf-8",
    )
    assert clawbot_transport_configured_from_env() is False
    (dependency.plugin_root / "package.json").write_text(
        json.dumps({"version": "2.4.6"}),
        encoding="utf-8",
    )

    dependency.recipients_path.chmod(0o644)
    assert clawbot_transport_configured_from_env() is False


def test_active_transport_does_not_fall_back_to_v1_owner_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dependency, manifest = _tree(tmp_path)
    _write_recipients(dependency.recipients_path)
    monkeypatch.setattr(clawbot, "VERSIONS_PATH", manifest)
    for name, value in zip(
        clawbot.CLAWBOT_PATH_ENV_NAMES[:-1],
        (
            dependency.openclaw_bin,
            dependency.node_bin,
            dependency.plugin_root,
            dependency.state_dir,
            dependency.config_path,
        ),
        strict=True,
    ):
        monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH", raising=False)
    monkeypatch.setenv("GUIYI_ALERT_CLAWBOT_OWNER_PATH", str(dependency.recipients_path))

    assert clawbot_transport_configured_from_env() is False
