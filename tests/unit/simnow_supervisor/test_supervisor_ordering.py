"""Manage cycle ordering with a real local account journal and no broker API."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sqlite3

from guiyi_quant import htdy_account_execution as a, htdy_execution as h
from guiyi_quant.simnow_execution.inbox import SignalInbox
from guiyi_quant.simnow_execution.inventory import read_snapshot
from guiyi_quant.simnow_execution.supervisor import Supervisor


SPEC = importlib.util.spec_from_file_location(
    "ordering_native_fixture",
    Path(__file__).parents[1] / "simnow_host/test_inventory.py",
)
assert SPEC and SPEC.loader
native_fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native_fixture)

ACCOUNT = "a" * 64
T = datetime(2026, 10, 27, 1, tzinfo=UTC)
NOW = T + timedelta(seconds=60)


def readback(at, source):
    return a.Readback(
        h.AccountSnapshot(ACCOUNT, at, Decimal(100000), Decimal(100000)),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        (),
        (),
        source,
        T + timedelta(hours=3),
        True,
    )


class Market:
    issues = {}

    def __init__(self, store):
        self.store = store
        self.events = []
        self.signal = h.Signal(
            "fresh-natural-source",
            "RB",
            "RB2701",
            T + timedelta(seconds=30),
            NOW,
            None,
            ("buy",),
            "b" * 64,
        )

    def plan(self, now):
        return SimpleNamespace(
            trading_day=date(2026, 10, 27),
            connect_allowed=True,
            active=True,
            next_open_at=None,
        )

    def authority(self, product, day, now):
        self.events.append(f"owner:{product}")
        return SimpleNamespace(owner=f"{product}2701", source_id=f"owner:{product}")

    def poll(self, now, after):
        # This is a first-seen receipt after the native readback and Owner facts.
        assert self.store.receipt("native-reconcile:synthetic") is not None
        assert all(p.owner == f"{p.product}2701" for p in self.store.current().products)
        self.events.append("poll")
        return (self.signal,)


class Adapter:
    _faulted = False

    def expire_unacknowledged(self, now):
        return None

    def drain(self):
        return ()


class Host:
    needs_recovery = False

    def __init__(self, store, snapshot, events):
        self.store = store
        self.snapshot = snapshot
        self.events = events
        self.adapter = Adapter()

    def reconcile(self, report, bindings, now, proofs):
        self.events.append("reconcile")
        tx = self.store.execute(
            "native-reconcile:synthetic",
            readback(T + timedelta(seconds=50), "native-flat"),
        )
        return self.snapshot, tx.state

    def tick(self, facts, bindings, now):
        self.events.append("managed-tick")
        tx = self.store.execute("managed-tick", a.ManagedTickV1(now, ()))
        assert tx.effects == ()
        return ()


class Driver:
    def __init__(self, snapshot):
        self.fact = snapshot
        self.report = object()

    def bindings_for(self, state, market, now, day):
        return ()

    def snapshot(self):
        return self.fact

    def execution_for(self, state, market, now, day, issues):
        return (), ()


def test_manage_reconciles_and_updates_owner_before_delivering_real_signal(tmp_path):
    folder = tmp_path / "output/simnow-controlled" / ACCOUNT
    folder.mkdir(parents=True, mode=0o700)
    initial = a.start(ACCOUNT, ("JM", "RB"), T, readback(T, "initial-synthetic"))
    store = a.LocalStore(folder / "account.sqlite", initial)
    inbox = SignalInbox(folder / "signals.sqlite", ACCOUNT, ("JM", "RB"))
    snapshot = read_snapshot(native_fixture.report())
    settings = SimpleNamespace(
        account_id=ACCOUNT, state_root=folder.parent, mode="manage", enabled=True
    )
    market = Market(store)
    supervisor = Supervisor(
        settings, ("JM", "RB"), market, lambda *_: None, clock=lambda: NOW
    )
    fake_host = Host(store, snapshot, market.events)
    supervisor.folder = folder
    supervisor.monitor = SimpleNamespace(publish=lambda *_args, **_kwargs: True)
    supervisor.inbox = inbox
    supervisor.store = store
    supervisor.host = fake_host
    supervisor.driver = Driver(snapshot)
    supervisor.day = "20261027"
    supervisor.prepared = True
    supervisor.active_seen = True
    try:
        supervisor.cycle()
        state = store.current()
        assert market.events == [
            "reconcile",
            "owner:JM",
            "owner:RB",
            "poll",
            "managed-tick",
        ]
        assert state.signals == (market.signal,)
        assert state.signals[0].observed_at == NOW
        assert state.orders == state.positions == state.reservations == ()
        assert store.receipt(inbox.command_key(market.signal)) is not None
        assert inbox.pending() == ()
        with sqlite3.connect(folder / "signals.sqlite") as connection:
            assert connection.execute("SELECT status FROM signals").fetchall() == [
                ("APPLIED",)
            ]
    finally:
        inbox.close()
        store.close()
