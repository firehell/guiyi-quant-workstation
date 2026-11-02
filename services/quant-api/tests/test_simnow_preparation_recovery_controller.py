"""Recovery controller effects are ordered, one-shot and never auto-retried."""

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import json

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def controller():
    path = ROOT / "scripts/ops/macos/simnow-preparation-recovery.py"
    spec = importlib.util.spec_from_file_location("preparation_controller_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Clock:
    def __init__(self):
        self.at = 1000
    def now(self):
        return self.at
    def sleep(self, seconds):
        self.at += seconds


class Backend:
    def __init__(self, folder, fail=None):
        self.calls = []
        self.fail = fail
        self.offline = False
        self.config = folder / "candidate.private.json"
        self.config.write_text('{}')
        self.config.chmod(0o600)
        lock = folder / "switch.lock"
        lock.touch(mode=0o600)
        self.snapshot_value = dict(host=dict(pid=15566, run_id="old"),
                                   old_config_path=str(folder / "old.private.json"), source={})

    def call(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise ValueError("INJECTED_FAILURE")

    def snapshot(self):
        self.call("snapshot")
        return self.snapshot_value

    def stop(self, pid):
        self.call("stop")

    def stopped(self, snapshot):
        self.call("stopped")
        return self.fail != "stuck"

    @contextmanager
    def offline_guard(self, snapshot):
        self.offline = True
        try:
            self.call("lock")
            yield
        finally:
            self.offline = False

    def verify_offline(self, snapshot):
        assert self.offline
        self.call("offline")

    def window_open(self):
        self.call("window")
        return True

    def install(self, snapshot):
        assert self.offline
        self.call("install")
        return True

    def issue(self, snapshot, intent):
        value = json.loads(intent.read_text())
        assert value["stage"] == "START_REQUESTED" and value["old_pid_exited"]
        assert "install" in self.calls and not self.offline
        self.call("issue")
        return "grant"

    def start(self, snapshot):
        self.call("start")
        return True

    def readback_held(self, snapshot):
        self.call("readback")
        return None if self.fail == "not_ready" else dict(pid=20000, run_id="new")


@pytest.fixture
def case(tmp_path, controller, monkeypatch):
    import app.runtime_handover
    @contextmanager
    def guard():
        yield
    monkeypatch.setattr(app.runtime_handover, "deployment_lock", guard)
    tmp_path.chmod(0o700)
    switch = controller.load_switch(ROOT)
    clock = Clock()
    backend = Backend(tmp_path)
    coordinator = controller.Coordinator(backend, tmp_path, switch, clock=clock.now, sleep=clock.sleep)
    return coordinator, backend, clock


def test_success_requires_ordered_stop_offline_install_grant_start_and_two_readbacks(case):
    coordinator, backend, clock = case
    result = coordinator.apply(coordinator.plan())
    assert result["stage"] == "COMPLETE" and result["result"] == "ACCOUNT_RECOVERED_HELD"
    assert backend.calls == ["snapshot", "snapshot", "stop", "stopped", "lock", "offline",
                             "window", "install", "issue", "start", "readback", "readback"]
    with pytest.raises(Exception):
        coordinator.apply(coordinator.plan())
    assert backend.calls.count("start") == 1


@pytest.mark.parametrize("failure", ["stop", "offline", "install", "issue", "start", "stuck", "not_ready"])
def test_any_effect_failure_or_unknown_is_durable_and_cannot_be_retried(case, failure):
    coordinator, backend, clock = case
    plan = coordinator.plan()
    backend.fail = failure
    with pytest.raises(Exception):
        coordinator.apply(plan)
    state = json.loads(coordinator.state.read_text())
    assert state["result"] == "UNKNOWN" and state["stage"] != "COMPLETE"
    effects = [x for x in backend.calls if x in {"stop", "install", "issue", "start"}]
    with pytest.raises(Exception):
        coordinator.apply(plan)
    assert [x for x in backend.calls if x in {"stop", "install", "issue", "start"}] == effects


@pytest.mark.parametrize("case_type", ["expired", "tampered", "drift"])
def test_stale_or_changed_plan_has_zero_effects(case, case_type):
    coordinator, backend, clock = case
    plan = coordinator.plan()
    if case_type == "expired":
        clock.at += 61
    elif case_type == "tampered":
        plan["snapshot"]["host"]["pid"] = 20000
    else:
        backend.snapshot_value = dict(backend.snapshot_value, host=dict(pid=20000, run_id="other"))
    with pytest.raises(Exception):
        coordinator.apply(plan)
    assert not {"stop", "install", "issue", "start"} & set(backend.calls)
    assert not coordinator.state.exists()
