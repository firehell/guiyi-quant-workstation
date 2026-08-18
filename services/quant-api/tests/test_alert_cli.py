from __future__ import annotations

from contextlib import nullcontext
import io
import json

import pytest

from app.alerts.composition import build_alert_runtime, build_wecom_sender_from_env
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

    assert set(command_action.choices) == {"status", "live", "alert", "alert-canary"}


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
                    "automation_completed": 1,
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
        "automation_completed": 1,
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
                    "automation_completed": 0,
                    "failed": 1,
                    "failed_aliases": ("primary_alert_group",),
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
        "automation_completed": 0,
        "failed": 1,
        "failed_aliases": ["primary_alert_group"],
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
