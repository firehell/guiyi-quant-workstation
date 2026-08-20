from __future__ import annotations

from contextlib import nullcontext
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.alerts.composition as alert_composition
from app.alerts.composition import build_alert_runtime
from app.alerts.clawbot import ClawbotError
from app.alerts.recipient_bootstrap import (
    BootstrapConfirmResult,
    BootstrapPrepareResult,
    RecipientRetireResult,
)
from app.alerts.recipients import ClawbotRecipient, RecipientDirectory
from app.guiyi_cli.main import build_parser, main


def _run(args: list[str], **factories):
    stdout = io.StringIO()
    stderr = io.StringIO()
    session_factory = factories.pop("session_factory", lambda: nullcontext(object()))
    code = main(
        args,
        session_factory=session_factory,
        stdout=stdout,
        stderr=stderr,
        **factories,
    )
    stream = stdout if stdout.getvalue() else stderr
    return code, json.loads(stream.getvalue())


def test_runtime_parser_exposes_alert_and_fixed_canary() -> None:
    parser = build_parser()
    runtime_action = next(action for action in parser._actions if action.dest == "domain")
    runtime_parser = runtime_action.choices["runtime"]
    command_action = next(
        action for action in runtime_parser._actions if action.dest == "runtime_command"
    )

    assert set(command_action.choices) == {
        "status",
        "live",
        "alert",
        "alert-canary",
        "clawbot-preflight",
    }


def test_recipient_parser_exposes_only_four_mutation_commands() -> None:
    parser = build_parser()
    domain_action = next(action for action in parser._actions if action.dest == "domain")
    recipients_parser = domain_action.choices["recipients"]
    command_action = next(
        action
        for action in recipients_parser._actions
        if action.dest == "recipients_command"
    )

    assert set(command_action.choices) == {"init", "prepare", "confirm", "retire"}


def test_runtime_alert_runs_only_injected_foreground_runtime() -> None:
    calls: list[str] = []

    class Runtime:
        def run_forever(self) -> None:
            calls.append("run_forever")

    def forbidden_outer_session():
        raise AssertionError("runtime alert must not hold one process-lifetime DB session")

    code, payload = _run(
        ["runtime", "alert"],
        session_factory=forbidden_outer_session,
        alert_runtime_factory=lambda: Runtime(),
    )

    assert code == 0
    assert calls == ["run_forever"]
    assert payload == {
        "schema_version": 1,
        "command": "runtime.alert",
        "status": "ok",
        "foreground": True,
    }


def test_recipients_init_is_nonreadonly_and_outputs_only_public_count() -> None:
    directory = RecipientDirectory(
        2,
        "openclaw-weixin",
        "fixture-account",
        (ClawbotRecipient("owner", "fixture-account", "fixture-owner@im.wechat"),),
        (),
    )
    calls: list[tuple[Path, Path]] = []

    code, payload = _run(
        ["recipients", "init"],
        recipient_paths=lambda: (Path("/private/owner.json"), Path("/private/recipients.json")),
        recipient_initializer=lambda owner, recipients: calls.append((owner, recipients)) or directory,
    )

    assert code == 0
    assert calls == [(Path("/private/owner.json"), Path("/private/recipients.json"))]
    assert payload == {
        "schema_version": 1,
        "command": "recipients.init",
        "status": "ok",
        "readonly": False,
        "channel": "openclaw-weixin",
        "recipient_count": 1,
    }
    assert "fixture" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("command", "result", "count_key", "count"),
    [
        ("prepare", BootstrapPrepareResult("alice", 2), "baseline_candidate_count", 2),
        ("confirm", BootstrapConfirmResult("alice", 1), "candidate_count", 1),
        ("retire", RecipientRetireResult("alice", 1), "active_recipient_count", 1),
    ],
)
def test_recipient_mutations_are_nonreadonly_and_output_only_alias_and_count(
    command: str,
    result: object,
    count_key: str,
    count: int,
) -> None:
    calls: list[tuple[str, str]] = []

    class Bootstrap:
        def __getattribute__(self, name: str):
            if name in {"prepare", "confirm", "retire"}:
                return lambda alias: calls.append((name, alias)) or result
            return super().__getattribute__(name)

    code, payload = _run(
        ["recipients", command, "--alias", "alice"],
        recipient_bootstrap_factory=lambda: Bootstrap(),
    )

    assert code == 0
    assert calls == [(command, "alice")]
    assert payload == {
        "schema_version": 1,
        "command": f"recipients.{command}",
        "status": "ok",
        "readonly": False,
        "channel": "openclaw-weixin",
        "alias": "alice",
        count_key: count,
    }


def test_recipient_failure_is_nonreadonly_and_never_exposes_private_values() -> None:
    class Bootstrap:
        def confirm(self, _alias: str) -> None:
            from app.alerts.recipient_bootstrap import RecipientBootstrapError

            raise RecipientBootstrapError("CLAWBOT_RECIPIENT_CANDIDATE_INVALID")

    code, payload = _run(
        ["recipients", "confirm", "--alias", "alice"],
        recipient_bootstrap_factory=lambda: Bootstrap(),
    )

    assert code == 1
    assert payload == {
        "schema_version": 1,
        "command": "recipients.confirm",
        "status": "error",
        "readonly": False,
        "error": {
            "code": "CLAWBOT_RECIPIENT_CANDIDATE_INVALID",
            "type": "RecipientBootstrapError",
        },
    }
    assert "fixture" not in json.dumps(payload)


@pytest.mark.parametrize(
    "arguments",
    [
        ["recipients", "prepare"],
        ["recipients", "confirm", "--alias", "alice", "--confirm"],
        ["recipients", "unknown"],
    ],
)
def test_recipient_parser_failures_remain_nonreadonly_mutations(
    arguments: list[str],
) -> None:
    code, payload = _run(arguments)

    assert code == 2
    assert payload["status"] == "error"
    assert payload["readonly"] is False
    assert payload["error"] == {
        "code": "CLI_ARGUMENT_INVALID",
        "type": "CliUsageError",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        ["runtime", "status", "--unexpected"],
        ["research", "unknown"],
    ],
)
def test_readonly_command_parser_failures_stay_readonly(arguments: list[str]) -> None:
    code, payload = _run(arguments)

    assert code == 2
    assert payload["status"] == "error"
    assert payload["readonly"] is True


def test_clawbot_preflight_loads_frozen_owner_and_never_sends() -> None:
    calls: list[object] = []
    owner = ClawbotRecipient(
        "owner", "fixture-account", "fixture-owner@im.wechat"
    )
    directory = RecipientDirectory(
        2,
        "openclaw-weixin",
        "fixture-account",
        (owner,),
        (),
    )

    class Runner:
        dependency = SimpleNamespace(recipients_path=Path("/private/recipients.json"))

        def probe(self, value: ClawbotRecipient) -> None:
            calls.append(value)

        def send_text(self, *_args: object) -> None:
            raise AssertionError("preflight must not send")

    code, payload = _run(
        ["runtime", "clawbot-preflight"],
        clawbot_runner_factory=lambda: Runner(),
        recipient_directory_loader=lambda _path: directory,
    )

    assert code == 0
    assert calls == [owner]
    assert payload == {
        "schema_version": 1,
        "command": "runtime.clawbot-preflight",
        "status": "ok",
        "readonly": True,
        "channel": "openclaw-weixin",
        "owner_alias": "owner",
        "account_configured": True,
        "context_available": True,
        "would_send": False,
    }


def test_alert_canary_uses_only_shared_sender_without_alert_mutation() -> None:
    calls: list[str] = []

    class Sender:
        def send_canary(self):
            calls.append("send_canary")
            return type(
                "Summary",
                (),
                {
                    "attempted": 1,
                    "provider_accepted": 1,
                    "failed": 0,
                    "failed_aliases": (),
                },
            )()

    def forbidden_session_factory():
        raise AssertionError("alert canary must not create Event or modify Scope")

    def forbidden_alert_runtime_factory():
        raise AssertionError("alert canary must not enable or construct Alert Runtime")

    code, payload = _run(
        ["runtime", "alert-canary"],
        session_factory=forbidden_session_factory,
        alert_runtime_factory=forbidden_alert_runtime_factory,
        alert_canary_sender_factory=lambda: Sender(),
    )

    assert code == 0
    assert calls == ["send_canary"]
    assert payload == {
        "schema_version": 1,
        "command": "runtime.alert-canary",
        "status": "ok",
        "attempted": 1,
        "provider_accepted": 1,
        "failed": 0,
        "failed_aliases": [],
    }


def test_alert_canary_partial_failure_is_normal_stdout_json_and_exit_one() -> None:
    class Sender:
        def send_canary(self):
            return type(
                "Summary",
                (),
                {
                    "attempted": 1,
                    "provider_accepted": 0,
                    "failed": 1,
                    "failed_aliases": ("owner",),
                },
            )()

    code, payload = _run(
        ["runtime", "alert-canary"],
        alert_canary_sender_factory=lambda: Sender(),
    )

    assert code == 1
    assert payload == {
        "schema_version": 1,
        "command": "runtime.alert-canary",
        "status": "failed",
        "attempted": 1,
        "provider_accepted": 0,
        "failed": 1,
        "failed_aliases": ["owner"],
    }


def test_alert_canary_factory_exception_is_execution_error() -> None:
    def fail_factory():
        raise ClawbotError("ALERT_NOTIFICATION_TRANSPORT_NOT_READY")

    code, payload = _run(
        ["runtime", "alert-canary"],
        alert_canary_sender_factory=fail_factory,
    )

    assert code == 1
    assert payload == {
        "schema_version": 1,
        "command": "runtime.alert-canary",
        "status": "error",
        "readonly": False,
        "error": {
            "code": "ALERT_NOTIFICATION_TRANSPORT_NOT_READY",
            "type": "ClawbotError",
        },
    }


def test_alert_canary_send_exception_is_execution_error() -> None:
    class Sender:
        def send_canary(self):
            raise ClawbotError("CLAWBOT_SEND_FAILED")

    code, payload = _run(
        ["runtime", "alert-canary"],
        alert_canary_sender_factory=lambda: Sender(),
    )

    assert code == 1
    assert payload["command"] == "runtime.alert-canary"
    assert payload["readonly"] is False
    assert payload["error"] == {
        "code": "CLAWBOT_SEND_FAILED",
        "type": "ClawbotError",
    }


def test_runtime_status_exception_remains_readonly() -> None:
    def fail_health(_session):
        raise RuntimeError("private health detail")

    code, payload = _run(
        ["runtime", "status"],
        runtime_health_builder=fail_health,
    )

    assert code == 1
    assert payload["command"] == "runtime.status"
    assert payload["readonly"] is True
    assert payload["error"] == {
        "code": "CLI_INTERNAL_ERROR",
        "type": "RuntimeError",
    }


@pytest.mark.parametrize("runtime_command", ("live", "alert"))
def test_foreground_runtime_exception_is_not_readonly(runtime_command: str) -> None:
    class Runtime:
        def run_forever(self) -> None:
            raise RuntimeError("private runtime detail")

    factories = (
        {"live_service_factory": lambda _session: Runtime()}
        if runtime_command == "live"
        else {"alert_runtime_factory": lambda: Runtime()}
    )

    code, payload = _run(["runtime", runtime_command], **factories)

    assert code == 1
    assert payload["command"] == f"runtime.{runtime_command}"
    assert payload["readonly"] is False
    assert payload["error"] == {
        "code": "CLI_INTERNAL_ERROR",
        "type": "RuntimeError",
    }


def test_default_alert_factories_fail_closed_without_activation_or_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "app.alerts.composition.ALERT_RUNTIME_ACTIVATION_MARKER",
        tmp_path / "missing-marker",
    )

    with pytest.raises(RuntimeError, match="ALERT_RUNTIME_NOT_ENABLED"):
        build_alert_runtime()


def test_alert_runtime_composition_uses_one_live_clawbot_probe_and_never_sends(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    marker = tmp_path / "alert-runtime-enabled"
    marker.write_text("enabled\n", encoding="utf-8")
    sender = object()
    calls: list[bool] = []
    monkeypatch.setattr(alert_composition, "ALERT_RUNTIME_ACTIVATION_MARKER", marker)
    monkeypatch.setattr(
        alert_composition,
        "build_clawbot_sender_from_env",
        lambda *, live_probe: calls.append(live_probe) or sender,
    )
    monkeypatch.setattr(alert_composition, "load_operational_products", lambda: ("ag",))
    monkeypatch.setattr(alert_composition, "load_product_taxonomy", lambda: {})
    monkeypatch.setattr(
        alert_composition,
        "get_redis_connection",
        lambda: SimpleNamespace(pubsub=lambda **_kwargs: object()),
    )

    runtime = build_alert_runtime()

    assert calls == [True]
    assert runtime._sender is sender
