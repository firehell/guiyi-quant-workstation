"""Pending takeover is a capability barrier, not a fresh-account assertion."""

from datetime import UTC, datetime, timedelta
import pytest
from guiyi_quant.simnow_execution.adapter import Adapter
from guiyi_quant.simnow_execution.host import Host
from test_deployment_connection import granted as _granted_fixture
from test_trade_switch import real_account as _account_fixture


@pytest.fixture(name="granted")
def private_grant(tmp_path):
    yield from _granted_fixture.__wrapped__(tmp_path)


@pytest.fixture(name="real_account")
def private_account(tmp_path, monkeypatch):
    return _account_fixture.__wrapped__(tmp_path, monkeypatch)


def test_adapter_blocks_every_dispatch_before_takeover():
    adapter = Adapter.__new__(Adapter)
    adapter.account_takeover_pending = True
    with pytest.raises(ValueError, match="ACCOUNT_TAKEOVER_PENDING"):
        adapter.dispatch(None, None, None, None, None, datetime.now(UTC))


def test_host_blocks_tick_and_effects_before_takeover():
    host = Host.__new__(Host)
    host.account_takeover_pending = True
    for operation in (
        lambda: host.tick((), (), datetime.now(UTC)),
        lambda: host.submit_effects((), (), (), datetime.now(UTC)),
    ):
        with pytest.raises(ValueError, match="ACCOUNT_TAKEOVER_PENDING"):
            operation()


@pytest.fixture
def pending_granted(tmp_path):
    from test_deployment_connection import grant_state

    yield from grant_state(tmp_path, pending=True)


def test_only_frozen_budget_exhausted_block_is_covered_once(pending_granted):
    from guiyi_quant.simnow_execution import deployment_connection as permit

    s, inbox, now, pm, *_ = pending_granted
    before = (
        inbox.conn.execute("SELECT * FROM attempts").fetchall(),
        inbox.conn.execute("SELECT * FROM blocks").fetchall(),
    )
    permit.activate(s, inbox, "1" * 32, now, clock=lambda: now)
    permit.consume(s, inbox, "1" * 32, "20261030", pm, clock=lambda: pm)
    assert before == (
        inbox.conn.execute("SELECT * FROM attempts").fetchall(),
        inbox.conn.execute("SELECT * FROM blocks").fetchall(),
    )
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_EXHAUSTED"):
        permit.consume(s, inbox, "1" * 32, "20261030", pm, clock=lambda: pm)


@pytest.mark.parametrize(
    "case",
    ["different_reason", "additional_day_block", "attempt_change", "deleted_block"],
)
def test_budget_exception_never_ignores_drift(pending_granted, case):
    from guiyi_quant.simnow_execution import deployment_connection as permit

    s, inbox, now, pm, *_ = pending_granted
    permit.activate(s, inbox, "1" * 32, now, clock=lambda: now)
    if case == "different_reason":
        inbox.conn.execute(
            "UPDATE blocks SET code=? WHERE day=?", ("UNKNOWN_SUBMISSION", "20261030")
        )
    if case == "additional_day_block":
        inbox.block("20261029", "UNCHANGED_MUST_BE_FROZEN")
    if case == "attempt_change":
        inbox.conn.execute("UPDATE attempts SET count=2 WHERE day=?", ("20261030",))
    if case == "deleted_block":
        inbox.conn.execute("DELETE FROM blocks WHERE day=?", ("20261030",))
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.consume(s, inbox, "1" * 32, "20261030", pm, clock=lambda: pm)


def test_old_stale_snapshot_is_history_not_account_acceptance(real_account):
    from datetime import timedelta

    e = real_account
    e.clock[0] += timedelta(hours=1)
    with pytest.raises(Exception, match="ACCOUNT_UNPROVEN"):
        e.b._account()
    e.b.settings.account_takeover_pending = True
    historical = e.b._account()
    assert historical["account_takeover_pending"] is True
    assert historical["native_account_verified"] is False
    assert (
        historical["unknown_positions"] is None and historical["unknown_orders"] is None
    )
    e.plan["snapshot"]["account"] = historical
    e.plan["snapshot"]["preimage"]["account"] = historical
    e.stop()
    assert e.offline()["protected_state_unchanged"] is True


def test_pending_deployment_still_rejects_local_unknown_claim(real_account):
    import sqlite3

    e = real_account
    e.b.settings.account_takeover_pending = True
    db = sqlite3.connect(e.folder / "dispatch.sqlite")
    db.execute(
        "INSERT INTO actions(action_key,order_id,kind,payload,order_ref,front_id,session_id,request_id,intent) VALUES (?,?,?,?,?,?,?,?,?)",
        ("unknown", "not-in-ledger", "SUBMIT", "{}", "1", 1, 1, 1, "unknown"),
    )
    db.commit()
    db.close()
    with pytest.raises(Exception, match="PENDING_OBLIGATIONS"):
        e.b._account()


def test_full_native_settlement_and_recover_clear_both_guards(tmp_path):
    from test_trade_end_to_end import seeded_account, Driver
    from guiyi_quant.simnow_execution.supervisor import Supervisor
    from guiyi_quant import htdy_account_execution as a

    settings, folder, clock, market = seeded_account(tmp_path)
    settings.account_takeover_pending = True
    captured = []
    drivers = []

    def factory(*args):
        driver = Driver(*args, clock)
        drivers.append(driver)
        return driver

    host = Supervisor(
        settings, ("RB", "JM"), market, factory, clock=clock.now, sleep=clock.sleep
    )
    original = host.status

    def status(code, **kwargs):
        if code == "TRADING":
            captured.append(
                (
                    host.account_takeover_pending,
                    host.host.account_takeover_pending,
                    host.host.adapter.account_takeover_pending,
                    host.store.current().readback_valid,
                )
            )
        original(code, **kwargs)

    host.status = status
    host.run(max_cycles=1)
    assert captured == [(False, False, False, True)]
    assert (
        "settlement" in drivers[0].gateway.calls
        and "confirm" in drivers[0].gateway.calls
    )
    assert "insert" not in drivers[0].gateway.calls
    assert any(
        type(row.command) is a.Recover
        for row in a.LocalStore.inspect(folder / "account.sqlite").audit
    )


@pytest.mark.parametrize(
    "failure", ["stale_after_settlement", "settlement", "unknown_position"]
)
def test_takeover_failure_never_unblocks_any_order_capability(tmp_path, failure):
    from test_trade_end_to_end import seeded_account, Driver, Gateway
    from guiyi_quant.simnow_execution.supervisor import Supervisor

    settings, folder, clock, market = seeded_account(tmp_path)
    settings.account_takeover_pending = True
    gateway = Gateway(clock)
    if failure == "unknown_position":
        gateway.positions = {"rb2701": (1, 100)}
    originalquery = gateway.query

    def query(kind, *args, **kwargs):
        if failure == "settlement" and kind == "confirm":
            raise ValueError("NATIVE_SETTLEMENT_CONFIRMATION_REQUIRED")
        return originalquery(kind, *args, **kwargs)

    gateway.query = query

    class StaleDriver(Driver):
        def adapter(self, *args, **kwargs):
            result = super().adapter(*args, **kwargs)
            if failure == "stale_after_settlement":
                clock.advance(31)
            return result

    runtime = Supervisor(
        settings,
        ("RB", "JM"),
        market,
        lambda *args: StaleDriver(*args, clock, gateway),
        clock=clock.now,
        sleep=clock.sleep,
    )
    ready = []
    original = runtime.status

    def status(code, **kwargs):
        if not runtime.account_takeover_pending:
            ready.append(code)
        original(code, **kwargs)

    runtime.status = status
    runtime.run(max_cycles=1)
    assert not ready and runtime.account_takeover_pending
    assert not {"insert", "cancel"} & set(gateway.calls)


def test_pending_monitor_publishes_explicit_unverified_state(tmp_path):
    import json
    from types import SimpleNamespace as NS
    from guiyi_quant.simnow_execution.supervisor import Supervisor

    settings = NS(mode="trade", enabled=True, account_takeover_pending=True)
    runtime = Supervisor(settings, ("RB",), NS(issues={}), lambda *_: None)
    runtime.folder = tmp_path
    runtime.latest_source = None
    published = []
    runtime.monitor = NS(publish=lambda *args, **kwargs: published.append(kwargs))
    runtime.status("WAITING_ACCOUNT_TAKEOVER")
    value = json.loads((tmp_path / "continuous.json").read_bytes())
    assert value["mode"] == "trade" and value["auto_order"] is True
    assert (
        value["account_takeover_pending"] is True and value["opening_enabled"] is False
    )
    assert published[-1]["account_takeover_pending"] is True


# Reuse actual private four-journal fixtures; these never access a broker.


def test_pending_source_anchor_migrates_code_only_and_removes_runtime_fields(
    pending_granted, tmp_path
):
    import json
    import hashlib
    from types import SimpleNamespace as NS
    from test_trade_switch import m
    from guiyi_quant.simnow_execution.settings import load_settings

    s, inbox, now, pm, *_ = pending_granted
    b = m.MacBackend.__new__(m.MacBackend)
    b.settings = s
    b.plist = tmp_path / "live.plist"
    b.monitor = tmp_path / "source.private.json"
    b.old_config = tmp_path / "old-observe.private.json"
    b.candidate_plist = tmp_path / "candidate.plist"
    b.config = s.source_config_path
    b.label = "gui/1/" + m.LABEL
    source = dict(
        schema=2,
        account_id=s.account_id,
        state_root=str(s.state_root),
        project_root=str(s.state_project_root),
        sdk_python=str(s.sdk_python),
        api_env=str(s.api_env),
        mode="observe",
        enabled=True,
        state_project_root=str(s.state_project_root),
    )
    for path, raw in (
        (b.plist, b"old-plist"),
        (b.monitor, json.dumps(source).encode()),
        (b.old_config, json.dumps(source).encode()),
        (b.candidate_plist, b"new-plist"),
    ):
        path.write_bytes(raw)
        path.chmod(0o600)
    original = b.monitor.read_bytes()
    b.run = lambda args: NS(
        returncode=113 if args[1] == "print" else 0,
        stdout="",
        stderr="Could not find service " + m.LABEL,
    )
    snapshot = dict(
        preimage=dict(
            monitor_target_sha256=hashlib.sha256(b.monitor_source()).hexdigest()
        )
    )
    assert b.install(snapshot)
    assert b.monitor.read_bytes() != original
    anchor = load_settings(b.monitor)
    assert (
        anchor.mode == "observe"
        and anchor.enabled
        and anchor.project_root == s.project_root
    )
    assert (
        anchor.state_root == s.state_root
        and anchor.state_project_root == s.state_project_root
    )
    assert (
        anchor.deployment_connection_permit is None
        and anchor.account_takeover_pending is False
    )
    assert b.monitor_bound(snapshot)
    assert (
        b.monitor.with_name(b.monitor.name + ".trade-switch-preimage").read_bytes()
        == original
    )
    assert not {
        "deployment_connection_permit",
        "account_takeover_pending",
        "source_config_path",
        "source_config_sha256",
    } & set(json.loads(b.monitor.read_bytes()))


def test_five_thousand_historical_snapshots_recover_with_real_clock_guard(tmp_path):
    from dataclasses import replace
    from datetime import timedelta
    import time
    from test_trade_end_to_end import seeded_account, Driver
    from guiyi_quant.simnow_execution.evidence import Evidence
    from guiyi_quant.simnow_execution.inventory import native_hash
    from guiyi_quant.simnow_execution.supervisor import Supervisor

    settings, folder, clock, market = seeded_account(tmp_path)
    settings.account_takeover_pending = True
    evidence = Evidence(folder / "native-evidence.sqlite", settings.account_id)
    original = evidence.latest()
    evidence.close()
    (folder / "native-evidence.sqlite").unlink()
    evidence = Evidence(folder / "native-evidence.sqlite", settings.account_id)
    evidence.conn.execute("BEGIN")
    for offset in range(4999, -1, -1):
        at = original.at - timedelta(seconds=offset * 2)
        value = replace(
            original,
            at=at,
            started_at=at - timedelta(seconds=1),
            source_id="ctp-inventory:"
            + original.trading_day
            + ":"
            + native_hash(
                (
                    original.account_id,
                    original.trading_day,
                    original.data,
                    at.isoformat(),
                )
            ),
        )
        evidence.append(value)
    evidence.conn.execute("COMMIT")
    evidence.close()
    monotonic = time.monotonic()
    virtual = clock.now
    clock.now = lambda: virtual() + timedelta(seconds=time.monotonic() - monotonic)
    runtime = Supervisor(
        settings,
        ("RB", "JM"),
        market,
        lambda *args: Driver(*args, clock),
        clock=clock.now,
        sleep=clock.sleep,
    )
    recovered = []
    original_status = runtime.status

    def status(code, **kwargs):
        if code == "TRADING":
            recovered.append(not runtime.account_takeover_pending)
        original_status(code, **kwargs)

    runtime.status = status
    started = time.monotonic()
    runtime.run(max_cycles=1)
    elapsed = time.monotonic() - started
    assert recovered == [True]
    assert elapsed < 30
    print(f"5000_snapshot_takeover_seconds={elapsed:.3f};fresh_recover_verified=true")


@pytest.mark.parametrize("runtime_status", ["STARTING", "ERROR", "STOPPED", "STALE"])
def test_monitor_exposes_pending_without_claiming_old_readback_current(
    tmp_path, runtime_status
):
    from datetime import timedelta
    from test_trade_end_to_end import seeded_account
    from guiyi_quant import htdy_account_execution as a
    from guiyi_quant.htdy_account_execution.codec import digest
    from guiyi_quant.simnow_execution.evidence import Evidence
    from guiyi_quant.simnow_execution.monitor import MonitorPublisher, MonitorReader

    settings, folder, clock, market = seeded_account(tmp_path)
    state = a.LocalStore.inspect(folder / "account.sqlite")
    evidence = Evidence(folder / "native-evidence.sqlite", settings.account_id)
    native = evidence.latest()
    evidence.close()
    old = MonitorPublisher(settings.state_root, settings.account_id, "old-run")
    assert old.publish(
        "ACTIVE",
        clock.now(),
        connection="LOGGED_IN",
        native_source_id=native.source_id,
        ledger_hash=digest(state),
        mode="observe",
        opening_enabled=False,
        host_status="OBSERVING",
    )
    new = MonitorPublisher(settings.state_root, settings.account_id, "new-run")
    status = "STARTING" if runtime_status == "STALE" else runtime_status
    assert new.publish(
        status,
        clock.now(),
        mode="trade",
        opening_enabled=False,
        host_status="WAITING_SESSION",
        account_takeover_pending=True,
    )
    now = clock.now() + timedelta(seconds=31 if runtime_status == "STALE" else 0)
    view = MonitorReader(settings.state_root).overview(now)
    assert view["observer"]["account_takeover_pending"] is True
    assert view["observer"]["connection"] != "LOGGED_IN"
    assert view["observer"]["opening_enabled"] is False
    assert view["position_projection_complete"] is False
    assert view["readback_status"] != "verified"
    assert (
        view["observer"]["status"]
        == {
            "STARTING": "running",
            "ERROR": "error",
            "STOPPED": "stopped",
            "STALE": "stale",
        }[runtime_status]
    )


def test_slow_store_read_cannot_clear_takeover_after_snapshot_ttl():
    from datetime import timedelta
    from types import SimpleNamespace as NS

    now = datetime(2026, 10, 30, 5, 28, tzinfo=UTC)
    clock = [now]
    snapshot = NS(
        at=now - timedelta(seconds=29, milliseconds=900),
        source_id="native-fixture",
        trading_day="20261030",
        account_id="a" * 64,
    )
    rb = NS(
        complete=True,
        source_id=snapshot.source_id,
        snapshot=NS(at=snapshot.at),
        valid_until=snapshot.at + timedelta(seconds=30),
    )
    state = NS(
        phase="READY",
        readback_valid=True,
        readback=rb,
        account_id=snapshot.account_id,
        orders=(),
    )

    def current():
        clock[0] += timedelta(milliseconds=200)
        return state

    host = Host.__new__(Host)
    host.account_takeover_pending = True
    host.takeover_clock = lambda: clock[0]
    host.needs_recovery = False
    host.pending = ()
    host.store = NS(current=current, _needs_recovery=False)
    host.adapter = NS(
        account_takeover_pending=True,
        _faulted=False,
        session=NS(
            trading_day="20261030",
            at=now - timedelta(minutes=1),
            valid_until=now + timedelta(minutes=1),
            login_source_id="login",
            settlement_source_id="settlement",
        ),
    )
    with pytest.raises(ValueError, match="ACCOUNT_TAKEOVER_FRESH_READBACK_REQUIRED"):
        host.complete_takeover(snapshot, state, now)
    assert host.account_takeover_pending and host.adapter.account_takeover_pending


@pytest.mark.parametrize(
    "database",
    ["account.sqlite", "dispatch.sqlite", "signals.sqlite", "native-evidence.sqlite"],
)
def test_grant_rechecks_all_four_frozen_databases_before_connection(
    pending_granted, database
):
    import sqlite3
    from guiyi_quant.simnow_execution import deployment_connection as permit

    s, inbox, now, pm, *_ = pending_granted
    permit.activate(s, inbox, "1" * 32, now, clock=lambda: now)
    path = s.state_root / s.account_id / database
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE unexpected_drift(value TEXT)")
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.consume(s, inbox, "1" * 32, "20261030", pm, clock=lambda: pm)


def test_slow_global_stamp_fsync_crossing_deployment_window_never_writes_grant(
    tmp_path, monkeypatch
):
    from test_deployment_connection import grant_state
    from guiyi_quant.simnow_execution import deployment_connection as permit
    import json

    generator = grant_state(tmp_path, pending=True, issue=False)
    s, inbox, now, pm, intent, record, binding = next(generator)
    try:
        intent.write_text(json.dumps(record))
        intent.chmod(0o600)
        clock = [pm - timedelta(seconds=661)]
        original = permit.os.fsync

        def slow(fd):
            original(fd)
            clock[0] += timedelta(seconds=2)

        monkeypatch.setattr(permit.os, "fsync", slow)
        with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
            permit.issue(s, binding, "a" * 64, intent, clock[0], clock=lambda: clock[0])
        assert (
            permit.global_marker(s).exists()
            and not s.deployment_connection_permit.exists()
        )
    finally:
        generator.close()


def test_mac_start_rechecks_authoritative_window_after_slow_code_and_sdk(monkeypatch):
    from types import SimpleNamespace as NS
    from test_trade_switch import m

    b = m.MacBackend.__new__(m.MacBackend)
    b.settings = NS(sdk_python="/fixed/sdk")
    events = []
    b.code_check = lambda: events.append("code")
    b.identity = lambda *a, **k: "sdk"

    def window():
        events.append("fresh-window")
        return False

    b.window_open = window
    b.run = lambda args: pytest.fail("late bootstrap")
    with pytest.raises(m.SwitchError, match="WINDOW_UNPROVEN"):
        b.start(dict(preimage=dict(sdk="sdk")))
    assert events == ["code", "fresh-window"]


def test_window_clock_is_sampled_after_authority_rows(monkeypatch):
    from test_trade_switch import m, session_rows
    from zoneinfo import ZoneInfo

    now = datetime(2026, 10, 30, 13, 18, 59, tzinfo=ZoneInfo("Asia/Shanghai"))
    clock = [now]

    class ClockDate(datetime):
        @staticmethod
        def now(tz):
            return clock[0]

    monkeypatch.setattr(m, "datetime", ClockDate)
    b = m.MacBackend.__new__(m.MacBackend)
    b.window = "midday"

    def rows(at):
        result = session_rows(at)
        clock[0] += timedelta(seconds=2)
        return result

    b._window_rows = rows
    result = b._window()
    assert result["window_open"] is False and result["next_session_gap_seconds"] == 659


def test_existing_global_stamp_prevents_sigterm_even_for_another_intent(
    pending_granted, tmp_path, monkeypatch
):
    import json
    from test_trade_switch import m
    from guiyi_quant.simnow_execution.settings import load_settings

    s, inbox, *_ = pending_granted
    other = tmp_path / "second-switch"
    other.mkdir(mode=0o700)
    config = tmp_path / "second-trade.private.json"
    value = json.loads(s.source_config_path.read_bytes())
    value["deployment_connection_permit"] = str(
        other / "deployment-connection-permit.private.json"
    )
    config.write_text(json.dumps(value))
    config.chmod(0o600)
    settings = load_settings(config)
    backend = m.MacBackend.__new__(m.MacBackend)
    backend.settings = settings
    backend.folder = settings.state_root / settings.account_id
    backend.old_config = tmp_path / "not-read-with-mocked-process-proof"
    backend._prove = lambda *args: None
    backend._stop_signals = backend.identity(backend.folder / "signals.sqlite")
    backend._stop_requires_permit = True
    monkeypatch.setattr(
        m.os,
        "kill",
        lambda *_: pytest.fail("consumed account/day exception must not stop host"),
    )
    with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN"):
        backend.stop(1234)
    assert not settings.deployment_connection_permit.exists()
