"""Ordinary signal -> native OPEN/CLOSE/reversal readbacks, entirely isolated."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo
import pytest
from guiyi_quant import htdy_account_execution as a, htdy_execution as h, simnow_execution as b
from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.host import Host
from guiyi_quant.simnow_execution.inventory import read_snapshot
from guiyi_quant.simnow_execution.strategy_native import validate_strategy_events
from test_host import f, report_at
from test_inventory import changed

SH = ZoneInfo('Asia/Shanghai')


@pytest.mark.parametrize('initial_side', [1, -1])
def test_real_shaped_normal_signal_reverses_only_after_close_readback(tmp_path, initial_side):
    ad, _unused, facts, binding, _permit, at, api = f.setup(tmp_path)
    initial = a.start(f.ACCOUNT, ('RB',), f.T, ad.store.current().initial_readback)
    initial = a.apply(initial, 'owner', h.Owner('RB', 'RB2701', f.T, 'owner')).state
    ad.store.close()
    store = a.LocalStore(tmp_path / 'normal.db', initial)
    journal = ad.journal
    proofs = []
    def authority(product, day, raw, contract):
        proofs.append((product, day, raw, contract))
        return NS(contract=contract, owner='RB2705', exchange='SHFE', session=facts.session)
    def validator(snapshot):
        validate_strategy_events(snapshot, authority, journal, store.current())
    adapter = b.Adapter(store, journal, ad.sdk, api, f.USER, ad.session,
                        strategy_correlated_native=True, native_validator=validator)
    evidence = Evidence(tmp_path / 'native.db', f.ACCOUNT)
    evidence.append(read_snapshot(report_at(at - timedelta(seconds=20), f.ACCOUNT)))
    host = Host(store, journal, evidence, adapter, 'RB', max_submits=3,
                run_id='normal', deadline=f.T + timedelta(hours=3))
    orders, trades = [], []
    commission = D(0)
    def materialize(when, held, order, fill_price):
        nonlocal commission
        bound = journal.find(order.order_id)
        raw = (when - timedelta(seconds=2)).astimezone(SH)
        native = dict(TradingDay='20261027', OrderRef=bound['order_ref'],
            FrontID=bound['front_id'], SessionID=bound['session_id'], InstrumentID='rb2701',
            ExchangeID='SHFE', Direction='0' if order.side == 'BUY' else '1',
            CombOffsetFlag=bound['offset'], CombHedgeFlag='1', LimitPrice=str(order.price),
            VolumeTotalOriginal=1, VolumeTraded=1, VolumeTotal=0, OrderStatus='0',
            OrderSubmitStatus='3', OrderSysID='sys-' + str(len(orders)),
            InsertDate=raw.strftime('%Y%m%d'), InsertTime=raw.strftime('%H:%M:%S'))
        orders.append(native)
        trades.append(dict(TradingDay='20261027', ExchangeID='SHFE', InstrumentID='rb2701',
            TradeID='trade-' + str(len(trades)), OrderSysID=native['OrderSysID'],
            Direction=native['Direction'], OffsetFlag=native['CombOffsetFlag'], HedgeFlag='1',
            TradeDate=native['InsertDate'], TradeTime=native['InsertTime'], Price=str(fill_price), Volume=1))
        commission += D('3.12')
        return snapshot(when + timedelta(seconds=3), held)
    def snapshot(when, held):
        report = report_at(when, f.ACCOUNT)
        for kind, rows in [('orders', orders), ('trades', trades), ('positions', [] if not held else [dict(
            TradingDay='20261027', ExchangeID='SHFE', InstrumentID='rb2701',
            PosiDirection='2' if held == 1 else '3', HedgeFlag='1', PositionDate='1',
            Position=1, TodayPosition=1, YdPosition=0, LongFrozen=0, ShortFrozen=0)])]:
            report = changed(report, kind, rows)
        funds = report['rounds'][0]['queries']['funds']['rows'][0]
        return changed(report, 'funds', [{**funds, 'Balance':str(D(100000)-commission),
            'Available':str(D(100000)-commission-(D(1000) if held else 0)),
            'CurrMargin':'1000' if held else '0', 'Commission':str(commission)}])
    def signal(end, side, identity):
        store.execute(identity, h.Signal(identity,'RB','RB2701',end,end+timedelta(seconds=2),
                                        store.current().products[0].last_bar,('buy' if side == 1 else 'sell',),'a'*64))
    def tick(when):
        fresh = replace(facts, quote=replace(facts.quote, at=when, valid_until=when+timedelta(seconds=10)))
        return host.tick((fresh,), (binding,), when)
    signal(at-timedelta(seconds=3), initial_side, 'first-natural')
    assert tick(at) == ('REQUEST_ACCEPTED_AWAIT_NATIVE',)
    opened = store.current().orders[-1]
    report = materialize(at, initial_side, opened, opened.price)
    # Stream and complete snapshot may disagree with the local clock; no priced Fill yet.
    native = orders[-1]
    adapter.order_callback(NS(**native, BrokerID='9999', InvestorID=f.USER), at+timedelta(seconds=1))
    assert adapter.drain()
    _, state = host.reconcile(report, (binding,), at+timedelta(seconds=20))
    assert state and state.positions[0].quantity == initial_side
    assert state.fills[0].filled_at < state.fills[0].request_started_at
    next_at = at + timedelta(minutes=60)
    host.reconcile(snapshot(next_at-timedelta(seconds=15), initial_side), (binding,), next_at)
    signal(next_at, -initial_side, 'reverse-natural')
    assert tick(next_at+timedelta(seconds=3)) == ('REQUEST_ACCEPTED_AWAIT_NATIVE',)
    closing = store.current().orders[-1]
    assert closing.offset == 'CLOSE' and journal.find(closing.order_id)['offset'] == '3'
    tick(next_at+timedelta(seconds=4))
    assert len(api.calls) == 2  # No reverse OPEN until actual CLOSE is reconciled.
    close_report = materialize(next_at+timedelta(seconds=3), 0, closing, closing.price)
    _, flat = host.reconcile(close_report, (binding,), next_at+timedelta(seconds=25))
    assert flat and not flat.positions and all(o.reconciled for o in flat.orders)
    assert tick(next_at+timedelta(seconds=26)) == ('REQUEST_ACCEPTED_AWAIT_NATIVE',)
    reverse = store.current().orders[-1]
    assert reverse.offset == 'OPEN' and reverse.side != opened.side
    report = materialize(next_at+timedelta(seconds=26), -initial_side, reverse, reverse.price)
    _, final = host.reconcile(report, (binding,), next_at+timedelta(seconds=45))
    assert final and final.positions[0].quantity == -initial_side
    assert len(final.fills) == 3
    assert all(type(fill) is a.StrategyCorrelatedNativeFillV1 for fill in final.fills)
    assert store.replay() == final
    assert not any(type(audit.command) is a.ManualBeginV1 for audit in final.audit)
    assert proofs and all(proof[3] == 'RB2701' for proof in proofs)  # old physical, not owner RB2705
    host.reconcile(report, (binding,), next_at+timedelta(seconds=45))
    assert len(store.current().fills) == len(api.calls) == 3
    evidence.close()
    journal.close()
    store.close()
