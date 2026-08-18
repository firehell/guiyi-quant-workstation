from __future__ import annotations

from contextlib import nullcontext
import io
import json

import pytest

from app.alerts.composition import build_alert_runtime, build_wecom_sender_from_env
from app.alerts.weixin import WeixinRegistrationError
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
        prompt_stream=factories.pop("prompt_stream", None),
        **factories,
    )
    selected = stdout if stdout.getvalue() else stderr
    return code, json.loads(selected.getvalue()), stdout.getvalue(), stderr.getvalue()


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
        "weixin-context",
        "weixin-register",
    }


def test_runtime_alert_runs_only_injected_foreground_runtime() -> None:
    calls: list[str] = []

    class Runtime:
        def run_forever(self) -> None:
            calls.append("run_forever")

    def forbidden_outer_session():
        raise AssertionError("runtime alert must not hold one process-lifetime DB session")

    code, payload, _stdout, _stderr = _run(
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


def test_runtime_weixin_context_runs_only_injected_foreground_monitor() -> None:
    calls: list[str] = []

    class Monitor:
        def run_forever(self) -> None:
            calls.append("run_forever")

    code, payload, _stdout, _stderr = _run(
        ["runtime", "weixin-context"],
        session_factory=lambda: (_ for _ in ()).throw(AssertionError("no DB session")),
        weixin_context_factory=lambda: Monitor(),
    )

    assert code == 0
    assert calls == ["run_forever"]
    assert payload == {
        "schema_version": 1,
        "command": "runtime.weixin-context",
        "status": "ok",
        "foreground": True,
    }


def test_alert_canary_uses_only_shared_sender_without_alert_mutation() -> None:
    calls: list[str] = []

    class Sender:
        def send_canary(self) -> None:
            calls.append("send_canary")

    def forbidden_session_factory():
        raise AssertionError("alert canary must not create Event or modify Scope")

    def forbidden_alert_runtime_factory():
        raise AssertionError("alert canary must not enable or construct Alert Runtime")

    code, payload, _stdout, _stderr = _run(
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
    }


def test_default_alert_factories_fail_closed_without_activation_or_webhook(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        "app.alerts.composition.ALERT_RUNTIME_ACTIVATION_MARKER",
        tmp_path / "missing-marker",
    )

    with pytest.raises(RuntimeError, match="WECOM_WEBHOOK_NOT_CONFIGURED"):
        build_wecom_sender_from_env()
    with pytest.raises(RuntimeError, match="ALERT_RUNTIME_NOT_ENABLED"):
        build_alert_runtime()


def test_weixin_register_uses_private_prompt_and_public_alias_only() -> None:
    prompt = io.StringIO()
    calls: list[tuple[str, io.StringIO]] = []

    def registration(alias: str, *, prompt_stream):
        calls.append((alias, prompt_stream))
        prompt_stream.write("challenge=secret-one-time-value\n")
        return object()

    code, payload, stdout, stderr = _run(
        ["runtime", "weixin-register", "--alias", "owner"],
        prompt_stream=prompt,
        weixin_register=registration,
    )

    assert code == 0
    assert calls == [("owner", prompt)]
    assert payload == {
        "schema_version": 1,
        "command": "runtime.weixin-register",
        "status": "ok",
        "alias": "owner",
    }
    assert "secret-one-time-value" not in stdout
    assert "@im.wechat" not in stdout
    assert stderr == ""
    assert "secret-one-time-value" in prompt.getvalue()


def test_weixin_register_failure_does_not_leak_private_values() -> None:
    prompt = io.StringIO()

    def registration(_alias: str, *, prompt_stream):
        prompt_stream.write("challenge=private-challenge\n")
        raise WeixinRegistrationError("WEIXIN_REGISTRATION_TIMEOUT")

    code, payload, stdout, stderr = _run(
        ["runtime", "weixin-register", "--alias", "owner"],
        prompt_stream=prompt,
        weixin_register=registration,
    )

    assert code == 1
    assert payload["error"]["code"] == "WEIXIN_REGISTRATION_TIMEOUT"
    assert stdout == ""
    assert "private-challenge" not in stderr
    assert "@im.wechat" not in stderr


def test_weixin_register_requires_dedicated_tty_before_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def registration(_alias: str, *, prompt_stream):
        nonlocal called
        called = True

    def unavailable_tty(*_args, **_kwargs):
        raise OSError("no controlling terminal")

    monkeypatch.setattr("builtins.open", unavailable_tty)
    code, payload, stdout, stderr = _run(
        ["runtime", "weixin-register", "--alias", "owner"],
        weixin_register=registration,
    )

    assert code == 1
    assert called is False
    assert payload["error"]["code"] == "WEIXIN_REGISTRATION_TTY_REQUIRED"
    assert stdout == ""
    assert "no controlling terminal" not in stderr
