"""Execute the real one-shot orchestration with a deterministic simulated gateway."""

from datetime import datetime, UTC, timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS
import importlib.util
import sys
import pytest
from test_host import f, report_at
from test_inventory import changed
from guiyi_quant import htdy_account_execution as a, htdy_execution as h

_spec = importlib.util.spec_from_file_location(
    "controlled_cli", Path(__file__).parents[3] / "scripts/broker/simnow_controlled.py"
)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


class Clock(datetime):
    current = datetime(2026, 10, 27, 1, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        cls.current += timedelta(seconds=0.2)
        return cls.current


def snapshot_report(account, order=None, trade=None, fee="0", held=False):
    value = report_at(Clock.current - timedelta(seconds=12), account)
    if order:
        value = changed(value, "orders", [order])
    if trade:
        value = changed(value, "trades", [trade])
    if held:
        value = changed(
            value,
            "positions",
            [
                dict(
                    TradingDay="20261027",
                    ExchangeID="SHFE",
                    InstrumentID="rb2701",
                    PosiDirection="2",
                    HedgeFlag="1",
                    PositionDate="1",
                    Position=1,
                    TodayPosition=1,
                    YdPosition=0,
                    LongFrozen=0,
                    ShortFrozen=0,
                )
            ],
        )
    funds = value["rounds"][0]["queries"]["funds"]["rows"][0]
    value = changed(
        value,
        "funds",
        [
            {
                **funds,
                "Balance": str(D(100000) - D(fee)),
                "Available": str(D(100000) - D(fee) - (D(1000) if held else 0)),
                "CurrMargin": "1000" if held else "0",
                "Commission": fee,
            }
        ],
    )
    return value


class FakeMarket:
    def __init__(self, product):
        self.started = None
        self.sent = False
        self.closed = False

    def authority(self, day, now, contract=None):
        return NS(
            contract=contract or "RB2701",
            owner="RB2701",
            exchange="SHFE",
            source_id="authority",
            session=a.Session(
                contract or "RB2701",
                now,
                now + timedelta(seconds=15),
                "session",
                now + timedelta(hours=2),
                True,
                True,
            ),
        )

    def activate(self, at):
        self.started = at

    def poll(self, now, after):
        if self.sent:
            return None
        self.sent = True
        return h.Signal(
            "new-natural",
            "RB",
            "RB2701",
            now - timedelta(milliseconds=10),
            now,
            None,
            ("buy",),
            "a" * 64,
        )

    def recovery(self, state, now):
        return (
            h.RecoveryInput(
                "RB", "RB2701", 1, now - timedelta(seconds=1), "complete-input"
            ),
        )

    def close(self):
        self.closed = True


class FakeGateway:
    def __init__(self, mode):
        self.mode = mode
        self.failed = False
        self.user = f.USER
        self.front = "tcp://182.254.243.31:30001"
        self.native_session = dict(front_id=1, session_id=2, max_order_ref=10)
        self.execution_adapter = None
        self.calls = []
        self.api = self
        self.request = None
        self.cancelled = False
        self.released = False

    def RegisterSpi(self, spi):
        self.calls.append(("register", spi))

    def Release(self):
        self.released = True

    def attach(self, adapter, snapshot):
        self.execution_adapter = adapter

    def query(self, kind, instrument="", *, exchange="", product=""):
        self.calls.append((kind, instrument))
        if kind == "instrument":
            assert exchange == "SHFE" and product == "rb"
            return (
                dict(
                    InstrumentID="rb2701",
                    ExchangeID="SHFE",
                    ProductID="rb",
                    ProductClass="1",
                    DeliveryYear=2027,
                    DeliveryMonth=1,
                    OpenDate="20260101",
                    ExpireDate="20270110",
                    StartDelivDate="20270115",
                    IsTrading=1,
                    VolumeMultiple=10,
                    PriceTick=1,
                    MinLimitOrderVolume=1,
                    MaxLimitOrderVolume=100,
                ),
            )
        if kind == "settlement":
            return (
                ()
                if self.mode == "unconfirmed"
                else (dict(ConfirmDate="20261027", ConfirmTime="09:00:00"),)
            )
        if kind == "confirm":
            return (dict(ConfirmDate="20261027", ConfirmTime="09:00:00"),)
        if kind == "margin":
            return (
                dict(
                    InstrumentID=instrument,
                    ExchangeID="SHFE",
                    BrokerID="9999",
                    HedgeFlag="1",
                    IsRelative=0,
                    LongMarginRatioByMoney=0.1,
                    ShortMarginRatioByMoney=0.1,
                    LongMarginRatioByVolume=0,
                    ShortMarginRatioByVolume=0,
                ),
            )
        if kind == "commission":
            return (
                dict(
                    InstrumentID=instrument,
                    ExchangeID="SHFE",
                    BrokerID="9999",
                    OpenRatioByMoney=0,
                    OpenRatioByVolume=3,
                ),
            )
        if kind == "book":
            local = Clock.current.astimezone(
                __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
            )
            return (
                dict(
                    InstrumentID=instrument,
                    ExchangeID="SHFE",
                    TradingDay="20261027",
                    ActionDay=local.strftime("%Y%m%d"),
                    UpdateTime=local.strftime("%H:%M:%S"),
                    UpdateMillisec=local.microsecond // 1000,
                    BidPrice1=999,
                    AskPrice1=1000,
                    BidVolume1=1,
                    AskVolume1=1,
                    LowerLimitPrice=900,
                    UpperLimitPrice=1100,
                ),
            )
        raise AssertionError(kind)

    def snapshot(self):
        # Native collector time is source time, never extended by the mapper.
        Clock.current += timedelta(seconds=13)
        if self.request is None:
            return snapshot_report(f.ACCOUNT)
        req = self.request
        native = self.sent_at.astimezone(
            __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
        )
        filled = self.mode in ("filled", "pending-fee")
        order = dict(
            TradingDay="20261027",
            InstrumentID="rb2701",
            ExchangeID="SHFE",
            OrderSysID="sys-one",
            FrontID=1,
            SessionID=2,
            OrderRef=req.OrderRef,
            OrderStatus="0" if filled else "5" if self.cancelled else "3",
            OrderSubmitStatus="3",
            Direction="0",
            CombOffsetFlag="0",
            CombHedgeFlag="1",
            LimitPrice="1000.0",
            VolumeTotalOriginal=1,
            VolumeTraded=int(filled),
            VolumeTotal=0 if filled or self.cancelled else 1,
            InsertDate=native.strftime("%Y%m%d"),
            InsertTime=native.strftime("%H:%M:%S"),
        )
        if self.mode == "unknown":
            order.update(OrderStatus="a", OrderSubmitStatus="0", OrderSysID="")
        trade = (
            dict(
                TradingDay="20261027",
                InstrumentID="rb2701",
                ExchangeID="SHFE",
                OrderSysID="sys-one",
                TradeID="run-trade",
                Direction="0",
                OffsetFlag="0",
                HedgeFlag="1",
                Price="1000.0",
                Volume=1,
                TradeDate=native.strftime("%Y%m%d"),
                TradeTime=native.strftime("%H:%M:%S"),
            )
            if filled
            else None
        )
        value = snapshot_report(
            f.ACCOUNT, order, trade, "3.12" if filled else "0", filled
        )
        if self.mode == "pending-fee" and trade:
            value = changed(
                value, "trades", [trade, {**trade, "TradeID": "ambiguous-second"}]
            )
        return value

    def ReqOrderInsert(self, req, rid):
        self.calls.append(("insert", rid))
        self.request = req
        self.sent_at = Clock.current
        if self.mode == "unknown":
            raise RuntimeError("do-not-emit")
        if self.mode == "gateway-failed":
            self.failed = True
        return 0

    def ReqOrderAction(self, req, rid):
        self.calls.append(("cancel", rid))
        self.cancelled = True
        return 0


def configured(monkeypatch):
    Clock.current = datetime(2026, 10, 27, 1, tzinfo=UTC)
    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setitem(
        sys.modules, "app.simnow_controlled_market", NS(MarketBridge=FakeMarket)
    )
    monkeypatch.setitem(
        sys.modules,
        "app.htdy_execution",
        NS(
            start_account_operational=lambda account, at, rb: a.start(
                account, ("RB",), at, rb
            )
        ),
    )
    return NS(
        product="rb", execute=True, initialize=True, max_seconds=60, max_submits=1
    )


@pytest.mark.parametrize("mode", ["unknown", "gateway-failed", "pending-fee"])
def test_actual_cli_run_classifies_unknown_pending_and_native_failure(
    monkeypatch, tmp_path, mode
):
    config = configured(monkeypatch)
    gateway = FakeGateway(mode)
    sdk = NS(CThostFtdcInputOrderField=NS, CThostFtdcInputOrderActionField=NS)
    result = cli.run(gateway, sdk, config, tmp_path)
    assert result["status"] == "CONTROLLED_RUN_REQUIRES_RECOVERY"
    assert result["orders"] and result["reservations"]
    assert any(not r["released"] for r in result["reservations"])
    assert result["broker_e2e_passed"] is False and gateway.released
    assert sum(c[0] == "insert" for c in gateway.calls) == 1
    assert result.get("error_code") not in ("do-not-emit",)


def test_actual_cli_success_is_native_inventory_not_reference_pnl(
    monkeypatch, tmp_path
):
    config = configured(monkeypatch)
    gateway = FakeGateway("filled")
    sdk = NS(CThostFtdcInputOrderField=NS, CThostFtdcInputOrderActionField=NS)
    result = cli.run(gateway, sdk, config, tmp_path)
    assert result["status"] == "CONTROLLED_RUN_ENDED"
    assert result["positions"][0]["quantity"] == 1
    assert result["performance"]["net_profit"] == "-3.12"
    assert all(o["reconciled"] for o in result["orders"])
    assert all(r["released"] for r in result["reservations"])
    assert gateway.released and gateway.api is None


def test_preflight_never_confirms_settlement_or_creates_trading_state(
    monkeypatch, tmp_path
):
    config = configured(monkeypatch)
    config.execute = False
    config.initialize = False
    gateway = FakeGateway("unconfirmed")
    result = cli.run(gateway, NS(), config, tmp_path)
    assert (
        result["status"] == "READ_ONLY_PREFLIGHT_COMPLETE"
        and not result["settlement_confirmed"]
    )
    assert all(c[0] not in ("confirm", "insert", "cancel") for c in gateway.calls)
    assert not (tmp_path / "output/simnow-controlled").exists()


@pytest.mark.parametrize(
    "args", [["--max-submits", "0"], ["--max-seconds", "3601"], ["--initialize"]]
)
def test_cli_rejects_unbounded_or_ambiguous_options(args):
    with pytest.raises(SystemExit):
        cli.options(["--product", "rb", *args])


def test_no_new_natural_signal_means_zero_native_orders(monkeypatch, tmp_path):
    config = configured(monkeypatch)
    gateway = FakeGateway("working")
    monkeypatch.setattr(FakeMarket, "poll", lambda *_: None)
    result = cli.run(
        gateway,
        NS(CThostFtdcInputOrderField=NS, CThostFtdcInputOrderActionField=NS),
        config,
        tmp_path,
    )
    assert result["status"] == "CONTROLLED_RUN_ENDED"
    assert not any(c[0] in ("insert", "cancel") for c in gateway.calls)


def test_execute_funding_failure_happens_before_settlement_mutation(
    monkeypatch, tmp_path
):
    config = configured(monkeypatch)
    gateway = FakeGateway("unconfirmed")
    original = gateway.snapshot

    def insufficient():
        value = original()
        funds = value["rounds"][0]["queries"]["funds"]["rows"][0]
        return changed(
            value, "funds", [{**funds, "Balance": "50000", "Available": "50000"}]
        )

    gateway.snapshot = insufficient
    with pytest.raises(ValueError):
        cli.run(gateway, NS(), config, tmp_path)
    assert not any(c[0] in ("confirm", "insert", "cancel") for c in gateway.calls)
    assert gateway.released


def test_release_tail_late_fill_is_retained_before_journals_close(
    monkeypatch, tmp_path
):
    config = configured(monkeypatch)
    gateway = FakeGateway("working")

    def release_tail():
        gateway.released = True
        if gateway.request is not None:
            native = gateway.sent_at.astimezone(
                __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
            )
            trade = NS(
                BrokerID="9999",
                InvestorID=f.USER,
                TradingDay="20261027",
                InstrumentID="rb2701",
                ExchangeID="SHFE",
                OrderRef=gateway.request.OrderRef,
                OrderSysID="sys-one",
                TradeID="release-tail",
                Direction="0",
                OffsetFlag="0",
                HedgeFlag="1",
                Price=1000.0,
                Volume=1,
                TradeDate=native.strftime("%Y%m%d"),
                TradeTime=native.strftime("%H:%M:%S"),
            )
            gateway.execution_adapter.trade_callback(trade, Clock.current)

    gateway.Release = release_tail
    result = cli.run(
        gateway,
        NS(CThostFtdcInputOrderField=NS, CThostFtdcInputOrderActionField=NS),
        config,
        tmp_path,
    )
    assert result["status"] == "CONTROLLED_RUN_REQUIRES_RECOVERY"
    assert result["pending_fees_or_identity"]
    assert result["position_projection_complete"] is False
    assert any(not r["released"] for r in result["reservations"])


def test_monitor_publication_failure_does_not_change_controlled_execution(
    monkeypatch, tmp_path
):
    from guiyi_quant.simnow_execution.monitor import MonitorPublisher

    config = configured(monkeypatch)

    def failed(*args, **kwargs):
        raise OSError("private observer failure")

    monkeypatch.setattr(MonitorPublisher, "publish", failed)
    gateway = FakeGateway("filled")
    sdk = NS(CThostFtdcInputOrderField=NS, CThostFtdcInputOrderActionField=NS)
    result = cli.run(gateway, sdk, config, tmp_path)
    assert result["status"] == "CONTROLLED_RUN_ENDED"
    assert result["monitor_status"] == "unavailable"
    assert "private observer failure" not in str(result)
    assert len([c for c in gateway.calls if c[0] == "insert"]) == 1


def test_preflight_batch_book_selects_exact_physical_contract(monkeypatch, tmp_path):
    config = configured(monkeypatch)
    config.execute = config.initialize = False
    gateway = FakeGateway("unconfirmed")
    original = gateway.query
    def batch(kind, instrument="", **scope):
        rows = original(kind, instrument, **scope)
        if kind != "book":
            return rows
        # Bad/stale unrelated rows cannot substitute for or poison the exact target.
        return tuple(dict(rows[0], InstrumentID=f"other{i}", BidPrice1=0) for i in range(32)) + rows
    gateway.query = batch
    result = cli.run(gateway, NS(), config, tmp_path)
    assert result["status"] == "READ_ONLY_PREFLIGHT_COMPLETE"
    observed = result["execution_input_observed"]
    assert observed["contract"] == "RB2701" and observed["native_contract"] == "rb2701"
    assert observed["bid"] == "999" and observed["ask"] == "1000"
    assert observed["scope"] == "OBSERVED_INPUT_NOT_CURRENT_ORDER_PERMISSION"
    diagnostic = gateway.book_selection_diagnostics
    assert diagnostic["batch_rows"] == 33 and diagnostic["exact_identity_matches"] == 1
    assert diagnostic["trading_day_matches"] is True
    assert 0 <= float(diagnostic["event_age_seconds"]) <= 5
    assert all(c[0] not in ("confirm", "insert", "cancel") for c in gateway.calls)
    assert not (tmp_path / "output/simnow-controlled").exists()


def test_preflight_duplicate_target_book_stops_without_mutation(monkeypatch, tmp_path):
    config = configured(monkeypatch)
    config.execute = config.initialize = False
    gateway = FakeGateway("unconfirmed")
    original = gateway.query
    def duplicate(kind, instrument="", **scope):
        rows = original(kind, instrument, **scope)
        return rows + rows if kind == "book" else rows
    gateway.query = duplicate
    with pytest.raises(ValueError, match="NATIVE_BOOK_TARGET_AMBIGUOUS"):
        cli.run(gateway, NS(), config, tmp_path)
    assert gateway.book_selection_diagnostics["exact_identity_matches"] == 2
    assert all(c[0] not in ("confirm", "insert", "cancel") for c in gateway.calls)
    assert not (tmp_path / "output/simnow-controlled").exists()


def rate_scope(kind):
    return dict(schema="native_rate_query_scope_v1", kind=kind, instrument="rb2701", exchange="SHFE", request_id=30003)


def test_blank_rate_exchange_requires_completed_query_scope(monkeypatch, tmp_path):
    config = configured(monkeypatch)
    config.execute = config.initialize = False
    gateway = FakeGateway("unconfirmed")
    original = gateway.query
    seen = []
    def scoped(kind, instrument="", **scope):
        rows = original(kind, instrument, **scope)
        if kind in ("margin", "commission"):
            assert scope["exchange"] == "SHFE"
            rows = tuple(dict(row, ExchangeID="", query_scope=rate_scope(kind)) for row in rows)
            seen.extend(rows)
        return rows
    gateway.query = scoped
    result = cli.run(gateway, NS(), config, tmp_path)
    assert result["status"] == "READ_ONLY_PREFLIGHT_COMPLETE"
    assert all(row["ExchangeID"] == "" for row in seen)
    assert all(c[0] not in ("confirm", "insert", "cancel") for c in gateway.calls)


@pytest.mark.parametrize("issue", ["no_scope", "wrong_scope_exchange", "wrong_scope_contract", "wrong_scope_kind", "wrong_request_id", "wrong_schema", "wrong_response_exchange", "wrong_response_contract", "wrong_broker"])
def test_rate_scope_never_repairs_conflicting_identity(monkeypatch, tmp_path, issue):
    config = configured(monkeypatch)
    config.execute = config.initialize = False
    gateway = FakeGateway("unconfirmed")
    original = gateway.query
    def bad(kind, instrument="", **scope):
        rows = original(kind, instrument, **scope)
        if kind == "margin":
            row = dict(rows[0], ExchangeID="", query_scope=rate_scope(kind))
            if issue == "no_scope":
                row.pop("query_scope")
            elif issue == "wrong_scope_exchange":
                row["query_scope"]["exchange"] = "DCE"
            elif issue == "wrong_scope_contract":
                row["query_scope"]["instrument"] = "rb2705"
            elif issue == "wrong_scope_kind":
                row["query_scope"]["kind"] = "commission"
            elif issue == "wrong_request_id":
                row["query_scope"]["request_id"] = True
            elif issue == "wrong_schema":
                row["query_scope"]["schema"] = "unknown"
            elif issue == "wrong_response_exchange":
                row["ExchangeID"] = "DCE"
            elif issue == "wrong_response_contract":
                row["InstrumentID"] = "rb2705"
            elif issue == "wrong_broker":
                row["BrokerID"] = "other"
            return (row,)
        return rows
    gateway.query = bad
    with pytest.raises(ValueError, match="NATIVE_RATE_IDENTITY"):
        cli.run(gateway, NS(), config, tmp_path)
    assert all(c[0] not in ("confirm", "insert", "cancel") for c in gateway.calls)


def test_flat_transient_old_book_waits_then_uses_fresh_quote(monkeypatch, tmp_path):
    config = configured(monkeypatch)
    gateway = FakeGateway("filled")
    original = gateway.query
    books = 0
    def intermittent(kind, instrument="", **scope):
        nonlocal books
        rows = original(kind, instrument, **scope)
        if kind == "book":
            books += 1
            if books == 2:
                return tuple(dict(row, ActionDay="20261026") for row in rows)
        return rows
    gateway.query = intermittent
    result = cli.run(gateway, NS(CThostFtdcInputOrderField=NS, CThostFtdcInputOrderActionField=NS), config, tmp_path)
    assert result["status"] == "CONTROLLED_RUN_ENDED"
    assert result["empty_account_quote_waits"] == 1
    assert result["submit_budget_used"] == 1
    assert books >= 3


def test_flat_old_book_until_deadline_never_submits(monkeypatch, tmp_path):
    config = configured(monkeypatch)
    gateway = FakeGateway("unconfirmed")
    original = gateway.query
    books = 0
    def old(kind, instrument="", **scope):
        nonlocal books
        rows = original(kind, instrument, **scope)
        if kind == "book":
            books += 1
            if books > 1:
                return tuple(dict(row, ActionDay="20261026") for row in rows)
        return rows
    gateway.query = old
    result = cli.run(gateway, NS(), config, tmp_path)
    assert result["status"] == "CONTROLLED_RUN_ENDED"
    assert result["empty_account_quote_waits"] > 0
    assert result["submit_budget_used"] == 0
    assert not result["orders"]
    assert all(call[0] != "insert" for call in gateway.calls)


@pytest.mark.parametrize("mode", ["future", "unknown-order", "bad-rate"])
def test_quote_wait_never_hides_future_identity_or_pending_order(monkeypatch, tmp_path, mode):
    config = configured(monkeypatch)
    gateway = FakeGateway("unknown" if mode == "unknown-order" else "filled")
    original = gateway.query
    books = 0
    def invalid(kind, instrument="", **scope):
        nonlocal books
        rows = original(kind, instrument, **scope)
        if mode == "bad-rate" and kind == "margin" and books >= 1:
            return tuple(dict(row, ExchangeID="DCE") for row in rows)
        if kind == "book":
            books += 1
            if (mode == "future" and books == 2) or (mode == "unknown-order" and books >= 3):
                return tuple(dict(row, ActionDay="20261028" if mode == "future" else "20261026") for row in rows)
        return rows
    gateway.query = invalid
    sdk = NS(CThostFtdcInputOrderField=NS, CThostFtdcInputOrderActionField=NS)
    result = cli.run(gateway, sdk, config, tmp_path)
    assert result["status"] == "CONTROLLED_RUN_REQUIRES_RECOVERY"
    assert result["empty_account_quote_waits"] == 0
    if mode == "unknown-order":
        assert result["submit_budget_used"] == 1
        assert any(not r["released"] for r in result["reservations"])
    else:
        assert result["submit_budget_used"] == 0


def test_initial_old_book_still_stops_before_settlement_or_initialization(monkeypatch, tmp_path):
    config = configured(monkeypatch)
    gateway = FakeGateway("unconfirmed")
    original = gateway.query
    def old(kind, instrument="", **scope):
        rows = original(kind, instrument, **scope)
        return tuple(dict(row, ActionDay="20261026") for row in rows) if kind == "book" else rows
    gateway.query = old
    with pytest.raises(ValueError, match="NATIVE_BOOK_STALE"):
        cli.run(gateway, NS(), config, tmp_path)
    assert not (tmp_path / "output/simnow-controlled").exists()
    assert all(c[0] not in ("confirm", "insert", "cancel") for c in gateway.calls)
