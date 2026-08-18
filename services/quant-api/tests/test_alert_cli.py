from __future__ import annotations

from contextlib import nullcontext
import io
import json

import pytest

import app.alerts.composition as alert_composition
from app.alerts.composition import (
    build_alert_runtime,
    build_wechat_group_sender_from_env,
)
from app.alerts.wechat_courier import WeChatCourierError
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
        "alert-target-verify",
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


def test_alert_target_verify_is_no_send_and_exposes_alias_only() -> None:
    calls: list[str] = []

    class Sender:
        def verify_target(self) -> None:
            calls.append("verify_target")

        def send(self, *_args: object) -> None:
            calls.append("send")

        def send_canary(self) -> None:
            calls.append("send_canary")

    code, payload = _run(
        ["runtime", "alert-target-verify"],
        alert_target_sender_factory=lambda: Sender(),
    )

    assert code == 0
    assert calls == ["verify_target"]
    assert payload == {
        "schema_version": 1,
        "command": "runtime.alert-target-verify",
        "status": "ok",
        "readonly": False,
        "group_alias": "primary_alert_group",
        "target_verified": True,
        "message_sent": False,
    }
    assert "fixture-group-title" not in json.dumps(payload)


def test_alert_target_verify_factory_failure_is_sanitized_and_no_send() -> None:
    calls: list[str] = []

    def fail_factory():
        calls.append("factory")
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")

    code, payload = _run(
        ["runtime", "alert-target-verify"],
        alert_target_sender_factory=fail_factory,
    )

    assert code == 1
    assert calls == ["factory"]
    assert payload["command"] == "runtime.alert-target-verify"
    assert payload["readonly"] is False
    assert payload["error"] == {
        "code": "WECHAT_COURIER_DEPENDENCY_INVALID",
        "type": "WeChatCourierError",
    }


def test_alert_target_verify_target_failure_is_sanitized_and_no_send() -> None:
    calls: list[str] = []

    class Sender:
        def verify_target(self) -> None:
            calls.append("verify_target")
            raise WeChatCourierError("WECHAT_GROUP_TARGET_UNVERIFIED")

        def send(self, *_args: object) -> None:
            calls.append("send")

    code, payload = _run(
        ["runtime", "alert-target-verify"],
        alert_target_sender_factory=lambda: Sender(),
    )

    assert code == 1
    assert calls == ["verify_target"]
    assert payload["readonly"] is False
    assert payload["error"] == {
        "code": "WECHAT_GROUP_TARGET_UNVERIFIED",
        "type": "WeChatCourierError",
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


def test_alert_canary_factory_exception_is_execution_error() -> None:
    def fail_factory():
        raise WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")

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
            "code": "WECHAT_COURIER_DEPENDENCY_INVALID",
            "type": "WeChatCourierError",
        },
    }


def test_alert_canary_send_exception_is_execution_error() -> None:
    class Sender:
        def send_canary(self):
            raise WeChatCourierError("WECHAT_COURIER_SEND_FAILED")

    code, payload = _run(
        ["runtime", "alert-canary"],
        alert_canary_sender_factory=lambda: Sender(),
    )

    assert code == 1
    assert payload["command"] == "runtime.alert-canary"
    assert payload["readonly"] is False
    assert payload["error"] == {
        "code": "WECHAT_COURIER_SEND_FAILED",
        "type": "WeChatCourierError",
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
    monkeypatch.delenv("GUIYI_WECHAT_COURIER_ROOT", raising=False)
    monkeypatch.delenv("GUIYI_ALERT_WECHAT_GROUP_PATH", raising=False)
    monkeypatch.setattr(
        "app.alerts.composition.ALERT_RUNTIME_ACTIVATION_MARKER",
        tmp_path / "missing-marker",
    )

    with pytest.raises(RuntimeError, match="ALERT_NOTIFICATION_TRANSPORT_NOT_READY"):
        build_wechat_group_sender_from_env()
    with pytest.raises(RuntimeError, match="ALERT_RUNTIME_NOT_ENABLED"):
        build_alert_runtime()


@pytest.mark.parametrize("failure", ("missing_config", "invalid_config", "wrong_commit"))
def test_group_sender_composition_collapses_private_config_and_dependency_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    failure: str,
) -> None:
    root = tmp_path / "courier"
    root.mkdir()
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    config = secrets / "alert-wechat-group.json"
    if failure != "missing_config":
        config.write_text(
            '{"version":1,"channel":"wechat-courier","group_alias":"primary_alert_group","target_chat":"fixture-group-title"}',
            encoding="utf-8",
        )
        config.chmod(0o644 if failure == "invalid_config" else 0o600)
    monkeypatch.setenv("GUIYI_WECHAT_COURIER_ROOT", str(root))
    monkeypatch.setenv("GUIYI_ALERT_WECHAT_GROUP_PATH", str(config))
    monkeypatch.setattr(alert_composition, "WECHAT_EXTERNAL_VOLUME_ROOT", tmp_path)
    if failure == "wrong_commit":
        monkeypatch.setattr(
            alert_composition,
            "resolve_wechat_courier_dependency",
            lambda _root: (_ for _ in ()).throw(
                WeChatCourierError("WECHAT_COURIER_DEPENDENCY_INVALID")
            ),
        )

    with pytest.raises(RuntimeError, match="^ALERT_NOTIFICATION_TRANSPORT_NOT_READY$"):
        build_wechat_group_sender_from_env()


def test_valid_group_sender_composition_does_no_gui_verify_or_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    root = tmp_path / "courier"
    root.mkdir()
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    config = secrets / "alert-wechat-group.json"
    config.write_text(
        '{"version":1,"channel":"wechat-courier","group_alias":"primary_alert_group","target_chat":"fixture-group-title"}',
        encoding="utf-8",
    )
    config.chmod(0o600)
    dependency = object()
    constructed: list[object] = []

    class StructuralRunner:
        def __init__(self, value: object) -> None:
            constructed.append(value)

        def verify_target(self, *_args: object) -> None:
            raise AssertionError("composition must not open GUI or verify")

        def send_text(self, *_args: object) -> None:
            raise AssertionError("composition must not send")

    monkeypatch.setenv("GUIYI_WECHAT_COURIER_ROOT", str(root))
    monkeypatch.setenv("GUIYI_ALERT_WECHAT_GROUP_PATH", str(config))
    monkeypatch.setattr(alert_composition, "WECHAT_EXTERNAL_VOLUME_ROOT", tmp_path)
    monkeypatch.setattr(
        alert_composition,
        "resolve_wechat_courier_dependency",
        lambda _root: dependency,
    )
    monkeypatch.setattr(alert_composition, "WeChatCourierRunner", StructuralRunner)

    sender = build_wechat_group_sender_from_env()

    assert constructed == [dependency]
    assert sender is not None


def test_group_sender_composition_rejects_external_volume_escape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    allowed_root = tmp_path / "Volumes"
    allowed_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    courier = outside / "courier"
    courier.mkdir()
    secrets = outside / "secrets"
    secrets.mkdir(mode=0o700)
    config = secrets / "alert-wechat-group.json"
    config.write_text(
        '{"version":1,"channel":"wechat-courier","group_alias":"primary_alert_group","target_chat":"fixture-group-title"}',
        encoding="utf-8",
    )
    config.chmod(0o600)
    escape = allowed_root / "escape"
    escape.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(alert_composition, "WECHAT_EXTERNAL_VOLUME_ROOT", allowed_root)
    monkeypatch.setenv("GUIYI_WECHAT_COURIER_ROOT", str(escape / "courier"))
    monkeypatch.setenv(
        "GUIYI_ALERT_WECHAT_GROUP_PATH",
        str(escape / "secrets/alert-wechat-group.json"),
    )
    monkeypatch.setattr(
        alert_composition,
        "load_wechat_group_target",
        lambda _path: (_ for _ in ()).throw(AssertionError("escaped path reached loader")),
    )

    with pytest.raises(RuntimeError, match="^ALERT_NOTIFICATION_TRANSPORT_NOT_READY$"):
        build_wechat_group_sender_from_env()
