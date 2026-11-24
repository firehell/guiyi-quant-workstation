from datetime import timedelta
from threading import Event
import os

import pytest

from gateway import NativeFill, NativeOrder, OrderStatus, Position, VeighNaOfflineGateway


def test_p2_to_real_veighna_callbacks_to_pg(scenario):
    if not os.getenv('GUIYI_VNPY_PROBE_DIR'):
        pytest.skip('native gateway test requires macOS sandbox-exec')
    from vnpy.event import Event as NativeEvent
    from vnpy_ctp import api
    from vnpy_ctp.gateway.ctp_gateway import symbol_contract_map

    holder = {}
    problems = []
    native = VeighNaOfflineGateway(
        on_event=lambda event, **scope: holder['host'].callback(event, **scope),
        on_error=problems.append,
        on_completed=lambda envelope, window, **scope: holder['host'].receive_observation(envelope, window, **scope),
        on_send=lambda _request: '7_13_42',
    )
    scenario.gateway = native
    drained = Event()
    native.events.register('fixture.barrier', lambda _event: drained.set())

    def drain():
        drained.clear()
        native.events.put(NativeEvent('fixture.barrier'))
        assert drained.wait(timeout=4)

    symbol = 'rb2701'
    market_day = scenario.day.strftime('%Y%m%d')
    try:
        with scenario.host() as host:
            holder['host'] = host
            with pytest.raises(RuntimeError, match='P5_OFFLINE_ONLY'):
                native.main.connect({}, 'P5_OFFLINE')
            native.native.td_api.onRspQryInstrument({
                'InstrumentID': symbol, 'ExchangeID': 'SHFE', 'InstrumentName': 'Fixture future',
                'ProductClass': api.THOST_FTDC_PC_Futures, 'VolumeMultiple': 10, 'PriceTick': 1.0,
                'MinLimitOrderVolume': 1, 'MaxLimitOrderVolume': 10,
            }, {'ErrorID': 0, 'ErrorMsg': ''}, 1, True)
            drain()
            assert native.template.inited and not native.template.trading
            scenario.prepare_builds(host, ('RB',))
            seal = scenario.signal_end + timedelta(seconds=4)
            host.advance(seal)
            assert [p['request'] for p in native.sends] == [['RB2701', 'SHFE', 'LONG', 'OPEN', '100.0', 1]]
            order = {
                'InstrumentID': symbol, 'ExchangeID': 'SHFE', 'TradingDay': market_day,
                'FrontID': 7, 'SessionID': 13, 'OrderRef': '42', 'OrderSysID': ' 000089',
                'OrderStatus': api.THOST_FTDC_OST_AllTraded, 'InsertDate': market_day, 'InsertTime': '09:50:04',
                'OrderPriceType': api.THOST_FTDC_OPT_LimitPrice, 'TimeCondition': api.THOST_FTDC_TC_GFD,
                'VolumeCondition': api.THOST_FTDC_VC_AV, 'Direction': api.THOST_FTDC_D_Buy,
                'CombOffsetFlag': api.THOST_FTDC_OFEN_Open, 'LimitPrice': 100, 'VolumeTotalOriginal': 1,
                'VolumeTraded': 1, 'OrderSubmitStatus': api.THOST_FTDC_OSS_Accepted, 'StatusMsg': '',
            }
            trade = {
                'InstrumentID': symbol, 'ExchangeID': 'SHFE', 'TradingDay': market_day,
                'OrderSysID': ' 000089', 'TradeID': '000101', 'TradeDate': market_day, 'TradeTime': '09:50:05',
                'Direction': api.THOST_FTDC_D_Buy, 'OffsetFlag': api.THOST_FTDC_OFEN_Open,
                'Price': 100, 'Volume': 1,
            }
            tail = seal + timedelta(seconds=1)
            native.push_ctp('order', order, generation=scenario.generation, sequence=1, known_at=seal)
            native.push_ctp('trade', trade, generation=scenario.generation, sequence=2, known_at=tail)
            native.push_ctp('trade', trade.copy(), generation=scenario.generation, sequence=3, known_at=tail)
            drain()
            assert problems == []
            assert host.status()['watermark'] == 3
            assert host.status()['status'] == 'RECONCILING'
            fills = host.store.projection('fills')['data']
            assert len(fills) == 1 and fills[0]['native_trade_id'] == '000101'
            converter = native.main.get_converter('P5_OFFLINE')
            assert converter.get_position_holding(f'{symbol}.SHFE').long_td == 1
            terminal = NativeOrder('SHFE', 'RB2701', scenario.day, '7_13_42', 1, 1, OrderStatus.FILLED)
            fill = NativeFill('SHFE', 'RB2701', scenario.day, '7_13_42', '000101', 1, scenario.D(100),
                              seal + timedelta(seconds=1))
            snap = scenario.snapshot(at=seal + timedelta(seconds=1), through=3, cash='10', margin='100',
                                     positions=(Position('SHFE', 'RB2701', 'RB', 1, 1, 0),),
                                     orders=(terminal,), fills=(fill,))
            assert host.reconcile(snap)
            assert host.store.projection('positions')['data'][0]['quantity'] == 1
            assert host.store.projection('orders')['data'][-1]['reserved'] == '0'
    finally:
        native.close()
        symbol_contract_map.pop(symbol, None)


def test_verified_prior_position_closes_in_a_cold_native_engine(scenario):
    if not os.getenv('GUIYI_VNPY_PROBE_DIR'):
        pytest.skip('native gateway test requires macOS sandbox-exec')
    from vnpy.event import Event as NativeEvent
    from vnpy_ctp import api
    from vnpy_ctp.gateway.ctp_gateway import symbol_contract_map

    from risk import ManagementPermit

    symbol = 'rb2701'
    native = VeighNaOfflineGateway(on_event=lambda *args, **kwargs: None, on_error=lambda _reason: None,
                                  on_completed=lambda *args, **kwargs: None)
    scenario.gateway = native
    try:
        with scenario.host() as host:
            native.native.td_api.onRspQryInstrument({
                'InstrumentID': symbol, 'ExchangeID': 'SHFE', 'InstrumentName': 'Fixture future',
                'ProductClass': api.THOST_FTDC_PC_Futures, 'VolumeMultiple': 10, 'PriceTick': 1.0,
                'MinLimitOrderVolume': 1, 'MaxLimitOrderVolume': 10,
            }, {'ErrorID': 0, 'ErrorMsg': ''}, 1, True)
            drained = Event()
            native.events.register('fixture.cold.barrier', lambda _event: drained.set())
            native.events.put(NativeEvent('fixture.cold.barrier'))
            assert drained.wait(timeout=4)
            host.activate(scenario.scope(('RB',)), expected_revision=None, supported=('RB',))
            host.register_policy(scenario.policy('RB'))
            host.activate(scenario.scope((), revision='r2'), expected_revision='r1', supported=('RB',))
            assert host.reconcile(scenario.snapshot(positions=(Position('SHFE', 'RB2701', 'RB', 1, 0, 0),)))
            assert native.main.get_all_positions() == []
            at = scenario.signal_end
            scenario.quoted(host, 'RB')
            permit = ManagementPermit('cold-native-close', 'r2', 'RB', 'SHFE', 'RB2701', scenario.day,
                                      (scenario.start, scenario.start + timedelta(hours=3)), at,
                                      at + timedelta(seconds=10), 1)
            host.manage_existing(permit, now=at + timedelta(seconds=1))
            assert [i['request'] for i in native.sends] == [['RB2701', 'SHFE', 'SHORT', 'CLOSEYESTERDAY', '99.0', 1]]
    finally:
        native.close()
        symbol_contract_map.pop(symbol, None)
