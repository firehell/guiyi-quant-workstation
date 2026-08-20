from __future__ import annotations

from contextlib import nullcontext
import io
import json
from types import SimpleNamespace

import pytest

import app.alerts.composition as alert_composition
from app.alerts.composition import build_alert_runtime
from app.alerts.notification import NotificationTransportError, ProviderAcceptance
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


def test_parser_exposes_only_active_runtime_domains_and_commands() -> None:
    parser = build_parser()
    domain_action = next(action for action in parser._actions if action.dest == "domain")
    assert set(domain_action.choices) == {"data", "research", "runtime"}
    runtime_parser = domain_action.choices["runtime"]
    command_action = next(
        action for action in runtime_parser._actions if action.dest == "runtime_command"
    )
    assert set(command_action.choices) == {
        "status",
        "live",
        "alert",
        "alert-canary",
    }


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


@pytest.mark.parametrize(
    "arguments",
    [
        ["runtime", "alert-canary"],
        ["runtime", "alert-canary", "--audience", "friend1"],
    ],
)
def test_alert_canary_requires_one_fixed_audience(arguments: list[str]) -> None:
    code, payload = _run(arguments)

    assert code == 2
    assert payload["readonly"] is False


@pytest.mark.parametrize("audience", ["owner", "htdy_observers"])
def test_alert_canary_uses_shared_sender_without_alert_mutation(
    audience: str,
) -> None:
    calls: list[str] = []

    class Sender:
        def send_canary(self, selected: str) -> ProviderAcceptance:
            calls.append(selected)
            return ProviderAcceptance("0123456789abcdef0123456789abcdef")

    def forbidden_session_factory():
        raise AssertionError("alert canary must not create Event or modify Scope")

    def forbidden_alert_runtime_factory():
        raise AssertionError("alert canary must not construct Alert Runtime")

    code, payload = _run(
        ["runtime", "alert-canary", "--audience", audience],
        session_factory=forbidden_session_factory,
        alert_runtime_factory=forbidden_alert_runtime_factory,
        alert_canary_sender_factory=lambda: Sender(),
    )

    assert code == 0
    assert calls == [audience]
    assert payload == {
        "schema_version": 1,
        "command": "runtime.alert-canary",
        "status": "accepted",
        "audience": audience,
        "provider_accepted": True,
        "provider_reference_suffix": "abcdef",
        "delivery_confirmed": False,
    }
    assert "0123456789abcdef0123456789abcdef" not in json.dumps(payload)


def test_alert_canary_factory_exception_is_sanitized_execution_error() -> None:
    def fail_factory():
        raise NotificationTransportError("ALERT_NOTIFICATION_CONFIG_INVALID")

    code, payload = _run(
        ["runtime", "alert-canary", "--audience", "owner"],
        alert_canary_sender_factory=fail_factory,
    )

    assert code == 1
    assert payload == {
        "schema_version": 1,
        "command": "runtime.alert-canary",
        "status": "error",
        "readonly": False,
        "error": {
            "code": "ALERT_NOTIFICATION_CONFIG_INVALID",
            "type": "NotificationTransportError",
        },
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


def test_default_alert_factory_fails_closed_without_activation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "app.alerts.composition.ALERT_RUNTIME_ACTIVATION_MARKER",
        tmp_path / "missing-marker",
    )

    with pytest.raises(RuntimeError, match="ALERT_RUNTIME_NOT_ENABLED"):
        build_alert_runtime()


def test_alert_runtime_composition_builds_one_sender_without_sending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    marker = tmp_path / "alert-runtime-enabled"
    marker.write_text("enabled\n", encoding="utf-8")
    sender = object()
    calls: list[str] = []
    monkeypatch.setattr(alert_composition, "ALERT_RUNTIME_ACTIVATION_MARKER", marker)
    monkeypatch.setattr(
        alert_composition,
        "build_notification_sender_from_env",
        lambda: calls.append("build") or sender,
    )
    monkeypatch.setattr(alert_composition, "load_operational_products", lambda: ("ag",))
    monkeypatch.setattr(alert_composition, "load_product_taxonomy", lambda: {})
    monkeypatch.setattr(
        alert_composition,
        "get_redis_connection",
        lambda: SimpleNamespace(pubsub=lambda **_kwargs: object()),
    )

    runtime = build_alert_runtime()

    assert calls == ["build"]
    assert runtime._sender is sender
