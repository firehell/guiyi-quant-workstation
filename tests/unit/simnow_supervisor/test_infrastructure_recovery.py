"""The exact interruption recovery uses disposable native/ledger fixtures only."""

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace as NS

import pytest

from guiyi_quant import htdy_account_execution as account
from guiyi_quant.simnow_execution import infrastructure_recovery as r
from guiyi_quant.simnow_execution.account_profile import AccountProfile
from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.inbox import SignalInbox
from guiyi_quant.simnow_execution.inventory import native_hash, read_snapshot
from guiyi_quant.simnow_execution.settings import load_settings
from guiyi_quant.simnow_execution.supervisor import Supervisor
from test_trade_end_to_end import seeded_account, Gateway, Driver

NOW = datetime(2026, 11, 3, 14, 20, tzinfo=UTC)
NATIVE = datetime(2026, 11, 3, 14, 4, 37, tzinfo=UTC)
RUN = "1" * 32


def write(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest())


def day_report(gateway):
    report = gateway.report()
    report["trading_day"] = r.DAY
    for record in report["rounds"]:
        for q in record["queries"].values():
            for row in q["rows"]:
                row["TradingDay"] = r.DAY
    report["round_hashes"] = [
        native_hash({k: q["rows"] for k, q in record["queries"].items()})
        for record in report["rounds"]
    ]
    return report


@pytest.fixture
def ready(tmp_path, monkeypatch):
    old, folder, clock, market = seeded_account(tmp_path)
    anchor = tmp_path / "state-project"
    (anchor / "output").mkdir(parents=True)
    newroot = anchor / "output/simnow-controlled"
    old.state_root.rename(newroot)
    folder = newroot / old.account_id
    code = tmp_path / "code"
    (code / "scripts/broker").mkdir(parents=True)
    (code / "scripts/broker/simnow_controlled.py").touch()
    oldcode = tmp_path / "old-code"
    oldcode.mkdir()
    python = tmp_path / "python"
    python.touch(mode=0o700)
    env = tmp_path / "api-env"
    env.mkdir()
    private = tmp_path / "recovery"
    private.mkdir(mode=0o700)
    global_root = tmp_path / "global-locks"
    global_root.mkdir(mode=0o700)
    from guiyi_quant.simnow_execution import supervisor

    monkeypatch.setattr(
        supervisor, "global_account_lock_directory", lambda: global_root
    )
    monkeypatch.setattr(r, "_exited", lambda *_: None)
    monkeypatch.setattr(
        r.io,
        "release_identity",
        lambda p: dict(
            root=str(p),
            tag="v1.16.75" if Path(p) == oldcode else "v1.16.77",
            commit=r.SOURCE_COMMIT if Path(p) == oldcode else "d" * 40,
        ),
    )
    monkeypatch.setattr(
        r.io, "sdk_identity", lambda p: dict(path=str(p), sha256="e" * 64)
    )
    state = account.LocalStore.inspect(folder / "account.sqlite")
    profile = asdict(
        AccountProfile(
            "original_anchor_v1",
            old.account_id,
            account.codec.digest(state.initial_readback),
        )
    )
    value = dict(
        schema=2,
        account_id=old.account_id,
        state_root=str(newroot),
        state_project_root=str(anchor),
        project_root=str(code),
        sdk_python=str(python),
        api_env=str(env),
        mode="trade",
        enabled=True,
        account_profile=profile,
        account_takeover_pending=True,
        account_recovery_hold=False,
        infrastructure_recovery_permit=str(private / r.NAME),
    )
    config = private / "candidate.private.json"
    write(config, value)
    settings = load_settings(config)
    oldcfg = {k: v for k, v in value.items() if k != "infrastructure_recovery_permit"}
    oldcfg["project_root"] = str(oldcode)
    oldref = write(private / "old.private.json", oldcfg)
    clock.at = NATIVE + timedelta(seconds=1)
    evidence = Evidence(folder / "native-evidence.sqlite", settings.account_id)
    evidence.append(read_snapshot(day_report(Gateway(clock)), now=clock.now()))
    evidence.close()
    inbox = SignalInbox(folder / "signals.sqlite", settings.account_id, ("RB", "JM"))
    inbox.conn.execute("INSERT INTO attempts VALUES (?,1)", (r.DAY,))
    inbox.block(r.DAY, r.BLOCK)
    inbox.conn.execute("INSERT INTO attempts VALUES ('20261103',3)")
    inbox.block("20261103", "OLD_BLOCK")
    # Original first-observation facts are already acknowledged and remain bytes-identical.
    for n in range(6):
        inbox.conn.execute(
            "INSERT INTO signals(product,bar,source,observed,payload,hash,status) VALUES (?,?,?,?,?,?,?)",
            (
                "RB",
                str(n),
                "old-buy-" + str(n),
                NOW.isoformat(),
                "{}",
                "f" * 64,
                "APPLIED",
            ),
        )
    inbox.close()
    failure = write(
        folder / r.FAILURE_NAME,
        dict(
            schema="simnow_continuous_failure_v1",
            code=r.BLOCK,
            at="2026-11-03T14:04:40.889840+00:00",
            diagnostic=dict(
                stage="ACCOUNT_SNAPSHOT",
                recovery_stage="READY",
                recovery_error_code="RECOVERY_ERROR_UNCLASSIFIED",
                dispatch=None,
                settlement=dict(status="CONFIRMED"),
                inventory=dict(
                    status="READ_ONLY_COMPLETE",
                    queries=[dict(complete=True, timed_out=False) for _ in range(8)],
                ),
            ),
        ),
    )
    outage = write(
        private / "outage.private.json",
        dict(
            schema="simnow_operator_infrastructure_interruption_v1",
            source_run_id=r.OLD_RUN,
            trading_day=r.DAY,
            operator_confirmed=True,
            services=["postgresql", "redis"],
            stopped_at="2026-11-03T14:04:27.622+00:00",
            recovered_at="2026-11-03T14:04:34.121+00:00",
            runtime_registry_sha256="f" * 64,
        ),
    )
    window = dict(
        trading_day=r.DAY,
        sessions=[
            dict(
                start=(NOW - timedelta(hours=1)).isoformat(),
                end=(NOW + timedelta(hours=1)).isoformat(),
            )
        ],
        session_facts_sha256="c" * 64,
    )
    source = dict(
        account_anchor=r.account_anchor(settings),
        budget=r.budget_binding(settings),
        window=window,
        failure=failure,
        outage=outage,
        old_config=oldref,
        old_pid=r.OLD_PID,
        old_run_id=r.OLD_RUN,
        old_process_identity="b" * 64,
    )
    intent = private / r.INTENT_NAME
    write(
        intent,
        dict(
            schema=r.SCHEMA,
            stage="START_REQUESTED",
            source=source,
            config_path=str(config),
            config_sha256=settings.source_config_sha256,
            old_pid_exited=True,
        ),
    )

    def authority():
        return {**window, "active": True, "runtime_registry_sha256": "f" * 64}

    r.issue(
        settings,
        source=source,
        intent_path=intent,
        now=NOW,
        expires_at=NOW + timedelta(seconds=120),
        authority=authority,
        clock=lambda: NOW,
    )
    clock.at = NOW
    inbox = SignalInbox(folder / "signals.sqlite", settings.account_id, ("RB", "JM"))
    yield NS(
        s=settings,
        folder=folder,
        clock=clock,
        market=market,
        source=source,
        config=config,
        inbox=inbox,
        authority=authority,
        private=private,
        global_root=global_root,
    )
    inbox.close()


def activate(f):
    r.activate(f.s, f.inbox, RUN, NOW, authority=f.authority, clock=lambda: NOW)


def consume(f):
    return r.consume(
        f.s, f.inbox, RUN, r.DAY, NOW, authority=f.authority, clock=lambda: NOW
    )


def test_exact_second_attempt_preserves_all_blocks_and_old_signals(ready):
    f = ready
    blocks = f.inbox.conn.execute("SELECT * FROM blocks ORDER BY day").fetchall()
    signals = f.inbox.conn.execute("SELECT * FROM signals ORDER BY id").fetchall()
    activate(f)
    count, window = consume(f)
    assert count == 2
    r.validate_connection(window, NOW, f.authority, clock=lambda: NOW)
    assert (
        f.inbox.conn.execute("SELECT * FROM blocks ORDER BY day").fetchall() == blocks
    )
    assert (
        f.inbox.conn.execute("SELECT * FROM signals ORDER BY id").fetchall() == signals
    )
    with pytest.raises(ValueError):
        consume(f)
    with pytest.raises(ValueError):
        r.activate(
            f.s, f.inbox, "2" * 32, NOW, authority=f.authority, clock=lambda: NOW
        )


@pytest.mark.parametrize(
    "damage",
    [
        "config",
        "failure",
        "extra_failure",
        "outage",
        "budget",
        "old_block",
        "native_dispatch",
        "queued",
        "old_process",
        "inactive",
    ],
)
def test_guards_precede_factory_and_claim_is_not_refunded(ready, monkeypatch, damage):
    f = ready
    activate(f)
    if damage == "config":
        f.config.write_text(f.config.read_text() + " ")
    elif damage == "failure":
        Path(f.source["failure"]["path"]).write_text("{}")
    elif damage == "extra_failure":
        write(f.folder / ("failure-" + r.OLD_RUN + "-new.json"), {})
    elif damage == "outage":
        Path(f.source["outage"]["path"]).write_text("{}")
    elif damage == "budget":
        f.inbox.conn.execute("UPDATE attempts SET count=2 WHERE day=?", (r.DAY,))
    elif damage == "old_block":
        f.inbox.conn.execute("UPDATE blocks SET code='changed' WHERE day='20261103'")
    elif damage == "native_dispatch":
        with sqlite3.connect(f.folder / "dispatch.sqlite") as db:
            db.execute(
                "INSERT INTO actions(action_key,order_id,kind,payload,order_ref,front_id,session_id,request_id,intent) VALUES ('x','x','SUBMIT','{}','1',1,1,1,'x')"
            )
    elif damage == "queued":
        f.inbox.conn.execute("UPDATE signals SET status='QUEUED' WHERE id=1")
    elif damage == "old_process":
        monkeypatch.setattr(r, "_exited", lambda *_: r.invalid())
    else:
        original = f.authority
        f.authority = lambda: {**original(), "active": False}
    with pytest.raises(ValueError):
        consume(f)
    assert (f.private / (r.NAME + ".attempt-claim")).exists()


@pytest.mark.parametrize(
    "damage", ["config", "signals_inode", "expiry", "authority_expiry"]
)
def test_consumed_connection_rechecks_actual_identity_and_final_clock(ready, damage):
    f = ready
    activate(f)
    _, window = consume(f)
    authority = f.authority

    def clock():
        return NOW

    if damage == "config":
        f.config.write_text(f.config.read_text() + " ")
    elif damage == "signals_inode":
        path = f.folder / "signals.sqlite"
        other = path.with_name("replacement.sqlite")
        other.write_bytes(path.read_bytes())
        other.chmod(0o600)
        other.replace(path)
    elif damage == "expiry":

        def clock():
            return NOW + timedelta(seconds=120)
    else:
        end = [NOW]

        def authority():
            end[0] = NOW + timedelta(seconds=120)
            return f.authority()

        def clock():
            return end[0]

    with pytest.raises(ValueError):
        r.validate_connection(window, NOW, authority, clock=clock)


def test_pure_connection_validation_replays_ledger_once(ready, monkeypatch):
    f = ready
    activate(f)
    _, window = consume(f)
    calls = []
    inspect = account.LocalStore.inspect

    def counted(path):
        calls.append(path)
        return inspect(path)

    monkeypatch.setattr(account.LocalStore, "inspect", counted)
    r.validate_connection(window, NOW, f.authority, clock=lambda: NOW)
    assert len(calls) == 1


def test_prestop_preflight_allows_old_live_but_issue_requires_exit(ready, monkeypatch):
    f = ready
    path = f.private / r.NAME
    path.unlink()
    monkeypatch.setattr(r, "_exited", lambda *_: r.invalid())
    r.preflight_source(f.s, f.source, NOW, NOW + timedelta(seconds=120), f.authority)
    with pytest.raises(ValueError):
        r.issue(
            f.s,
            source=f.source,
            intent_path=f.private / r.INTENT_NAME,
            now=NOW,
            expires_at=NOW + timedelta(seconds=120),
            authority=f.authority,
            clock=lambda: NOW,
        )
    assert not path.exists()
    monkeypatch.setattr(r, "_exited", lambda *_: None)
    r.issue(
        f.s,
        source=f.source,
        intent_path=f.private / r.INTENT_NAME,
        now=NOW,
        expires_at=NOW + timedelta(seconds=120),
        authority=f.authority,
        clock=lambda: NOW,
    )
    assert path.exists()


class ConnectionFault:
    def __init__(self, conn, *, after_commit=False):
        self.conn = conn
        self.after_commit = after_commit

    def __getattr__(self, key):
        return getattr(self.conn, key)

    def execute(self, sql, *args):
        if sql == "COMMIT":
            if self.after_commit:
                self.conn.execute(sql, *args)
            raise sqlite3.OperationalError("fixture commit result unavailable")
        return self.conn.execute(sql, *args)


@pytest.mark.parametrize("after_commit", [False, True])
def test_commit_unknown_is_spent_and_never_refunded(ready, after_commit):
    f = ready
    activate(f)
    before = r._tables(f.inbox.conn, f.s.account_id)
    real = f.inbox.conn
    f.inbox.conn = ConnectionFault(real, after_commit=after_commit)
    try:
        with pytest.raises(ValueError):
            consume(f)
        assert (f.private / (r.NAME + ".attempt-claim")).exists()
        with sqlite3.connect(
            (f.folder / "signals.sqlite").as_uri() + "?mode=ro", uri=True
        ) as db:
            actual = r._tables(db, f.s.account_id)
        assert actual["blocks"] == before["blocks"]
        assert dict(actual["attempts"])[r.DAY] == (2 if after_commit else 1)
        with pytest.raises(ValueError):
            consume(f)
    finally:
        f.inbox.conn = real
        if real.in_transaction:
            real.rollback()


def test_trigger_cannot_write_beside_budget_update(ready):
    f = ready
    # The source preimage intentionally includes this real schema. The SQL
    # authorizer, rather than a preimage mismatch, must reject its side write.
    f.inbox.conn.execute(
        "CREATE TRIGGER bad_budget AFTER UPDATE ON attempts BEGIN UPDATE signals SET status='QUEUED'; END"
    )
    source = dict(f.source, account_anchor=r.account_anchor(f.s))
    path = f.private / r.NAME
    path.unlink()
    intent = f.private / r.INTENT_NAME
    write(
        intent,
        dict(
            schema=r.SCHEMA,
            stage="START_REQUESTED",
            source=source,
            config_path=str(f.config),
            config_sha256=f.s.source_config_sha256,
            old_pid_exited=True,
        ),
    )
    r.issue(
        f.s,
        source=source,
        intent_path=intent,
        now=NOW,
        expires_at=NOW + timedelta(seconds=120),
        authority=f.authority,
        clock=lambda: NOW,
    )
    activate(f)
    with pytest.raises(ValueError):
        consume(f)
    assert dict(r._tables(f.inbox.conn, f.s.account_id)["attempts"])[r.DAY] == 1
    assert f.inbox.conn.execute(
        "SELECT COUNT(*) FROM signals WHERE status='QUEUED'"
    ).fetchone() == (0,)


def test_full_supervisor_recovers_once_without_replaying_old_signals(ready):
    f = ready
    created = []

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

    def factory(settings, folder):
        created.append(IncidentDriver(settings, folder, f.clock))
        return created[-1]

    f.market.plan = lambda now: NS(
        trading_day=date(2026, 11, 4), active=True, connect_allowed=True
    )
    f.market.infrastructure_recovery_window = lambda day, now: f.authority()
    f.market.poll = lambda now, after: ()
    before = f.inbox.conn.execute("SELECT * FROM signals ORDER BY id").fetchall()
    supervisor = Supervisor(
        f.s, ("RB", "JM"), f.market, factory, clock=f.clock.now, sleep=f.clock.sleep
    )
    supervisor.run_id = RUN
    statuses = []
    status = supervisor.status
    errors = []
    connect = supervisor.connect

    def tracked_connect(day):
        try:
            return connect(day)
        except Exception as exc:
            errors.append((type(exc).__name__, str(exc)))
            raise

    supervisor.connect = tracked_connect

    def retain_status(code, **kw):
        statuses.append((code, supervisor.account_takeover_pending))
        return status(code, **kw)

    supervisor.status = retain_status
    supervisor.run(max_cycles=1)
    assert len(created) == 1
    assert ("TRADING", False) in statuses, (statuses, errors)
    assert dict(r._tables(f.inbox.conn, f.s.account_id)["attempts"])[r.DAY] == 2
    assert (
        f.inbox.conn.execute("SELECT * FROM signals ORDER BY id").fetchall() == before
    )
    assert all(
        "insert" not in d.gateway.calls
        and not d.gateway.orders
        and not d.gateway.trades
        for d in created
    )
    with sqlite3.connect(f.folder / "dispatch.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM actions").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM results").fetchone() == (0,)


@pytest.mark.parametrize(
    "failure", ["factory", "native_connect", "snapshot", "market_poll"]
)
def test_full_failed_run_never_retries_even_after_day_changes(ready, failure):
    f = ready
    factories = []
    connects = []
    blocks = r._tables(f.inbox.conn, f.s.account_id)["blocks"]
    signals = f.inbox.conn.execute("SELECT * FROM signals ORDER BY id").fetchall()

    class FailedDriver(Driver):
        def connect(self):
            self.pre_native_guard()
            connects.append(True)
            if failure == "native_connect":
                raise ValueError("NATIVE_TRANSPORT_FAILED")
            super().connect()
            self.gateway.result["trading_day"] = r.DAY
            self.gateway.inventory_diagnostics = lambda: {}

        def snapshot(self):
            if failure == "snapshot":
                raise ValueError("NATIVE_SNAPSHOT_CHANGED")
            self.clock.advance(15)
            self.report = day_report(self.gateway)
            return read_snapshot(self.report, now=self.clock.now())

    def factory(settings, folder):
        factories.append(True)
        if failure == "factory":
            raise RuntimeError("fixture construction failed")
        return FailedDriver(settings, folder, f.clock)

    f.market.plan = lambda now: NS(
        trading_day=date(2026, 11, 4)
        if now < NOW + timedelta(hours=1)
        else date(2026, 11, 5),
        active=True,
        connect_allowed=True,
    )
    f.market.infrastructure_recovery_window = lambda day, now: f.authority()

    def poll(*args):
        raise ConnectionError("fixture dependency unavailable")

    f.market.poll = poll
    supervisor = Supervisor(
        f.s,
        ("RB", "JM"),
        f.market,
        factory,
        clock=f.clock.now,
        sleep=lambda _: f.clock.advance(86400),
    )
    supervisor.run_id = RUN
    supervisor.run(max_cycles=3)
    assert len(factories) == 1 and len(connects) == (0 if failure == "factory" else 1)
    assert supervisor.infrastructure_recovery_failed
    actual = r._tables(f.inbox.conn, f.s.account_id)
    assert actual["blocks"] == blocks and dict(actual["attempts"])[r.DAY] == 2
    assert (
        f.inbox.conn.execute("SELECT * FROM signals ORDER BY id").fetchall() == signals
    )


def test_delayed_start_cannot_bypass_incident_claim_on_future_day(ready):
    f = ready
    created = []
    f.market.plan = lambda now: NS(
        trading_day=date(2026, 11, 5), active=True, connect_allowed=True
    )
    supervisor = Supervisor(
        f.s,
        ("RB", "JM"),
        f.market,
        lambda *args: created.append(True),
        clock=f.clock.now,
    )
    with pytest.raises(ValueError, match="INFRASTRUCTURE_RECOVERY_INVALID"):
        supervisor.run(max_cycles=1)
    assert (
        not created
        and dict(r._tables(f.inbox.conn, f.s.account_id)["attempts"])[r.DAY] == 1
    )
