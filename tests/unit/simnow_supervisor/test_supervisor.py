"""Continuous host safety checks with an existing local account and fake native driver."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import fcntl
import importlib.util
import os
import sqlite3

import pytest

from guiyi_quant import htdy_account_execution as a, htdy_execution as h
from guiyi_quant.htdy_execution import Signal
from guiyi_quant.simnow_execution.inbox import SignalInbox
from guiyi_quant.simnow_execution.inventory import project_readback, read_snapshot
from guiyi_quant.simnow_execution.supervisor import Supervisor, account_lock


SPEC = importlib.util.spec_from_file_location(
    "native_fixture", Path(__file__).parents[1] / "simnow_host/test_inventory.py"
)
assert SPEC and SPEC.loader
native_fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native_fixture)

ACCOUNT = "a" * 64
T = datetime(2026, 10, 27, 1, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.at = T + timedelta(minutes=1)

    def now(self):
        return self.at

    def sleep(self, seconds):
        self.at += timedelta(seconds=max(61, seconds))


class FakeMarket:
    def __init__(
        self, connect_allowed=True, day=date(2026, 10, 27), *, active=True, signals=()
    ):
        self.connect_allowed = connect_allowed
        self.day = day
        self.active = active
        self.signals = signals
        self.issues = {}
        self.activations = 0
        self.polls = 0
        self.closed = False

    def plan(self, now):
        return SimpleNamespace(
            trading_day=self.day,
            connect_allowed=self.connect_allowed,
            active=self.active,
            next_open_at=None,
        )

    def activate(self, now):
        self.activations += 1

    def poll(self, now, after):
        self.polls += 1
        return self.signals

    def close(self):
        self.closed = True


class FakeDriver:
    def __init__(
        self,
        snapshot,
        *,
        fail=None,
        transport_failed=False,
        snapshot_failures=(),
        close_fail=False,
    ):
        self.fact = snapshot
        self.fail = fail
        self.transport_failed = transport_failed
        self.connects = 0
        self.snapshots = 0
        self.snapshot_failures = frozenset(snapshot_failures)
        self.observations = 0
        self.closed = False
        self.close_fail = close_fail
        self.read_journal = None

    def connect(self):
        self.connects += 1
        if self.fail:
            raise (
                self.fail
                if isinstance(self.fail, Exception)
                else RuntimeError("private native diagnostic")
            )

    def snapshot(self):
        self.snapshots += 1
        if self.snapshots in self.snapshot_failures:
            raise ValueError("NATIVE_SNAPSHOT_CHANGED")
        return self.fact

    def bindings_for(self, state, market, now, day):
        return ()

    def observe_next(self, products, market, now, day, issues):
        self.observations += 1

    def close(self):
        self.closed = True
        if self.close_fail:
            raise RuntimeError("private cleanup diagnostic")


def setup(tmp_path, *, enabled=True, mode="observe", journal=True, held=False):
    state_root = tmp_path / "output/simnow-controlled"
    settings = SimpleNamespace(
        state_root=state_root, account_id=ACCOUNT, mode=mode, enabled=enabled
    )
    snapshot = read_snapshot(native_fixture.report())
    if journal:
        folder = state_root / ACCOUNT
        folder.mkdir(parents=True, mode=0o700)
        state_root.chmod(0o700)
        if held:
            rb = a.Readback(
                h.AccountSnapshot(ACCOUNT, T, D(100000), D(100000)),
                D(0),
                D(0),
                D(0),
                (),
                (),
                "initial-synthetic",
                T + timedelta(hours=3),
                True,
            )
            state = a.start(ACCOUNT, ("JM", "RB"), T, rb)
        else:
            rb, _ = project_readback(
                snapshot, (), None, None, snapshot.at + timedelta(minutes=1)
            )
            state = a.start(ACCOUNT, ("JM", "RB"), snapshot.at, rb)
        store = a.LocalStore(folder / "account.sqlite", state)
        if held:
            store.execute("owner", h.Owner("RB", "RB2701", T, "owner"))
            store.execute(
                "signal",
                Signal(
                    "held-signal",
                    "RB",
                    "RB2701",
                    T + timedelta(minutes=60),
                    T + timedelta(minutes=60, seconds=2),
                    None,
                    ("buy",),
                    "b" * 64,
                ),
            )
            at = T + timedelta(minutes=61)
            facts = a.ExecutionInput(
                a.Instrument(
                    "RB",
                    "RB2701",
                    T,
                    T + timedelta(hours=3),
                    "instrument",
                    D(1),
                    D(10),
                    D(".1"),
                    D(".1"),
                    D(3),
                ),
                a.Session(
                    "RB2701",
                    T,
                    T + timedelta(hours=3),
                    "session",
                    T + timedelta(hours=6),
                    True,
                    True,
                ),
                a.Quote(
                    "RB2701",
                    at,
                    at + timedelta(seconds=10),
                    "quote",
                    D(999),
                    D(1000),
                    3,
                    3,
                    D(900),
                    D(1100),
                ),
            )
            order = store.execute("tick", a.Tick(at, (facts,))).effects[0].order
            store.execute(
                "accepted",
                a.OrderUpdate(
                    ACCOUNT,
                    order.order_id,
                    at + timedelta(seconds=1),
                    "accepted",
                    "WORKING",
                    at + timedelta(seconds=1),
                ),
            )
            store.execute(
                "fill",
                h.Fill(
                    "held-fill",
                    order.order_id,
                    ACCOUNT,
                    order.contract,
                    at + timedelta(seconds=2),
                    at + timedelta(seconds=3),
                    order.price,
                    D(3),
                    1,
                ),
            )
        store.close()
    return settings, snapshot


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def test_disabled_creates_no_files_and_never_calls_driver(tmp_path):
    settings, snapshot = setup(tmp_path, enabled=False, journal=False)
    market = FakeMarket()
    calls = []
    host = Supervisor(
        settings,
        ("JM", "RB"),
        market,
        lambda *_: calls.append(1) or FakeDriver(snapshot),
        clock=Clock().now,
    )
    assert host.run(max_cycles=1) == "DISABLED"
    assert not settings.state_root.exists()
    assert calls == []


def test_observe_never_mutates_existing_account_or_invokes_adapter(tmp_path):
    settings, snapshot = setup(tmp_path)
    path = settings.state_root / ACCOUNT / "account.sqlite"
    before = digest(path)
    market = FakeMarket()
    driver = FakeDriver(snapshot)
    clock = Clock()
    host = Supervisor(
        settings,
        ("JM", "RB"),
        market,
        lambda *_: driver,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert host.run(max_cycles=1) == "STOPPED"
    assert digest(path) == before
    assert driver.connects == 1 and driver.observations == 1
    assert driver.closed and market.closed


@pytest.mark.parametrize('mode, expected_connections', [('observe', 1), ('manage', 0), ('trade', 0)])
def test_explicit_closed_account_readback_is_observe_only(tmp_path, mode, expected_connections):
    from contextlib import closing
    from guiyi_quant.simnow_execution.evidence import Evidence
    settings, snapshot = setup(tmp_path, mode=mode)
    with closing(Evidence(settings.state_root / ACCOUNT / 'native-evidence.sqlite', ACCOUNT)) as evidence:
        evidence.append(snapshot)
    path = settings.state_root / ACCOUNT / 'account.sqlite'
    before = digest(path)
    market = FakeMarket(connect_allowed=False, active=False)
    market.closed_observation_allowed = lambda _: True
    driver = FakeDriver(snapshot)
    clock = Clock()
    host = Supervisor(settings, ('JM', 'RB'), market, lambda *_: driver,
        clock=clock.now, sleep=clock.sleep)
    codes = []
    status = host.status
    def record(code, **kwargs):
        codes.append(code)
        return status(code, **kwargs)
    host.status = record
    host.run(max_cycles=1)
    assert driver.connects == expected_connections
    assert driver.observations == 0  # No execution-input polling while fully CLOSED.
    assert digest(path) == before
    if mode == 'observe':
        assert 'OBSERVING_CLOSED' in codes


def test_closed_observation_does_not_consume_or_block_next_trading_day(tmp_path):
    from contextlib import closing
    from guiyi_quant.simnow_execution.evidence import Evidence
    from dataclasses import replace
    settings, snapshot = setup(tmp_path)
    path = settings.state_root / ACCOUNT / 'native-evidence.sqlite'
    with closing(Evidence(path, ACCOUNT)) as evidence:
        evidence.append(snapshot)
    market = FakeMarket(connect_allowed=False, day=date(2026, 10, 28), active=False)
    market.closed_observation_allowed = lambda _: True
    drivers = []
    def factory(*_):
        drivers.append(FakeDriver(snapshot))
        return drivers[-1]
    host = Supervisor(settings, ('JM', 'RB'), market, factory, clock=Clock().now)
    host.run(max_cycles=1)
    assert not drivers  # Last proven native day is still the previous one.
    box = SignalInbox(settings.state_root / ACCOUNT / 'signals.sqlite', ACCOUNT, ('JM', 'RB'))
    assert box.conn.execute('SELECT * FROM attempts').fetchall() == []
    assert not box.blocked('20261028')
    box.close()
    snapshot = replace(snapshot, trading_day='20261028',
        source_id='ctp-inventory:20261028:' + 'c' * 64,
        started_at=snapshot.at + timedelta(seconds=1), at=snapshot.at + timedelta(seconds=2))
    market.active = market.connect_allowed = True
    market.closed_observation_allowed = lambda _: False
    resumed = Supervisor(settings, ('JM', 'RB'), market, factory, clock=Clock().now)
    resumed.run(max_cycles=1)
    assert len(drivers) == 1 and drivers[0].observations == 1


def test_account_product_scope_mismatch_blocks_before_observation(tmp_path):
    settings, snapshot = setup(tmp_path)
    path = settings.state_root / ACCOUNT / "account.sqlite"
    before = digest(path)
    driver = FakeDriver(snapshot)
    host = Supervisor(
        settings, ("RB",), FakeMarket(), lambda *_: driver, clock=Clock().now
    )
    assert host.run(max_cycles=1) == "STOPPED"
    assert digest(path) == before
    assert driver.observations == 0
    status = (settings.state_root / ACCOUNT / "continuous.json").read_text()
    assert (
        "CONTINUOUS_ACCOUNT_SCOPE_MISMATCH" in status or host.blocked_day == "20261027"
    )


def test_account_lock_excludes_old_host_lock(tmp_path):
    settings, _ = setup(tmp_path, journal=False)
    folder = settings.state_root / ACCOUNT
    folder.mkdir(parents=True, mode=0o700)
    settings.state_root.chmod(0o700)
    fd = os.open(folder / "host.lock", os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="ACCOUNT_HOST_ALREADY_RUNNING"):
            with account_lock(settings):
                pytest.fail("second account writer entered")
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "day,connect_allowed,expected",
    [
        (None, False, 0),
        (date(2026, 10, 27), False, 0),
        (date(2026, 10, 27), True, 1),
    ],
)
def test_session_plan_controls_new_connection(tmp_path, day, connect_allowed, expected):
    settings, snapshot = setup(tmp_path)
    market = FakeMarket(connect_allowed, day)
    drivers = []

    def factory(*_):
        driver = FakeDriver(snapshot)
        drivers.append(driver)
        return driver

    host = Supervisor(settings, ("JM", "RB"), market, factory, clock=Clock().now)
    assert host.run(max_cycles=1) == "STOPPED"
    assert len(drivers) == expected


def test_preopen_connection_does_not_accept_a_queued_signal(tmp_path):
    settings, snapshot = setup(tmp_path)
    trigger = Signal(
        "preopen",
        "RB",
        "RB2701",
        T + timedelta(minutes=60),
        T + timedelta(minutes=60, seconds=2),
        None,
        ("buy",),
        "b" * 64,
    )
    market = FakeMarket(connect_allowed=True, active=False, signals=(trigger,))
    host = Supervisor(
        settings,
        ("JM", "RB"),
        market,
        lambda *_: FakeDriver(snapshot),
        clock=Clock().now,
    )
    assert host.run(max_cycles=1) == "STOPPED"
    path = settings.state_root / ACCOUNT / "signals.sqlite"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM signals").fetchone() == (0,)


def test_lunch_break_keeps_connection_and_records_fresh_completed_signal(tmp_path):
    settings, snapshot = setup(tmp_path)
    market = FakeMarket()
    driver = FakeDriver(snapshot)
    clock = Clock()
    trigger = Signal(
        "lunch",
        "RB",
        "RB2701",
        T + timedelta(minutes=60),
        T + timedelta(minutes=60, seconds=2),
        None,
        ("buy",),
        "c" * 64,
    )

    def advance(seconds):
        clock.sleep(seconds)
        market.active = False
        market.connect_allowed = False
        market.signals = (trigger,)

    host = Supervisor(
        settings,
        ("JM", "RB"),
        market,
        lambda *_: driver,
        clock=clock.now,
        sleep=advance,
    )
    assert host.run(max_cycles=2) == "STOPPED"
    assert driver.connects == 1
    path = settings.state_root / ACCOUNT / "signals.sqlite"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT source,status FROM signals").fetchall() == [
            ("lunch", "OBSERVED")
        ]


def test_trading_day_change_disconnects_without_resetting_account(tmp_path):
    settings, snapshot = setup(tmp_path)
    path = settings.state_root / ACCOUNT / "account.sqlite"
    before = digest(path)
    market = FakeMarket()
    drivers = []
    clock = Clock()

    def factory(*_):
        driver = FakeDriver(snapshot)
        drivers.append(driver)
        return driver

    def advance(seconds):
        clock.sleep(seconds)
        market.day = date(2026, 10, 28)

    host = Supervisor(
        settings, ("JM", "RB"), market, factory, clock=clock.now, sleep=advance
    )
    assert host.run(max_cycles=2) == "STOPPED"
    assert drivers[0].closed and len(drivers) == 2
    # The second native snapshot is still the old day, so recovery fails closed.
    assert digest(path) == before


def test_initial_changed_snapshot_waits_on_same_login_then_prepares(tmp_path):
    settings, snapshot = setup(tmp_path)
    market = FakeMarket()
    driver = FakeDriver(snapshot, snapshot_failures=(1,))
    clock = Clock()
    host = Supervisor(
        settings,
        ("JM", "RB"),
        market,
        lambda *_: driver,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert host.run(max_cycles=2) == "STOPPED"
    assert driver.connects == 1 and driver.observations == 1
    with sqlite3.connect(
        settings.state_root / ACCOUNT / "signals.sqlite"
    ) as connection:
        assert connection.execute(
            "SELECT count FROM attempts WHERE day='20261027'"
        ).fetchone() == (1,)


def test_later_changed_snapshot_keeps_prepared_connection_without_flat_fallback(
    tmp_path,
):
    settings, snapshot = setup(tmp_path)
    path = settings.state_root / ACCOUNT / "account.sqlite"
    before = digest(path)
    driver = FakeDriver(snapshot, snapshot_failures=(3,))
    clock = Clock()
    host = Supervisor(
        settings,
        ("JM", "RB"),
        FakeMarket(),
        lambda *_: driver,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert host.run(max_cycles=3) == "STOPPED"
    assert driver.connects == 1 and driver.observations == 2
    assert digest(path) == before
    with sqlite3.connect(
        settings.state_root / ACCOUNT / "signals.sqlite"
    ) as connection:
        assert connection.execute(
            "SELECT count FROM attempts WHERE day='20261027'"
        ).fetchone() == (1,)


def test_unknown_calendar_day_while_connected_does_not_poll_or_touch_host(tmp_path):
    settings, snapshot = setup(tmp_path)
    path = settings.state_root / ACCOUNT / "account.sqlite"
    before = digest(path)
    market = FakeMarket()
    driver = FakeDriver(snapshot)
    clock = Clock()

    def calendar_lost(seconds):
        clock.sleep(seconds)
        market.day = None

    host = Supervisor(
        settings,
        ("JM", "RB"),
        market,
        lambda *_: driver,
        clock=clock.now,
        sleep=calendar_lost,
    )
    assert host.run(max_cycles=2) == "STOPPED"
    assert market.polls == 1 and driver.observations == 1
    assert driver.connects == 1 and driver.snapshots == 2
    assert digest(path) == before


def test_held_position_survives_unproven_day_change_without_initialize(tmp_path):
    settings, snapshot = setup(tmp_path, held=True)
    path = settings.state_root / ACCOUNT / "account.sqlite"
    assert len(a.LocalStore.inspect(path).positions) == 1
    before = digest(path)
    # Native snapshot is deliberately flat/old-day, so neither day can be
    # reconciled. This must leave the existing held-position journal intact.
    first = Supervisor(
        settings,
        ("JM", "RB"),
        FakeMarket(),
        lambda *_: FakeDriver(snapshot),
        clock=Clock().now,
    )
    assert first.run(max_cycles=1) == "STOPPED"
    second = Supervisor(
        settings,
        ("JM", "RB"),
        FakeMarket(day=date(2026, 10, 28)),
        lambda *_: FakeDriver(snapshot),
        clock=Clock().now,
    )
    assert second.run(max_cycles=1) == "STOPPED"
    assert digest(path) == before
    assert len(a.LocalStore.inspect(path).positions) == 1


def test_transport_retry_budget_is_durable_across_runs(tmp_path):
    settings, snapshot = setup(tmp_path, journal=False)
    market = FakeMarket()
    drivers = []
    clock = Clock()

    def factory(*_):
        driver = FakeDriver(
            snapshot, fail=ValueError("NATIVE_TRANSPORT_FAILED"), transport_failed=True
        )
        drivers.append(driver)
        return driver

    host = Supervisor(
        settings, ("JM", "RB"), market, factory, clock=clock.now, sleep=clock.sleep
    )
    assert host.run(max_cycles=4) == "STOPPED"
    assert len(drivers) == 3
    second = Supervisor(settings, ("JM", "RB"), FakeMarket(), factory, clock=clock.now)
    assert second.run(max_cycles=1) == "STOPPED"
    assert len(drivers) == 3


def test_failure_record_write_fault_blocks_reconnect_and_still_closes_driver(
    tmp_path, monkeypatch
):
    import guiyi_quant.simnow_execution.supervisor as module

    settings, snapshot = setup(tmp_path, journal=False)
    drivers = []
    clock = Clock()

    def factory(*_):
        driver = FakeDriver(
            snapshot, fail=ValueError("NATIVE_TRANSPORT_FAILED"), transport_failed=True
        )
        drivers.append(driver)
        return driver

    def fail_record(*_):
        raise OSError("fixture disk unavailable")

    monkeypatch.setattr(module, "retain_failure", fail_record)
    host = Supervisor(
        settings,
        ("JM", "RB"),
        FakeMarket(),
        factory,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert host.run(max_cycles=3) == "STOPPED"
    assert len(drivers) == 1 and drivers[0].closed
    again = Supervisor(settings, ("JM", "RB"), FakeMarket(), factory, clock=clock.now)
    assert again.run(max_cycles=1) == "STOPPED"
    assert len(drivers) == 1


def test_unknown_error_blocks_same_day_without_retry(tmp_path):
    settings, snapshot = setup(tmp_path, journal=False)
    drivers = []
    clock = Clock()

    def factory(*_):
        # A transport flag alone cannot classify an arbitrary native exception.
        driver = FakeDriver(
            snapshot,
            fail=RuntimeError("private native diagnostic"),
            transport_failed=True,
        )
        drivers.append(driver)
        return driver

    host = Supervisor(
        settings,
        ("JM", "RB"),
        FakeMarket(),
        factory,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert host.run(max_cycles=3) == "STOPPED"
    assert len(drivers) == 1
    again = Supervisor(settings, ("JM", "RB"), FakeMarket(), factory, clock=clock.now)
    assert again.run(max_cycles=1) == "STOPPED"
    assert len(drivers) == 1
    box = SignalInbox(
        settings.state_root / ACCOUNT / "signals.sqlite", ACCOUNT, ("JM", "RB")
    )
    assert box.blocked("20261027")
    box.close()


def test_transport_cleanup_failure_persists_block_across_runs(tmp_path):
    settings, snapshot = setup(tmp_path, journal=False)
    drivers = []
    clock = Clock()

    def factory(*_):
        driver = FakeDriver(
            snapshot,
            fail=ValueError("NATIVE_TRANSPORT_FAILED"),
            transport_failed=True,
            close_fail=True,
        )
        drivers.append(driver)
        return driver

    host = Supervisor(settings, ("JM", "RB"), FakeMarket(), factory, clock=clock.now)
    with pytest.raises(ValueError, match="CONTINUOUS_CLEANUP_UNCERTAIN"):
        host.run(max_cycles=1)
    assert drivers[0].closed
    box = SignalInbox(
        settings.state_root / ACCOUNT / "signals.sqlite", ACCOUNT, ("JM", "RB")
    )
    assert box.blocked("20261027")
    box.close()
    resumed = Supervisor(settings, ("JM", "RB"), FakeMarket(), factory, clock=clock.now)
    assert resumed.run(max_cycles=1) == "STOPPED"
    assert len(drivers) == 1


def test_restart_drops_uncommitted_old_signal_without_account_mutation(tmp_path):
    settings, snapshot = setup(tmp_path)
    folder = settings.state_root / ACCOUNT
    account_path = folder / "account.sqlite"
    before = digest(account_path)
    inbox = SignalInbox(folder / "signals.sqlite", ACCOUNT, ("JM", "RB"))
    inbox.enqueue(
        Signal(
            "old-source",
            "RB",
            "RB2701",
            T - timedelta(hours=1),
            T - timedelta(hours=1) + timedelta(seconds=2),
            None,
            ("buy",),
            "b" * 64,
        )
    )
    inbox.close()
    driver = FakeDriver(snapshot)
    host = Supervisor(
        settings, ("JM", "RB"), FakeMarket(), lambda *_: driver, clock=Clock().now
    )
    assert host.run(max_cycles=1) == "STOPPED"
    assert digest(account_path) == before
    inbox = SignalInbox(folder / "signals.sqlite", ACCOUNT, ("JM", "RB"))
    assert inbox.pending() == ()
    inbox.close()


def test_same_account_cannot_run_from_two_different_roots(tmp_path):
    first = SimpleNamespace(state_root=tmp_path / "first", account_id=ACCOUNT)
    second = SimpleNamespace(state_root=tmp_path / "second", account_id=ACCOUNT)
    with account_lock(first):
        with pytest.raises(ValueError, match="ACCOUNT_HOST_ALREADY_RUNNING"):
            with account_lock(second):
                pytest.fail("second account writer acquired")
    with account_lock(second):
        pass


@pytest.mark.parametrize(
    "code,pending,expected",
    [
        ("TRADING", False, True),
        ("TRADING", True, False),
        ("READBACK_NOT_STABLE", False, False),
        ("ACCOUNT_RECONCILIATION_REQUIRED", False, False),
    ],
)
def test_opening_status_requires_current_trade_cycle_and_no_unreconciled_order(
    tmp_path, code, pending, expected
):
    import json

    settings, _ = setup(tmp_path, mode="trade")
    host = Supervisor(
        settings, ("JM", "RB"), FakeMarket(), lambda *_: None, clock=Clock().now
    )
    host.folder = settings.state_root / ACCOUNT
    host.latest_source = host.ledger_hash = None
    host.monitor = SimpleNamespace(publish=lambda *_args, **_kwargs: True)
    host.prepared = host.session_active = True
    host.day = "20261027"
    state = a.LocalStore.inspect(host.folder / "account.sqlite")
    from dataclasses import replace

    state = replace(
        state, readback=replace(state.readback, valid_until=T + timedelta(hours=3))
    )
    state = SimpleNamespace(
        **{
            **vars(state),
            "orders": (SimpleNamespace(reconciled=False),) if pending else (),
        }
    )
    host.store = SimpleNamespace(current=lambda: state)
    host.host = SimpleNamespace(pending=(), adapter=SimpleNamespace(_faulted=False))
    host.status(code, connected=True)
    assert (
        json.loads((host.folder / "continuous.json").read_text())["opening_enabled"]
        is expected
    )


def test_observe_status_retains_timestamped_diagnostic_after_disconnect(tmp_path):
    import json

    settings, _ = setup(tmp_path)
    host = Supervisor(settings, ('JM', 'RB'), FakeMarket(), lambda *_: None, clock=Clock().now)
    host.folder = settings.state_root / ACCOUNT
    host.latest_source = host.ledger_hash = None
    host.monitor = SimpleNamespace(publish=lambda *_args, **_kwargs: True)
    detail = {'JM': {'at': T.isoformat(), 'stage': 'NATIVE_BOOK', 'code': 'NATIVE_BOOK_STALE'}}
    host.driver = SimpleNamespace(input_diagnostics=detail)
    host.status('OBSERVING', connected=True)
    host.driver = None
    host.status('RECOVERY_BLOCKED')
    result = json.loads((host.folder / 'continuous.json').read_text())
    assert result['input_diagnostics'] == detail
    assert result['connection'] == 'UNKNOWN'
    assert result['opening_enabled'] is False
    assert result['auto_order'] is False
