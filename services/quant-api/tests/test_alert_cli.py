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
    code = main(
        args,
        session_factory=lambda: nullcontext(object()),
        stdout=stdout,
        stderr=stderr,
        **factories,
    )
    return code, json.loads((stdout if code == 0 else stderr).getvalue())


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

    code, payload = _run(
        ["runtime", "alert"],
        alert_runtime_factory=lambda _session: Runtime(),
    )

    assert code == 0
    assert calls == ["run_forever"]
    assert payload == {
        "schema_version": 1,
        "command": "runtime.alert",
        "status": "ok",
        "foreground": True,
    }


def test_alert_canary_calls_only_fixed_sender_without_db_session_use() -> None:
    calls: list[str] = []

    class Sender:
        def send_canary(self) -> None:
            calls.append("send_canary")

    code, payload = _run(
        ["runtime", "alert-canary"],
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
        build_alert_runtime(object())  # type: ignore[arg-type]
