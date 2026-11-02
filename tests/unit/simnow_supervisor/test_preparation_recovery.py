"""Held preparation recovery; every account, grant, API and native fact is local."""
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace as NS

import pytest

from guiyi_quant.simnow_execution import preparation_recovery as recovery
from guiyi_quant.simnow_execution.account_binding import existing_account
from guiyi_quant.simnow_execution.settings import load_settings
from guiyi_quant.simnow_execution.inbox import SignalInbox
from guiyi_quant.htdy_account_execution.codec import digest
from test_settings import existing_v2, write

NOW = datetime(2026, 11, 2, 13, 1, tzinfo=UTC)  # Night session belongs to Nov 3.
RUN = "1" * 32
OLD_PID = 2147483647


@pytest.fixture
def ready(tmp_path, monkeypatch, request):
    config, value, folder = existing_v2(tmp_path)
    private = tmp_path / "recovery"
    private.mkdir(mode=0o700)
    global_root = tmp_path / "global-locks"
    global_root.mkdir(mode=0o700)
    from guiyi_quant.simnow_execution import supervisor
    monkeypatch.setattr(supervisor, "global_account_lock_directory", lambda: global_root)
    monkeypatch.setattr(recovery, "release_identity", lambda root: dict(root=str(root), tag="v1.16.99", commit="a" * 40))
    state = existing_account(Path(value["state_root"]), value["account_id"])
    value.update(enabled=True, account_takeover_pending=True, account_recovery_hold=True,
                 preparation_recovery_permit=str(private / recovery.NAME),
                 account_profile=dict(profile_id="original_anchor_v1", account_id=value["account_id"],
                                      initial_readback_sha256=digest(state.initial_readback)))
    write(config, value)
    settings = load_settings(config)
    inbox = SignalInbox(folder / "signals.sqlite", settings.account_id, ("RB",))
    inbox.conn.execute("INSERT INTO attempts VALUES ('20261102',3)")
    inbox.conn.execute("INSERT INTO attempts VALUES ('20261103',2)")
    inbox.block("20261102", "OLD_UNTOUCHED")
    inbox.block(recovery.DAY, recovery.BLOCK)
    if getattr(request, "param", None) == "signals_trigger":
        inbox.conn.execute(
            "INSERT INTO signals(product,bar,source,observed,payload,hash,status) VALUES (?,?,?,?,?,?,?)",
            ("RB", NOW.isoformat(), "retained-source", NOW.isoformat(), "{}", "f"*64, "QUEUED"),
        )
        inbox.conn.execute("CREATE TRIGGER budget_side_write AFTER UPDATE OF count ON attempts "
                           "BEGIN UPDATE signals SET status='RESTART_DROPPED'; END")
    inbox.close()
    facts = dict(trading_day=recovery.DAY,
                 sessions=[dict(start=(NOW-timedelta(minutes=1)).isoformat(),
                                end=(NOW+timedelta(hours=2)).isoformat())],
                 session_facts_sha256="c" * 64)
    source = dict(account_anchor=recovery.account_anchor(settings), budget=recovery.budget_binding(settings), window=facts)
    for name in ("failure", "diagnostic", "release_receipt"):
        path = private / (name + ".private.json")
        write(path, {"fact": name})
        source[name] = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    intent = private / recovery.INTENT_NAME
    write(intent, dict(schema=recovery.INTENT_SCHEMA, stage="START_REQUESTED", source=source,
                       config_path=str(config), config_sha256=settings.source_config_sha256,
                       old_run_id="0" * 32, old_pid=OLD_PID, old_pid_exited=True, created_at=NOW.isoformat()))
    real_kill = os.kill
    def kill(pid, sig):
        if pid == OLD_PID:
            raise ProcessLookupError()
        return real_kill(pid, sig)
    monkeypatch.setattr(recovery.os, "kill", kill)
    recovery.issue(settings, config, intent_path=intent, source=source, now=NOW,
                   expires_at=NOW+timedelta(seconds=250), clock=lambda: NOW)
    inbox = SignalInbox(folder / "signals.sqlite", settings.account_id, ("RB",))
    def authority():
        return {**facts, "active": True}
    value = NS(s=settings, inbox=inbox, source=source, config=config, intent=intent,
               authority=authority, folder=folder, global_root=global_root)
    yield value
    inbox.close()


def activate(f):
    recovery.activate(f.s, f.inbox, RUN, NOW, clock=lambda: NOW, authority=f.authority)


def consume(f, **kwargs):
    return recovery.consume(f.s, f.inbox, kwargs.get("run", RUN), kwargs.get("day", recovery.DAY),
                            kwargs.get("now", NOW), clock=kwargs.get("clock", lambda: NOW),
                            authority=kwargs.get("authority", f.authority))


def test_one_attempt_updates_only_two_to_three_and_retains_every_old_block(ready):
    f = ready
    before = recovery._tables(f.inbox.conn, f.s.account_id)
    activate(f)
    assert recovery.available(f.s, f.inbox, RUN, recovery.DAY, NOW, authority=f.authority)
    count, window = consume(f)
    assert count == 3
    recovery.validate_connection(window, NOW, f.authority)
    after = recovery._tables(f.inbox.conn, f.s.account_id)
    assert after == {**before, "attempts": [["20261102", 3], [recovery.DAY, 3]]}
    assert not recovery.available(f.s, f.inbox, RUN, recovery.DAY, NOW, authority=f.authority)
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_CONSUMED"):
        consume(f)
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_CONSUMED"):
        recovery.activate(f.s, f.inbox, "2" * 32, NOW, clock=lambda: NOW, authority=f.authority)


@pytest.mark.parametrize("case", ["expiry", "config", "account", "failure", "intent", "sdk", "release", "budget", "block", "authority", "inactive", "wrong_run", "old_run", "wrong_day", "clock", "live_old_pid"])
def test_every_guard_denies_before_native_factory_and_attempt_cannot_be_retried(ready, monkeypatch, case):
    f = ready
    activate(f)
    args = {}
    if case == "expiry":
        args.update(now=NOW+timedelta(seconds=250), clock=lambda: NOW+timedelta(seconds=250))
    if case == "config":
        f.config.write_text(f.config.read_text()+" ")
    if case == "account":
        (f.folder / "account.sqlite").write_bytes(b"changed")
    if case == "failure":
        Path(f.source["failure"]["path"]).write_text('{"changed":true}')
    if case == "intent":
        f.intent.write_text(f.intent.read_text()+" ")
    if case == "sdk":
        monkeypatch.setattr(recovery, "sdk_identity", lambda _: {})
    if case == "release":
        monkeypatch.setattr(recovery, "release_identity", lambda _: {})
    if case == "budget":
        f.inbox.conn.execute("INSERT INTO attempts VALUES ('20261101',1)")
    if case == "block":
        f.inbox.block("20261101", "UNTOUCHED")
    if case == "authority":
        args["authority"] = lambda: {**f.authority(), "session_facts_sha256": "d" * 64}
    if case == "inactive":
        args["authority"] = lambda: {**f.authority(), "active": False}
    if case == "wrong_run":
        args["run"] = "2" * 32
    if case == "old_run":
        args["run"] = "0" * 32
    if case == "wrong_day":
        args["day"] = "20261104"
    if case == "clock":
        args["clock"] = lambda: NOW+timedelta(seconds=251)
    if case == "live_old_pid":
        monkeypatch.setattr(recovery.os, "kill", lambda *_: None)
    sdk_calls = []
    def native():
        sdk_calls.append("factory")
    with pytest.raises(ValueError):
        consume(f, **args)
        native()
    assert sdk_calls == []
    assert f.inbox.conn.execute("SELECT count FROM attempts WHERE day=?", (recovery.DAY,)).fetchone() == (2,)
    assert not recovery.available(f.s, f.inbox, RUN, recovery.DAY, NOW, authority=f.authority)


def test_unknown_commit_is_consumed_with_no_sql_retry_or_block_rewrite(ready):
    f = ready
    activate(f)
    original = f.inbox.conn
    before_blocks = recovery._tables(original, f.s.account_id)["blocks"]
    calls = []
    class UnknownCommit:
        def set_authorizer(self, callback):
            original.set_authorizer(callback)
        @property
        def in_transaction(self):
            return original.in_transaction
        def execute(self, sql, *args):
            calls.append(sql)
            result = original.execute(sql, *args)
            if sql == "COMMIT":
                raise sqlite3.OperationalError("unknown private commit")
            return result
    f.inbox.conn = UnknownCommit()
    try:
        with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
            consume(f)
        with pytest.raises(ValueError, match="PREPARATION_RECOVERY_CONSUMED"):
            consume(f)
        assert calls.count("COMMIT") == 1
        assert not recovery.available(f.s, f.inbox, RUN, recovery.DAY, NOW, authority=f.authority)
        assert recovery._tables(original, f.s.account_id)["blocks"] == before_blocks
        assert original.execute("SELECT count FROM attempts WHERE day=?", (recovery.DAY,)).fetchone() == (3,)
    finally:
        f.inbox.conn = original


@pytest.mark.parametrize("component", ["adapter", "host_tick", "host_submit"])
def test_all_three_hold_barriers_precede_any_order_or_state_work_even_after_pending_clears(component):
    from guiyi_quant.simnow_execution.adapter import Adapter
    from guiyi_quant.simnow_execution.host import Host
    instance = object.__new__(Adapter if component == "adapter" else Host)
    instance.execution_hold = True
    instance.account_takeover_pending = False
    instance.last_dispatch_diagnostic = None
    # No store, journal, SDK, facts or order objects exist; the barrier must run first.
    with pytest.raises(ValueError, match="ACCOUNT_RECOVERY_HOLD"):
        if component == "adapter":
            instance.dispatch(None, None, None, None, None, NOW)
        elif component == "host_tick":
            instance.tick(None, None, NOW)
        else:
            instance.submit_effects(None, None, None, NOW)
    if component == "adapter":
        assert instance.last_dispatch_diagnostic["code"] == "ACCOUNT_RECOVERY_HOLD"


def test_hold_status_stays_nontrading_and_held_cycle_never_polls_delivers_or_audits(tmp_path):
    from guiyi_quant.simnow_execution.supervisor import Supervisor
    events = []
    state = NS(products=(), phase="READY", readback_valid=True, blocked_products=())
    settings = NS(mode="trade", enabled=True, account_recovery_hold=True, account_takeover_pending=False)
    market = NS(issues={}, plan=lambda _: NS(trading_day=date(2026,11,3), active=True),
                poll=lambda *_: events.append("poll"), recovery=lambda *_: (), close=lambda: None)
    sup = Supervisor(settings, (), market, None, clock=lambda: NOW)
    sup.driver = NS(snapshot=lambda: NS(trading_day=recovery.DAY, source_id="snapshot"),
                    bindings_for=lambda *_: (), report={}, audit_next=lambda *_: events.append("audit"))
    sup.day = recovery.DAY
    sup.prepared = True
    sup.store = NS(current=lambda: state, _needs_recovery=True)
    sup.host = NS(needs_recovery=False, reconcile=lambda *_: (None, state),
                  adapter=NS(expire_unacknowledged=lambda *_: events.append("expire")))
    sup.inbox = NS(enqueue=lambda *_: events.append("enqueue"), deliver=lambda *_: events.append("deliver"))
    statuses = []
    sup.status = lambda code, **kw: statuses.append((code, kw))
    sup.cycle()
    assert events == []
    assert statuses == [("ACCOUNT_RECOVERED_HELD", {"connected": True})]
    assert not sup.account_takeover_pending
    with pytest.raises(ValueError, match="ACCOUNT_RECOVERY_HOLD"):
        sup.refresh_before_book()


def test_status_declares_auto_order_and_opening_false_after_pending_cleared(ready, monkeypatch):
    from guiyi_quant.simnow_execution import supervisor
    f = ready
    value = []
    monkeypatch.setattr(supervisor, "publish_status", lambda _, v: value.append(v))
    sup = supervisor.Supervisor(f.s, ("RB",), NS(issues={}), None, clock=lambda: NOW)
    sup.folder = f.folder
    sup.latest_source = None
    sup.monitor = NS(publish=lambda *a, **kw: None)
    sup.account_takeover_pending = False
    sup.status("TRADING", connected=True)
    assert value[0]["auto_order"] is False
    assert value[0]["opening_enabled"] is False
    assert value[0]["account_recovery_hold"] is True
    assert value[0]["account_takeover_pending"] is False


@pytest.mark.parametrize("change", ["ordinary", "deployment", "pending", "hold", "disabled", "observe", "profile", "relative", "public_dir"])
def test_recovery_settings_are_narrow_and_old_configs_default_hold_off(ready, change):
    f = ready
    value = json.loads(f.config.read_text())
    if change == "ordinary":
        value["ordinary_takeover_permit"] = str(f.s.preparation_recovery_permit.parent / "ordinary-takeover-permit.private.json")
    if change == "deployment":
        value["deployment_connection_permit"] = str(f.s.preparation_recovery_permit.parent / "deployment-connection-permit.private.json")
    if change == "pending":
        value["account_takeover_pending"] = False
    if change == "hold":
        value["account_recovery_hold"] = False
    if change == "disabled":
        value["enabled"] = False
    if change == "observe":
        value["mode"] = "observe"
    if change == "profile":
        del value["account_profile"]
    if change == "relative":
        value["preparation_recovery_permit"] = "preparation-recovery-permit.private.json"
    if change == "public_dir":
        f.s.preparation_recovery_permit.parent.chmod(0o755)
    write(f.config, value)
    with pytest.raises(ValueError):
        load_settings(f.config)


def test_old_configuration_still_loads_without_hold_or_recovery(tmp_path):
    config, _, _ = existing_v2(tmp_path)
    settings = load_settings(config)
    assert settings.account_recovery_hold is False
    assert settings.preparation_recovery_permit is None


@pytest.mark.parametrize("close_fail", [False, True])
def test_supervisor_failure_uses_last_attempt_once_and_never_rewrites_original_blocks(ready, close_fail):
    from guiyi_quant.simnow_execution.supervisor import Supervisor
    f = ready
    before = recovery._tables(f.inbox.conn, f.s.account_id)
    f.inbox.close()
    calls = []
    market = NS(issues={}, plan=lambda _: NS(trading_day=date(2026,11,3), active=True, connect_allowed=True),
                ordinary_takeover_window=lambda *_: f.source["window"], activate=lambda _: None, close=lambda: None)
    def connect():
        calls.append("connect")
        raise ValueError("NATIVE_TRANSPORT_FAILED")
    def close():
        calls.append("close")
        if close_fail:
            raise RuntimeError("private cleanup failed")
    def factory(*_):
        calls.append("factory")
        return NS(connect=connect, close=close, transport_failed=True,
                  failure_diagnostics=lambda: {"stage": "TEST"})
    sup = Supervisor(f.s, ("RB",), market, factory, clock=lambda: NOW, sleep=lambda _: None)
    sup.run_id = RUN
    try:
        if close_fail:
            with pytest.raises(ValueError, match="CONTINUOUS_CLEANUP_UNCERTAIN"):
                sup.run(max_cycles=3)
        else:
            assert sup.run(max_cycles=3) == "STOPPED"
        assert calls == ["factory", "connect", "close"]
    finally:
        f.inbox = SignalInbox(f.folder / "signals.sqlite", f.s.account_id, ("RB",))
    after = recovery._tables(f.inbox.conn, f.s.account_id)
    assert after == {**before, "attempts": [["20261102", 3], [recovery.DAY, 3]]}
    assert len(list(f.folder.glob("failure-" + RUN + "-*.json"))) == 1
    assert (f.s.preparation_recovery_permit.parent / (recovery.NAME + ".attempt-claim")).is_file()


def test_authoritative_overlapping_product_sessions_keep_earliest_end():
    window = dict(trading_day=recovery.DAY, session_facts_sha256="c"*64,
                  sessions=[dict(start=(NOW-timedelta(minutes=1)).isoformat(), end=(NOW+timedelta(minutes=n)).isoformat()) for n in (3, 60, 120)])
    grant = dict(source={"window": window}, issued_at=NOW.isoformat(), expires_at=(NOW+timedelta(seconds=179)).isoformat())
    recovery._time(grant, NOW)
    grant["expires_at"] = (NOW+timedelta(seconds=181)).isoformat()
    with pytest.raises(ValueError):
        recovery._time(grant, NOW)


@pytest.mark.parametrize("ready", ["signals_trigger"], indirect=True)
def test_existing_sqlite_trigger_cannot_write_signal_status_or_reach_native(ready, monkeypatch):
    f = ready
    activate(f)
    before = recovery._database_contents(f.inbox.conn)
    budget = recovery._tables(f.inbox.conn, f.s.account_id)
    total_changes = f.inbox.conn.total_changes
    original_authorizer = recovery._budget_authorizer
    denied = []
    def recording_authorizer(*args):
        result = original_authorizer(*args)
        if result == sqlite3.SQLITE_DENY:
            denied.append(args)
        return result
    monkeypatch.setattr(recovery, "_budget_authorizer", recording_authorizer)
    native_calls = []
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_INVALID"):
        consume(f)
        native_calls.extend(("factory", "SDK"))
    assert native_calls == []
    assert any(action == sqlite3.SQLITE_UPDATE and table == "signals"
               and column == "status" and trigger == "budget_side_write"
               for action, table, column, database, trigger in denied)
    assert f.inbox.conn.total_changes == total_changes
    assert recovery._database_contents(f.inbox.conn) == before
    assert recovery._tables(f.inbox.conn, f.s.account_id) == budget
    assert f.inbox.conn.execute("SELECT status FROM signals").fetchall() == [("QUEUED",)]
    assert f.s.preparation_recovery_permit.with_name(recovery.NAME + ".attempt-claim").is_file()
    assert not recovery.available(f.s, f.inbox, RUN, recovery.DAY, NOW, authority=f.authority)
    with pytest.raises(ValueError, match="PREPARATION_RECOVERY_CONSUMED"):
        consume(f)
