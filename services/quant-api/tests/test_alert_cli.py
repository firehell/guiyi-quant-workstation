from __future__ import annotations

from contextlib import nullcontext
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.alerts.composition as alert_composition
from app.alerts.composition import build_alert_runtime
from app.alerts.clawbot import ClawbotError, ClawbotOwnerCandidate
from app.alerts.clawbot_owner import ClawbotOwner
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
        "clawbot-owner-bootstrap",
        "clawbot-preflight",
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


def test_clawbot_owner_bootstrap_discovery_is_readonly_and_hides_ids() -> None:
    class Runner:
        dependency = SimpleNamespace(owner_path=Path("/private/owner.json"))

        def discover_owner(self) -> ClawbotOwnerCandidate:
            return ClawbotOwnerCandidate("fixture-account", "fixture-owner@im.wechat")

    code, payload = _run(
        ["runtime", "clawbot-owner-bootstrap"],
        clawbot_runner_factory=lambda: Runner(),
    )

    assert code == 0
    assert payload == {
        "schema_version": 1,
        "command": "runtime.clawbot-owner-bootstrap",
        "status": "ready",
        "readonly": True,
        "channel": "openclaw-weixin",
        "owner_alias": "owner",
        "account_count": 1,
        "owner_candidate_count": 1,
        "context_available": True,
        "owner_written": False,
    }
    assert "fixture-account" not in json.dumps(payload)
    assert "fixture-owner" not in json.dumps(payload)


def test_clawbot_owner_bootstrap_write_requires_explicit_flag_and_hides_ids() -> None:
    writes: list[tuple[Path, str, str]] = []

    class Runner:
        dependency = SimpleNamespace(owner_path=Path("/private/owner.json"))

        def discover_owner(self) -> ClawbotOwnerCandidate:
            return ClawbotOwnerCandidate("fixture-account", "fixture-owner@im.wechat")

    code, payload = _run(
        ["runtime", "clawbot-owner-bootstrap", "--confirm-write-owner"],
        clawbot_runner_factory=lambda: Runner(),
        clawbot_owner_writer=lambda path, *, account_id, target_user_id: writes.append(
            (path, account_id, target_user_id)
        ),
    )

    assert code == 0
    assert writes == [(Path("/private/owner.json"), "fixture-account", "fixture-owner@im.wechat")]
    assert payload == {
        "schema_version": 1,
        "command": "runtime.clawbot-owner-bootstrap",
        "status": "ok",
        "readonly": False,
        "channel": "openclaw-weixin",
        "owner_alias": "owner",
        "owner_written": True,
    }
    assert "fixture-account" not in json.dumps(payload)


def test_clawbot_preflight_loads_frozen_owner_and_never_sends() -> None:
    calls: list[object] = []
    owner = ClawbotOwner(1, "openclaw-weixin", "owner", "fixture-account", "fixture-owner@im.wechat")

    class Runner:
        dependency = SimpleNamespace(owner_path=Path("/private/owner.json"))

        def probe(self, value: ClawbotOwner) -> None:
            calls.append(value)

        def send_text(self, *_args: object) -> None:
            raise AssertionError("preflight must not send")

    code, payload = _run(
        ["runtime", "clawbot-preflight"],
        clawbot_runner_factory=lambda: Runner(),
        clawbot_owner_loader=lambda _path: owner,
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
