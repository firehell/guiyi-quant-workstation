"""Offline full manual round trip through the real store, Host and Adapter."""

from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from guiyi_quant import htdy_account_execution as a, simnow_execution as b
from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.host import Host
from guiyi_quant.simnow_execution.inventory import project_readback, read_snapshot
from guiyi_quant.simnow_execution.manual_host import acceptance
from test_host import f, report_at
from test_inventory import changed


TEST_ID = "manual:97039e1c-850a-44af-9ab1-60af6c561ac4"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _report_from_snapshot(snapshot, at):
    report = report_at(at, snapshot.account_id)
    for kind, rows in snapshot.data.items():
        report = changed(report, kind, rows)
    return report


def _native_order(adapter, effect, at, *, closing=False):
    row = f.row(adapter, effect, at, "0").__dict__.copy()
    row.pop("BrokerID")
    row.pop("InvestorID")
    row["LimitPrice"] = str(effect.order.price)
    if closing:
        row.update(Direction="1", CombOffsetFlag="3", OrderSysID="sys-close")
    return row


def _native_trade(effect, at, *, closing=False):
    row = f.native_trade().__dict__.copy()
    row.pop("BrokerID")
    row.pop("InvestorID")
    row.pop("OrderRef")
    row["Price"] = str(effect.order.price if closing else D(999))
    row["TradeTime"] = at.astimezone(SHANGHAI).strftime("%H:%M:%S")
    row["TradeID"] = "manual-close" if closing else "manual-open"
    if closing:
        row.update(Direction="1", OffsetFlag="3", OrderSysID="sys-close")
    return row


def _facts(at, price):
    return a.ExecutionInput(
        a.Instrument(
            "RB",
            "RB2701",
            f.T,
            f.T + timedelta(hours=3),
            "instrument",
            D(1),
            D(10),
            D(".1"),
            D(".1"),
            D(3),
        ),
        a.Session(
            "RB2701",
            f.T,
            f.T + timedelta(hours=3),
            "session",
            f.T + timedelta(hours=3),
            True,
            True,
        ),
        a.Quote(
            "RB2701",
            at,
            at + timedelta(seconds=10),
            "quote:" + at.isoformat(),
            D(price) - 1,
            D(price),
            3,
            3,
            D(900),
            D(1100),
        ),
    )


def test_manual_full_roundtrip_reconciles_two_actual_fees_and_equity(tmp_path):
    open_at = f.T + timedelta(minutes=61)
    baseline = read_snapshot(report_at(open_at - timedelta(seconds=20), f.ACCOUNT))
    binding = b.Contract(
        "RB2701", "rb2701", "SHFE", "native-instrument", f.T, f.T + timedelta(hours=3)
    )
    rb, inventory = project_readback(
        baseline, (binding,), None, None, open_at + timedelta(seconds=30)
    )
    assert inventory == ()
    state = a.start(f.ACCOUNT, ("RB",), baseline.at, rb)
    state = a.apply(
        state, "owner", f.h.Owner("RB", "RB2701", baseline.at, "owner:RB")
    ).state
    assert state.signals == ()
    store = a.LocalStore(tmp_path / "account.db", state)
    journal = b.Journal(tmp_path / "dispatch.db", f.ACCOUNT)
    evidence = Evidence(tmp_path / "evidence.db", f.ACCOUNT)
    evidence.append(baseline)
    api = f.FakeApi()
    session = b.Session(
        f.ACCOUNT,
        "SIMNOW_FIRST",
        "tcp://182.254.243.31:30001",
        "20261027",
        1,
        2,
        10,
        "native-login",
        "native-settlement-confirm",
        f.T,
        f.T + timedelta(hours=3),
    )
    sdk = SimpleNamespace(
        CThostFtdcInputOrderField=SimpleNamespace,
        CThostFtdcInputOrderActionField=SimpleNamespace,
    )
    adapter = b.Adapter(store, journal, sdk, api, f.USER, session)
    host = Host(
        store,
        journal,
        evidence,
        adapter,
        "RB",
        run_id="manual",
        deadline=open_at + timedelta(minutes=2),
        manual_test_id=TEST_ID,
    )
    assert host.baseline == baseline

    store.execute(
        "manual-begin",
        a.ManualBeginV1(
            TEST_ID,
            "RB",
            "RB2701",
            open_at - timedelta(seconds=1),
            open_at + timedelta(minutes=1),
        ),
    )
    opening_facts = _facts(open_at, 1000)
    opened = store.execute(
        "manual-open", a.ManualTickV1(open_at, (opening_facts,), TEST_ID)
    )
    opening = opened.effects[0]
    assert opening.order.offset == "OPEN" and opening.order.signal_id == TEST_ID
    assert host.submit_effects((opening,), (binding,), (opening_facts,), open_at) == (
        "REQUEST_ACCEPTED_AWAIT_NATIVE",
    )
    open_report = report_at(open_at + timedelta(seconds=3), f.ACCOUNT)
    open_report = changed(
        open_report, "orders", [_native_order(adapter, opening, open_at)]
    )
    open_report = changed(open_report, "trades", [_native_trade(opening, open_at)])
    open_report = changed(
        open_report,
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
    funds = open_report["rounds"][0]["queries"]["funds"]["rows"][0]
    open_report = changed(
        open_report,
        "funds",
        [
            {
                **funds,
                "Balance": "99996.88",
                "Available": "98996.88",
                "CurrMargin": "1000",
                "Commission": "3.12",
            }
        ],
    )
    open_snapshot, open_state = host.reconcile(
        open_report, (binding,), open_at + timedelta(seconds=20)
    )
    assert open_state is not None and open_state.phase == "READY"
    assert len(open_state.fills) == 1 and open_state.fills[0].fee == D("3.12")
    due = a.manual_status(open_state, TEST_ID).due_at
    assert due == open_snapshot.at + timedelta(seconds=600)
    assert store.current().signals == ()

    hold_report = _report_from_snapshot(open_snapshot, due - timedelta(seconds=15))
    hold_snapshot, hold_state = host.reconcile(hold_report, (binding,), due)
    assert hold_state is not None and hold_state.phase == "READY"
    assert hold_snapshot.at < due < host.inventory[0].valid_until
    early_at = due - timedelta(seconds=1)
    early = store.execute(
        "manual-before-due",
        a.ManualTickV1(early_at, (_facts(early_at, 1010),), TEST_ID),
    )
    assert early.effects == () and len(api.calls) == 1
    close_at = due + timedelta(seconds=1)
    closing_facts = _facts(close_at, 1010)
    closed = store.execute(
        "manual-close", a.ManualTickV1(close_at, (closing_facts,), TEST_ID)
    )
    closing = closed.effects[0]
    assert closing.order.offset == "CLOSE" and closing.order.side == "SELL"
    assert host.submit_effects((closing,), (binding,), (closing_facts,), close_at) == (
        "REQUEST_ACCEPTED_AWAIT_NATIVE",
    )
    assert len(api.calls) == 2
    assert [req.CombOffsetFlag for _, req, _ in api.calls] == ["0", "3"]

    close_report = report_at(close_at + timedelta(seconds=3), f.ACCOUNT)
    close_report = changed(
        close_report,
        "orders",
        [
            *open_snapshot.data["orders"],
            _native_order(adapter, closing, close_at, closing=True),
        ],
    )
    close_report = changed(
        close_report,
        "trades",
        [
            *open_snapshot.data["trades"],
            _native_trade(closing, close_at, closing=True),
        ],
    )
    close_report = changed(close_report, "positions", [])
    close_funds = close_report["rounds"][0]["queries"]["funds"]["rows"][0]
    gross = (closing.order.price - open_state.fills[0].price) * D(10)
    fees = D("6.24")
    balance = D(100000) + gross - fees
    close_report = changed(
        close_report,
        "funds",
        [
            {
                **close_funds,
                "Balance": str(balance),
                "Available": str(balance),
                "CurrMargin": "0",
                "Commission": str(fees),
                "CloseProfit": str(gross),
            }
        ],
    )
    close_snapshot, final = host.reconcile(
        close_report, (binding,), close_at + timedelta(seconds=20)
    )
    assert final is not None and final.phase == "READY"
    result = acceptance(final, close_snapshot, TEST_ID, baseline=host.baseline)
    assert result["broker_roundtrip_passed"]
    assert result["actual_fees"] == "6.24"
    assert result["fees_reconciled"] and result["equity_reconciled"]
    assert final.signals == () and store.replay() == final
    assert [c[0] for c in api.calls] == ["insert", "insert"]
    adapter.journal.close()
    adapter.store.close()
    evidence.close()
