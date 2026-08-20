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
    ClawbotDeliveryError,
    ClawbotError,
    ClawbotOwnerCandidate,
    ClawbotRunner,
    clawbot_transport_status_from_env,
    clawbot_transport_configured_from_env,
    resolve_clawbot_dependency,
)
from app.alerts.clawbot_owner import write_clawbot_owner_atomic
from app.alerts.notification import ALERT_CANARY_TEXT, AlertNotificationMessage, format_alert_message
from app.alerts.recipients import (
    ClawbotRecipient,
    RecipientDirectory,
    initialize_recipients_from_owner,
)


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
    owner_parent = tmp_path / "private"
    owner_parent.mkdir(mode=0o700)
    owner_parent.chmod(0o700)
    recipients = owner_parent / "recipients.json"
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


def _friend(alias: str = "alice") -> ClawbotRecipient:
    return ClawbotRecipient(
        alias,
        "fixture-account",
        f"fixture-{alias}@im.wechat",
    )


def _directory(*recipients: ClawbotRecipient) -> RecipientDirectory:
    return RecipientDirectory(
        2,
        "openclaw-weixin",
        "fixture-account",
        recipients or (_recipient(),),
        (),
    )


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

    candidate = ClawbotRunner(
        dependency, recipient_directory=_directory(), run_process=run
    ).discover_owner()

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


def test_runner_captures_one_private_context_snapshot_without_exposing_it_in_repr(
    tmp_path: Path,
) -> None:
    dependency, _ = _tree(tmp_path)
    calls = 0

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        assert json.loads(str(kwargs["input"])) == {"action": "snapshot_contexts"}
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "status": "ready",
                    "action": "snapshot_contexts",
                    "account_id": "fixture-account",
                    "contexts": [
                        {
                            "user_id": "fixture-friend@im.wechat",
                            "context_token": "fixture-friend-context",
                        },
                        {
                            "user_id": "fixture-owner@im.wechat",
                            "context_token": "fixture-owner-context",
                        },
                    ],
                }
            ),
            "private raw stderr",
        )

    account_id, contexts = ClawbotRunner(
        dependency, recipient_directory=_directory(), run_process=run
    ).snapshot_contexts()

    assert calls == 1
    assert account_id == "fixture-account"
    assert tuple((item.user_id, item.context_token) for item in contexts) == (
        ("fixture-friend@im.wechat", "fixture-friend-context"),
        ("fixture-owner@im.wechat", "fixture-owner-context"),
    )
    assert "fixture" not in repr(contexts)


def test_runner_rejects_recipient_outside_frozen_directory_before_starting_child(
    tmp_path: Path,
) -> None:
    dependency, _ = _tree(tmp_path)
    calls = 0

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        raise AssertionError("unbound recipient must fail before child")

    runner = ClawbotRunner(
        dependency,
        recipient_directory=_directory(),
        run_process=run,
    )
    unbound = ClawbotRecipient(
        "friend", "fixture-account", "fixture-friend@im.wechat"
    )

    with pytest.raises(ClawbotError, match="^CLAWBOT_RECIPIENT_INVALID$"):
        runner.probe(unbound)
    with pytest.raises(ClawbotError, match="^CLAWBOT_RECIPIENT_INVALID$"):
        runner.send_text(unbound, "fixture alert")

    assert calls == 0


def test_runner_allows_frozen_active_recipient_for_probe_and_send(tmp_path: Path) -> None:
    dependency, _ = _tree(tmp_path)
    payloads: list[dict[str, object]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        payload = json.loads(str(kwargs["input"]))
        payloads.append(payload)
        output = (
            {"status": "ready", "action": "probe", "account_configured": True, "context_available": True}
            if payload["action"] == "probe"
            else {"status": "accepted", "action": "send"}
        )
        return subprocess.CompletedProcess(argv, 0, json.dumps(output), "")

    active = ClawbotRecipient(
        "friend", "fixture-account", "fixture-friend@im.wechat"
    )
    runner = ClawbotRunner(
        dependency,
        recipient_directory=_directory(_recipient(), active),
        run_process=run,
    )

    runner.probe(active)
    runner.send_text(active, "fixture alert")

    assert [payload["action"] for payload in payloads] == ["probe", "send"]


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
        ClawbotRunner(
            dependency, recipient_directory=_directory(), run_process=run
        ).discover_owner()


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
        ClawbotRunner(
            dependency, recipient_directory=_directory(), run_process=run
        ).probe(_recipient())

    assert calls == 1
    assert "private" not in str(captured.value)


def test_sender_fans_htdy_out_to_every_frozen_recipient_once(tmp_path: Path) -> None:
    dependency, _ = _tree(tmp_path)
    payloads: list[dict[str, object]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        payloads.append(json.loads(str(kwargs["input"])))
        return subprocess.CompletedProcess(argv, 0, '{"status":"accepted","action":"send"}', "")

    directory = _directory(_recipient(), _friend())
    sender = ClawbotAlertSender(
        directory,
        ClawbotRunner(
            dependency, recipient_directory=directory, run_process=run
        ),
    )
    sender.send(_message())

    assert payloads == [
        {"action": "send", "account_id": "fixture-account", "target_user_id": "fixture-owner@im.wechat", "text": format_alert_message(_message())},
        {"action": "send", "account_id": "fixture-account", "target_user_id": "fixture-alice@im.wechat", "text": format_alert_message(_message())},
    ]


def test_sender_routes_subing_to_owner_only(tmp_path: Path) -> None:
    dependency, _ = _tree(tmp_path)
    targets: list[str] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        targets.append(json.loads(str(kwargs["input"]))["target_user_id"])
        return subprocess.CompletedProcess(argv, 0, '{"status":"accepted","action":"send"}', "")

    directory = _directory(_recipient(), _friend())
    sender = ClawbotAlertSender(
        directory,
        ClawbotRunner(dependency, recipient_directory=directory, run_process=run),
    )
    message = AlertNotificationMessage(
        rule_code="subing_entry_signal_v1",
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="5m",
        bar_end=datetime(2026, 8, 13, 2, 45, tzinfo=UTC),
        result_codes=("buy",),
    )

    sender.send(message)

    assert targets == ["fixture-owner@im.wechat"]


def test_sender_continues_after_recipient_failure_then_raises_public_summary(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dependency, _ = _tree(tmp_path)
    targets: list[str] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        target = json.loads(str(kwargs["input"]))["target_user_id"]
        targets.append(target)
        if target == "fixture-alice@im.wechat":
            raise RuntimeError("private provider detail")
        return subprocess.CompletedProcess(argv, 0, '{"status":"accepted","action":"send"}', "")

    directory = _directory(_recipient(), _friend(), _friend("bob"))
    sender = ClawbotAlertSender(
        directory,
        ClawbotRunner(dependency, recipient_directory=directory, run_process=run),
    )

    with pytest.raises(ClawbotDeliveryError) as captured:
        sender.send(_message())

    assert targets == [
        "fixture-owner@im.wechat",
        "fixture-alice@im.wechat",
        "fixture-bob@im.wechat",
    ]
    assert captured.value.summary.attempted == 3
    assert captured.value.summary.provider_accepted == 2
    assert captured.value.summary.failed == 1
    assert captured.value.summary.failed_aliases == ("alice",)
    public = f"{captured.value!r} {caplog.text}"
    assert "alice" in public
    assert "private provider detail" not in public
    assert "fixture-alice@im.wechat" not in public


def test_canary_selects_one_active_alias_and_reports_provider_acceptance(tmp_path: Path) -> None:
    dependency, _ = _tree(tmp_path)
    payloads: list[dict[str, object]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        payloads.append(json.loads(str(kwargs["input"])))
        return subprocess.CompletedProcess(argv, 0, '{"status":"accepted","action":"send"}', "")

    directory = _directory(_recipient(), _friend())
    sender = ClawbotAlertSender(
        directory,
        ClawbotRunner(dependency, recipient_directory=directory, run_process=run),
    )
    summary = sender.send_canary("alice")

    assert payloads == [
        {"action": "send", "account_id": "fixture-account", "target_user_id": "fixture-alice@im.wechat", "text": ALERT_CANARY_TEXT},
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

    summary = ClawbotAlertSender(
        _directory(),
        ClawbotRunner(
            dependency, recipient_directory=_directory(), run_process=run
        ),
    ).send_canary("owner")

    assert calls == 1
    assert summary.attempted == 1
    assert summary.provider_accepted == 0
    assert summary.failed == 1
    assert summary.failed_aliases == ("owner",)


def test_preflight_probes_every_active_recipient_without_sending_and_summarizes_failures(
    tmp_path: Path,
) -> None:
    dependency, _ = _tree(tmp_path)
    actions: list[tuple[str, str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        payload = json.loads(str(kwargs["input"]))
        actions.append((payload["action"], payload["target_user_id"]))
        if payload["target_user_id"] == "fixture-alice@im.wechat":
            raise RuntimeError("private probe failure")
        return subprocess.CompletedProcess(
            argv,
            0,
            '{"status":"ready","action":"probe","account_configured":true,"context_available":true}',
            "",
        )

    directory = _directory(_recipient(), _friend(), _friend("bob"))
    sender = ClawbotAlertSender(
        directory,
        ClawbotRunner(dependency, recipient_directory=directory, run_process=run),
    )

    summary = sender.preflight()

    assert actions == [
        ("probe", "fixture-owner@im.wechat"),
        ("probe", "fixture-alice@im.wechat"),
        ("probe", "fixture-bob@im.wechat"),
    ]
    assert summary.recipient_count == 3
    assert summary.ready_count == 2
    assert summary.failed_aliases == ("alice",)


def test_sender_builder_loads_directory_once_and_preflights_all_before_return(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dependency, _ = _tree(tmp_path)
    directory = _directory(_recipient(), _friend())
    loads: list[Path] = []
    actions: list[str] = []

    monkeypatch.setattr(
        clawbot,
        "build_clawbot_dependency_from_env",
        lambda *, verify_versions: dependency,
    )
    monkeypatch.setattr(
        clawbot,
        "load_recipient_directory",
        lambda path: loads.append(path) or directory,
    )

    class Runner(ClawbotRunner):
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def probe(self, recipient: ClawbotRecipient) -> None:
            actions.append(recipient.alias)

    monkeypatch.setattr(clawbot, "ClawbotRunner", Runner)

    sender = clawbot.build_clawbot_sender_from_env(live_probe=True)

    assert loads == [dependency.recipients_path]
    assert actions == ["owner", "alice"]
    assert isinstance(sender, ClawbotAlertSender)


def test_structural_transport_check_reads_files_without_version_probe_or_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dependency, manifest = _tree(tmp_path)
    owner_path = dependency.recipients_path.with_name("owner.json")
    write_clawbot_owner_atomic(
        owner_path,
        account_id="fixture-account",
        target_user_id="fixture-owner@im.wechat",
    )
    initialize_recipients_from_owner(owner_path, dependency.recipients_path)
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

    assert clawbot_transport_status_from_env() == {
        "transport": "clawbot-openclaw-weixin",
        "configured": True,
        "recipient_count": 1,
        "ready_count": 1,
        "would_send": False,
    }
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


def test_dependency_from_env_uses_only_the_v2_recipients_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = {
        "GUIYI_OPENCLAW_BIN": tmp_path / "openclaw",
        "GUIYI_OPENCLAW_NODE_BIN": tmp_path / "node",
        "GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT": tmp_path / "plugin",
        "GUIYI_OPENCLAW_STATE_DIR": tmp_path / "state",
        "GUIYI_OPENCLAW_CONFIG_PATH": tmp_path / "config.json",
        "GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH": tmp_path / "recipients.json",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("GUIYI_ALERT_CLAWBOT_OWNER_PATH", raising=False)
    observed: dict[str, Path] = {}
    marker = object()

    def resolve(**kwargs: object) -> object:
        observed.update({key: value for key, value in kwargs.items() if isinstance(value, Path)})
        return marker

    monkeypatch.setattr(clawbot, "resolve_clawbot_dependency", resolve)

    assert clawbot.build_clawbot_dependency_from_env(verify_versions=False) is marker
    assert observed["recipients_path"] == values["GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH"]
    assert "owner_path" not in observed


def test_dependency_repr_hides_private_paths(tmp_path: Path) -> None:
    dependency, _ = _tree(tmp_path)

    value = repr(dependency)

    assert "ClawbotDependency" in value
    assert str(dependency.recipients_path) not in value
