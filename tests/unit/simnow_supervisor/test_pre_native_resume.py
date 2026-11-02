"""Single pre-native continuation. All parent files and transports are local fixtures."""
from datetime import date, timedelta
import hashlib
import json
import os
from types import SimpleNamespace as NS

import pytest

from guiyi_quant.simnow_execution import preparation_recovery as recovery
from guiyi_quant.simnow_execution.settings import load_settings
from guiyi_quant.simnow_execution.supervisor import Supervisor
from test_settings import write
from test_preparation_recovery import NOW, RUN
import test_preparation_recovery as recovery_fixtures

ready = recovery_fixtures.ready

pytestmark = pytest.mark.parametrize("ready", ["parent_v68"], indirect=True)
PARENT_PID = 2147483646
PARENT_RUN = "3" * 32
OLD_PROCESS = "d" * 64


def ref(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def resume(ready, monkeypatch):
    f = ready
    original_settings = f.s
    with monkeypatch.context() as parent_process:
        parent_process.setattr(recovery.os, "getpid", lambda: PARENT_PID)
        recovery.activate(f.s, f.inbox, PARENT_RUN, NOW, clock=lambda: NOW, authority=f.authority)
    root = original_settings.preparation_recovery_permit.parent
    grant, grant_sha = recovery.read(root / recovery.NAME)
    state = root / "state.private.json"
    write(state, dict(schema=recovery.PARENT_STATE_SCHEMA, stage="VERIFYING", result="UNKNOWN",
                      plan_hash="e"*64, at=NOW.timestamp(), grant=grant_sha))
    failure = f.folder / ("failure-" + PARENT_RUN + "-0.json")
    write(failure, dict(schema="simnow_continuous_failure_v1", code=recovery.BLOCK, at=NOW.isoformat(),
                        diagnostic=dict(stage="DRIVER_UNAVAILABLE", recovery_stage="NOT_STARTED",
                                        recovery_error_code="RECOVERY_ERROR_UNCLASSIFIED", dispatch=None)))
    refs = dict(grant=ref(root / recovery.NAME), intent=ref(root / recovery.INTENT_NAME),
                state=ref(state), run_claim=ref(root / (recovery.NAME + ".run-claim")),
                global_claim=ref(recovery._global(original_settings)), failure=ref(failure))
    child = root / recovery.RESUME_DIRECTORY
    child.mkdir(mode=0o700)
    config = child / "continuous.private.json"
    value = json.loads(f.config.read_text())
    value["preparation_recovery_permit"] = str(child / recovery.NAME)
    write(config, value)
    settings = load_settings(config)
    monkeypatch.setattr(recovery, "release_identity", lambda path: dict(root=str(path), tag="v1.16.69", commit="b"*40))
    previous_kill = os.kill
    def kill(pid, sig):
        if pid == PARENT_PID:
            raise ProcessLookupError()
        return previous_kill(pid, sig)
    monkeypatch.setattr(recovery.os, "kill", kill)
    source = {**f.source, "failure": refs["failure"], "pre_native_parent": refs}
    return NS(s=settings, inbox=f.inbox, source=source, authority=f.authority, config=config,
              original_settings=original_settings, folder=f.folder, root=root, child=child,
              intent=child / recovery.INTENT_NAME, old_refs=refs, parent_grant=grant)


def issue(f):
    write(f.intent, dict(schema=recovery.INTENT_SCHEMA, stage="START_REQUESTED", source=f.source,
                         config_path=str(f.config), config_sha256=f.s.source_config_sha256,
                         old_run_id=PARENT_RUN, old_pid=PARENT_PID, old_pid_exited=True,
                         old_process_identity=OLD_PROCESS, created_at=NOW.isoformat()))
    return recovery.issue(f.s, f.config, intent_path=f.intent, source=f.source, now=NOW,
                          expires_at=NOW+timedelta(seconds=240), clock=lambda: NOW, authority=f.authority)


def activate(f):
    recovery.activate(f.s, f.inbox, RUN, NOW, clock=lambda: NOW, authority=f.authority)


def consume(f):
    return recovery.consume(f.s, f.inbox, RUN, recovery.DAY, NOW, clock=lambda: NOW, authority=f.authority)


def test_single_resume_preserves_every_parent_byte_and_spends_only_original_last_attempt(resume):
    f = resume
    paths = [item["path"] for item in f.old_refs.values()]
    from pathlib import Path
    original = {path: Path(path).read_bytes() for path in paths}
    before = recovery._tables(f.inbox.conn, f.s.account_id)
    contents = sorted(p.name for p in f.child.iterdir())
    preflight = recovery.preflight_source(f.s, f.source, NOW, NOW+timedelta(seconds=240), f.authority)
    assert preflight["code"] == "PASSED"
    assert sorted(p.name for p in f.child.iterdir()) == contents
    issue(f)
    assert recovery.read(f.s.preparation_recovery_permit)[0]["schema"] == recovery.RESUME_SCHEMA
    activate(f)
    new_global = recovery._global(f.s)
    assert new_global.name.endswith("preparation-recovery-prenative-resume.run-claim")
    assert new_global != recovery._global(f.original_settings)
    assert recovery.read(new_global)[0]["old_process_identity"] == OLD_PROCESS
    native_calls = []
    count, window = consume(f)
    recovery.validate_connection(window, NOW, f.authority, clock=lambda: NOW)
    native_calls.append("factory")
    assert count == 3 and native_calls == ["factory"]
    assert recovery._tables(f.inbox.conn, f.s.account_id) == {
        **before, "attempts": [["20261102", 3], [recovery.DAY, 3]]}
    assert {path: Path(path).read_bytes() for path in paths} == original
    assert not recovery.available(f.s, f.inbox, RUN, recovery.DAY, NOW, authority=f.authority)
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_CONSUMED"):
        consume(f)
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_CONSUMED"):
        recovery.activate(f.s, f.inbox, "4"*32, NOW, clock=lambda: NOW, authority=f.authority)
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_CONSUMED"):
        recovery.activate(f.original_settings, f.inbox, "4"*32, NOW, clock=lambda: NOW, authority=f.authority)


def test_pure_preflight_does_not_test_pid_exit_or_write_any_claim(resume, monkeypatch):
    f = resume
    monkeypatch.setattr(recovery.os, "kill", lambda *_: (_ for _ in ()).throw(AssertionError("PID exit is not a preflight condition")))
    assert recovery.preflight_source(f.s, f.source, NOW, NOW+timedelta(seconds=240), f.authority)["code"] == "PASSED"
    assert not f.intent.exists()
    assert not f.s.preparation_recovery_permit.exists()
    assert not recovery._global(f.s).exists()
    assert not f.s.preparation_recovery_permit.with_name(recovery.NAME+".attempt-claim").exists()


@pytest.mark.parametrize("case", ["attempt", "broken_attempt", "recursive", "state", "failure", "hash", "source", "window", "anchor", "blocks", "global_bytes", "old_failure"])
def test_parent_or_current_evidence_mismatch_is_zero_native_and_zero_new_claim(resume, case):
    f = resume
    from pathlib import Path
    if case in {"attempt", "broken_attempt"}:
        path = f.root / (recovery.NAME + ".attempt-claim")
        if case == "attempt":
            write(path, {})
        else:
            path.symlink_to(f.root / "missing-claim")
    if case == "recursive":
        path = Path(f.old_refs["grant"]["path"])
        value = recovery.read(path)[0]
        value["schema"] = recovery.RESUME_SCHEMA
        write(path, value)
        f.old_refs["grant"].update(ref(path))
    if case == "state":
        path = Path(f.old_refs["state"]["path"])
        value = recovery.read(path)[0]
        value["result"] = "RECOVERED"
        write(path, value)
        f.old_refs["state"].update(ref(path))
    if case == "failure":
        path = Path(f.old_refs["failure"]["path"])
        value = recovery.read(path)[0]
        value["diagnostic"]["stage"] = "NATIVE_LOGIN"
        write(path, value)
        f.old_refs["failure"].update(ref(path))
    if case == "hash":
        f.old_refs["state"]["sha256"] = "f"*64
    if case == "source":
        f.source["unexpected"] = True
    if case == "window":
        f.source["window"] = {**f.source["window"], "session_facts_sha256": "f"*64}
    if case == "anchor":
        (f.folder / "dispatch.sqlite").write_bytes(b"drift")
    if case == "blocks":
        f.inbox.block("20261101", "UNTOUCHED")
    if case == "global_bytes":
        path = Path(f.old_refs["global_claim"]["path"])
        path.write_text(path.read_text()+" ")
        f.old_refs["global_claim"].update(ref(path))
    if case == "old_failure":
        path = Path(f.parent_grant["source"]["failure"]["path"])
        path.write_text(path.read_text()+" ")
    native = []
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        recovery.preflight_source(f.s, f.source, NOW, NOW+timedelta(seconds=240), f.authority)
        native.append("factory")
    assert native == []
    assert not f.s.preparation_recovery_permit.exists()
    assert not recovery._global(f.s).exists()
    assert f.inbox.conn.execute("SELECT count FROM attempts WHERE day=?", (recovery.DAY,)).fetchone() == (2,)


@pytest.mark.parametrize("case", ["same", "unknown", "permission"])
def test_resume_refuses_same_process_birth_unknown_ps_or_permission_failure(resume, monkeypatch, case):
    f = resume
    def kill(*_):
        if case == "permission":
            raise PermissionError("private process context")
    monkeypatch.setattr(recovery.os, "kill", kill)
    def identity(_):
        if case == "unknown":
            raise OSError("private ps context")
        return OLD_PROCESS
    monkeypatch.setattr(recovery, "_process_identity", identity)
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        issue(f)
    assert not f.s.preparation_recovery_permit.exists()
    assert not recovery._global(f.s).exists()
    diagnostic = recovery.guard_diagnostic()
    assert diagnostic["stage"] == "OLD_PROCESS_EXIT"
    assert "private" not in json.dumps(diagnostic)
    assert all(type(v) is bool for v in diagnostic["checks"].values())


def test_resume_accepts_reused_pid_only_with_different_birth_and_never_kills_it(resume, monkeypatch):
    f = resume
    signals = []
    monkeypatch.setattr(recovery.os, "kill", lambda pid, signal: signals.append(signal))
    monkeypatch.setattr(recovery, "_process_identity", lambda _: "e"*64)
    issue(f)
    activate(f)
    assert consume(f)[0] == 3
    assert signals and set(signals) == {0}
    assert recovery.read(recovery._global(f.s))[0]["old_process_identity"] == OLD_PROCESS


def test_supervisor_retains_fixed_authority_failure_stage_without_private_exception(resume):
    f = resume
    issue(f)
    calls = []
    samples = []
    def window(*_):
        samples.append(1)
        if len(samples) == 3:
            raise RuntimeError("private secret authority failure")
        return f.source["window"]
    market = NS(issues={}, plan=lambda _: NS(trading_day=date(2026,11,3), active=True, connect_allowed=True),
                ordinary_takeover_window=window, activate=lambda _: None, close=lambda: None)
    sup = Supervisor(f.s, ("RB",), market, lambda *_: calls.append("factory"), clock=lambda: NOW, sleep=lambda _: None)
    sup.run_id = RUN
    sup.run(max_cycles=2)
    assert calls == []
    failure = recovery.read(f.folder / ("failure-" + RUN + "-0.json"))[0]
    diagnostic = failure["diagnostic"]
    assert diagnostic["recovery_error_code"] == "PREPARATION_RECOVERY_INVALID"
    assert diagnostic["safe_guard_diagnostics"]["stage"] == "AUTHORITY"
    assert diagnostic["safe_guard_diagnostics"]["exception_category"] == "UNCLASSIFIED"
    assert "private secret" not in json.dumps(failure)
    assert not f.s.preparation_recovery_permit.with_name(recovery.NAME+".attempt-claim").exists()
    assert f.inbox.conn.execute("SELECT count FROM attempts WHERE day=?", (recovery.DAY,)).fetchone() == (2,)


def test_parent_attempt_appearing_after_activation_denies_before_sql_and_spends_new_claim(resume):
    f = resume
    issue(f)
    activate(f)
    write(f.root / (recovery.NAME+".attempt-claim"), {})
    native = []
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        consume(f)
        native.append("SDK")
    assert native == []
    assert f.inbox.conn.execute("SELECT count FROM attempts WHERE day=?", (recovery.DAY,)).fetchone() == (2,)
    assert f.s.preparation_recovery_permit.with_name(recovery.NAME+".attempt-claim").is_file()
    assert not recovery.available(f.s, f.inbox, RUN, recovery.DAY, NOW, authority=f.authority)


def test_startup_authority_guard_also_retains_fixed_diagnostic_without_native(resume):
    f = resume
    issue(f)
    calls = []
    def window(*_):
        raise PermissionError("private authority context")
    market = NS(issues={}, plan=lambda _: NS(trading_day=date(2026,11,3), active=True, connect_allowed=True),
                ordinary_takeover_window=window, activate=lambda _: None, close=lambda: None)
    sup = Supervisor(f.s, ("RB",), market, lambda *_: calls.append("factory"), clock=lambda: NOW, sleep=lambda _: None)
    sup.run_id = RUN
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        sup.run(max_cycles=1)
    assert calls == []
    failure = recovery.read(f.folder / ("failure-" + RUN + "-0.json"))[0]
    diagnostic = failure["diagnostic"]
    assert diagnostic["recovery_error_code"] == "PREPARATION_RECOVERY_INVALID"
    assert diagnostic["safe_guard_diagnostics"]["stage"] == "AUTHORITY"
    assert diagnostic["safe_guard_diagnostics"]["exception_category"] == "PermissionError"
    assert "private authority" not in json.dumps(failure)
    assert not recovery._global(f.s).exists()


@pytest.mark.parametrize("case", ["signals", "schema", "ledger", "claim", "budget", "inode"])
def test_consumed_budget_allows_only_the_single_attempt_row_change(resume, case):
    f = resume
    issue(f)
    activate(f)
    _, window = consume(f)
    if case == "signals":
        f.inbox.conn.execute("INSERT INTO signals(product,bar,source,observed,payload,hash,status) VALUES (?,?,?,?,?,?,?)",
                             ("RB", NOW.isoformat(), "source", NOW.isoformat(), "{}", "f"*64, "QUEUED"))
    if case == "schema":
        f.inbox.conn.execute("CREATE TABLE unexpected(value TEXT)")
    if case == "ledger":
        import sqlite3
        with sqlite3.connect(f.folder / "dispatch.sqlite") as conn:
            conn.execute("CREATE TABLE unexpected(value TEXT)")
    if case == "claim":
        path = f.s.preparation_recovery_permit.with_name(recovery.NAME+".attempt-claim")
        path.write_text(path.read_text()+" ")
    if case == "budget":
        f.inbox.conn.execute("UPDATE attempts SET count=2 WHERE day=?", (recovery.DAY,))
    if case == "inode":
        path = f.folder / "signals.sqlite"
        alternate = path.with_name("replacement.private.sqlite")
        alternate.write_bytes(path.read_bytes())
        alternate.chmod(0o600)
        alternate.replace(path)
    calls = []
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        recovery.validate_connection(window, NOW, f.authority, clock=lambda: NOW)
        calls.append("factory")
    assert calls == []


def test_supervisor_resume_reaches_exactly_one_factory_and_login_then_real_host_stays_held(resume, monkeypatch):
    from guiyi_quant import htdy_account_execution as account
    from guiyi_quant.simnow_execution.adapter import Adapter
    from guiyi_quant.simnow_execution.inventory import native_hash, read_snapshot
    from guiyi_quant.simnow_execution.model import Session, FRONT
    from guiyi_quant.simnow_execution import supervisor
    import test_supervisor as fixtures
    f = resume
    issue(f)
    clock = NS(at=NOW)
    calls = []
    records = []
    original_publish = supervisor.publish_status
    def publish(folder, value):
        records.append(value)
        original_publish(folder, value)
    monkeypatch.setattr(supervisor, "publish_status", publish)
    class HeldAdapter:
        correlated_native = True
        strategy_correlated_native = True
        _faulted = False
        execution_hold = True
        dispatch = Adapter.dispatch
        last_dispatch_diagnostic = None
        def __init__(self, state, journal, native_validator):
            self.store, self.journal = state, journal
            self.account_profile = f.s.account_profile
            self.native_validator = native_validator
            self.account_takeover_pending = True
            self.session = Session(f.s.account_id, "SIMNOW_FIRST", FRONT, recovery.DAY,
                                   1, -123, 0, "fixture-login", "fixture-settlement",
                                   clock.at-timedelta(seconds=2), clock.at+timedelta(hours=1))
        def correlate_snapshot(self, snapshot):
            self.native_validator(snapshot)
        def drain(self):
            return ()
        def disconnected(self, _):
            pass
    class Driver:
        transport_failed = False
        def set_pre_native_guard(self, guard):
            self.pre_native_guard = guard
        def connect(self):
            self.pre_native_guard()
            calls.append("connect")
        def snapshot(self):
            clock.at += timedelta(seconds=20)
            report = fixtures.native_fixture.report()
            report["trading_day"] = recovery.DAY
            for n, round_ in enumerate(report["rounds"]):
                start = clock.at-timedelta(seconds=13-10*n)
                round_.update(started_at=start.isoformat(), completed_at=(start+timedelta(seconds=2)).isoformat())
                for query in round_["queries"].values():
                    query.update(started_at=start.isoformat(), completed_at=(start+timedelta(seconds=1)).isoformat())
                round_["queries"]["funds"]["rows"][0]["TradingDay"] = recovery.DAY
            payload = {k: v["rows"] for k, v in report["rounds"][0]["queries"].items()}
            report["round_hashes"] = [native_hash(payload)]*2
            self.report = report
            return read_snapshot(report, now=clock.at)
        def bindings_for(self, *_):
            return ()
        def adapter(self, state, journal, snapshot, now, **kwargs):
            result = HeldAdapter(state, journal, kwargs["native_validator"])
            adapters.append(result)
            return result
        def execution_for(self, *_args, **_kwargs):
            calls.append("execution")
            raise AssertionError("held host cannot construct execution inputs")
        def audit_next(self, *_):
            calls.append("audit")
        def close(self):
            calls.append("close")
    adapters = []
    def factory(*_):
        assert f.inbox.conn.execute("SELECT count FROM attempts WHERE day=?", (recovery.DAY,)).fetchone() == (3,)
        calls.append("factory")
        return Driver()
    market = NS(issues={}, plan=lambda _: NS(trading_day=date(2026,11,3), active=True, connect_allowed=True),
                ordinary_takeover_window=lambda *_: f.source["window"], recovery=lambda *_: (),
                authority=lambda *_: None, activate=lambda _: None, close=lambda: None,
                poll=lambda *_: calls.append("poll"))
    sup = Supervisor(f.s, ("RB",), market, factory, clock=lambda: clock.at, sleep=lambda _: None)
    sup.run_id = RUN
    assert sup.run(max_cycles=2) == "STOPPED"
    assert calls == ["factory", "connect", "close"]
    held = [r for r in records if r["status"] == "ACCOUNT_RECOVERED_HELD"]
    assert len(held) == 2
    assert all(r["account_takeover_pending"] is False and r["auto_order"] is False
               and r["opening_enabled"] is False for r in held)
    state = account.LocalStore.inspect(f.folder / "account.sqlite")
    assert state.phase == "READY" and state.readback_valid
    assert state.orders == () and state.fills == ()
    assert adapters[0].account_takeover_pending is False
    with pytest.raises(ValueError, match="ACCOUNT_RECOVERY_HOLD"):
        adapters[0].dispatch(None, None, None, None, None, clock.at)


def test_authority_work_crossing_expiry_is_denied_by_final_connection_clock(resume):
    f = resume
    issue(f)
    activate(f)
    _, window = consume(f)
    clock = NS(at=NOW)
    def slow_authority():
        clock.at = window.expires_at
        return f.authority()
    calls = []
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        recovery.validate_connection(window, NOW, slow_authority, clock=lambda: clock.at)
        calls.append("factory")
    assert calls == []
    assert recovery.guard_diagnostic()["stage"] == "TIME_WINDOW"
    assert recovery.guard_diagnostic()["checks"]["current_time_valid"] is False


@pytest.mark.parametrize("validation_number", [1, 2, 3])
def test_supervisor_connection_checks_resample_after_expensive_guards(resume, monkeypatch, validation_number):
    f = resume
    issue(f)
    activate(f)
    clock = NS(at=NOW)
    calls = []
    validations = []
    original = recovery._consumed_state
    def expensive_state(*args):
        original(*args)
        validations.append(1)
        if len(validations) == validation_number:
            clock.at = NOW+timedelta(seconds=240)
    monkeypatch.setattr(recovery, "_consumed_state", expensive_state)
    market = NS(issues={}, plan=lambda _: NS(trading_day=date(2026,11,3), active=True, connect_allowed=True),
                ordinary_takeover_window=lambda *_: f.source["window"])
    def factory(*_):
        calls.append("factory")
        driver = NS(pre_native_guard=None)
        driver.set_pre_native_guard = lambda guard: setattr(driver, "pre_native_guard", guard)
        driver.connect = lambda: (driver.pre_native_guard(), calls.append("connect"))
        return driver
    sup = Supervisor(f.s, ("RB",), market, factory, clock=lambda: clock.at)
    sup.run_id = RUN
    sup.folder, sup.inbox = f.folder, f.inbox
    sup.status = lambda *_args, **_kwargs: None
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        sup.connect(recovery.DAY)
    assert calls == (["factory"] if validation_number == 3 else [])
    assert len(validations) == validation_number
    assert f.inbox.conn.execute("SELECT count FROM attempts WHERE day=?", (recovery.DAY,)).fetchone() == (3,)
    assert f.s.preparation_recovery_permit.with_name(recovery.NAME+".attempt-claim").is_file()
    assert not recovery.available(f.s, f.inbox, RUN, recovery.DAY, clock.at, authority=f.authority)


def test_consumed_budget_proof_cannot_redefine_the_grants_third_attempt(resume):
    f = resume
    issue(f)
    activate(f)
    _, window = consume(f)
    f.inbox.conn.execute("UPDATE attempts SET count=2 WHERE day=?", (recovery.DAY,))
    altered = window._replace(consumption={**window.consumption, "budget": f.source["budget"]})
    calls = []
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        recovery.validate_connection(altered, NOW, f.authority, clock=lambda: NOW)
        calls.append("factory")
    assert calls == []
    diagnostic = recovery.guard_diagnostic()
    assert diagnostic["stage"] == "CONSUMED_STATE"
    assert diagnostic["checks"]["proof_budget_matches_grant"] is False
    assert diagnostic["checks"]["budget_exactly_third"] is False


def test_actual_native_portfolio_checks_after_keychain_work_before_connector(resume, monkeypatch):
    from guiyi_quant.simnow_execution import native_portfolio as native
    f = resume
    issue(f)
    activate(f)
    clock = NS(at=NOW)
    calls = []
    def credentials(*_):
        calls.append("credentials")
        clock.at = NOW+timedelta(seconds=240)
        return NS(user="fixture-user", password="fixture-password")
    monkeypatch.setattr(native.CredentialStore, "load", credentials)
    def gateway(user, password, **_):
        calls.append("gateway")
        return NS(user=user, password=password, api=None)
    def factory(*_):
        calls.append("factory")
        return native.NativePortfolio(f.s, f.folder, NS(tdapi=object(), Gateway=gateway),
                                      lambda *_: calls.append("connector"), now=lambda: clock.at)
    market = NS(issues={}, plan=lambda _: NS(trading_day=date(2026,11,3), active=True, connect_allowed=True),
                ordinary_takeover_window=lambda *_: f.source["window"])
    sup = Supervisor(f.s, ("RB",), market, factory, clock=lambda: clock.at)
    sup.run_id, sup.folder, sup.inbox = RUN, f.folder, f.inbox
    sup.status = lambda *_args, **_kwargs: None
    try:
        with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
            sup.connect(recovery.DAY)
        assert calls == ["factory", "credentials", "gateway"]
        assert sup.driver.stage == "PRE_NATIVE_GUARD"
        assert f.inbox.conn.execute("SELECT count FROM attempts WHERE day=?", (recovery.DAY,)).fetchone() == (3,)
        assert not recovery.available(f.s, f.inbox, RUN, recovery.DAY, clock.at, authority=f.authority)
    finally:
        if sup.driver is not None:
            sup.driver.close()


def test_supervisor_rejects_driver_without_final_native_guard_capability(resume):
    f = resume
    issue(f)
    activate(f)
    calls = []
    market = NS(issues={}, plan=lambda _: NS(trading_day=date(2026,11,3), active=True, connect_allowed=True),
                ordinary_takeover_window=lambda *_: f.source["window"])
    def factory(*_):
        calls.append("factory")
        return NS(connect=lambda: calls.append("connector"))
    sup = Supervisor(f.s, ("RB",), market, factory, clock=lambda: NOW)
    sup.run_id, sup.folder, sup.inbox = RUN, f.folder, f.inbox
    sup.status = lambda *_args, **_kwargs: None
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        sup.connect(recovery.DAY)
    assert calls == ["factory"]


def test_actual_native_portfolio_with_recovery_settings_requires_guard_before_credentials(resume, monkeypatch):
    from guiyi_quant.simnow_execution import native_portfolio as native
    f = resume
    calls = []
    monkeypatch.setattr(native.CredentialStore, "load", lambda *_: calls.append("credentials"))
    driver = native.NativePortfolio(f.s, f.folder, NS(), lambda *_: calls.append("connector"), now=lambda: NOW)
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        driver.connect()
    assert calls == []
