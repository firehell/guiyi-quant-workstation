"""Full native-report -> actual fee -> fill -> readback flow without network."""

from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
import importlib.util
import pytest
from test_inventory import report, changed, T
from guiyi_quant.simnow_execution.inventory import read_snapshot
from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.finance import performance
from guiyi_quant.simnow_execution.host import Host
from guiyi_quant import htdy_execution as h, htdy_account_execution as a

_spec = importlib.util.spec_from_file_location(
    "adapter_fixtures", Path(__file__).parents[1] / "simnow_execution/test_adapter.py"
)
f = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f)


def report_at(when, account):
    value = report()
    value["account_fingerprint"] = account
    for index, r in enumerate(value["rounds"]):
        start = when + timedelta(seconds=index * 10)
        r["started_at"] = start.isoformat()
        r["completed_at"] = (start + timedelta(seconds=2)).isoformat()
        for q in r["queries"].values():
            q["started_at"] = start.isoformat()
            q["completed_at"] = (start + timedelta(seconds=1)).isoformat()
    return value


def filled_report(ad, e, at, commission="3.12", multiple=False):
    value = report_at(at + timedelta(seconds=3), ad.session.account_id)
    order = f.row(ad, e, at, "0").__dict__.copy()
    order.pop("BrokerID")
    order.pop("InvestorID")
    order["LimitPrice"] = str(order["LimitPrice"])
    trade = f.native_trade().__dict__.copy()
    trade.pop("BrokerID")
    trade.pop("InvestorID")
    trade.pop("OrderRef")
    trade["Price"] = str(trade["Price"])
    trade["TradeID"] = "host-trade"
    value = changed(value, "orders", [order])
    value = changed(value, "trades", [trade])
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
    value = changed(value, "positions", [position])
    funds = value["rounds"][0]["queries"]["funds"]["rows"][0]
    value = changed(
        value,
        "funds",
        [
            {
                **funds,
                "Balance": "99996.88",
                "Available": "98996.88",
                "CurrMargin": "1000",
                "Commission": commission,
            }
        ],
    )
    if multiple:
        value = changed(value, "trades", [trade, {**trade, "TradeID": "second-trade"}])
    return value


def host_setup(tmp_path):
    ad, e, facts, b, p, at, api = f.setup(tmp_path)
    baseline = read_snapshot(
        report_at(at - timedelta(minutes=1), ad.session.account_id)
    )
    book = Evidence(tmp_path / "evidence.db", ad.session.account_id)
    book.append(baseline)
    host = Host(
        ad.store,
        ad.journal,
        book,
        ad,
        "RB",
        run_id="one",
        deadline=at + timedelta(minutes=10),
    )
    ad.dispatch(e, b, None, facts, p, at)
    return host, ad, e, facts, b, at, api


def test_real_shaped_fill_counter_and_readback_complete_without_fake_commission(
    tmp_path,
):
    host, ad, e, facts, b, at, api = host_setup(tmp_path)
    snapshot, state = host.reconcile(
        filled_report(ad, e, at), (b,), at + timedelta(seconds=20)
    )
    assert state.phase == "READY" and state.readback_valid
    assert state.fills[0].fee == D("3.12")
    assert state.positions[0].quantity == 1 and state.orders[0].reconciled
    assert state.reservations[0].released
    assert host.summary(snapshot)["performance"]["net_profit"] == "-3.12"
    host.reconcile(filled_report(ad, e, at), (b,), at + timedelta(seconds=20))
    assert len(ad.store.current().fills) == 1 and len(api.calls) == 1


def test_multiple_new_trades_preserve_pending_and_block_new_send(tmp_path):
    host, ad, e, facts, b, at, api = host_setup(tmp_path)
    snapshot, state = host.reconcile(
        filled_report(ad, e, at, multiple=True), (b,), at + timedelta(seconds=20)
    )
    assert state is None and len(host.pending) == 2
    assert ad.store.current().fills == ()
    assert not ad.store.current().readback_valid
    assert len(host.evidence.snapshots()) == 2


def test_restart_after_snapshot_before_fee_reconstructs_actual_proof(tmp_path):
    host, ad, e, facts, b, at, api = host_setup(tmp_path)
    report = filled_report(ad, e, at)
    host.evidence.append(read_snapshot(report))
    ad.store.close()
    ad.store = a.LocalStore(tmp_path / "account.db")
    host = Host(
        ad.store,
        ad.journal,
        host.evidence,
        ad,
        "RB",
        run_id="restarted",
        deadline=at + timedelta(minutes=10),
    )
    proof = h.RecoveryInput(
        "RB", "RB2701", 1, T + timedelta(minutes=60), "complete-input"
    )
    _, state = host.reconcile(report, (b,), at + timedelta(seconds=20), (proof,))
    assert len(state.fills) == 1 and state.fills[0].fee == D("3.12")
    assert state.phase == "READY" and state.readback_valid
    assert ad.store.replay() == state


def test_unclaimed_local_proposal_can_abort_but_claimed_never_releases(tmp_path):
    ad, e, facts, b, p, at, api = f.setup(tmp_path)
    result = ad.abort_unsent(e.order.order_id, "LOCAL_QUOTE_STALE", at)
    assert result.state.orders[0].status == "LOCAL_ABORTED"
    assert result.state.reservations[0].released
    assert ad.store.replay() == result.state
    assert api.calls == []


def test_claimed_unknown_order_cannot_use_local_abort(tmp_path):
    host, ad, e, facts, b, at, api = host_setup(tmp_path)
    with pytest.raises(ValueError):
        ad.abort_unsent(e.order.order_id, "NO_SEND", at)
    assert not ad.store.current().reservations[0].released


def test_cross_day_performance_keeps_cashflow_unproven():
    from dataclasses import replace

    base = read_snapshot(report())
    other = replace(base, trading_day="20261028", at=base.at + timedelta(days=1))
    summary = performance(base, other)
    assert (
        summary.status == "CASHFLOW_CONTINUITY_REQUIRED" and summary.net_profit is None
    )


def test_late_known_trade_without_fee_relocks_prior_released_reservation(tmp_path):
    host, ad, e, facts, b, at, api = host_setup(tmp_path)
    ad.order_callback(f.row(ad, e, at, "5"), at + timedelta(seconds=1))
    ad.drain()
    rb = a.Readback(
        h.AccountSnapshot(
            ad.session.account_id,
            at + timedelta(seconds=2),
            D(100000),
            D(100000),
            (),
            (h.OrderReport(e.order.order_id, "CANCELLED"),),
            (e.order.order_id,),
        ),
        D(0),
        D(0),
        D(0),
        (),
        (),
        "cancel-complete",
        at + timedelta(minutes=1),
        True,
    )
    ad.store.execute("cancel-readback", rb)
    assert ad.store.current().reservations[0].released
    identity = ad.trade_callback(f.native_trade(), at + timedelta(seconds=3))
    assert ad.drain() == (identity,)
    assert not ad.store.current().reservations[0].released
    assert not ad.store.current().readback_valid
    assert ad.store.current().fills == ()


def test_restart_proven_never_claimed_proposal_does_not_deadlock_recovery(tmp_path):
    ad, e, facts, b, p, at, api = f.setup(tmp_path)
    ad.store.close()
    ad.store = a.LocalStore(tmp_path / "account.db")
    ad.abort_unsent(
        e.order.order_id, "RESTART_VERIFIED_NEVER_CLAIMED", at + timedelta(seconds=1)
    )
    assert ad.store.current().phase == "RECOVERY_REQUIRED"
    assert ad.store.current().orders[0].status == "LOCAL_ABORTED"
    assert ad.store.current().reservations[0].released
    assert api.calls == []
    assert ad.store.replay().orders[0].status == "LOCAL_ABORTED"
