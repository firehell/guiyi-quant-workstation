"""Disposable native controller fixtures; no launchd, provider or Broker I/O."""

from contextlib import contextmanager, nullcontext
from datetime import date, datetime
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from guiyi_quant.simnow_execution import infrastructure_recovery as r
from test_infrastructure_recovery import ready as ready, NOW, write

ROOT = Path(__file__).resolve().parents[3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def modules():
    controller = load(
        "infra_test_controller",
        ROOT / "scripts/ops/macos/simnow-infrastructure-recovery.py",
    )
    prep = load(
        "infra_test_prep", ROOT / "scripts/ops/macos/simnow-preparation-recovery.py"
    )
    switch = prep.load_switch(ROOT)
    return controller, prep, switch


@pytest.fixture
def lifecycle(ready, modules, monkeypatch):
    f = ready
    controller, prep, switch = modules
    (f.private / r.NAME).unlink()
    (f.private / r.INTENT_NAME).unlink()
    lock = f.private / "switch.lock"
    lock.touch(mode=0o600)
    oldalive = [True]
    calls = []
    offline = [False]
    monkeypatch.setattr(r, "_exited", lambda *_: r.invalid() if oldalive[0] else None)
    import app.runtime_handover as handover

    monkeypatch.setattr(handover, "deployment_lock", lambda: nullcontext())

    class Backend:
        settings = f.s
        config = f.config

        def snapshot(self):
            return snapshot

        def preflight(self, snapshot):
            calls.append("preflight")
            r.preflight_source(
                f.s,
                f.source,
                NOW,
                NOW.replace(second=NOW.second)
                + __import__("datetime").timedelta(seconds=120),
                f.authority,
            )
            return {"passed": True}

        def validate_preflight(self, snapshot, proof):
            assert proof == {"passed": True}

        def stop(self, pid, *, expires_at, clock):
            assert oldalive[0] and clock() < expires_at
            calls.append("stop")
            oldalive[0] = False

        def stopped(self, snapshot):
            return not oldalive[0]

        @contextmanager
        def offline_guard(self, snapshot):
            assert not oldalive[0]
            offline[0] = True
            calls.append("locks")
            try:
                yield
            finally:
                offline[0] = False
                calls.append("unlock")

        def verify_offline(self, snapshot):
            assert offline[0]
            calls.append("offline")

        def window_open(self):
            return True

        def install(self, snapshot):
            assert offline[0]
            calls.append("install")
            return True

        def issue(self, snapshot, intent):
            assert offline[0]
            calls.append("issue")
            return r.issue(
                f.s,
                source=f.source,
                intent_path=intent,
                now=NOW,
                expires_at=NOW + __import__("datetime").timedelta(seconds=120),
                authority=f.authority,
                clock=lambda: NOW,
            )

        def start(self, snapshot):
            assert not offline[0]
            calls.append("start")
            return True

        def readback(self, snapshot):
            return dict(pid=40000, run_id="1" * 32)

    snapshot = dict(
        source=f.source,
        host=dict(pid=r.OLD_PID),
        old_config_path=f.source["old_config"]["path"],
        source_lock=dict(
            path=str(lock), device=lock.stat().st_dev, inode=lock.stat().st_ino
        ),
    )
    backend = Backend()
    coordinator = controller.Coordinator(
        backend, f.private, switch, clock=lambda: NOW.timestamp(), sleep=lambda _: None
    )
    return NS(
        f=f,
        controller=controller,
        prep=prep,
        switch=switch,
        b=backend,
        c=coordinator,
        calls=calls,
        alive=oldalive,
    )


def test_old_live_plan_to_stopped_issue_keeps_original_block(lifecycle):
    e = lifecycle
    plan = e.c.plan()
    assert e.alive[0] and not (e.f.private / r.NAME).exists()
    assert e.c.apply(plan)["result"] == "ACCOUNT_RECOVERED"
    assert e.calls == [
        "preflight",
        "stop",
        "locks",
        "offline",
        "install",
        "issue",
        "unlock",
        "start",
    ]
    assert dict(r._tables(e.f.inbox.conn, e.f.s.account_id)["attempts"])[r.DAY] == 1
    with pytest.raises(Exception):
        e.c.apply(plan)
    assert e.calls.count("stop") == 1


@pytest.mark.parametrize(
    "failure", ["preflight", "snapshot_drift", "expired", "bad_hash", "lock_inode"]
)
def test_pre_stop_failures_have_zero_effects(lifecycle, failure):
    e = lifecycle
    if failure == "preflight":
        e.b.preflight = lambda *_: r.invalid()
        with pytest.raises(ValueError):
            e.c.plan()
    else:
        plan = e.c.plan()
        if failure == "snapshot_drift":
            e.b.snapshot = lambda: {"changed": True}
        elif failure == "expired":
            e.c.clock = lambda: NOW.timestamp() + 60
        elif failure == "bad_hash":
            plan["plan_hash"] = "0" * 64
        else:
            path = Path(plan["snapshot"]["source_lock"]["path"])
            other = path.with_name("replacement")
            other.touch(mode=0o600)
            other.replace(path)
        with pytest.raises(Exception):
            e.c.apply(plan)
    assert "stop" not in e.calls and not e.c.state.exists()


@pytest.mark.parametrize(
    "failure", ["verify_offline", "install", "issue", "start", "readback"]
)
def test_post_stop_failure_is_unknown_and_cannot_be_reapplied(lifecycle, failure):
    e = lifecycle
    plan = e.c.plan()

    def reject(*_):
        raise ValueError("FIXTURE_FAILURE")

    setattr(e.b, failure, reject)
    with pytest.raises(ValueError):
        e.c.apply(plan)
    assert json.loads(e.c.state.read_bytes())["result"] == "UNKNOWN"
    with pytest.raises(Exception):
        e.c.apply(plan)
    assert e.calls.count("stop") == 1


def test_actual_backend_uses_real_stopped_reader_dual_locks_and_install(
    tmp_path, monkeypatch, modules
):
    from test_trade_switch import real_account

    e = real_account.__wrapped__(tmp_path, monkeypatch)
    controller, prep, switch = modules
    # Use the same native switch module as the real account fixture so its
    # temporary clock and OS-only former-PID simulation are shared.
    from test_trade_switch import m

    Backend = controller.backend_type(m, prep)
    b = Backend.__new__(Backend)
    b.__dict__.update(e.b.__dict__)
    b.settings.account_takeover_pending = True
    b.ordinary = False
    snapshot = json.loads(json.dumps(e.plan["snapshot"]))
    snapshot["host"] = prep.host_fact(snapshot["host"]["pid"], "run-fixture", "command")
    account = b._account()
    snapshot["account"] = account
    snapshot["preimage"]["account"] = account
    snapshot["source"] = {}
    snapshot["historical_contract_anchor"] = "anchor"
    b._historical_anchor = lambda: "anchor"
    b._source = lambda: {}
    e.stop()
    for path in (e.folder / "continuous.json", e.settings.state_root / "monitor.json"):
        value = json.loads(path.read_bytes())
        value["mode"] = "trade"
        write(path, value)
    # Real inherited offline_preflight verifies the complete four DBs and
    # STOPPED state while actual private OS locks are held by offline_guard.
    with b.offline_guard(snapshot):
        b.verify_offline(snapshot)
        for name, raw in (
            ("plist", b"old-plist"),
            ("monitor", b"old-monitor"),
            ("old_config", b"old-config"),
            ("candidate_plist", b"new-plist"),
            ("config", b"new-config"),
        ):
            path = tmp_path / (name + ".private")
            path.write_bytes(raw)
            path.chmod(0o600)
            setattr(b, name, path)
        b.label = "gui/fixture/" + m.LABEL
        b.settings.account_takeover_pending = False
        b.run = lambda args: NS(
            returncode=113 if args[1] == "print" else 0,
            stdout="",
            stderr="Could not find service " + m.LABEL,
        )
        assert b.install(snapshot)
    assert b.plist.read_bytes() == b"new-plist"
    assert (
        b.old_config.with_name(
            b.old_config.name + ".trade-switch-preimage"
        ).read_bytes()
        == b"old-config"
    )


def test_readback_prefix_proof_detects_original_rows_and_schema_drift(ready, modules):
    f = ready
    controller, prep, switch = modules
    b = controller.backend_type(switch, prep).__new__(
        controller.backend_type(switch, prep)
    )
    b.folder = f.folder
    frozen = b._prefixes()
    assert b._prefixes(frozen) == frozen
    f.inbox.conn.execute("UPDATE signals SET status='changed' WHERE id=1")
    assert b._prefixes(frozen) != frozen


def test_actual_backend_snapshot_reads_real_four_db_prefixes(
    ready, modules, monkeypatch
):
    import plistlib

    f = ready
    controller, prep, switch = modules
    Backend = controller.backend_type(switch, prep)
    b = Backend.__new__(Backend)
    b.settings = f.s
    b.folder = f.folder
    b.config = f.config
    b.code = f.s.project_root
    b.cfg = json.loads(f.config.read_bytes())
    b.tag = "v1.16.77"
    b.exact = "d" * 40
    b.old_pid = r.OLD_PID
    b.old_run = r.OLD_RUN
    b.ordinary = True
    b.enable_auto_order = False
    b.recover_held_readonly_source = False
    b.outage = Path(f.source["outage"]["path"])
    b.old_config = Path(f.source["old_config"]["path"])
    for root in (b.code, Path(json.loads(b.old_config.read_bytes())["project_root"])):
        (root / "scripts/broker").mkdir(parents=True, exist_ok=True)
        (root / "scripts/broker/simnow_supervisor.py").touch()
    b.monitor = f.private / "monitor-config.private.json"
    write(
        b.monitor,
        dict(
            schema=2,
            mode="observe",
            enabled=True,
            account_id=f.s.account_id,
            state_root=str(f.s.state_root),
            state_project_root=str(f.s.state_project_root),
        ),
    )
    b.plist = f.private / "old.private.plist"
    b.candidate_plist = f.private / "candidate.private.plist"
    old = json.loads(b.old_config.read_bytes())
    b.plist.write_bytes(
        plistlib.dumps(
            dict(
                Label=switch.LABEL,
                ProgramArguments=[
                    old["sdk_python"],
                    "-I",
                    str(
                        Path(old["project_root"])
                        / "scripts/broker/simnow_supervisor.py"
                    ),
                    "--config",
                    str(b.old_config),
                    "--trade",
                ],
            )
        )
    )
    b.plist.chmod(0o600)
    b.candidate_plist.write_bytes(b"candidate")
    b.candidate_plist.chmod(0o600)
    b.locks = (f.global_root / "fixture.lock", f.folder / "host.lock")
    for path in b.locks:
        path.touch(mode=0o600)
    (f.private / "switch.lock").touch(mode=0o600)
    write(
        f.folder / "continuous.json",
        dict(
            run_id=r.OLD_RUN,
            status="RECOVERY_BLOCKED",
            account_takeover_pending=True,
            account_recovery_hold=False,
            auto_order=True,
            opening_enabled=False,
            trading_day=r.DAY,
            at=NOW.isoformat(),
        ),
    )
    write(f.s.state_root / "monitor.json", dict(run_id=r.OLD_RUN))
    b.release_identity = r.io.release_identity
    b._window = f.authority
    b._candidate = lambda: ("d" * 40, dict(candidate_valid=True))
    b._pid = lambda: r.OLD_PID
    b._prove = lambda *_: "fixture exact command"
    b._probe = lambda: "b" * 64
    b._historical_anchor = lambda: "historical-facts"
    monkeypatch.setattr(controller.time, "time", lambda: NOW.timestamp())
    value = b.snapshot()
    assert value["source"] == f.source
    assert set(value["immutable_prefixes"]) == {
        "account.sqlite",
        "signals.sqlite",
        "dispatch.sqlite",
        "native-evidence.sqlite",
    }
    assert value["account"]["today_attempts"] == 1
    assert value["host"]["mode"] == "trade"


@pytest.mark.parametrize(
    "damage",
    [
        None,
        "local_claim",
        "global_claim",
        "attempt_claim",
        "new_failure",
        "new_pid",
        "database_inode",
        "grant_drift",
    ],
)
def test_success_readback_binds_actual_recovered_run_and_physical_originals(
    ready, modules, monkeypatch, damage
):
    import os
    from guiyi_quant import htdy_account_execution as account
    from guiyi_quant.simnow_execution.supervisor import Supervisor
    from guiyi_quant.simnow_execution.inventory import read_snapshot
    from test_infrastructure_recovery import day_report, RUN
    from test_trade_end_to_end import Driver

    f = ready
    controller, prep, switch = modules
    b = controller.backend_type(switch, prep).__new__(
        controller.backend_type(switch, prep)
    )
    b.settings = f.s
    b.folder = f.folder
    b.config = f.config
    b.old_run = r.OLD_RUN
    b._issued_grant_sha256 = r.io.read(f.private/r.NAME)[1]
    b._pid = lambda: os.getpid()
    b._prove = lambda *_: None
    b.plist = f.private / "installed.plist"
    b.candidate_plist = f.private / "candidate.plist"
    for path in (b.plist, b.candidate_plist):
        path.write_bytes(b"candidate")
        path.chmod(0o600)
    b.monitor = f.private / "monitor.private.json"
    b.monitor.write_bytes(b"monitor-config")
    b.monitor.chmod(0o600)
    b.monitor_source = lambda: b"monitor-config"
    snapshot = dict(
        source=f.source,
        preimage=dict(
            config=b.identity(f.config),
            sdk=b.identity(f.s.sdk_python, interpreter=True),
        ),
        immutable_prefixes=b._prefixes(),
        historical_account=prep.retained_history(
            account.LocalStore.inspect(f.folder / "account.sqlite")
        ),
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return f.clock.now()

    monkeypatch.setattr(controller, "datetime", Clock)
    monkeypatch.setattr(controller.time, "time", lambda: f.clock.now().timestamp())

    class IncidentDriver(Driver):
        def connect(self):
            self.pre_native_guard()
            super().connect()
            self.gateway.result["trading_day"] = r.DAY
            self.gateway.inventory_diagnostics = lambda: {}

        def snapshot(self):
            self.clock.advance(15)
            self.report = day_report(self.gateway)
            return read_snapshot(self.report, now=self.clock.now())

    f.market.plan = lambda now: NS(
        trading_day=date(2026, 11, 4), active=True, connect_allowed=True
    )
    f.market.infrastructure_recovery_window = lambda day, now: f.authority()
    f.market.poll = lambda *args: ()
    runtime = Supervisor(
        f.s,
        ("RB", "JM"),
        f.market,
        lambda *args: IncidentDriver(*args, f.clock),
        clock=f.clock.now,
        sleep=lambda _: None,
    )
    runtime.run_id = RUN
    publish = runtime.status
    values = []

    def status(code, **kw):
        result = publish(code, **kw)
        if code == "TRADING":
            path = f.private / r.NAME
            if damage in {"local_claim", "global_claim", "attempt_claim"}:
                target = (
                    r._global(f.s)
                    if damage == "global_claim"
                    else path.with_name(
                        path.name
                        + (
                            ".run-claim"
                            if damage == "local_claim"
                            else ".attempt-claim"
                        )
                    )
                )
                value = json.loads(target.read_bytes())
                value["pid"] += 1
                write(target, value)
            elif damage == "new_failure":
                write(f.folder / ("failure-" + RUN + "-new.json"), {})
            elif damage == "new_pid":
                b._pid = lambda: os.getpid() + 1
            elif damage == "grant_drift":
                path.write_bytes(path.read_bytes()+b' ')
            elif damage == "database_inode":
                target = f.folder / "signals.sqlite"
                other = f.private / "replacement.sqlite"
                other.write_bytes(target.read_bytes())
                other.chmod(0o600)
                other.replace(target)
            if damage:
                with pytest.raises(Exception):
                    b.readback(snapshot)
                values.append("rejected")
            else:
                values.append(b.readback(snapshot))
        return result

    runtime.status = status
    runtime.run(max_cycles=1)
    assert values
    if damage:
        assert values == ["rejected"]
    else:
        assert values[0]["pid"] == os.getpid() and values[0]["run_id"] == RUN
        assert values[0]["account_takeover_pending"] is False
