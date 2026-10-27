"""Offline native portfolio control flow, using a serial fake CTP gateway."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace as NS
from threading import Event
from zoneinfo import ZoneInfo

import pytest

from guiyi_quant import htdy_account_execution as a, htdy_execution as h
from guiyi_quant.simnow_execution import Journal
from guiyi_quant.simnow_execution.native_portfolio import NativePortfolio, ReadJournal


T = datetime(2026, 10, 27, 1, tzinfo=UTC)
USER = "123456"
ACCOUNT = sha256(
    json.dumps(["SIMNOW_FIRST", "9999", USER], separators=(",", ":")).encode()
).hexdigest()
SPEC = importlib.util.spec_from_file_location(
    "native_inventory_fixture",
    Path(__file__).parents[1] / "simnow_host/test_inventory.py",
)
assert SPEC and SPEC.loader
native_fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native_fixture)


def instrument(product):
    exchange = "DCE" if product == "JM" else "SHFE"
    return dict(
        InstrumentID=product.lower() + "2701",
        ExchangeID=exchange,
        ProductID=product.lower(),
        ProductClass="1",
        DeliveryYear=2027,
        DeliveryMonth=1,
        OpenDate="20260101",
        ExpireDate="20270110",
        StartDelivDate="20270115",
        IsTrading=1,
        MinLimitOrderVolume=1,
        MaxLimitOrderVolume=100,
        VolumeMultiple=10,
        PriceTick=1,
    )


def book(product):
    return dict(
        InstrumentID=product.lower() + "2701",
        ExchangeID="DCE" if product == "JM" else "SHFE",
        TradingDay="20261027",
        ActionDay="20261027",
        UpdateTime="09:00:00",
        UpdateMillisec=0,
        BidPrice1=999,
        AskPrice1=1000,
        BidVolume1=1,
        AskVolume1=1,
        LowerLimitPrice=900,
        UpperLimitPrice=1100,
    )


class Gateway:
    def __init__(self, *, fail_product=None):
        self.fail_product = fail_product
        self.queries = []
        self.failed = False
        self.result = {"status": "READ_ONLY_COMPLETE"}
        self.extra = {}
        self.query_diagnostics = []
        self.login_done = Event()
        self.login_done.set()
        self.front = "tcp://182.254.243.31:30001"
        self.native_session = dict(front_id=1, session_id=2, max_order_ref=10)
        self.user = USER
        self.api = NS()
        self.attached = None

    def query(self, kind, instrument_id=None, **scope):
        product = (
            (instrument_id or scope.get("product") or "").upper().removesuffix("2701")
        )
        self.queries.append((kind, product))
        if product == self.fail_product:
            raise ValueError("FIXTURE_NATIVE_PRODUCT_UNAVAILABLE")
        if kind == "instrument":
            return [instrument(product)]
        if kind == "book":
            return [book(product)]
        if kind == "margin":
            return [
                dict(
                    InstrumentID=instrument_id,
                    BrokerID="9999",
                    ExchangeID=scope["exchange"],
                    HedgeFlag="1",
                    IsRelative=0,
                    LongMarginRatioByVolume=0,
                    ShortMarginRatioByVolume=0,
                    LongMarginRatioByMoney="0.1",
                    ShortMarginRatioByMoney="0.1",
                )
            ]
        if kind == "commission":
            return [
                dict(
                    InstrumentID=instrument_id,
                    BrokerID="9999",
                    ExchangeID=scope["exchange"],
                    OpenRatioByMoney="0",
                    OpenRatioByVolume="3",
                )
            ]
        if kind == "settlement":
            return [{"ConfirmDate": "20261102"}]
        raise AssertionError(kind)

    def attach(self, adapter, snapshot):
        self.attached = adapter

    def snapshot(self):
        return native_fixture.report()


class Market:
    def authority(self, product, day, now, contract=None):
        physical = contract or product + "2701"
        return NS(
            contract=physical,
            exchange="DCE" if product == "JM" else "SHFE",
            session=a.Session(
                physical,
                now,
                now + timedelta(seconds=15),
                "calendar:" + product,
                now + timedelta(hours=6),
                True,
                True,
            ),
        )


def portfolio(tmp_path, *, gateway=None, at=T):
    value = NativePortfolio(
        NS(account_id=ACCOUNT),
        tmp_path,
        NS(tdapi=NS()),
        lambda *_: None,
        now=lambda: at,
    )
    value.gateway = gateway or Gateway()
    return value


def test_manual_grace_is_opt_in_at_native_portfolio_boundary(monkeypatch, tmp_path):
    from guiyi_quant.simnow_execution import native_portfolio as module

    calls = []
    monkeypatch.setattr(
        module.CredentialStore, "load", lambda *_: NS(user="000000", password="fixture")
    )
    monkeypatch.setattr(module, "ReadJournal", lambda *_: object())
    fake_module = NS(
        tdapi=object(), Gateway=lambda *args, **kwargs: calls.append(kwargs) or object()
    )
    for timeout in (15, 45):
        value = NativePortfolio(
            NS(account_id=ACCOUNT),
            tmp_path,
            fake_module,
            lambda *_: None,
            now=lambda: T,
            initial_funds_timeout=timeout,
        )
        value.connect()
        assert calls[-1] == ({} if timeout == 15 else {"initial_funds_timeout": 45})
        value.flow.cleanup()
    for invalid in (14, 46, True, "45"):
        with pytest.raises(ValueError):
            NativePortfolio(
                NS(account_id=ACCOUNT),
                tmp_path,
                fake_module,
                lambda *_: None,
                now=lambda: T,
                initial_funds_timeout=invalid,
            )


def state(*, desired_rb=-1, desired_jm=-1, positions=("RB", "JM"), orders=()):
    products = (
        a.Product(
            "RB",
            "RB2701",
            desired=desired_rb,
            signal_id="signal:RB",
            signal_at=T - timedelta(minutes=1),
        ),
        a.Product(
            "JM",
            "JM2701",
            desired=desired_jm,
            signal_id="signal:JM",
            signal_at=T - timedelta(minutes=1),
        ),
    )
    return NS(
        products=products,
        positions=tuple(h.Position(p, p + "2701", 1) for p in positions),
        orders=orders,
    )


def test_reverse_signal_without_must_close_selects_held_contract(tmp_path):
    native = portfolio(tmp_path)
    facts, bindings = native.execution_for(
        state(positions=("RB",), desired_rb=-1, desired_jm=0),
        Market(),
        T,
        "20261027",
        {},
    )
    assert len(facts) == len(bindings) == 1
    assert facts[0].instrument.product == "RB"
    assert bindings[0].canonical == "RB2701"


def test_snapshot_uses_authoritative_inventory_validation(tmp_path):
    native = portfolio(tmp_path, at=T + timedelta(seconds=20))
    native.gateway.query_diagnostics = []
    snapshot = native.snapshot()
    assert snapshot.trading_day == "20261027"
    assert snapshot.account_id == "a" * 64
    assert snapshot.source_id.startswith("ctp-inventory:")


def test_failed_first_product_does_not_starve_other_pending_close(tmp_path):
    gateway = Gateway(fail_product="JM")
    native = portfolio(tmp_path, gateway=gateway)
    issues = {}
    facts, bindings = native.execution_for(state(), Market(), T, "20261027", issues)
    assert issues == {"JM": "EXECUTION_INPUT_UNPROVEN"}
    assert [item.instrument.product for item in facts] == ["RB"]
    assert [item.canonical for item in bindings] == ["RB2701"]
    assert ("instrument", "JM") in gateway.queries
    assert ("instrument", "RB") in gateway.queries


def test_cached_old_facts_cannot_starve_another_pending_close(tmp_path):
    gateway = Gateway()
    native = portfolio(tmp_path, gateway=gateway)
    native.facts("JM", "JM2701", Market(), "20261027")
    assert "JM2701" in native.last_facts
    gateway.queries.clear()
    gateway.fail_product = "JM"

    issues = {}
    facts, bindings = native.execution_for(state(), Market(), T, "20261027", issues)

    assert gateway.queries[0] == ("margin", "JM")
    assert ("book", "RB") in gateway.queries
    assert issues == {"JM": "EXECUTION_INPUT_UNPROVEN"}
    assert [item.canonical for item in bindings] == ["RB2701"]
    assert len(facts) == 1
    assert facts[0].instrument.product == "RB"
    assert facts[0].quote is not None and facts[0].quote.contract == "RB2701"


def test_only_one_eligible_close_input_is_acquired_per_cycle(tmp_path):
    native = portfolio(tmp_path)
    facts, _ = native.execution_for(state(), Market(), T, "20261027", {})
    assert len(facts) == 1 and facts[0].instrument.product == "JM"
    assert {product for _, product in native.gateway.queries} == {"JM"}


def test_unresolved_order_keeps_priority_even_when_other_close_is_ready(tmp_path):
    gateway = Gateway(fail_product="JM")
    native = portfolio(tmp_path, gateway=gateway)
    unknown = a.Order(
        "pending-jm",
        "JM",
        "JM2701",
        "BUY",
        "CLOSE",
        "signal:JM",
        T - timedelta(minutes=1),
        D(1000),
        "instrument",
        "quote",
        "session",
        status="UNKNOWN",
        reconciled=False,
    )
    issues = {}
    facts, _ = native.execution_for(
        state(positions=("RB",), desired_jm=0, orders=(unknown,)),
        Market(),
        T,
        "20261027",
        issues,
    )
    assert facts == ()
    assert issues == {"JM": "EXECUTION_INPUT_UNPROVEN"}
    assert {product for _, product in gateway.queries} == {"JM"}


def test_friday_night_native_session_covers_monday_close(tmp_path):
    friday_night = datetime(2026, 10, 30, 21, tzinfo=ZoneInfo("Asia/Shanghai"))
    native = portfolio(tmp_path, at=friday_night)
    snapshot = NS(account_id=ACCOUNT, trading_day="20261102")
    journal = NS(account_id=ACCOUNT)
    adapter = native.adapter(None, journal, snapshot, friday_night)
    monday_close = datetime(2026, 11, 2, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    next_midnight = datetime.combine(
        date(2026, 11, 3), time(), ZoneInfo("Asia/Shanghai")
    )
    assert adapter.session.at == friday_night
    assert monday_close < adapter.session.valid_until == next_midnight
    assert native.gateway.attached is adapter


def test_correlated_adapter_binds_full_snapshot_before_buffer_attach(tmp_path):
    from guiyi_quant.simnow_execution.inventory import read_snapshot

    native = portfolio(tmp_path, at=T + timedelta(minutes=1))
    report = native_fixture.report()
    report["account_fingerprint"] = ACCOUNT
    snapshot = read_snapshot(report)
    native.gateway.query = lambda kind: [{"ConfirmDate": "20261027"}]
    attached = []

    def attach(adapter, _snapshot):
        attached.append(adapter._correlated_snapshot is not None)

    native.gateway.attach = attach
    adapter = native.adapter(None, NS(account_id=ACCOUNT, events=lambda: ()), snapshot,
                             T + timedelta(minutes=1), close_only=True,
                             correlated_native=True)
    assert adapter.close_only and adapter.correlated_native
    assert attached == [True]
    assert adapter._correlated_snapshot[0] == snapshot


def test_read_journal_connection_is_sqlite_read_only(tmp_path):
    path = tmp_path / "dispatch.sqlite"
    writable = Journal(path, ACCOUNT)
    writable.close()
    reader = ReadJournal(path, ACCOUNT)
    try:
        assert reader.conn.execute("SELECT account FROM identity").fetchone() == (
            ACCOUNT,
        )
        with pytest.raises(sqlite3.OperationalError):
            reader.conn.execute(
                "INSERT INTO identity VALUES (?,?)", (ACCOUNT, "unexpected")
            )
    finally:
        reader.close()


@pytest.mark.parametrize(
    "status,expected",
    [
        ("FRONT_DISCONNECTED", True),
        ("QUERY_TIMEOUT", True),
        ("LOGIN_TIMEOUT", True),
        ("EXECUTION_CALLBACK_BLOCKED", False),
        ("NATIVE_FACT_RESPONSE_INVALID", False),
        ("LOGIN_REJECTED", False),
    ],
)
def test_transport_failure_classifies_fixed_gateway_status(tmp_path, status, expected):
    gateway = Gateway()
    gateway.failed = True
    gateway.result = {"status": status}
    assert portfolio(tmp_path, gateway=gateway).transport_failed is expected


@pytest.mark.parametrize(
    "extra,diagnostics,expected",
    [
        ({}, [{"timed_out": True}], True),
        ({"callback_error": "private"}, [{"timed_out": True}], False),
        ({}, [{"timed_out": False}], False),
        ({}, [{"timed_out": True}, {"timed_out": False}], False),
        (None, [{"timed_out": True}], False),
        ({}, [], False),
    ],
)
def test_query_failed_requires_last_query_timeout_without_callback_error(
    tmp_path, extra, diagnostics, expected
):
    gateway = Gateway()
    gateway.failed = True
    gateway.result = {"status": "NATIVE_FACT_QUERY_FAILED"}
    gateway.extra = extra
    gateway.query_diagnostics = diagnostics
    assert portfolio(tmp_path, gateway=gateway).transport_failed is expected


@pytest.mark.parametrize(
    "status", ["WAITING_CONNECTION", "WAITING_AUTH", "WAITING_LOGIN"]
)
def test_unfinished_login_wait_is_bounded_transport_timeout(tmp_path, status):
    gateway = Gateway()
    gateway.result = {"status": status}
    gateway.login_done.clear()
    native = portfolio(tmp_path, gateway=gateway)
    assert native.transport_failed
    gateway.login_done.set()
    assert not native.transport_failed
