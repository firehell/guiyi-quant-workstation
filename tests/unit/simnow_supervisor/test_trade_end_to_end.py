"""No network: durable inbox -> real policy/adapter -> fake native -> monitor."""

from datetime import timedelta, date
from decimal import Decimal as D
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo
from pathlib import Path
import importlib.util
import json
import sqlite3
import pytest
from guiyi_quant import htdy_account_execution as a, htdy_execution as h
from guiyi_quant.simnow_execution import Journal
from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.inbox import SignalInbox
from guiyi_quant.simnow_execution.inventory import read_snapshot
from guiyi_quant.simnow_execution.native_portfolio import NativePortfolio, ReadJournal
from guiyi_quant.simnow_execution.supervisor import Supervisor
from guiyi_quant.simnow_execution.monitor import MonitorReader
from test_native_portfolio import instrument, book, ACCOUNT, USER, T

SPEC = importlib.util.spec_from_file_location(
    "trade_native_report_fixture",
    Path(__file__).parents[1] / "simnow_host/test_inventory.py",
)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)
SH = ZoneInfo("Asia/Shanghai")


class Clock:
    def __init__(self):
        self.at = T + timedelta(minutes=10)

    def now(self):
        return self.at

    def advance(self, seconds):
        self.at += timedelta(seconds=seconds)

    def sleep(self, seconds):
        self.advance(60)


class Market:
    def __init__(self, clock):
        self.clock = clock
        self.issues = {}
        self.seen = set()
        self.started = None

    def plan(self, now):
        return NS(trading_day=date(2026, 10, 27), active=True, connect_allowed=True)

    def activate(self, now):
        self.started = now

    def close(self):
        pass

    def authority(self, product, day, now, contract=None):
        physical = contract or product + "2701"
        return NS(
            owner=product + "2701",
            contract=physical,
            exchange="DCE" if product == "JM" else "SHFE",
            source_id="fixture-owner-" + product,
            session=a.Session(
                physical,
                now,
                now + timedelta(seconds=15),
                "fixture-session",
                T + timedelta(hours=6),
                True,
                True,
            ),
        )

    def recovery(self, state, now):
        return tuple(
            h.RecoveryInput(
                p.product,
                p.owner or p.product + "2701",
                next(
                    (x.quantity for x in state.positions if x.product == p.product), 0
                ),
                p.last_bar or now - timedelta(seconds=1),
                "complete-fixture-" + p.product,
            )
            for p in state.products
        )

    def poll(self, now, after):
        result = []
        for product, minute, direction in [
            ("RB", 60, "buy"),
            ("JM", 60, "buy"),
            ("RB", 120, "sell"),
        ]:
            end = T + timedelta(minutes=minute)
            key = product + str(minute)
            if key in self.seen or end <= self.started or now <= end:
                continue
            self.seen.add(key)
            self.clock.advance(0.001)
            result.append(
                h.Signal(
                    "natural-fixture:" + key,
                    product,
                    product + "2701",
                    end,
                    self.clock.now(),
                    after[product],
                    (direction,),
                    "a" * 64,
                )
            )
        return tuple(result)


class Gateway:
    def __init__(self, clock):
        self.clock = clock
        self.user = USER
        self.password = "fixture"
        self.api = self
        self.front = "tcp://182.254.243.31:30001"
        self.native_session = dict(front_id=1, session_id=2, max_order_ref=10)
        self.failed = False
        self.result = {"status": "READ_ONLY_COMPLETE"}
        self.query_diagnostics = []
        self.orders = []
        self.trades = []
        self.positions = {}
        self.commission = D(0)
        self.closed_profit = D(0)
        self.adapter = None
        self.calls = []
        self.confirmed = False

    def query(self, kind, native=None, **scope):
        self.calls.append(kind)
        product = (native or scope.get("product") or "").upper().removesuffix("2701")
        if kind == "instrument":
            return [instrument(product)]
        if kind == "margin":
            return [
                dict(
                    InstrumentID=native,
                    BrokerID="9999",
                    ExchangeID=scope["exchange"],
                    HedgeFlag="1",
                    IsRelative=0,
                    LongMarginRatioByVolume=0,
                    ShortMarginRatioByVolume=0,
                    LongMarginRatioByMoney=".1",
                    ShortMarginRatioByMoney=".1",
                )
            ]
        if kind == "commission":
            return [
                dict(
                    InstrumentID=native,
                    BrokerID="9999",
                    ExchangeID=scope["exchange"],
                    OpenRatioByMoney="0",
                    OpenRatioByVolume="3",
                )
            ]
        if kind == "book":
            row = book(product)
            row["UpdateTime"] = self.clock.now().astimezone(SH).strftime("%H:%M:%S")
            return [row]
        if kind == "settlement":
            return [{"ConfirmDate": "20261027"}] if self.confirmed else []
        if kind == "confirm":
            self.confirmed = True
            return [{"ConfirmDate": "20261027"}]
        raise AssertionError(kind)

    def attach(self, adapter, snapshot):
        self.adapter = adapter

    def report(self):
        data = fixture.report()
        data["account_fingerprint"] = ACCOUNT
        for index, round_ in enumerate(data["rounds"]):
            start = self.clock.now() - timedelta(seconds=13 - index * 10)
            round_["started_at"] = start.isoformat()
            round_["completed_at"] = (start + timedelta(seconds=2)).isoformat()
            for q in round_["queries"].values():
                q["started_at"] = start.isoformat()
                q["completed_at"] = (start + timedelta(seconds=1)).isoformat()
        positions = []
        for native, (qty, price) in self.positions.items():
            positions.append(
                dict(
                    TradingDay="20261027",
                    ExchangeID="DCE" if native.startswith("jm") else "SHFE",
                    InstrumentID=native,
                    PosiDirection="2" if qty == 1 else "3",
                    HedgeFlag="1",
                    PositionDate="1",
                    Position=1,
                    TodayPosition=1,
                    YdPosition=0,
                    LongFrozen=0,
                    ShortFrozen=0,
                )
            )
        for kind, rows in [
            ("orders", self.orders),
            ("trades", self.trades),
            ("positions", positions),
        ]:
            data = fixture.changed(data, kind, rows)
        funds = data["rounds"][0]["queries"]["funds"]["rows"][0]
        balance = D(100000) + self.closed_profit - self.commission
        margin = D(1000) * len(self.positions)
        return fixture.changed(
            data,
            "funds",
            [
                {
                    **funds,
                    "Balance": str(balance),
                    "Available": str(balance - margin),
                    "CurrMargin": str(margin),
                    "Commission": str(self.commission),
                    "CloseProfit": str(self.closed_profit),
                }
            ],
        )

    def ReqOrderInsert(self, request, request_id):
        self.calls.append("insert")
        assert all(o["OrderStatus"] == "0" for o in self.orders)
        raw = (self.clock.now() - timedelta(seconds=2)).astimezone(SH)
        side = 1 if request.Direction == "0" else -1
        native = request.InstrumentID
        price = D(str(request.LimitPrice))
        if request.CombOffsetFlag == "0":
            assert native not in self.positions
            self.positions[native] = (side, price)
        else:
            held, opened = self.positions.pop(native)
            assert held == -side
            self.closed_profit += (price - opened) * D(10) * held
        self.commission += D(3)
        row = dict(
            TradingDay="20261027",
            OrderRef=request.OrderRef,
            FrontID=1,
            SessionID=2,
            InstrumentID=native,
            ExchangeID=request.ExchangeID,
            Direction=request.Direction,
            CombOffsetFlag=request.CombOffsetFlag,
            CombHedgeFlag="1",
            LimitPrice=str(price),
            VolumeTotalOriginal=1,
            VolumeTraded=1,
            VolumeTotal=0,
            OrderStatus="0",
            OrderSubmitStatus="3",
            OrderSysID="system-" + str(len(self.orders)),
            InsertDate=raw.strftime("%Y%m%d"),
            InsertTime=raw.strftime("%H:%M:%S"),
        )
        self.orders.append(row)
        trade = dict(
            TradingDay="20261027",
            InstrumentID=native,
            ExchangeID=request.ExchangeID,
            Direction=request.Direction,
            OffsetFlag=request.CombOffsetFlag,
            HedgeFlag="1",
            Price=str(price),
            Volume=1,
            TradeID="trade-" + str(len(self.trades)),
            OrderSysID=row["OrderSysID"],
            TradeDate=row["InsertDate"],
            TradeTime=row["InsertTime"],
        )
        self.trades.append(trade)
        self.adapter.order_callback(
            NS(**row, BrokerID="9999", InvestorID=USER), self.clock.now()
        )
        self.adapter.trade_callback(
            NS(**trade, OrderRef=request.OrderRef, BrokerID="9999", InvestorID=USER),
            self.clock.now(),
        )
        return 0

    def ReqOrderAction(self, *args):
        raise AssertionError("unexpected cancel")

    def RegisterSpi(self, spi):
        pass

    def Release(self):
        pass


class Driver(NativePortfolio):
    def __init__(self, settings, folder, clock, gateway=None):
        super().__init__(
            settings,
            folder,
            NS(
                tdapi=NS(
                    CThostFtdcInputOrderField=NS, CThostFtdcInputOrderActionField=NS
                )
            ),
            None,
            now=clock.now,
        )
        self.clock = clock
        self.fixture_gateway = gateway

    def connect(self):
        self.gateway = self.fixture_gateway or Gateway(self.clock)
        self.gateway.user = USER  # New login, reusing only the fake exchange facts.
        self.read_journal = ReadJournal(self.folder / "dispatch.sqlite", ACCOUNT)

    def snapshot(self):
        self.clock.advance(
            15
        )  # Two complete serial native rounds take real elapsed time.
        self.report = self.gateway.report()
        return read_snapshot(self.report, now=self.clock.now())


def seeded_account(tmp_path):
    root = tmp_path / "account-root"
    root.mkdir(mode=0o700)
    folder = root / ACCOUNT
    folder.mkdir(mode=0o700)
    clock = Clock()
    market = Market(clock)
    settings = NS(
        schema=2, state_root=root, account_id=ACCOUNT, mode="trade", enabled=True
    )
    initial_gateway = Gateway(clock)
    native = read_snapshot(initial_gateway.report())
    from guiyi_quant.simnow_execution.inventory import project_readback

    rb, _ = project_readback(native, (), None, None, native.at + timedelta(seconds=30))
    state = a.start(ACCOUNT, ("RB", "JM"), native.at, rb)
    a.LocalStore(folder / "account.sqlite", state).close()
    Journal(folder / "dispatch.sqlite", ACCOUNT).close()
    SignalInbox(folder / "signals.sqlite", ACCOUNT, ("RB", "JM")).close()
    evidence = Evidence(folder / "native-evidence.sqlite", ACCOUNT)
    evidence.append(native)
    evidence.close()
    return settings, folder, clock, market


def test_continuous_host_queue_actual_policy_native_fee_and_monitor_closed_loop(
    tmp_path, monkeypatch
):
    from guiyi_quant.simnow_execution.credentials import CredentialStore

    monkeypatch.setattr(
        CredentialStore, "load", lambda *_: pytest.fail("real Keychain accessed")
    )
    settings, folder, clock, market = seeded_account(tmp_path)
    root = settings.state_root
    drivers = []

    def factory(settings, folder):
        value = Driver(settings, folder, clock)
        drivers.append(value)
        return value

    supervisor = Supervisor(
        settings, ("RB", "JM"), market, factory, clock=clock.now, sleep=clock.sleep
    )
    supervisor.stopped = lambda: (
        supervisor.store is not None
        and len(supervisor.store.current().fills) >= 4
        and all(o.reconciled for o in supervisor.store.current().orders)
    )
    supervisor.run(max_cycles=150)
    final = a.LocalStore.inspect(folder / "account.sqlite")
    assert len(final.fills) == 4 and [o.offset for o in final.orders] == [
        "OPEN",
        "OPEN",
        "CLOSE",
        "OPEN",
    ], json.loads((folder / "continuous.json").read_text())
    assert all(type(fill) is a.StrategyCorrelatedNativeFillV1 for fill in final.fills)
    assert {p.product: p.quantity for p in final.positions} == {"JM": 1, "RB": -1}
    assert len(drivers) == 1
    assert len(final.signals) == 3 and len(final.risk_decisions) == 3
    with sqlite3.connect(folder / "signals.sqlite") as db:
        assert db.execute("SELECT count FROM attempts").fetchall() == [(1,)]
        assert db.execute("SELECT status FROM signals").fetchall() == [("APPLIED",)] * 3
    overview = MonitorReader(root).overview(clock.now())
    assert overview["status"] in ("available", "partial")
    assert (
        overview["observer"]["mode"] == "trade"
        and not overview["observer"]["opening_enabled"]
    )
    assert (
        not overview["position_projection_complete"]
        or overview["observer"]["connection"] != "LOGGED_IN"
    )


@pytest.mark.parametrize(
    "next_mode,expected_offsets",
    [
        ("trade", ["OPEN", "CLOSE", "OPEN"]),
        ("manage", ["OPEN", "CLOSE"]),
    ],
)
def test_trade_restart_keeps_journals_budget_and_drops_missed_open_target(
    tmp_path, next_mode, expected_offsets
):
    settings, folder, clock, market = seeded_account(tmp_path)
    gateway = Gateway(clock)

    def factory(settings, folder):
        return Driver(settings, folder, clock, gateway)

    def make_host():
        return Supervisor(
            settings, ("RB", "JM"), market, factory, clock=clock.now, sleep=clock.sleep
        )

    query = gateway.query

    def first_query(kind, native=None, **scope):
        if kind == "book" and native.startswith("jm"):
            raise ValueError("FIXTURE_JM_BOOK_WAITING")
        return query(kind, native, **scope)

    gateway.query = first_query
    first = make_host()
    first.stopped = lambda: (
        first.store is not None
        and len(first.store.current().fills) >= 1
        and all(o.reconciled for o in first.store.current().orders)
    )
    first.run(max_cycles=75)
    before = a.LocalStore.inspect(folder / "account.sqlite")
    assert len(before.fills) == 1 and before.positions[0].quantity == 1
    # Existing target JM was observed but never sent; restarting must not backfill it.
    assert len(before.signals) == 2
    gateway.query = query
    settings.mode = next_mode
    second = make_host()
    second.stopped = lambda: (
        second.store is not None
        and len(second.store.current().fills) >= len(expected_offsets)
        and all(o.reconciled for o in second.store.current().orders)
    )
    second.run(max_cycles=85)
    after = a.LocalStore.inspect(folder / "account.sqlite")
    assert [o.offset for o in after.orders] == expected_offsets
    assert all(o.product == "RB" for o in after.orders)
    assert after.fills[:1] == before.fills
    assert all(o.reconciled for o in after.orders)
    assert {p.product: p.quantity for p in after.positions} == (
        {"RB": -1} if next_mode == "trade" else {}
    )
    with sqlite3.connect(folder / "signals.sqlite") as db:
        assert db.execute("SELECT count FROM attempts").fetchall() == [(2,)]
    assert (
        MonitorReader(settings.state_root).overview(clock.now())["observer"]["mode"]
        == next_mode
    )
