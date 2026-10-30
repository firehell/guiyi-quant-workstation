"""Offline unknown OPEN recovery through a close-only correlated native Host."""

from datetime import datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from guiyi_quant import htdy_account_execution as a, simnow_execution as b
from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.host import Host
from guiyi_quant.simnow_execution.inventory import project_readback, read_snapshot
from guiyi_quant.simnow_execution.manual_host import acceptance
from test_host import f, report_at
from test_inventory import changed
from test_manual_integration import (
    SHANGHAI,
    TEST_ID,
    _facts,
    _native_order,
    _native_trade,
    _report_from_snapshot,
)


def _full_report(
    at,
    account,
    orders,
    trades,
    positions,
    *,
    balance,
    available,
    margin,
    commission,
    close_profit="0",
):
    report = report_at(at, account)
    for kind, rows in (
        ("orders", orders),
        ("trades", trades),
        ("positions", positions),
    ):
        report = changed(report, kind, rows)
    funds = report["rounds"][0]["queries"]["funds"]["rows"][0]
    return changed(
        report,
        "funds",
        [
            {
                **funds,
                "Balance": str(balance),
                "Available": str(available),
                "CurrMargin": str(margin),
                "Commission": str(commission),
                "CloseProfit": str(close_profit),
            }
        ],
    )


def test_unknown_open_raw_clock_skew_recovers_then_only_closes(tmp_path):
    open_at = f.T + timedelta(minutes=61, milliseconds=785)
    baseline = read_snapshot(report_at(open_at - timedelta(seconds=20), f.ACCOUNT))
    binding = b.Contract(
        "RB2701", "rb2701", "SHFE", "native-instrument", f.T, f.T + timedelta(hours=3)
    )
    rb, inventory = project_readback(
        baseline, (binding,), None, None, open_at + timedelta(seconds=30)
    )
    assert inventory == ()
    initial = a.start(f.ACCOUNT, ("RB",), baseline.at, rb)
    initial = a.apply(
        initial,
        "owner",
        f.h.Owner(
            "RB",
            "RB2701",
            baseline.at,
            "owner:RB",
        ),
    ).state
    store = a.LocalStore(tmp_path / "account.db", initial)
    journal = b.Journal(tmp_path / "dispatch.db", f.ACCOUNT)
    evidence = Evidence(tmp_path / "evidence.db", f.ACCOUNT)
    evidence.append(baseline)
    api = f.FakeApi()
    api.error = True
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
    strict_adapter = b.Adapter(store, journal, sdk, api, f.USER, session)
    strict_host = Host(
        store,
        journal,
        evidence,
        strict_adapter,
        "RB",
        run_id="manual-initial",
        deadline=open_at + timedelta(minutes=2),
        manual_test_id=TEST_ID,
    )
    assert strict_host.baseline == baseline and initial.signals == ()
    store.execute(
        "begin",
        a.ManualBeginV1(
            TEST_ID,
            "RB",
            "RB2701",
            open_at - timedelta(seconds=1),
            open_at + timedelta(minutes=1),
        ),
    )
    open_facts = _facts(open_at, 1000)
    opened = store.execute("open", a.ManualTickV1(open_at, (open_facts,), TEST_ID))
    opening = opened.effects[0]
    assert strict_host.submit_effects(
        (opening,), (binding,), (open_facts,), open_at
    ) == ("SEND_OUTCOME_UNKNOWN",)
    assert len(api.calls) == 1 and api.calls[0][0] == "insert"
    claimed_open = journal.find(opening.order.order_id)
    assert open_at <= datetime.fromisoformat(claimed_open["request_started_at"]) < open_at + timedelta(seconds=1)

    raw_at = open_at - timedelta(seconds=2)
    native_order = _native_order(strict_adapter, opening, raw_at)
    native_trade = _native_trade(opening, raw_at)
    raw_order_at = datetime.strptime(
        native_order["InsertDate"] + native_order["InsertTime"], "%Y%m%d%H:%M:%S"
    ).replace(tzinfo=SHANGHAI)
    raw_trade_at = datetime.strptime(
        native_trade["TradeDate"] + native_trade["TradeTime"], "%Y%m%d%H:%M:%S"
    ).replace(tzinfo=SHANGHAI)
    assert raw_order_at == raw_trade_at < open_at - timedelta(seconds=2)
    order_callback = SimpleNamespace(**native_order, BrokerID="9999", InvestorID=f.USER)
    trade_callback = SimpleNamespace(
        **native_trade,
        BrokerID="9999",
        InvestorID=f.USER,
        OrderRef=claimed_open["order_ref"],
    )
    with pytest.raises(ValueError, match="NATIVE_CALLBACK_BLOCKED"):
        strict_adapter.order_callback(order_callback, open_at + timedelta(seconds=3))
    strict_adapter.trade_callback(trade_callback, open_at + timedelta(seconds=3))
    pending = strict_adapter.drain()
    assert pending and store.current().fills == ()
    assert any(p["kind"] == "fault" for _, p, _ in journal.events())
    assert store.current().phase != "READY"
    prior_receipts = dict(store.replay().receipts)

    # Restart with the same immutable journals, a fresh adapter, and close-only power.
    store.close()
    store = a.LocalStore(tmp_path / "account.db")
    journal.close()
    journal = b.Journal(tmp_path / "dispatch.db", f.ACCOUNT)
    api.error = False
    correlated_adapter = b.Adapter(
        store,
        journal,
        sdk,
        api,
        f.USER,
        session,
        close_only=True,
        correlated_native=True,
    )
    approved = {}

    def authorize(report):
        snapshot = read_snapshot(report)
        approved[snapshot.source_id] = snapshot
        return report

    def native_validator(snapshot):
        if approved.get(snapshot.source_id) != snapshot:
            raise ValueError("UNAUTHORIZED_NATIVE_FIXTURE")

    host = Host(
        store,
        journal,
        evidence,
        correlated_adapter,
        "RB",
        run_id="manual-close-only",
        deadline=open_at + timedelta(minutes=2),
        manual_test_id=TEST_ID,
        close_only=True,
        native_validator=native_validator,
    )
    assert host.baseline == baseline
    position = dict(
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
    open_report = authorize(
        _full_report(
            open_at + timedelta(seconds=3),
            f.ACCOUNT,
            [native_order],
            [native_trade],
            [position],
            balance="99996.88",
            available="98996.88",
            margin="1000",
            commission="3.12",
        )
    )
    proof = f.h.RecoveryInput("RB", "RB2701", 1, f.T, "manual-native-recovery")
    open_snapshot, recovered = host.reconcile(
        open_report, (binding,), open_at + timedelta(seconds=20), (proof,)
    )
    assert recovered is not None and recovered.phase == "READY"
    assert len(recovered.fills) == 1
    fill = recovered.fills[0]
    assert type(fill) is a.CorrelatedNativeFillV1
    assert fill.filled_at < fill.request_started_at
    assert fill.recorded_at == open_snapshot.at
    assert fill.readback_source_id == open_snapshot.source_id
    assert fill.fee == D("3.12")
    assert recovered.signals == () and recovered.positions[0].quantity == 1
    due = a.manual_status(recovered, TEST_ID).due_at
    assert due == open_snapshot.at + timedelta(seconds=600)
    assert len(api.calls) == 1

    hold_report = authorize(
        _report_from_snapshot(
            open_snapshot,
            due - timedelta(seconds=15),
        )
    )
    hold_snapshot, holding = host.reconcile(hold_report, (binding,), due)
    assert holding is not None and holding.phase == "READY"
    assert hold_snapshot.at < due < host.inventory[0].valid_until
    early_at = due - timedelta(seconds=1)
    assert (
        store.execute(
            "early",
            a.ManualTickV1(
                early_at,
                (_facts(early_at, 1010),),
                TEST_ID,
            ),
        ).effects
        == ()
    )
    assert len(api.calls) == 1
    close_at = due + timedelta(seconds=1)
    close_facts = _facts(close_at, 1010)
    closing = store.execute(
        "close",
        a.ManualTickV1(
            close_at,
            (close_facts,),
            TEST_ID,
        ),
    ).effects[0]
    assert closing.order.offset == "CLOSE"
    assert host.submit_effects((closing,), (binding,), (close_facts,), close_at) == (
        "REQUEST_ACCEPTED_AWAIT_NATIVE",
    )
    assert [req.CombOffsetFlag for _, req, _ in api.calls] == ["0", "3"]

    close_order = _native_order(correlated_adapter, closing, close_at, closing=True)
    close_trade = _native_trade(closing, close_at, closing=True)
    gross = (closing.order.price - fill.price) * D(10)
    fees = D("6.24")
    balance = D(100000) + gross - fees
    close_report = authorize(
        _full_report(
            close_at + timedelta(seconds=3),
            f.ACCOUNT,
            [native_order, close_order],
            [native_trade, close_trade],
            [],
            balance=balance,
            available=balance,
            margin="0",
            commission=fees,
            close_profit=gross,
        )
    )
    close_snapshot, final = host.reconcile(
        close_report, (binding,), close_at + timedelta(seconds=20)
    )
    assert final is not None and final.phase == "READY"
    result = acceptance(final, close_snapshot, TEST_ID, baseline=host.baseline)
    assert result["broker_roundtrip_passed"]
    assert result["fees_reconciled"] and result["equity_reconciled"]
    assert final.signals == () and store.replay() == final
    assert all(
        dict(final.receipts)[key] == value for key, value in prior_receipts.items()
    )
    assert len(api.calls) == 2 and [call[0] for call in api.calls] == [
        "insert",
        "insert",
    ]
    store.close()
    journal.close()
    evidence.close()
