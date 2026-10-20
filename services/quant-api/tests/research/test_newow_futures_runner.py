"""Offline matrix and one-shot collector validation; constructed evidence only."""
from datetime import date
from decimal import Decimal as D
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts.research.newow_futures_execution_facts import (
    FactsCaptureError, MAX_BYTES, PRODUCTS, capture, make_plan, validate_plan,
)


def plan():
    products = {p:{p.upper()+'2505':{'start':'2025-01-02','end':'2025-01-02','days':['2025-01-02'],'requested_days':['2025-01-02']}}
                for p in PRODUCTS}
    return make_plan(products,code_revision='a'*40)


def test_plan_binds_dates_methods_budget_and_code():
    frozen = plan()
    assert frozen['max_logical_calls'] == 18
    validate_plan(frozen)
    frozen['products']['jm']['JM2505']['days'].append('2025-01-03')
    with pytest.raises(FactsCaptureError,match='FACTS_PLAN_INVALID'):
        validate_plan(frozen)


def _api():
    import pandas as pd
    def frame(contract, start_date, end_date, fields, **kwargs):
        numbers = {'commission_type':'by_volume','long_margin_ratio':'0.1','short_margin_ratio':'0.1',
                   'open_commission':'1','close_commission':'2','close_commission_today':'3',
                   'settlement':'100','prev_settlement':'99','limit_up':'110','limit_down':'90'}
        return pd.DataFrame([{'order_book_id':contract,'date':start_date,**{f:numbers[f] for f in fields}}])
    return SimpleNamespace(user=SimpleNamespace(get_quota=lambda:{'bytes_limit':MAX_BYTES*2,'bytes_used':0}),
        instruments=lambda c:SimpleNamespace(order_book_id=c,tick_size=lambda:D('0.5'),contract_multiplier=60),
        futures=SimpleNamespace(get_trading_parameters=frame,get_exchange_daily=frame),get_price=frame)


def test_capture_has_exact_4n_plus_2_calls_and_fresh_attempt_boundary(tmp_path):
    out = tmp_path/'attempt'
    capture(plan(),settings={},out=out,api_factory=_api)
    events = [json.loads(row) for row in (out/'journal.jsonl').read_text().splitlines()]
    assert len([row for row in events if row['state']=='started']) == 18
    assert all(row['state'] != 'failed' for row in events)
    assert json.loads((out/'jm.json').read_text())['contracts']['JM2505']['daily'][0]['limit_down'] == '90'
    with pytest.raises(FileExistsError):
        capture(plan(),settings={},out=out,api_factory=lambda:pytest.fail('no retry'))


def test_partial_fee_failure_retains_every_instrument_and_never_retries(tmp_path):
    api = _api()
    calls = []
    def fail(*args,**kwargs):
        calls.append(args[0])
        raise RuntimeError('secret must never be emitted')
    api.futures.get_trading_parameters = fail
    out = tmp_path/'attempt'
    with pytest.raises(FactsCaptureError,match='PROVIDER_CAPTURE_FAILED'):
        capture(plan(),settings={},out=out,api_factory=lambda:api)
    assert calls == ['JM2505']
    assert all((out/f'{product}-ticks.json').exists() for product in PRODUCTS)
    assert 'secret' not in (out/'journal.jsonl').read_text()
    assert not (out/'jm.json').exists()


def _install_engine(monkeypatch):
    engine = ModuleType('guiyi_quant.newow_futures.engine')
    engine.run_research = lambda *args,**kwargs:pytest.fail('blocked input must not run account')
    monkeypatch.setitem(sys.modules,engine.__name__,engine)


def test_missing_product_still_emits_each_of_144_typed_cells(monkeypatch):
    _install_engine(monkeypatch)
    from scripts.research.newow_futures import run_matrix
    packets = list(run_matrix(product='jm',source=None,facts_dir=None,code_revision='a'*40,
                              input_error={'code':'DATA_INSUFFICIENT'}))
    assert len(packets) == 144
    assert len({(p['metadata']['strategy'],p['metadata']['frequency'],p['metadata']['scenario']) for p in packets}) == 144
    assert sum(p['metadata']['status']=='NOT_APPLICABLE' for p in packets) == 3
    assert all(p['summary']['final_equity'] is None for p in packets)


def test_source_object_without_any_verified_bar_does_not_claim_current_data_cutoff():
    from scripts.research.newow_futures import build_packet
    from guiyi_quant.newow_futures import Profile, Variant
    empty = SimpleNamespace(bars_by_frequency={}, diagnostics={}, gaps_by_frequency={}, input_snapshot_hash='a'*64)
    value = build_packet(product='jm', profile=Profile(Variant.TREND, '5m'), scenario='baseline',
                         code_revision='b'*40, status='DATA_INSUFFICIENT', source=empty)
    assert value['metadata']['as_of_kind'] == 'publication_time_only'


def test_packet_direct_call_derives_cutoff_from_verified_input():
    from datetime import datetime, UTC
    from scripts.research.newow_futures import build_packet
    from guiyi_quant.newow_futures import Profile, Variant
    at = datetime(2026, 10, 19, 7, tzinfo=UTC)
    source = SimpleNamespace(bars_by_frequency={'5m': [SimpleNamespace(
        confirmed_at=at, observation_eligible=True)]}, diagnostics={},
        gaps_by_frequency={}, input_snapshot_hash='a'*64)
    value = build_packet(product='jm', profile=Profile(Variant.TREND, '5m'),
                         scenario='baseline', code_revision='b'*40,
                         status='COMPLETED', source=source)
    assert value['metadata']['as_of'] == at.isoformat()
    assert value['metadata']['as_of_kind'] == 'verified_completed_input'


def test_missing_fees_preserve_independent_reference_and_decimal_packet(monkeypatch):
    _install_engine(monkeypatch)
    import scripts.research.newow_futures as runner
    from app.market_data.newow_futures_research import NewowFuturesInputError
    from guiyi_quant.newow_futures import reference
    source = SimpleNamespace(bars_by_frequency={}, minute_bars=(),input_snapshot_hash='b'*64,
                             diagnostics={'minute_complete':True},gaps_by_frequency={})
    monkeypatch.setattr(runner,'read_product_facts',lambda *args:({},{}))
    def missing(*args,**kwargs):
        raise NewowFuturesInputError('EXECUTION_FACTS_MISSING')
    monkeypatch.setattr(runner,'load_execution_facts',missing)
    monkeypatch.setattr(runner,'load_reference_ticks',lambda *args,**kwargs:{('JM2505',date(2025,1,2)):D('0.5')})
    calls = []
    def project(profile,*args,**kwargs):
        calls.append(profile.profile_id)
        return {'summary':{'status':'COMPLETED','executable':False},'snapshot':{'side':'LONG'},
                'trades':[],'actions':[],'equity':[],
                'chart':{'bars':[{'close':D('123.5')}]*2100,'frames':[]}}
    monkeypatch.setattr(reference,'run_reference',project)
    packets = list(runner.run_matrix(product='jm',source=source,facts_dir=None,code_revision='a'*40))
    assert len(calls) == 47
    packet = packets[0]
    assert packet['metadata']['status'] == 'EXECUTION_FACTS_MISSING'
    assert packet['reference']['snapshot']['side'] == 'LONG'
    assert len(packet['chart']['bars']) == 2000 and packet['chart']['bars'][0]['close'] == '123.5'
    assert packet['summary']['final_equity'] is None


def test_minute_gap_blocks_both_paths_but_keeps_known_price_chart(monkeypatch):
    _install_engine(monkeypatch)
    import scripts.research.newow_futures as runner
    from app.market_data.newow_futures_research import load_newow_futures_inputs
    from guiyi_quant.newow_futures import reference
    from .test_newow_futures_inputs import Market, DAY
    source = load_newow_futures_inputs(Market(('1m',)),product='jm',since=DAY,through=DAY)
    monkeypatch.setattr(reference,'run_reference',lambda *args,**kwargs:pytest.fail('incomplete minute path'))
    packet = next(runner.run_matrix(product='jm',source=source,facts_dir=None,code_revision='a'*40))
    assert packet['metadata']['status']=='DATA_INSUFFICIENT'
    assert packet['reference']['snapshot']['side']=='UNAVAILABLE'
    assert packet['reference']['trades']==[] and len(packet['chart']['bars'])==1


def test_real_engine_fixture_matrix_publishes_valid_packets(monkeypatch,tmp_path):
    import scripts.research.newow_futures as runner
    from app.market_data.newow_futures_research import load_newow_futures_inputs
    from app.newow_futures_research.store import publish_packet
    from .test_newow_futures_inputs import Market, DAY, _raw
    source = load_newow_futures_inputs(Market(),product='jm',since=DAY,through=DAY)
    raw = _raw()
    raw['contracts']['JM2505'].update(parameters=[{'date':DAY.isoformat(),'commission_type':'by_volume',
        'open_commission':'1','close_commission':'2','close_commission_today':'3',
        'long_margin_ratio':'0.1','short_margin_ratio':'0.1'}],
        daily=[{'date':DAY.isoformat(),'prev_settlement':'100','limit_up':'110','limit_down':'90'}])
    monkeypatch.setattr(runner,'read_product_facts',lambda *args:(raw,raw))
    packets = list(runner.run_matrix(product='jm',source=source,facts_dir=None,code_revision='a'*40))
    assert len(packets)==144
    for packet in packets:
        frozen = publish_packet(tmp_path,packet)
        assert frozen['metadata']['status'] in ('DATA_INSUFFICIENT','NOT_APPLICABLE')
        assert packet['summary']['final_equity'] is None
    assert len(json.loads((tmp_path/'index.json').read_text())['runs'])==144


def test_switch_back_provider_span_is_frozen_complete_then_selects_owner_days(tmp_path):
    from scripts.research.newow_futures_execution_facts import catalog_preimage
    from app.market_data.newow_futures_research import load_execution_facts, load_newow_futures_inputs
    from .test_newow_futures_inputs import Market, DAY
    from dataclasses import replace
    from datetime import timedelta
    calendar_days = (DAY, date(2025,1,3), date(2025,1,6))
    def calendar(product,since,through):
        return tuple((since+timedelta(days=i),since+timedelta(days=i) in calendar_days)
                     for i in range((through-since).days+1))
    def mappings(product,since,through):
        return tuple(SimpleNamespace(trade_date=day,contract=product.upper()+suffix)
                     for day,suffix in zip(calendar_days,('2505','2509','2505')))
    products = catalog_preimage(SimpleNamespace(calendar_days=calendar,main_map=mappings))
    span = products['jm']['JM2505']
    assert span['days']==['2025-01-02','2025-01-06']
    assert span['requested_days']==['2025-01-02','2025-01-03','2025-01-06']
    frozen = make_plan(products,code_revision='a'*40)
    api = _api()
    single = api.futures.get_trading_parameters
    import pandas as pd
    def full_span(contract,start_date,end_date,fields,**kwargs):
        return pd.concat([single(contract,day.isoformat(),day.isoformat(),fields)
                          for day in calendar_days if start_date <= day.isoformat() <= end_date])
    api.futures.get_trading_parameters = full_span
    api.futures.get_exchange_daily = full_span
    api.get_price = full_span
    out = tmp_path/'attempt'
    capture(frozen,settings={},out=out,api_factory=lambda:api)
    raw = json.loads((out/'jm.json').read_text())
    body = raw['contracts']['JM2505']
    assert [row['date'] for row in body['daily']] == span['days']
    evidence = json.loads((out/'JM2505-provider.json').read_text())
    assert [row['date'] for row in evidence['provider_response']['daily']] == span['requested_days']
    assert evidence['selection']['owner_days'] == span['days']
    minute = load_newow_futures_inputs(Market(),product='jm',since=DAY,through=DAY).minute_bars[0]
    bars = (minute,replace(minute,trading_day=date(2025,1,6),bar_end=minute.bar_end+timedelta(days=4),
                           confirmed_at=minute.bar_end+timedelta(days=4)))
    # Selected product contains the other owner too, as an exact real product snapshot does.
    extra = replace(minute,physical_contract='JM2509',trading_day=date(2025,1,3),
                    bar_end=minute.bar_end+timedelta(days=1),confirmed_at=minute.bar_end+timedelta(days=1))
    facts,_ = load_execution_facts(raw,product='jm',bars=(*bars,extra))
    assert len(facts)==3
    events = [json.loads(row) for row in (out/'journal.jsonl').read_text().splitlines()]
    assert len([row for row in events if row['state']=='started'])==frozen['max_logical_calls']==34


def test_rehashed_plan_cannot_omit_or_expand_switch_back_request_calendar():
    from app.market_data.newow_futures_research import payload_hash
    products = plan()['products']
    products['jm'] = {
        'JM2505':{'start':'2025-01-02','end':'2025-01-06',
                  'days':['2025-01-02','2025-01-06'],
                  'requested_days':['2025-01-02','2025-01-03','2025-01-06']},
        'JM2509':{'start':'2025-01-03','end':'2025-01-03',
                  'days':['2025-01-03'],'requested_days':['2025-01-03']}}
    frozen = make_plan(products,code_revision='a'*40)
    for requested in (['2025-01-02','2025-01-06'],
                      ['2025-01-02','2025-01-03','2025-01-04','2025-01-06']):
        body = json.loads(json.dumps(frozen))
        body.pop('plan_hash')
        body['products']['jm']['JM2505']['requested_days'] = requested
        body['plan_hash'] = payload_hash(body)
        with pytest.raises(FactsCaptureError,match='FACTS_PLAN_INVALID'):
            validate_plan(body)
