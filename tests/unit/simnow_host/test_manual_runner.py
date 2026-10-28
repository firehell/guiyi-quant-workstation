"""Manual runner control fences with no native login or Keychain access."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
import importlib.util
import json

import pytest

from guiyi_quant.simnow_execution.inbox import SignalInbox
from guiyi_quant.simnow_execution.manual_host import acceptance


ROOT = Path(__file__).parents[3]
SPEC = importlib.util.spec_from_file_location(
    "isolated_manual_runner", ROOT / "scripts/broker/simnow_manual_roundtrip.py"
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

ACCOUNT = "a" * 64
TEST_ID = "manual:97039e1c-850a-44af-9ab1-60af6c561ac4"


class Market:
    def __init__(self, *, active=True, tradable=True):
        self.active = active
        self.tradable = tradable
        self.closed = False
        self.authority_calls = 0

    def plan(self, now):
        return NS(active=self.active, trading_day=now.date() if self.active else None)

    def authority(self, product, day, now, contract=None):
        self.authority_calls += 1
        return NS(
            product="RB",
            owner="RB2701",
            contract="RB2701",
            exchange="SHFE",
            trading_day=day,
            source_id="authority-fixture",
            contiguous_session_end=now + timedelta(hours=2) if self.tradable else None,
            session=NS(
                can_trade=self.tradable,
                at=now - timedelta(seconds=1),
                valid_until=now + timedelta(seconds=15),
            ),
        )

    def close(self):
        self.closed = True


class Monitor:
    def __init__(self, *args):
        self.events = []

    def publish(self, status, *args, **kwargs):
        self.events.append(status)


def isolated(monkeypatch, tmp_path, market):
    from app import simnow_portfolio_market
    from guiyi_quant.simnow_execution import monitor, supervisor

    folder = tmp_path / ACCOUNT
    folder.mkdir(mode=0o700)
    settings = NS(state_root=tmp_path, account_id=ACCOUNT)

    @contextmanager
    def lock(_settings):
        yield folder

    monkeypatch.setattr(
        simnow_portfolio_market, "PortfolioMarket", lambda products: market
    )
    monkeypatch.setattr(monitor, "MonitorPublisher", Monitor)
    monkeypatch.setattr(supervisor, "account_lock", lock)
    return settings, folder


@pytest.mark.parametrize("active,tradable", [(False, False), (True, False)])
def test_nonactive_or_lunch_blocks_before_login_claim_and_native_driver(
    monkeypatch, tmp_path, active, tradable
):
    from guiyi_quant.simnow_execution import native_portfolio

    market = Market(active=active, tradable=tradable)
    settings, folder = isolated(monkeypatch, tmp_path, market)
    created = []
    monkeypatch.setattr(
        native_portfolio, "NativePortfolio", lambda *_args, **_kwargs: created.append(1)
    )
    assert runner.run(settings, None, None, TEST_ID) == 2
    assert created == [] and market.closed
    assert not list(folder.glob("*-login.json"))
    status = json.loads(next(folder.glob("*-status.json")).read_text())
    assert status["stage"] == "SESSION_ADMISSION" and status["passed"] is False


def test_invalid_manual_id_rejected_before_status_or_lock_write(tmp_path):
    settings = NS(state_root=tmp_path, account_id=ACCOUNT)
    before = tuple(tmp_path.iterdir())
    with pytest.raises(ValueError, match="MANUAL_TEST_ID_INVALID"):
        runner.run(settings, None, None, "manual:../bad")
    assert tuple(tmp_path.iterdir()) == before


def test_login_claim_is_single_use_without_spending_observer_attempts(
    monkeypatch, tmp_path
):
    from guiyi_quant import htdy_account_execution as a
    from guiyi_quant.simnow_execution import native_portfolio

    market = Market()
    settings, folder = isolated(monkeypatch, tmp_path, market)
    inbox = SignalInbox(folder / "signals.sqlite", ACCOUNT, ("RB",))
    day = datetime.now(UTC).strftime("%Y%m%d")
    assert inbox.attempt(day) == 1 and inbox.attempt(day) == 2
    inbox.close()
    initial = NS(audit=(), positions=(), orders=(), reservations=())
    monkeypatch.setattr(a.LocalStore, "inspect", staticmethod(lambda _: initial))
    created = []

    class NoNetworkDriver:
        def __init__(self, *args, **kwargs):
            created.append(1)

        def connect(self):
            raise ValueError("NATIVE_LOGIN_BLOCKED_FIXTURE")

        def close(self):
            pass

        def failure_diagnostics(self):
            return {"stage": "FIXTURE"}

    monkeypatch.setattr(native_portfolio, "NativePortfolio", NoNetworkDriver)
    assert runner.run(settings, None, None, TEST_ID) == 2
    assert runner.run(settings, None, None, TEST_ID) == 2
    assert len(created) == 1
    claim = json.loads(next(folder.glob("*-login.json")).read_text())
    assert claim["connections"] == claim["max_connections"] == 1
    inbox = SignalInbox(folder / "signals.sqlite", ACCOUNT, ("RB",))
    assert inbox.attempt(day) == 3
    inbox.close()


def test_financial_dry_failure_precedes_settlement_and_ledger_open(
    monkeypatch, tmp_path
):
    from guiyi_quant import htdy_account_execution as a
    from guiyi_quant.simnow_execution import native_portfolio, supervisor, inventory

    market = Market()
    settings, folder = isolated(monkeypatch, tmp_path, market)
    initial = NS(audit=(), positions=(), orders=(), reservations=())
    created_store = []

    class LocalStore:
        @staticmethod
        def inspect(path):
            return initial

        def __init__(self, path):
            created_store.append(path)

    monkeypatch.setattr(a, "LocalStore", LocalStore)
    monkeypatch.setattr(supervisor, "verify_recovery_ownership", lambda *_: None)
    monkeypatch.setattr(inventory, "project_readback", lambda *_: (object(), ()))
    monkeypatch.setattr(a, "Recover", lambda *_: object())
    monkeypatch.setattr(a, "ManualTickV1", lambda *_: object())
    calls = []

    def dry_apply(state, key, command):
        calls.append(key)
        return NS(state=state, effects=())

    monkeypatch.setattr(a, "apply", dry_apply)
    driver_state = {"adapter_calls": 0, "closed": False}

    class Driver:
        def __init__(self, *args, **kwargs):
            self.read_journal = None

        def connect(self):
            pass

        def snapshot(self):
            now = datetime.now(UTC)
            return NS(
                account_id=ACCOUNT,
                trading_day=now.strftime("%Y%m%d"),
                source_id="native-flat",
                at=now,
            )

        def facts(self, *args):
            return NS(canonical="RB2701"), object()

        def adapter(self, *args):
            driver_state["adapter_calls"] += 1
            raise AssertionError("settlement adapter must not be opened")

        def close(self):
            driver_state["closed"] = True

        def failure_diagnostics(self):
            return {"stage": "FIXTURE"}

    monkeypatch.setattr(native_portfolio, "NativePortfolio", Driver)
    assert runner.run(settings, None, None, TEST_ID) == 2
    assert calls[-1] == TEST_ID + ":dry-tick"
    assert created_store == [] and driver_state == {"adapter_calls": 0, "closed": True}
    status = json.loads(next(folder.glob("*-status.json")).read_text())
    assert status["stage"] == "NATIVE_ACCOUNT_PREFLIGHT" and status["passed"] is False


def test_stale_quote_after_hold_due_keeps_close_obligation_and_no_pass(
    monkeypatch, tmp_path
):
    from guiyi_quant import htdy_account_execution as a
    from guiyi_quant.htdy_account_execution import codec
    from guiyi_quant.simnow_execution import (
        evidence,
        host as host_module,
        inventory,
        journal,
        manual_host,
        native_portfolio,
        supervisor,
    )

    started = datetime(2026, 10, 27, 6, tzinfo=UTC)

    class ClockDateTime:
        current = started

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(runner, "datetime", ClockDateTime)
    monkeypatch.setattr(
        runner.time,
        "sleep",
        lambda _seconds: setattr(
            ClockDateTime, "current", started + timedelta(seconds=601)
        ),
    )
    market = Market()
    settings, folder = isolated(monkeypatch, tmp_path, market)
    initial = NS(audit=(), positions=(), orders=(), reservations=())
    held = NS(
        positions=(NS(product="RB", quantity=1),),
        orders=(),
        reservations=(),
        phase="READY",
        readback_valid=True,
        audit=(),
    )
    store_holder = {}

    class LocalStore:
        @staticmethod
        def inspect(path):
            return initial

        def __init__(self, path):
            store_holder["store"] = self

        def current(self):
            return held

        def execute(self, *args):
            if isinstance(args[1], a.ManualBeginV1):
                held.audit = (NS(command=args[1]),)
            return NS()

        def close(self):
            pass

    monkeypatch.setattr(a, "LocalStore", LocalStore)
    monkeypatch.setattr(a, "Recover", lambda *_: object())
    monkeypatch.setattr(a, "ManualTickV1", lambda *_: object())
    monkeypatch.setattr(
        a,
        "apply",
        lambda state, key, cmd: NS(
            state=state,
            effects=(NS(order=NS(offset="OPEN")),) if key.endswith(":dry-tick") else (),
        ),
    )
    monkeypatch.setattr(codec, "digest", lambda *_: "synthetic-state-hash")
    monkeypatch.setattr(supervisor, "verify_recovery_ownership", lambda *_: None)
    monkeypatch.setattr(inventory, "project_readback", lambda *_: (object(), ()))

    class Resource:
        def __init__(self, *args):
            pass

        def close(self):
            pass

    monkeypatch.setattr(journal, "Journal", Resource)
    monkeypatch.setattr(evidence, "Evidence", Resource)
    observations = {"facts": 0, "reconciles": 0, "manual_effects": 0, "closed": False}

    class Driver:
        transport_failed = False
        read_journal = None
        report = object()
        last_facts = {}

        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            pass

        def snapshot(self):
            return NS(
                account_id=ACCOUNT,
                trading_day="20261027",
                at=ClockDateTime.current,
                source_id="native-held",
            )

        def facts(self, *args):
            observations["facts"] += 1
            if observations["facts"] == 2:
                raise ValueError("NATIVE_BOOK_STALE")
            return NS(canonical="RB2701"), object()

        def adapter(self, *args):
            return object()

        def close(self):
            observations["closed"] = True

        def failure_diagnostics(self):
            return {"stage": "FIXTURE"}

    class Host:
        pending = ()
        needs_recovery = False

        def __init__(self, *args, **kwargs):
            self.adapter = NS(expire_unacknowledged=lambda *_: None, drain=lambda: ())

        def reconcile(self, *args):
            observations["reconciles"] += 1

    monkeypatch.setattr(native_portfolio, "NativePortfolio", Driver)
    monkeypatch.setattr(host_module, "Host", Host)
    monkeypatch.setattr(
        manual_host,
        "manual_effects",
        lambda *_: observations.__setitem__(
            "manual_effects", observations["manual_effects"] + 1
        ),
    )
    monkeypatch.setattr(
        a,
        "manual_status",
        lambda *_: NS(
            due_at=started + timedelta(seconds=600),
            phase="CLOSE_DUE" if observations["facts"] >= 2 else "HOLDING",
            terminal=observations["facts"] >= 2,
        ),
    )
    monkeypatch.setattr(
        manual_host,
        "acceptance",
        lambda *_args, **_kwargs: {
            "broker_roundtrip_passed": False,
            "native_flat_observed": False,
        },
    )
    assert runner.run(settings, None, None, TEST_ID) == 2
    assert observations["facts"] == 2  # preflight, then stale at close due
    assert observations["manual_effects"] == 0
    assert observations["closed"] and store_holder["store"].current().positions
    status = json.loads(next(folder.glob("*-status.json")).read_text())
    assert status["broker_roundtrip_passed"] is False
    assert status["native_flat_observed"] is False


def test_stale_book_still_drives_pending_open_deadline_cancel(monkeypatch, tmp_path):
    from guiyi_quant import htdy_account_execution as a
    from guiyi_quant.htdy_account_execution import codec
    from guiyi_quant.simnow_execution import (
        evidence,
        host as host_module,
        inventory,
        journal,
        manual_host,
        native_portfolio,
        supervisor,
    )

    started = datetime(2026, 10, 27, 6, tzinfo=UTC)
    current = [started]

    @dataclass(frozen=True)
    class CachedFact:
        instrument: object
        session: object
        quote: object | None

    cached = CachedFact(
        NS(contract="RB2701", valid_until=started + timedelta(minutes=5)),
        object(),
        object(),
    )
    seen = []

    class FreshMarket(Market):
        def authority(self, *args):
            result = super().authority(*args)
            self.latest_session = result.session
            return result

    market = FreshMarket()
    settings, folder = isolated(monkeypatch, tmp_path, market)
    initial = NS(audit=(), positions=(), orders=(), reservations=())
    pending_open = NS(signal_id=TEST_ID, offset="OPEN", reconciled=False)
    state = NS(audit=(), orders=(), positions=(), reservations=())

    class LocalStore:
        @staticmethod
        def inspect(_path):
            return initial

        def __init__(self, _path):
            pass

        def current(self):
            return state

        def execute(self, _key, command):
            if isinstance(command, a.ManualBeginV1):
                state.audit = (NS(command=command),)
            return NS()

        def close(self):
            pass

    class Resource:
        def __init__(self, *args):
            pass

        def close(self):
            pass

    class Driver:
        transport_failed = False
        read_journal = None
        report = object()
        last_facts = {"RB2701": cached}

        def __init__(self, *args, **kwargs):
            self.fact_calls = 0

        def connect(self):
            pass

        def snapshot(self):
            return NS(
                account_id=ACCOUNT,
                trading_day="20261027",
                at=current[0],
                source_id="native-open-pending",
            )

        def facts(self, *_args):
            self.fact_calls += 1
            if self.fact_calls > 2:
                raise ValueError("NATIVE_BOOK_STALE")
            return NS(canonical="RB2701"), cached

        def binding(self, *_args):
            return (NS(canonical="RB2701"),)

        def adapter(self, *_args):
            return object()

        def close(self):
            pass

        def failure_diagnostics(self):
            return {"stage": "FIXTURE"}

    class Host:
        pending = ()
        needs_recovery = False

        def __init__(self, *_args, **_kwargs):
            self.adapter = NS(expire_unacknowledged=lambda *_: None, drain=lambda: ())

        def reconcile(self, *_args):
            pass

    def manual_effects(_host, facts, _bindings, at, _test_id):
        seen.append((at, facts[0]))
        if not state.orders:
            state.orders = (pending_open,)
            return ("SEND_OUTCOME_UNKNOWN",)
        if at >= started + timedelta(seconds=180):
            pending_open.reconciled = True
        return ()

    monkeypatch.setattr(a, "LocalStore", LocalStore)
    monkeypatch.setattr(a, "Recover", lambda *_: object())
    monkeypatch.setattr(a, "ManualTickV1", lambda *_: object())
    monkeypatch.setattr(
        a,
        "apply",
        lambda state_, key, cmd: NS(
            state=state_,
            effects=(NS(order=NS(offset="OPEN")),) if key.endswith(":dry-tick") else (),
        ),
    )
    monkeypatch.setattr(
        a,
        "manual_status",
        lambda *_: NS(
            due_at=None,
            phase="OPEN_NO_FILL" if pending_open.reconciled else "OPEN_PENDING",
            terminal=pending_open.reconciled,
        ),
    )
    monkeypatch.setattr(codec, "digest", lambda *_: "synthetic-state-hash")
    monkeypatch.setattr(supervisor, "verify_recovery_ownership", lambda *_: None)
    monkeypatch.setattr(inventory, "project_readback", lambda *_: (object(), ()))
    monkeypatch.setattr(journal, "Journal", Resource)
    monkeypatch.setattr(evidence, "Evidence", Resource)
    monkeypatch.setattr(native_portfolio, "NativePortfolio", Driver)
    monkeypatch.setattr(host_module, "Host", Host)
    monkeypatch.setattr(manual_host, "manual_effects", manual_effects)
    monkeypatch.setattr(
        manual_host,
        "acceptance",
        lambda *_args, **_kwargs: {
            "broker_roundtrip_passed": False,
            "native_flat_observed": True,
        },
    )

    def advance(_seconds):
        current[0] = started + timedelta(seconds=180)

    assert (
        runner.run(
            settings, None, None, TEST_ID, clock=lambda: current[0], sleep=advance
        )
        == 2
    )
    assert len(seen) == 2  # one opening call, one cancellation call
    assert seen[1][0] == started + timedelta(seconds=180)
    assert seen[1][1].quote is None
    assert seen[1][1].instrument is cached.instrument
    assert seen[1][1].session is market.latest_session
    assert pending_open.reconciled
    status = json.loads(next(folder.glob("*-status.json")).read_text())
    assert status["broker_roundtrip_passed"] is False


def test_terminal_flat_native_sample_cannot_replace_missing_fill_proof(monkeypatch):
    from guiyi_quant import htdy_account_execution as a

    monkeypatch.setattr(
        a,
        "manual_status",
        lambda *_: NS(
            complete=True,
            phase="COMPLETE",
            due_at=datetime.now(UTC) - timedelta(seconds=1),
            confirmed_at=datetime.now(UTC),
            terminal=True,
        ),
    )
    state = NS(
        orders=(),
        fills=(),
        positions=(),
        reservations=(),
        phase="READY",
        readback_valid=True,
        readback=NS(
            source_id="flat-native",
            used_margin=0,
            frozen_margin=0,
            frozen_fee=0,
            snapshot=NS(available=0, balance=0),
        ),
        unresolved_fill_ids=(),
    )
    snapshot = NS(
        source_id="flat-native",
        at=datetime.now(UTC),
        data={
            "positions": [],
            "orders": [],
            "funds": [{"Commission": "0", "Balance": "0"}],
        },
    )
    result = acceptance(state, snapshot, TEST_ID)
    assert result["native_flat_observed"] is True
    assert result["broker_roundtrip_passed"] is False


@pytest.mark.parametrize("release_fails", [False, True])
def test_full_manual_lifecycle_requires_release_after_confirmed_hold(
    monkeypatch, tmp_path, release_fails
):
    """Drive the runner across both broker fills with an advancing isolated clock."""
    from guiyi_quant import htdy_account_execution as a
    from guiyi_quant.htdy_account_execution import codec
    from guiyi_quant.simnow_execution import (
        evidence,
        host as host_module,
        inventory,
        journal,
        manual_host,
        monitor,
        native_portfolio,
        supervisor,
    )

    start = datetime(2026, 10, 27, 6, tzinfo=UTC)
    tick = [start]
    events = []

    def clock():
        return tick[0]

    def sleep(seconds):
        tick[0] += timedelta(seconds=seconds)

    market = Market()
    settings, folder = isolated(monkeypatch, tmp_path, market)
    initial = NS(audit=(), positions=(), orders=(), reservations=())
    order = NS(
        open=False,
        open_filled=False,
        close=False,
        close_filled=False,
        confirmed_at=None,
        close_at=None,
    )

    class LocalStore:
        @staticmethod
        def inspect(_path):
            return initial

        def __init__(self, _path):
            self.audit = ()

        def current(self):
            orders = []
            if order.open:
                orders.append(NS(signal_id=TEST_ID, offset="OPEN"))
            if order.close:
                orders.append(NS(signal_id=TEST_ID, offset="CLOSE"))
            return NS(
                audit=self.audit,
                orders=tuple(orders),
                positions=()
                if order.close_filled or not order.open_filled
                else (NS(product="RB", quantity=1),),
            )

        def execute(self, _key, command):
            if isinstance(command, a.ManualBeginV1):
                self.audit = (NS(command=command),)
            return NS()

        def close(self):
            pass

    class Resource:
        def __init__(self, *args):
            pass

        def latest(self):
            return NS(source_id="native-lifecycle")

        def close(self):
            pass

    published = []

    class CaptureMonitor:
        def __init__(self, *args):
            pass

        def publish(self, status, *args, **kwargs):
            published.append((status, kwargs))

    class Driver:
        transport_failed = False
        read_journal = None
        report = object()

        def __init__(self, *args, **kwargs):
            self.released = False

        def connect(self):
            events.append(("login", clock()))

        def snapshot(self):
            return NS(
                account_id=ACCOUNT,
                trading_day="20261027",
                at=clock(),
                source_id="native-lifecycle",
                data={
                    "positions": []
                    if order.close or not order.open_filled
                    else [{"Position": 1}],
                    "orders": [],
                    "funds": [{"Commission": "0"}],
                },
            )

        def facts(self, *_args):
            return NS(canonical="RB2701"), object()

        def adapter(self, *_args):
            return object()

        def close(self):
            events.append(("release", clock()))
            if release_fails:
                raise RuntimeError("synthetic release failure")
            self.released = True

        def failure_diagnostics(self):
            return {"stage": "FIXTURE"}

    class Adapter:
        def expire_unacknowledged(self, at):
            events.append(("expire", at))

        def drain(self):
            events.append(("drain", clock()))
            return ()

    class Host:
        pending = ()
        needs_recovery = False

        def __init__(self, *_args, **_kwargs):
            self.adapter = Adapter()

        def reconcile(self, *_args):
            if order.open and not order.open_filled:
                # The first readback after an unknown send has no fill proof.
                if not hasattr(self, "open_seen"):
                    self.open_seen = True
                    return
                order.open_filled = True
                order.confirmed_at = clock()
                events.append(("open_confirmed", clock()))
            elif order.close and not order.close_filled:
                order.close_filled = True
                events.append(("close_confirmed", clock()))

    def manual_effects(_host, _facts, _bindings, at, _test_id):
        if not order.open:
            order.open = True
            events.append(("open_sent", at))
            return ("SEND_OUTCOME_UNKNOWN",)
        if (
            order.open_filled
            and not order.close
            and at >= order.confirmed_at + timedelta(seconds=600)
        ):
            order.close = True
            order.close_at = at
            events.append(("close_sent", at))
        return ()

    def manual_status(_state, _test_id):
        if not order.open_filled:
            return NS(due_at=None, phase="OPEN_PENDING", terminal=False)
        due = order.confirmed_at + timedelta(seconds=600)
        if order.close_filled:
            return NS(due_at=due, phase="COMPLETE", terminal=True)
        return NS(
            due_at=due,
            phase="CLOSE_PENDING" if order.close else "HOLDING",
            terminal=False,
        )

    def acceptance(_state, snapshot, _test_id, *, baseline=None):
        flat = not snapshot.data["positions"]
        return {
            "broker_roundtrip_passed": bool(order.close_filled and flat),
            "native_flat_observed": flat,
        }

    monkeypatch.setattr(a, "LocalStore", LocalStore)
    monkeypatch.setattr(a, "Recover", lambda *_: object())
    monkeypatch.setattr(a, "ManualTickV1", lambda *_: object())
    monkeypatch.setattr(
        a,
        "apply",
        lambda state, key, cmd: NS(
            state=state,
            effects=(NS(order=NS(offset="OPEN")),) if key.endswith(":dry-tick") else (),
        ),
    )
    monkeypatch.setattr(a, "manual_status", manual_status)
    monkeypatch.setattr(codec, "digest", lambda *_: "synthetic-state-hash")
    monkeypatch.setattr(supervisor, "verify_recovery_ownership", lambda *_: None)
    monkeypatch.setattr(inventory, "project_readback", lambda *_: (object(), ()))
    monkeypatch.setattr(journal, "Journal", Resource)
    monkeypatch.setattr(evidence, "Evidence", Resource)
    monkeypatch.setattr(monitor, "MonitorPublisher", CaptureMonitor)
    monkeypatch.setattr(native_portfolio, "NativePortfolio", Driver)
    monkeypatch.setattr(host_module, "Host", Host)
    monkeypatch.setattr(manual_host, "manual_effects", manual_effects)
    monkeypatch.setattr(manual_host, "acceptance", acceptance)

    outcome = runner.run(settings, None, None, TEST_ID, clock=clock, sleep=sleep)
    assert outcome == (2 if release_fails else 0), (
        tick[0],
        [n for n, _ in events if n not in ("expire", "drain")],
        events[-8:],
    )
    assert [name for name, _ in events].count("open_sent") == 1
    assert [name for name, _ in events].count("close_sent") == 1
    assert order.close_at >= order.confirmed_at + timedelta(seconds=600)
    names = [name for name, _ in events]
    assert names.index("open_confirmed") < names.index("close_sent")
    assert names.index("close_confirmed") < names.index("release")
    assert "expire" in names and "drain" in names
    status = json.loads(next(folder.glob("*-status.json")).read_text())
    assert status["broker_roundtrip_passed"] is not release_fails
    assert status["native_released"] is not release_fails
    terminal, fields = published[-1]
    assert terminal == ("ERROR" if release_fails else "STOPPED")
    assert fields["connection"] == ("UNKNOWN" if release_fails else "RELEASED")
    assert fields["native_source_id"] == "native-lifecycle"
    assert fields["ledger_hash"] == "synthetic-state-hash"
