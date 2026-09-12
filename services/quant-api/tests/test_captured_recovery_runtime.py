from __future__ import annotations

from datetime import UTC, datetime, timedelta
from contextlib import nullcontext
import importlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
from types import SimpleNamespace

import pytest


NOW = datetime(2026, 9, 8, 2, 0, tzinfo=UTC)
COMMIT = "a" * 40


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    module = importlib.import_module("app.market_data.captured_recovery_runtime")
    root = tmp_path.resolve()
    marker_dir = root / ".run"
    marker_dir.mkdir(mode=0o700)
    for name in ("market-runtime-enabled", "alert-runtime-enabled"):
        marker = marker_dir / name
        marker.write_text("enabled\n")
        marker.chmod(0o600)
    monkeypatch.setenv("GUIYI_LIVE_RECOVERY_ENABLED", "1")
    outputs = {
        "root": str(root), "branch": "HEAD", "commit": COMMIT,
        "tag": "v1.10.4", "tag_type": "tag", "peeled": COMMIT, "status": "",
        "live": f"gui/501/com.guiyi.quant-live = {{\nstate = running\npid = 123\n"
        f"working directory = {root}\nenvironment = {{\n"
        f"GUIYI_PROJECT_ROOT => {root}\nGUIYI_RUNTIME_COMMIT => {COMMIT}\n}}\n"
        "resource coalition = {\nstate = active\n}\n}\n",
    }
    outputs["alert"] = outputs["live"]
    outputs["after_market"] = outputs["live"].replace(
        "state = running\npid = 123\n", "state = not running\n",
    )
    home = root / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    plist = home / "Library" / "LaunchAgents" / "com.guiyi.quant-after-market.plist"
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps({
        "Label": "com.guiyi.quant-after-market", "WorkingDirectory": str(root),
        "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": str(root), "GUIYI_RUNTIME_COMMIT": COMMIT},
    }))
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "/bin/launchctl":
            key = ("live" if args[-1].endswith("quant-live") else
                   "alert" if args[-1].endswith("quant-alert") else "after_market")
        elif args[-1] == "--show-toplevel":
            key = "root"
        elif "--abbrev-ref" in args:
            key = "branch"
        elif "--exact-match" in args:
            key = "tag"
        elif "cat-file" in args:
            key = "tag_type"
        elif args[-1].endswith("^{commit}"):
            key = "peeled"
        elif "status" in args:
            key = "status"
        else:
            key = "commit"
        return SimpleNamespace(returncode=0, stdout=outputs[key], stderr="secret stderr")

    monkeypatch.setattr(module.subprocess, "run", run)
    heartbeat = {
        "generated_at": NOW.isoformat(), "runtime_root": str(root),
        "runtime_commit": COMMIT, "recovery_guard_enabled": True,
    }
    return SimpleNamespace(module=module, root=root, outputs=outputs,
                           heartbeat=heartbeat, calls=calls, plist=plist)


def verify(runtime, **changes):
    values = dict(now=NOW, root=runtime.root,
                  live_heartbeat=runtime.heartbeat.copy(),
                  alert_heartbeat=runtime.heartbeat.copy())
    values.update(changes)
    return runtime.module.verify_captured_recovery_runtime(**values)


def test_exact_runtime_identity_and_fixed_read_only_commands(runtime):
    result = verify(runtime)
    assert result == json.dumps({"root": str(runtime.root), "commit": COMMIT,
                                 "tag": "v1.10.4"}, sort_keys=True, separators=(",", ":"))
    for args, kwargs in runtime.calls:
        assert args[0] in {"/usr/bin/git", "/bin/launchctl"}
        assert kwargs["timeout"] <= 5
        assert not kwargs.get("shell", False)
        assert kwargs["stderr"] == subprocess.DEVNULL


@pytest.mark.parametrize("key,value", [
    ("root", "/other"), ("branch", "develop"), ("commit", "wrong"),
    ("tag", "v1.10.4-1-gabc"), ("tag", "candidate"), ("status", " M tracked.py"),
    ("status", "?? untracked.py"), ("alert", ""),
    ("tag_type", "commit"), ("peeled", "b" * 40),
])
def test_inexact_code_or_loaded_identity_fails_closed(runtime, key, value):
    runtime.outputs[key] = value
    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError) as caught:
        verify(runtime)
    assert caught.value.code.startswith("CAPTURED_RECOVERY_RUNTIME_")
    assert str(caught.value) == caught.value.code


@pytest.mark.parametrize("replace", [
    ("state = running", "state = waiting"), ("pid = 123", "pid = 0"),
    (COMMIT, "b" * 40), ("GUIYI_PROJECT_ROOT", "UNKNOWN_ROOT"),
    ("working directory", "UNKNOWN_DIRECTORY"),
])
def test_loaded_service_must_be_running_and_match(runtime, replace):
    runtime.outputs["alert"] = runtime.outputs["alert"].replace(*replace)
    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError):
        verify(runtime)


def test_duplicate_identity_fields_fail_closed(runtime):
    runtime.outputs["live"] = runtime.outputs["live"].replace(
        f"GUIYI_RUNTIME_COMMIT => {COMMIT}",
        f"GUIYI_RUNTIME_COMMIT => {COMMIT}\nGUIYI_RUNTIME_COMMIT => {COMMIT}",
    )
    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError):
        verify(runtime)


@pytest.mark.parametrize("service", ["live_heartbeat", "alert_heartbeat"])
@pytest.mark.parametrize("change", [
    None, {}, {"recovery_guard_enabled": False}, {"recovery_guard_enabled": 1},
    {"runtime_root": "/other"}, {"runtime_commit": "b" * 40},
    {"generated_at": (NOW - timedelta(seconds=31)).isoformat()},
    {"generated_at": (NOW + timedelta(microseconds=1)).isoformat()},
    {"generated_at": NOW.replace(tzinfo=None).isoformat()},
])
def test_old_stale_mismatched_or_disabled_heartbeat_is_rejected(runtime, service, change):
    heartbeat = None if change is None else ({**runtime.heartbeat, **change} if change else {})
    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError):
        verify(runtime, **{service: heartbeat})


def test_freshness_boundary_is_inclusive(runtime):
    runtime.heartbeat["generated_at"] = (NOW - timedelta(seconds=30)).isoformat()
    verify(runtime)


@pytest.mark.parametrize("mode", ["missing", "unsafe", "symlink", "contents"])
def test_marker_must_be_safe_enabled_regular_file(runtime, mode):
    marker = runtime.root / ".run" / "alert-runtime-enabled"
    if mode in {"missing", "symlink"}:
        marker.unlink()
        if mode == "symlink":
            marker.symlink_to("market-runtime-enabled")
    elif mode == "unsafe":
        marker.chmod(0o644)
    else:
        marker.write_text("disabled\n")
    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError):
        verify(runtime)


def test_environment_disabled_before_commands(runtime, monkeypatch):
    monkeypatch.delenv("GUIYI_LIVE_RECOVERY_ENABLED")
    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError):
        verify(runtime)
    assert not runtime.calls


@pytest.mark.parametrize("error", [OSError("secret"), subprocess.TimeoutExpired("secret", 5)])
def test_subprocess_failures_are_sanitized(runtime, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(runtime.module.subprocess, "run", fail)
    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError) as caught:
        verify(runtime)
    assert "secret" not in str(caught.value)


def test_launchd_reader_accepts_only_explicit_label_absence(runtime, monkeypatch):
    monkeypatch.setattr(runtime.module, "_read_command", lambda *args, **kwargs: "domain")
    monkeypatch.setattr(
        runtime.module,
        "_command_result",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="Could not find service"
        ),
    )

    assert (
        runtime.module._read_launchd_service(
            "com.guiyi.quant-after-market", root=runtime.root
        )
        is None
    )


def test_launchd_reader_rejects_quoted_absence_for_a_different_label(
    runtime, monkeypatch
):
    monkeypatch.setattr(runtime.module, "_read_command", lambda *args, **kwargs: "domain")
    monkeypatch.setattr(
        runtime.module,
        "_command_result",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=113,
            stdout="",
            stderr=(
                'Could not find service "com.guiyi.quant-live" '
                f"in domain for user gui: {os.getuid()}"
            ),
        ),
    )

    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError) as caught:
        runtime.module._read_launchd_service(
            "com.guiyi.quant-after-market", root=runtime.root
        )

    assert caught.value.code == "CAPTURED_RECOVERY_RUNTIME_IDENTITY_UNAVAILABLE"


@pytest.mark.parametrize(
    "stderr", ["permission denied", "Could not find service\npermission denied", ""]
)
def test_launchd_reader_never_treats_errors_as_absence(runtime, monkeypatch, stderr):
    monkeypatch.setattr(runtime.module, "_read_command", lambda *args, **kwargs: "domain")
    monkeypatch.setattr(
        runtime.module,
        "_command_result",
        lambda *args, **kwargs: SimpleNamespace(returncode=77, stdout="", stderr=stderr),
    )

    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError) as caught:
        runtime.module._read_launchd_service(
            "com.guiyi.quant-after-market", root=runtime.root
        )
    assert caught.value.code == "CAPTURED_RECOVERY_RUNTIME_IDENTITY_UNAVAILABLE"


@pytest.mark.parametrize("worker,guard", [(False, False), (True, False), (True, True)])
def test_live_heartbeat_proves_actual_worker_and_guard(monkeypatch, worker, guard):
    from app.core.env import PROJECT_ROOT
    from app.market_data.live_market import LiveMarketService

    monkeypatch.setenv("GUIYI_RUNTIME_COMMIT", COMMIT)
    monkeypatch.setenv("GUIYI_LIVE_RECOVERY_ENABLED", "1")
    captured = []
    service = LiveMarketService(
        provider_factory=lambda: None, dominant_source=None, phase_resolver=None,
        store=SimpleNamespace(set_heartbeat=captured.append), operational_products=(),
        recovery_fetch_factory=(lambda: None) if worker else None,
        recovery_sessions=(lambda symbol, day: ()) if worker else None,
        recovery_guard_factory=(lambda symbol: nullcontext()) if guard else None,
    )
    service._publish_heartbeat(NOW, {})
    assert captured[0]["recovery_guard_enabled"] is (worker and guard)
    assert captured[0]["runtime_root"] == str(PROJECT_ROOT)
    assert captured[0]["runtime_commit"] == COMMIT


@pytest.mark.parametrize("guard", [False, True])
def test_alert_heartbeat_proves_actual_guard_without_status_schema_change(monkeypatch, guard):
    from app.core.env import PROJECT_ROOT
    from app.alerts.runtime import AlertRuntime, empty_alert_runtime_status

    monkeypatch.setenv("GUIYI_RUNTIME_COMMIT", COMMIT)
    monkeypatch.setenv("GUIYI_LIVE_RECOVERY_ENABLED", "1")
    captured = []
    session = SimpleNamespace(scalars=lambda query: SimpleNamespace(all=lambda: []),
                              in_transaction=lambda: False)
    service = AlertRuntime(
        session_factory=lambda: nullcontext(session), market_read_factory=lambda _: None,
        sender=None, operational_products=(), taxonomy={},
        heartbeat_store=SimpleNamespace(write=lambda payload, **kwargs: captured.append(payload)),
        live_processing_guard=(lambda symbol: nullcontext()) if guard else None,
    )
    service._write_heartbeat(NOW)
    assert captured[0]["recovery_guard_enabled"] is guard
    assert captured[0]["runtime_root"] == str(PROJECT_ROOT)
    assert captured[0]["runtime_commit"] == COMMIT
    assert "recovery_guard_enabled" not in empty_alert_runtime_status()


def test_heartbeat_does_not_publish_unvalidated_commit(monkeypatch):
    module = importlib.import_module("app.market_data.captured_recovery_runtime")
    monkeypatch.setenv("GUIYI_RUNTIME_COMMIT", "secret\ninvalid")
    assert module.runtime_heartbeat_identity()["runtime_commit"] is None


@pytest.mark.parametrize("state", ["not running", "waiting", "running"])
def test_after_market_loaded_same_version_may_be_idle(runtime, state):
    runtime.outputs["after_market"] = runtime.outputs["live"].replace("state = running", f"state = {state}")
    verify(runtime)
    assert any(args[-1].endswith("quant-after-market") for args, _ in runtime.calls)


@pytest.mark.parametrize("alteration", ["missing", "commit", "root", "state", "running_no_pid"])
def test_after_market_loaded_identity_must_prove_shared_guard_code(runtime, alteration):
    output = runtime.outputs["after_market"]
    if alteration == "missing":
        output = ""
    elif alteration == "commit":
        output = output.replace(COMMIT, "b" * 40)
    elif alteration == "root":
        output = output.replace(str(runtime.root), "/another-root")
    elif alteration == "state":
        output = output.replace("state = not running", "state = unknown")
    else:
        output = output.replace("state = not running", "state = running")
    runtime.outputs["after_market"] = output
    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError):
        verify(runtime)


@pytest.mark.parametrize("alteration", ["missing", "invalid", "symlink", "unsafe", "commit", "root", "label"])
def test_after_market_installed_plist_must_match_loaded_identity(runtime, alteration):
    if alteration in {"missing", "symlink"}:
        runtime.plist.unlink()
        if alteration == "symlink":
            target = runtime.plist.parent / "other.plist"
            target.write_bytes(b"not a plist")
            runtime.plist.symlink_to(target)
    elif alteration == "invalid":
        runtime.plist.write_bytes(b"not a plist")
    elif alteration == "unsafe":
        runtime.plist.chmod(0o666)
    else:
        payload = plistlib.loads(runtime.plist.read_bytes())
        if alteration == "commit":
            payload["EnvironmentVariables"]["GUIYI_RUNTIME_COMMIT"] = "b" * 40
        elif alteration == "root":
            payload["WorkingDirectory"] = "/another-root"
        else:
            payload["Label"] = "wrong"
        runtime.plist.write_bytes(plistlib.dumps(payload))
    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError):
        verify(runtime)


# Matches the observed launchctl nesting; labels and values are synthetic.
_CALENDAR_TRIGGER_BLOCK = """event triggers = {
    scheduled-event => {
        stream = com.apple.launchd.calendarinterval
        descriptor = {
            Hour => 18
            Minute => 5
        }
    }
}
event channels = {
    com.apple.launchd.calendarinterval = {
        active = 1
    }
}
"""


def _with_calendar_trigger(output):
    return output.replace("resource coalition = {", _CALENDAR_TRIGGER_BLOCK + "resource coalition = {")


@pytest.mark.parametrize("state", ["not running", "waiting", "running"])
def test_scheduled_service_accepts_mixed_arrow_and_equals_blocks(runtime, state):
    runtime.outputs["after_market"] = _with_calendar_trigger(
        runtime.outputs["live"].replace("state = running", f"state = {state}")
    )
    result = json.loads(verify(runtime))
    assert result == {"root": str(runtime.root), "commit": COMMIT, "tag": "v1.10.4"}


def test_arrow_trigger_cannot_override_service_or_environment_fields(runtime):
    output = _with_calendar_trigger(runtime.outputs["after_market"])
    output = output.replace("stream = com.apple.launchd.calendarinterval", """state = failed
pid = 0
working directory = /untrusted
GUIYI_PROJECT_ROOT => /untrusted
GUIYI_RUNTIME_COMMIT => invalid
environment = {
    GUIYI_PROJECT_ROOT => /untrusted
    GUIYI_RUNTIME_COMMIT => invalid
}""")
    runtime.outputs["after_market"] = output
    assert json.loads(verify(runtime))["commit"] == COMMIT


@pytest.mark.parametrize("alteration", [
    "missing_commit", "wrong_root", "duplicate_commit", "unclosed_block", "extra_close",
    "unknown_operator", "arrow_environment", "arrow_service",
])
def test_scheduled_service_keeps_identity_and_structure_checks(runtime, alteration):
    output = _with_calendar_trigger(runtime.outputs["after_market"])
    commit_line = f"GUIYI_RUNTIME_COMMIT => {COMMIT}"
    if alteration == "missing_commit":
        output = output.replace(commit_line, "UNKNOWN_COMMIT => invalid")
    elif alteration == "wrong_root":
        output = output.replace(f"GUIYI_PROJECT_ROOT => {runtime.root}", "GUIYI_PROJECT_ROOT => /other")
    elif alteration == "duplicate_commit":
        output = output.replace(commit_line, f"{commit_line}\n{commit_line}")
    elif alteration == "unclosed_block":
        output = output.removesuffix("}\n")
    elif alteration == "extra_close":
        output += "}\n"
    elif alteration == "unknown_operator":
        output = output.replace("scheduled-event => {", "scheduled-event -> {")
    elif alteration == "arrow_environment":
        output = output.replace("environment = {", "environment => {")
    else:
        output = output.replace("gui/501/com.guiyi.quant-live = {", "gui/501/com.guiyi.quant-live => {")
    runtime.outputs["after_market"] = output
    with pytest.raises(runtime.module.CapturedRecoveryRuntimeError) as caught:
        verify(runtime)
    assert caught.value.code == "CAPTURED_RECOVERY_RUNTIME_SERVICE_IDENTITY_INVALID"
