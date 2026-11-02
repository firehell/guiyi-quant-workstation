"""Recovery controller effects are ordered, one-shot and never auto-retried."""

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/quant-core"))


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
                                   old_config_path=str(folder / "old.private.json"), source={},
                                   process_identity="a" * 64,
                                   source_lock=dict(path=str(lock), device=lock.stat().st_dev,
                                                    inode=lock.stat().st_ino))

    def call(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise ValueError("INJECTED_FAILURE")

    def snapshot(self):
        self.call("snapshot")
        return self.snapshot_value

    def preflight(self, snapshot):
        self.call("sdk_preflight")
        return {"source": snapshot["source"], "passed": True}

    def validate_preflight(self, snapshot, proof):
        self.call("validate_preflight")
        assert proof == {"source": snapshot["source"], "passed": True}

    def stop(self, pid, *, expires_at, clock):
        assert clock() < expires_at
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
        assert value["old_pid"] == snapshot["host"]["pid"]
        assert value["old_run_id"] == snapshot["host"]["run_id"]
        if "pre_native_parent" in snapshot["source"]:
            assert value["old_process_identity"] == snapshot["process_identity"]
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
    assert backend.calls == ["snapshot", "sdk_preflight", "snapshot", "validate_preflight", "stop", "stopped", "lock", "offline",
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


def test_sdk_preflight_failure_is_zero_effect_and_writes_no_intent(case):
    coordinator, backend, clock = case
    backend.fail = "sdk_preflight"
    with pytest.raises(Exception):
        coordinator.plan()
    assert backend.calls == ["snapshot", "sdk_preflight"]
    assert not coordinator.state.exists()


def test_expired_or_changed_sdk_proof_cannot_start_apply(case):
    coordinator, backend, clock = case
    plan = coordinator.plan()
    backend.fail = "validate_preflight"
    with pytest.raises(Exception):
        coordinator.apply(plan)
    assert not {"stop", "install", "issue", "start"} & set(backend.calls)
    assert not coordinator.state.exists()


def test_resume_intent_binds_parent_run_pid_and_birth_without_rewriting_parent(case):
    coordinator, backend, clock = case
    backend.snapshot_value["host"] = dict(pid=15437, run_id="c7a83cf0a185498b8d58315211718b87")
    backend.snapshot_value["source"] = {"pre_native_parent": {"state": {"sha256": "f" * 64}}}
    before = json.dumps(backend.snapshot_value, sort_keys=True)
    coordinator.apply(coordinator.plan())
    origin = json.loads((coordinator.directory / "preparation-recovery-intent.private.json").read_text())
    assert origin["old_process_identity"] == "a" * 64
    assert origin["old_pid"] == 15437
    assert origin["old_run_id"] == "c7a83cf0a185498b8d58315211718b87"
    assert json.dumps(backend.snapshot_value, sort_keys=True) == before
    assert backend.calls.count("sdk_preflight") == 1


def test_parent_source_builds_six_exact_refs_and_retains_original_diagnostic(controller, tmp_path, monkeypatch):
    from guiyi_quant.simnow_execution import preparation_recovery as permit
    from guiyi_quant.simnow_execution import supervisor
    tmp_path.chmod(0o700)
    switch = controller.load_switch(ROOT)
    cls = controller.backend_type(switch)
    backend = cls.__new__(cls)
    backend.directory = tmp_path / "pre-native-resume"
    backend.directory.mkdir(mode=0o700)
    backend.folder = tmp_path / "account"
    backend.folder.mkdir(mode=0o700)
    backend.settings = SimpleNamespace(account_id="a" * 64)
    backend.old_pid, backend.old_run = controller.PARENT_PID, controller.PARENT_RUN
    global_dir = tmp_path / "global"
    global_dir.mkdir(mode=0o700)
    monkeypatch.setattr(supervisor, "global_account_lock_directory", lambda: global_dir)
    original = dict(account_anchor={"preserved": True}, budget={"attempts": [[controller.DAY, 2]]},
                    window={"trading_day": controller.DAY}, failure={"path": "original-4af-failure", "sha256": "1" * 64},
                    diagnostic={"path": "original-4af-diagnostic", "sha256": "2" * 64},
                    release_receipt={"path": "original-release-receipt", "sha256": "3" * 64})
    paths = {"grant": tmp_path / permit.NAME, "intent": tmp_path / permit.INTENT_NAME,
             "state": tmp_path / "state.private.json", "run_claim": tmp_path / (permit.NAME + ".run-claim"),
             "global_claim": global_dir / (backend.settings.account_id + "." + controller.DAY + ".preparation-recovery.run-claim"),
             "failure": backend.folder / ("failure-" + controller.PARENT_RUN + "-0.json")}
    values = {key: {} for key in paths}
    values["grant"] = {"source": original}
    values["run_claim"] = {"pid": controller.PARENT_PID, "run_id": controller.PARENT_RUN}
    for key, path in paths.items():
        path.write_text(json.dumps(values[key], sort_keys=True))
        path.chmod(0o600)
    before = {key: path.read_bytes() for key, path in paths.items()}
    checks = []
    monkeypatch.setattr(permit, "_parent", lambda settings, source, root: checks.append((source, root)))
    source = backend._resume_source(original)
    assert source["diagnostic"] == original["diagnostic"]
    assert source["release_receipt"] == original["release_receipt"]
    assert source["failure"] == source["pre_native_parent"]["failure"]
    assert source["failure"]["path"] == str(paths["failure"])
    assert set(source["pre_native_parent"]) == set(paths)
    assert all(ref["path"] == str(paths[key]) for key, ref in source["pre_native_parent"].items())
    assert checks == [(source, tmp_path)]
    assert {key: path.read_bytes() for key, path in paths.items()} == before
    backend.old_run = "different"
    with pytest.raises(Exception):
        backend._resume_source(original)


@pytest.mark.parametrize("same_birth", [True, False])
def test_stopped_is_bound_to_birth_not_the_reused_pid(controller, tmp_path, monkeypatch, same_birth):
    switch = controller.load_switch(ROOT)
    cls = controller.backend_type(switch)
    backend = cls.__new__(cls)
    backend.folder = tmp_path
    status = tmp_path / "continuous.json"
    status.write_text(json.dumps(dict(status="STOPPED", run_id=controller.PARENT_RUN)))
    status.chmod(0o600)
    monkeypatch.setattr(controller.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(controller, "process_identity", lambda pid, run: "a" * 64 if same_birth else "b" * 64)
    backend.run = lambda *args: None
    snapshot = dict(host=dict(pid=controller.PARENT_PID, run_id=controller.PARENT_RUN), process_identity="a" * 64)
    assert backend.stopped(snapshot) is (not same_birth)


@pytest.mark.parametrize("age", [90, 91])
def test_fresh_gc_proof_keeps_exact_ninety_second_limit(controller, tmp_path, monkeypatch, age):
    switch = controller.load_switch(ROOT)
    cls = controller.backend_type(switch)
    backend = cls.__new__(cls)
    backend.old_pid, backend.run = controller.PARENT_PID, lambda *args: None
    backend.probe = tmp_path / "probe.json"
    at = datetime.now(UTC)
    value = dict(status="READ_ONLY_INSPECTED", detached=True, target_calls=0, target_writes=0,
                 pid=controller.PARENT_PID, process_identity="a" * 64, gateway_count=0, portfolio_count=0,
                 supervisor_count=1, proof_at=(at - timedelta(seconds=age)).isoformat(),
                 supervisors=[dict(driver_absent=True, host_absent=True, pending=True, expected_run=True)])
    backend.probe.write_text(json.dumps(value))
    backend.probe.chmod(0o600)
    monkeypatch.setattr(controller.time, "time", lambda: at.timestamp())
    monkeypatch.setattr(controller, "process_identity", lambda *args: "a" * 64)
    if age == 90:
        assert backend._probe() == "a" * 64
    else:
        with pytest.raises(Exception):
            backend._probe()


def test_check_source_is_pure_and_returns_bound_sdk_proof(controller, tmp_path, monkeypatch):
    from guiyi_quant.simnow_execution import preparation_recovery as permit
    from guiyi_quant.simnow_execution import deployment_connection as io
    at = datetime.now(UTC)
    source = dict(window={"sessions": [dict(start=(at - timedelta(minutes=1)).isoformat(),
                                           end=(at + timedelta(minutes=10)).isoformat())]})
    settings = SimpleNamespace(source_config_sha256="a" * 64, sdk_python=tmp_path / "sdk")
    calls = []
    def preflight(actual_settings, actual_source, issued, expires, authority):
        calls.append((actual_settings is settings, actual_source is source, callable(authority)))
        return dict(code="PASSED", checks={"read_only": True})
    monkeypatch.setattr(permit, "preflight_source", preflight)
    monkeypatch.setattr(io, "sdk_identity", lambda path: {"sha256": "b" * 64})
    before = list(tmp_path.iterdir())
    proof = controller.check_source(settings, source)
    assert proof["status"] == "SOURCE_PREFLIGHT_PASSED"
    assert proof["config_sha256"] == "a" * 64 and proof["sdk_sha256"] == "b" * 64
    assert proof["source_sha256"] == controller.load_switch(ROOT).digest(source)
    assert calls == [(True, True, True)]
    assert list(tmp_path.iterdir()) == before
    assert datetime.fromisoformat(proof["valid_until"]) - datetime.fromisoformat(proof["checked_at"]) <= timedelta(seconds=60)


def test_slow_stop_prechecks_reaching_expiry_never_send_sigterm(controller, tmp_path, monkeypatch):
    switch = controller.load_switch(ROOT)
    cls = controller.backend_type(switch)
    backend = cls.__new__(cls)
    clock = Clock()
    backend.old_pid, backend.old_config, backend.folder = controller.PARENT_PID, tmp_path / "old", tmp_path
    backend._stop_signals = backend._stop_historical_anchor = "unchanged"
    backend._stop_process_identity = "a" * 64
    backend._prove = lambda *args: None
    backend.identity = lambda *args: "unchanged"
    def slow_authority():
        clock.at += 61
        return "unchanged"
    backend._historical_anchor = slow_authority
    backend.run = lambda *args: None
    monkeypatch.setattr(controller, "process_identity", lambda *args: "a" * 64)
    signals = []
    monkeypatch.setattr(controller.os, "kill", lambda *args: signals.append(args))
    with pytest.raises(Exception, match="PLAN_EXPIRED"):
        backend.stop(controller.PARENT_PID, expires_at=1060, clock=clock.now)
    assert signals == []


def test_missing_source_lock_is_rejected_in_plan_before_sdk_gate(case):
    coordinator, backend, clock = case
    Path(backend.snapshot_value["source_lock"]["path"]).unlink()
    with pytest.raises(Exception):
        coordinator.plan()
    assert backend.calls == ["snapshot"]
    assert not coordinator.state.exists()


def test_replaced_source_lock_inode_is_rejected_before_any_effect(case):
    coordinator, backend, clock = case
    plan = coordinator.plan()
    path = Path(backend.snapshot_value["source_lock"]["path"])
    moved = path.with_name("original-lock")
    path.rename(moved)
    path.touch(mode=0o600)
    with pytest.raises(Exception):
        coordinator.apply(plan)
    assert not {"stop", "install", "issue", "start"} & set(backend.calls)
    assert not coordinator.state.exists()


@pytest.mark.parametrize("changed", ["source_sha256", "config_sha256", "sdk_sha256", "controller_sha256", "expiry"])
def test_sdk_proof_cannot_be_reused_for_another_source_or_after_expiry(controller, tmp_path, changed):
    switch = controller.load_switch(ROOT)
    cls = controller.backend_type(switch)
    backend = cls.__new__(cls)
    backend.config = tmp_path / "config"
    backend.settings = SimpleNamespace(sdk_python=tmp_path / "sdk")
    backend.identity = lambda *args, **kwargs: {"sha256": "a" * 64}
    at = datetime.now(UTC)
    snapshot = {"source": {"preserved": True}}
    proof = dict(status="SOURCE_PREFLIGHT_PASSED", diagnostic=dict(code="PASSED", checks={"bound": True}),
                 checked_at=at.isoformat(), valid_until=(at + timedelta(seconds=60)).isoformat(),
                 source_sha256=switch.digest(snapshot["source"]), config_sha256="a" * 64,
                 sdk_sha256="a" * 64,
                 controller_sha256=controller.hashlib.sha256(Path(controller.__file__).read_bytes()).hexdigest())
    backend.validate_preflight(snapshot, proof)
    if changed == "expiry":
        proof["checked_at"] = (at - timedelta(seconds=61)).isoformat()
        proof["valid_until"] = (at - timedelta(seconds=1)).isoformat()
    else:
        proof[changed] = "b" * 64
    with pytest.raises(Exception):
        backend.validate_preflight(snapshot, proof)


@pytest.mark.parametrize("hold", [False, None])
def test_held_readback_requires_explicit_runtime_hold(controller, tmp_path, hold):
    switch = controller.load_switch(ROOT)
    cls = controller.backend_type(switch)
    backend = cls.__new__(cls)
    backend.folder = tmp_path
    control = dict(status="ACCOUNT_RECOVERED_HELD", account_takeover_pending=False,
                   opening_enabled=False, auto_order=False)
    if hold is not None:
        control["account_recovery_hold"] = hold
    path = tmp_path / "continuous.json"
    path.write_text(json.dumps(control))
    path.chmod(0o600)
    assert backend.readback_held({}) is None
