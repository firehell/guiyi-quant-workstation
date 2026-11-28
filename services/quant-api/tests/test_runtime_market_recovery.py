"""Injection tests use a temporary registry; the Lua boundary runs against a dedicated Redis."""

from contextlib import nullcontext
from dataclasses import asdict
from datetime import date, datetime, timedelta, UTC
import json
import os

import pytest

from app import runtime_market_recovery as recovery
from app.market_data.observation_stream import ObservationStream
from app.runtime_bindings import BindingRegistry, CONTRACTS, ServiceBinding, read_bindings, registry_path
from app.runtime_cohort_errors import CohortError
from app.runtime_contracts import REQUIRED_SERVICES
from app.runtime_handover import _read, _write

DAY = date(2026, 11, 30)


class Host(recovery.RecoveryHost):
    def __init__(self, home):
        self.home = home
        self.directory = registry_path(home).parent
        self.directory.mkdir(mode=0o700, parents=True)
        self.root = home / "candidate"
        self.root.mkdir()
        prior = home / "lost"
        prior.mkdir()
        current = home / "current"
        current.mkdir()
        self.contracts = {k: "a" * 64 for k in CONTRACTS}
        services = {
            n: ServiceBinding(
                n,
                str(current if n in recovery.PAIR else prior),
                "v1.1.0",
                "a" * 40,
                100 if n in recovery.PAIR else 97,
                n not in {"alert", "home-projection"},
                self.contracts,
            )
            for n in REQUIRED_SERVICES | {"home-projection"}
        }
        registry_path(home).write_bytes(json.dumps(asdict(BindingRegistry(1, services))).encode())
        registry_path(home).chmod(0o600)
        prior.rmdir()
        self.calls = []
        self.running = False
        self.registered = False
        self.boundary_changed = False
        self.fail_start = False
        self.lose_register = False
        self.guarded = False
        self._now = datetime(2026, 11, 28, 12, tzinfo=UTC)

    def now(self):
        return self._now

    def targets(self, root, tag, commit, old):
        return (
            {
                n: ServiceBinding(n, str(root), tag, commit, 101, True, self.contracts)
                for n in recovery.START_ORDER
            },
            ["market-foundation/v0.1.5", "c" * 40],
            "0060",
        )

    def settings(self):
        return ({}, "config")

    def check_calendar_window(self, targets):
        pass

    def old_web(self, old):
        pass

    def ready_artifacts(self, item, boundary):
        pass

    def evidence(self, old, root, *, peers_only, skip_names=()):
        return {n: {"probe": n} for n in old.services if n not in set(skip_names) | set(recovery.PAIR)}

    def boundary(self, day, *, registered=False):
        assert self.registered is registered
        return {
            "day": day.isoformat(),
            "first_session": datetime(2026, 11, 30, 1, tzinfo=UTC).isoformat(),
            "originals": "drift" if self.boundary_changed else "frozen",
        }

    def installation_preimage(self, old):
        return {"native": "unchanged"}

    def park(self, old, root, files, attempt):
        self.calls.append("park")

    def guards_for_direct_start(self, scope, settings):
        from contextlib import contextmanager

        @contextmanager
        def held():
            assert scope.services.keys() == set(recovery.START_ORDER)
            self.guarded = True
            try:
                yield
            finally:
                self.guarded = False

        return held()

    def install(self, targets, attempt, files):
        assert self.guarded
        self.calls.append("install")

    def alert_registered(self, day):
        return self.registered

    def register_alert(self, boundary, *, may_exist):
        assert self.guarded and self.registered == may_exist
        if not self.registered:
            self.calls.append("register")
            self.registered = True
            if self.lose_register:
                raise OSError("lost reply")

    def start_selected(self, targets):
        assert not self.guarded
        self.calls.append("start")
        if self.fail_start:
            raise CohortError("INJECTED")
        self.running = True

    def stop_selected(self, targets):
        self.calls.append("stop")
        self.running = False


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    host = Host(tmp_path)
    monkeypatch.setattr(recovery, "assert_no_unknown_deployment", lambda **_: None)
    monkeypatch.setattr(recovery, "read_launchd_service", lambda *_, **__: None)
    monkeypatch.setattr(recovery, "closed_ports", lambda: None)

    def verify(h, old, targets, plan):
        if not h.running:
            raise CohortError("MARKET_OWNER_NOT_READY_API")
        return {"services": list(targets), "generation": 101}

    monkeypatch.setattr(recovery, "verify_switched", verify)
    return host, recovery.prepare(host, host.root, "v1.1.1", "b" * 40, DAY)


def test_exact_partial_registry_and_only_one_new_cursor(scenario):
    host, plan = scenario
    old = host.inventory()[0].services
    assert recovery.apply(host, plan)["phase"] == "switched"
    assert recovery.readback(host, plan)["authority"] == "new"
    assert recovery.apply(host, plan, resume=True)["phase"] == "switched"
    assert host.calls == ["park", "install", "register", "start"]
    new = host.inventory()[0].services
    assert {n for n in new if new[n] != old[n]} == set(recovery.START_ORDER)
    assert (
        read_bindings(home=host.home, services=("after-market", "live")).services["live"].generation == 101
    )


def test_lost_cas_reply_never_repeats_committed_cas(scenario, monkeypatch):
    host, plan = scenario
    original = recovery.write_recovered_market

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("reply")

    monkeypatch.setattr(recovery, "write_recovered_market", lost)
    with pytest.raises(CohortError, match="CAS_READBACK"):
        recovery.apply(host, plan)
    assert recovery.readback(host, plan) == {"authority": "new", "phase": "cas_intent"}
    assert recovery.apply(host, plan, resume=True)["phase"] == "switched"
    assert host.calls.count("park") == 1


def test_interrupted_first_registration_is_read_back(scenario):
    host, plan = scenario
    host.lose_register = True
    with pytest.raises(OSError):
        recovery.apply(host, plan)
    assert recovery.readback(host, plan)["phase"] == "alert_intent"
    recovery.apply(host, plan, resume=True)
    assert host.calls.count("register") == 1


def test_verified_complete_processes_survive_restart_after_open(scenario):
    host, plan = scenario
    recovery.apply(host, plan)
    p = host.directory / "market-recovery.json"
    _write(p, {**_read(p), "phase": "starting"})
    host._now += timedelta(days=3)
    assert recovery.apply(host, plan, resume=True)["phase"] == "switched"
    assert "stop" not in host.calls and host.calls.count("start") == 1


def test_failed_partial_start_parks_and_resumes_without_new_cursor(scenario):
    host, plan = scenario
    host.fail_start = True
    with pytest.raises(CohortError, match="INJECTED"):
        recovery.apply(host, plan)
    assert recovery.readback(host, plan)["phase"] == "start_failed"
    host.fail_start = False
    recovery.apply(host, plan, resume=True)
    assert host.calls.count("register") == 1


def test_source_drift_or_foreign_registration_prevents_drain(scenario):
    host, plan = scenario
    host.boundary_changed = True
    with pytest.raises(CohortError, match="BOUNDARY_DRIFT"):
        recovery.apply(host, plan)
    host.registered = True
    with pytest.raises(CohortError, match="REGISTRATION_UNPROVEN"):
        recovery.apply(host, plan)
    assert host.calls == []


def test_calendar_became_busy_after_disable_is_never_booted_out(scenario, monkeypatch):
    host, _ = scenario
    ctl = []
    item = host.inventory()[0].services["after-market"]
    monkeypatch.setattr(recovery, "after_market_recovery_guard", lambda **_: nullcontext())
    from app.runtime_bindings import authorized_program_arguments

    args = "\n".join(authorized_program_arguments(item, host.home))
    output = f"service = {{\n\targuments = {{\n{args}\n\t}}\n\tstate = running\n\tpid = 123\n}}"
    monkeypatch.setattr(recovery, "read_launchd_service", lambda *_, **__: output)
    monkeypatch.setattr(host, "verify_loaded", lambda *args: None)
    monkeypatch.setattr(host, "launch", lambda *args: ctl.append(args))
    with pytest.raises(CohortError, match="OLD_JOB_BUSY"):
        host.unload_verified(item, host.root)
    assert [cmd[0] for cmd in ctl] == ["disable"]


def test_atomic_new_alert_at_exact_frozen_tail():
    port = os.getenv("GUIYI_TEST_REDIS_PORT")
    if not port:
        pytest.skip("dedicated Redis required")
    from redis import Redis

    assert int(port) > 1024 and int(port) != 6379
    with Redis(host="127.0.0.1", port=int(port), decode_responses=True) as client:
        assert client.dbsize() == 0
        source = ObservationStream(client, kind="source")
        stream = ObservationStream(client, kind="completed")
        names = (
            stream.cursor_key("alert", DAY),
            stream.registration_key("alert"),
            source.registration_key("live"),
            source.cursor_key("live", DAY),
            source.key(DAY),
            source.identity_key(DAY),
            stream.key(DAY),
            stream.identity_key(DAY),
        )
        try:
            first = client.xadd(names[4], {"v": "original"})
            last = client.xadd(names[6], {"v": "original"})
            client.hset(names[5], "original", first)
            client.hset(names[7], "original", last)
            client.mset({names[2]: DAY.isoformat(), names[3]: first})

            def register(tail):
                return client.eval(
                    recovery.NEW_ALERT, 8, *names, DAY.isoformat(), first, 1, tail, 1, 259200
                )

            assert register("0-0") == 0 and client.exists(*names[:2]) == 0
            assert register(last) == 1
            assert client.mget(*names[:4]) == [last, DAY.isoformat(), DAY.isoformat(), first]
            assert register(last) == 0 and client.xlen(names[4]) == client.xlen(names[6]) == 1
        finally:
            client.delete(*names)
