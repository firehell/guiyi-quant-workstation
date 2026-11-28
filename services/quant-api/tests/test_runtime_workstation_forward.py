"""Desktop-only cold deployment: isolated filesystem and injected launchd failure modes."""

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from app import runtime_workstation_forward as forward
from app.runtime_bindings import (
    BindingRegistry,
    CONTRACTS,
    RuntimeBindingError,
    ServiceBinding,
    market_start_preimage,
    read_bindings,
    registry_path,
    resolve_service_binding,
)
from app.runtime_cohort_errors import CohortError
from app.runtime_contracts import REQUIRED_SERVICES

CONTRACT = {key: "a" * 64 for key in CONTRACTS}


class Host(forward.WorkstationHost):
    def __init__(self, home):
        self.home = home
        self.directory = registry_path(home).parent
        self.directory.mkdir(parents=True, mode=0o700)
        self.root = home / "v1.2.1"
        self.root.mkdir()
        path = self.home / "old"
        path.mkdir()
        old = {
            n: ServiceBinding(
                n,
                str(path),
                "v1.2.0",
                "b" * 40,
                12,
                n != "alert",
                CONTRACT,
                f"com.guiyi.quant-{n}-candidate-{'a' * 32}" if n in forward.PAIR else None,
            )
            for n in REQUIRED_SERVICES
        }
        registry_path(home).write_text(json.dumps(asdict(BindingRegistry(1, old))))
        registry_path(home).chmod(0o600)
        path.rmdir()
        self.calls = []
        self.lose_cas = False
        self.fail_start = False
        self.drift = False

    def assert_no_backtest_autostart(self, root):
        pass

    def candidate(self, root, tag, commit, previous):
        return (
            {n: ServiceBinding(n, str(root), tag, commit, 13, True, CONTRACT) for n in forward.PAIR},
            "config",
            "0060",
        )

    def evidence(self, old, root, *, peers_only=False):
        return {
            k: {"loaded": self.drift if k == "live" else False}
            for k in old.services
            if not peers_only or k not in forward.PAIR
        }

    def preflight_start(self, pair, *, resume=False):
        pass

    def verify_targets_absent(self, pair):
        pass

    def commit_pair(self, pair, before):
        self.calls.append("cas")
        super().commit_pair(pair, before)
        if self.lose_cas:
            raise OSError

    def park_old_pair(self, pair, root):
        assert set(pair) == set(forward.PAIR)
        self.calls.append("park")

    def install_pair(self, pair, attempt):
        assert set(pair) == set(forward.PAIR)
        self.calls.append("start")

    def ready(self, pair):
        if self.fail_start:
            raise CohortError("TEST_NOT_READY")

    def stop_new(self, pair):
        assert set(pair) == set(forward.PAIR)
        self.calls.append("stop")


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(forward, "assert_no_unknown_deployment", lambda **kw: None)
    return Host(tmp_path)


def plan(host):
    return forward.make_plan(host, host.root, "v1.2.1", "c" * 40)


def test_other_records_are_retained_under_partial_resolution(host):
    old, _, raw = host.inventory()
    original = json.loads(raw)["services"]
    frozen = plan(host)
    result = forward.apply(host, frozen)
    assert result["phase"] == "switched"
    after = json.loads(registry_path(host.home).read_text())["services"]
    assert {n: v for n, v in after.items() if n not in forward.PAIR} == {
        n: v for n, v in original.items() if n not in forward.PAIR
    }
    assert resolve_service_binding("api", home=host.home).generation == 13
    with pytest.raises(RuntimeBindingError, match="SERVICE_BINDING_ROOT_UNAVAILABLE"):
        resolve_service_binding("live", home=host.home)
    with pytest.raises(RuntimeBindingError):
        read_bindings(home=host.home)
    assert forward.status(host, frozen)[0] == "new"
    with pytest.raises(CohortError, match="ATTEMPT_CONSUMED"):
        forward.apply(host, frozen)
    assert host.calls == ["cas", "park", "start"]


def test_cas_reply_loss_is_read_back_before_bounded_resume(host):
    frozen = plan(host)
    host.lose_cas = True
    with pytest.raises(CohortError, match="CAS_READBACK_REQUIRED"):
        forward.apply(host, frozen)
    assert host.calls == ["cas"] and forward.status(host, frozen)[0] == "new"
    assert forward.apply(host, frozen, resume=True)["phase"] == "switched"
    assert host.calls == ["cas", "park", "start"]


def test_start_failure_parks_only_new_targets(host):
    frozen = plan(host)
    host.fail_start = True
    with pytest.raises(CohortError, match="TEST_NOT_READY|START_FAILED"):
        forward.apply(host, frozen)
    assert host.calls == ["cas", "park", "start", "stop"]
    host.fail_start = False
    assert forward.apply(host, frozen, resume=True)["phase"] == "switched"


def test_peer_drift_and_reappeared_root_stop_before_cas(host):
    frozen = plan(host)
    host.drift = True
    with pytest.raises(CohortError, match="PLAN_DRIFT"):
        forward.apply(host, frozen)
    assert host.calls == []
    old, _, _ = host.inventory()
    Path(old.services["live"].root).mkdir()
    with pytest.raises(CohortError, match="CAS_READBACK_REQUIRED"):
        forward.apply(host, plan(host))


def test_lost_reply_without_registry_change_resolves_once(host, monkeypatch):
    frozen = plan(host)

    def lost(*args):
        raise OSError

    monkeypatch.setattr(host, "commit_pair", lost)
    with pytest.raises(CohortError, match="CAS_READBACK_REQUIRED"):
        forward.apply(host, frozen)
    assert forward.status(host, frozen)[0] == "old"
    assert forward.cancel_uncommitted(host, frozen)["phase"] == "cancelled"
    with pytest.raises(CohortError, match="ATTEMPT_CONSUMED"):
        forward.apply(host, frozen)


def test_failure_after_install_before_bootstrap_disables_unloaded_definition(host, monkeypatch):
    pair = forward.parse_plan(plan(host))
    controls = {}
    monkeypatch.setattr(forward, "read_launchd_service", lambda *args, **kwargs: None)
    monkeypatch.setattr(forward, "closed_ports", lambda: None)
    monkeypatch.setattr(
        host, "launch", lambda op, target: controls.update({target.rsplit("/", 1)[1]: op == "disable"})
    )
    monkeypatch.setattr(host, "authorities", lambda root: (controls, set()))
    monkeypatch.setattr(host, "_plist", lambda binding: binding.service.encode())
    for name, binding in pair.items():
        path = host.path(binding)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    forward.WorkstationHost.stop_new(host, pair)
    assert controls == {"com.guiyi.quant-api": True, "com.guiyi.quant-web": True}


def test_preflight_validates_both_before_partial_restart(host, monkeypatch):
    pair = forward.parse_plan(plan(host))
    web = host.path(pair["web"])
    web.parent.mkdir(parents=True)
    web.write_bytes(b"wrong")
    monkeypatch.setattr(host, "_plist", lambda binding: b"target")
    monkeypatch.setattr(forward, "read_launchd_service", lambda *args, **kwargs: None)

    class Closed:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, target):
            pass

    monkeypatch.setattr(forward.socket, "socket", Closed)
    with pytest.raises(CohortError, match="TARGET_PLIST_DRIFT"):
        forward.WorkstationHost.preflight_start(host, pair)
    assert host.calls == []


def test_unfinished_forward_blocks_general_deployment(host, monkeypatch):
    from app import runtime_deployment as deployment

    monkeypatch.setattr(deployment, "runtime_directory", lambda: host.directory)
    forward._write(
        host.directory / "workstation-forward.json", {"phase": "cas_unknown", "plan_sha256": "a" * 64}
    )
    with pytest.raises(deployment.DeploymentError, match="WORKSTATION_CAS_READBACK_REQUIRED"):
        deployment.assert_no_unknown_deployment()
    deployment.assert_no_unknown_deployment(workstation_plan_sha256="a" * 64)


def test_dangling_selected_root_never_uses_absent_role_exception(host):
    old, _, _ = host.inventory()
    missing = Path(old.services["api"].root)
    missing.symlink_to(host.home / "elsewhere")
    with pytest.raises(RuntimeBindingError, match="INVALID_BINDING_REGISTRY|INVALID_SERVICE_BINDING"):
        resolve_service_binding("api", home=host.home)


def test_resume_parks_exact_idle_target_only_after_both_ports_are_proven(host, monkeypatch):
    pair = forward.parse_plan(plan(host))
    label = pair["api"].label
    loaded = {label}
    disabled, calls = {}, []

    def read(name, *, root):
        return "\tstate = spawn scheduled" if name in loaded else None

    def launch(action, target):
        calls.append((action, target))
        if action == "disable":
            disabled[target.rsplit("/", 1)[1]] = True
        elif action == "bootout":
            loaded.remove(target.rsplit("/", 1)[1])

    class FreePort:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, address):
            calls.append(("check", address[1]))

    monkeypatch.setattr(forward, "read_launchd_service", read)
    monkeypatch.setattr(forward, "owner_lock_available", lambda *a, **k: True)
    monkeypatch.setattr(forward.socket, "socket", FreePort)
    monkeypatch.setattr(host, "verify_loaded", lambda b, o: None)
    monkeypatch.setattr(host, "launch", launch)
    monkeypatch.setattr(host, "authorities", lambda path: (disabled, set()))
    forward.WorkstationHost.preflight_start(host, pair, resume=True)
    assert calls[:2] == [("check", 8000), ("check", 5173)]
    assert [op for op, value in calls[2:]] == ["disable", "bootout"]
    assert disabled == {label: True} and not loaded
