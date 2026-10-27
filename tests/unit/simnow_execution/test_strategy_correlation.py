"""Ordinary strategy fills across separate broker/client clocks; fixtures only."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import pytest
from guiyi_quant import htdy_account_execution as a, simnow_execution as b
from guiyi_quant.htdy_account_execution.codec import checkpoint, restore, load
from test_adapter import USER, setup, row, native_trade, correlated_snapshot


def strategy_adapter(ad, api, validator=lambda snapshot: None):
    return b.Adapter(ad.store, ad.journal, ad.sdk, api, USER, ad.session,
                     strategy_correlated_native=True, native_validator=validator)


def test_strategy_open_retains_raw_clock_requires_snapshot_and_actual_fee(tmp_path):
    ad, effect, facts, binding, permit, at, api = setup(tmp_path)
    verified = []
    adapter = strategy_adapter(ad, api, lambda snapshot: verified.append(snapshot.source_id))
    adapter.dispatch(effect, binding, None, facts, permit, at)
    adapter.order_callback(row(adapter, effect, at - timedelta(seconds=2), "0"), at + timedelta(seconds=1))
    adapter.trade_callback(native_trade(clock="10:00:58"), at + timedelta(seconds=1))
    assert adapter.drain() and not ad.store.current().fills
    snapshot = correlated_snapshot(adapter, effect, at)
    adapter.correlate_snapshot(snapshot)
    assert verified == [snapshot.source_id]
    assert adapter.drain()
    assert not ad.store.current().fills
    identity = adapter.drain()[0]
    adapter.fee(b.Fee(identity, Decimal(3), "ctp-commission-delta:fixture"), snapshot.at)
    assert adapter.drain() == ()
    fill = ad.store.current().fills[0]
    assert type(fill) is a.StrategyCorrelatedNativeFillV1
    assert fill.filled_at < fill.request_started_at
    assert fill.recorded_at == snapshot.at
    assert fill.correlation_policy_version == "simnow_strategy_correlated_fill_v1"
    assert load(checkpoint(ad.store.current())) == ad.store.current()
    assert restore(checkpoint(ad.store.current())).phase == "RECOVERY_REQUIRED"
    assert restore(checkpoint(ad.store.current())).fills == ad.store.current().fills
    assert ad.store.replay() == ad.store.current()
    adapter.drain()
    assert len(ad.store.current().fills) == len(api.calls) == 1


def test_strategy_protocol_cannot_skip_authoritative_session_validation(tmp_path):
    ad, effect, facts, binding, permit, at, api = setup(tmp_path)
    with pytest.raises(ValueError, match="NATIVE_CAPABILITY_INVALID"):
        b.Adapter(ad.store, ad.journal, ad.sdk, api, USER, ad.session,
                  strategy_correlated_native=True)
    def reject(_):
        raise ValueError("NATIVE_EVENT_SESSION_UNPROVEN")
    adapter = strategy_adapter(ad, api, reject)
    adapter.dispatch(effect, binding, None, facts, permit, at)
    with pytest.raises(ValueError, match="NATIVE_EVENT_SESSION_UNPROVEN"):
        adapter.correlate_snapshot(correlated_snapshot(adapter, effect, at))
    assert adapter._correlated_snapshot is None


def test_strategy_pending_trade_survives_restart_and_blocks_sends(tmp_path):
    ad, effect, facts, binding, permit, at, api = setup(tmp_path)
    adapter = strategy_adapter(ad, api)
    adapter.dispatch(effect, binding, None, facts, permit, at)
    adapter.trade_callback(native_trade(clock="10:00:58"), at + timedelta(seconds=1))
    restarted = strategy_adapter(ad, api)
    assert restarted.drain()
    with pytest.raises(ValueError, match="UNDRAINED_NATIVE_FACTS"):
        restarted._preflight(ad.store.current(), effect, binding, None, facts, permit, at)


def test_strategy_fill_requires_recorded_strategy_signal(tmp_path):
    ad, effect, _, _, _, at, _ = setup(tmp_path)
    command = a.StrategyCorrelatedNativeFillV1(
        "trade", effect.order.order_id, ad.session.account_id, effect.order.contract,
        at - timedelta(seconds=2), at + timedelta(seconds=1), effect.order.price,
        Decimal(3), 1, at, "dispatch:1", "sys", readback_source_id="snapshot",
        native_order_ref="11", native_front_id=1, native_session_id=2,
    )
    with pytest.raises(ValueError, match="STRATEGY_NATIVE_FILL_SIGNAL_REQUIRED"):
        a.apply(replace(ad.store.current(), signals=()), "no-signal", command)


@pytest.mark.parametrize('skew', [-120, -2, 2, 120])
def test_strategy_fact_does_not_compare_raw_clock_to_local_receipt(tmp_path, skew):
    ad, effect, _, _, _, at, _ = setup(tmp_path)
    fill = a.StrategyCorrelatedNativeFillV1(
        'skewed-native', effect.order.order_id, ad.session.account_id, effect.order.contract,
        at + timedelta(seconds=skew), at + timedelta(seconds=1), effect.order.price,
        Decimal(3), 1, at, 'dispatch:1', 'sys', readback_source_id='snapshot',
        native_order_ref='11', native_front_id=1, native_session_id=2,
    )
    ad.store.execute('skewed-fill', fill)
    assert ad.store.current().fills == (fill,)
    assert ad.store.replay() == ad.store.current()
    with pytest.raises(ValueError, match='NATIVE_FILL_PRECISION_INVALID'):
        replace(fill, request_started_at=fill.recorded_at + timedelta(seconds=1))


@pytest.mark.parametrize('field,value', [('InvestorID','other'),('OrderRef','999'),
    ('OrderSysID',''),('Direction','1'),('InstrumentID','al2612'),('OffsetFlag','3'),
    ('Volume',2),('Price',1001.0),('TradingDay','20261028')])
def test_strategy_unexplained_callback_faults_without_fill_or_resend(tmp_path, field, value):
    ad, effect, facts, binding, permit, at, api = setup(tmp_path)
    adapter = strategy_adapter(ad, api)
    adapter.dispatch(effect, binding, None, facts, permit, at)
    native = native_trade(clock='10:00:58')
    setattr(native, field, value)
    with pytest.raises(ValueError, match='NATIVE_CALLBACK_BLOCKED'):
        adapter.trade_callback(native, at+timedelta(seconds=1))
    assert adapter._faulted and not ad.store.current().fills
    assert len(api.calls) == 1
    assert any(payload['kind'] == 'fault' for _,payload,_ in ad.journal.events())


def test_strategy_snapshot_identity_drift_never_qualifies_pending(tmp_path):
    ad, effect, facts, binding, permit, at, api = setup(tmp_path)
    adapter = strategy_adapter(ad, api)
    adapter.dispatch(effect, binding, None, facts, permit, at)
    adapter.trade_callback(native_trade(clock='10:00:58'), at+timedelta(seconds=1))
    snapshot = correlated_snapshot(adapter, effect, at)
    with pytest.raises(ValueError, match='NATIVE_CORRELATION_SOURCE_INVALID'):
        adapter.correlate_snapshot(replace(snapshot, source_id='ctp-inventory:drifted'))
    assert adapter.drain() and not ad.store.current().fills


def test_strategy_pending_native_fill_is_recoverable_after_store_restart(tmp_path):
    ad, effect, facts, binding, permit, at, api = setup(tmp_path)
    adapter = strategy_adapter(ad, api)
    adapter.dispatch(effect, binding, None, facts, permit, at)
    adapter.trade_callback(native_trade(clock='10:00:58'), at+timedelta(seconds=1))
    assert adapter.drain()
    ad.store.close()
    ad.store = a.LocalStore(tmp_path/'account.db')
    restarted = strategy_adapter(ad, api)
    snapshot = correlated_snapshot(restarted, effect, at)
    restarted.correlate_snapshot(snapshot)
    restarted.order_callback(row(restarted,effect,at-timedelta(seconds=2),'0'),snapshot.at)
    pending = restarted.drain()
    assert pending
    trade_id = next(p['trade_id'] for _,p,_ in ad.journal.events() if p['kind']=='trade')
    restarted.fee(b.Fee(trade_id,Decimal(3),'ctp-commission-delta:fixture'),snapshot.at)
    assert restarted.drain() == ()
    assert type(ad.store.current().fills[0]) is a.StrategyCorrelatedNativeFillV1
    assert ad.store.current().phase == 'RECOVERY_REQUIRED'
    assert a.LocalStore.inspect(tmp_path/'account.db').fills == ad.store.current().fills
    assert len(api.calls) == 1


def test_strategy_protocol_does_not_enable_continuous_opening(tmp_path):
    from guiyi_quant.simnow_execution.evidence import Evidence
    from guiyi_quant.simnow_execution.host import Host
    ad, effect, facts, binding, permit, at, api = setup(tmp_path)
    adapter = strategy_adapter(ad, api)
    evidence = Evidence(tmp_path/'evidence.db',ad.session.account_id)
    host = Host(ad.store,ad.journal,evidence,adapter,('RB',),continuous=True,
                run_id='managed',deadline=None)
    with pytest.raises(ValueError,match='CONTINUOUS_OPEN_NOT_AUTHORIZED'):
        host.submit_effects((effect,),(binding,),(facts,),at)
    assert api.calls == [] and not ad.journal.claimed(effect.order.order_id)
    evidence.close()
