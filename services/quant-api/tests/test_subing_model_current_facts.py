from datetime import UTC,date,datetime
from types import SimpleNamespace as NS
import json
import pandas as pd
import pytest
from scripts.research.subing_model_facts import collect,snapshot_daily
from scripts.research.new_subing_execution_facts import FactsCaptureError

DAY=date(2026,11,5);NOW=datetime(2026,11,5,0,tzinfo=UTC)
WINDOWS=[NS(start=datetime(2026,11,4,13,tzinfo=UTC),end=datetime(2026,11,4,15,tzinfo=UTC)),NS(start=datetime(2026,11,5,1,tzinfo=UTC),end=datetime(2026,11,5,7,tzinfo=UTC))]

def quote(**changes):
    return NS(**(dict(order_book_id='JM2701',datetime='2026-11-04T23:00:00.004000',prev_settlement=1365,limit_up=1474,limit_down=1256)|changes))

def parameters(**changes):
    row=dict(order_book_id='JM2701',trading_date=pd.Timestamp('2026-11-05'),long_margin_ratio=.12,short_margin_ratio=.12,commission_type='by_money',open_commission=.0001,close_commission=.0001,close_commission_today=.0002)
    return pd.DataFrame([row|changes]).set_index(['order_book_id','trading_date'])

def test_snapshot_uses_authoritative_night_day_envelope_and_never_last_price():
    daily,at=snapshot_daily(quote(), 'JM2701',DAY,WINDOWS,NOW,'.5')
    assert daily==dict(date='2026-11-05',prev_settlement='1365',limit_up='1474',limit_down='1256')
    assert at.endswith('+08:00')

@pytest.mark.parametrize('changes',[
    dict(order_book_id='JM2609'),dict(datetime='2026-11-04T15:00:00'),
    dict(datetime='2026-11-05T09:01:00'),dict(trading_date='2026-11-04'),
    dict(limit_up=float('nan')),dict(limit_down=1500),dict(limit_up=1474.1),dict(prev_settlement=0),
])
def test_foreign_stale_future_and_invalid_constraints_fail_closed(changes):
    with pytest.raises(FactsCaptureError):snapshot_daily(quote(**changes),'JM2701',DAY,WINDOWS,NOW,'.5')


def test_current_branch_has_no_dates_and_preserves_provider_evidence(tmp_path):
    called=[]
    def current(contract,**kwargs):
        assert contract=='JM2701' and 'start_date' not in kwargs and 'end_date' not in kwargs
        return parameters()
    api=NS(instruments=lambda _:NS(order_book_id='JM2701',tick_size=.5,contract_multiplier=60),
           futures=NS(get_trading_parameters=current),current_snapshot=lambda _:quote())
    def call(name,fn):called.append(name);return fn()
    result=collect(api,call,'JM2701',DAY,WINDOWS,tmp_path,date(2026,11,4))
    assert called==['instruments','current_parameters','current_snapshot']
    assert result['contracts']['JM2701']['daily'][0]['date']==str(DAY)
    assert result['fee_assumption']['assumed'] is False and result['fee_assumption']['source_day']==str(DAY)
    assert result['capture_version']=='rqdata_current_constraints_model_fee_v2'
    assert json.loads((tmp_path/'current-parameters.json').read_text())['missing_fields']==[]


def test_missing_commissions_use_whole_previous_day_bundle_and_record_assumption(tmp_path):
    raw=parameters(commission_type=float('nan'),open_commission=.999,close_commission=float('nan'),close_commission_today=float('nan'))
    called=[]
    def get(contract,**kwargs):
        called.append(kwargs)
        return parameters(trading_date=pd.Timestamp('2026-11-04'),open_commission=.0003) if 'start_date' in kwargs else raw
    api=NS(instruments=lambda _:NS(order_book_id='JM2701',tick_size=.5,contract_multiplier=60),futures=NS(get_trading_parameters=get),current_snapshot=lambda _:quote())
    result=collect(api,lambda _,fn:fn(),'JM2701',DAY,WINDOWS,tmp_path,date(2026,11,4))
    assert called[-1]['start_date']==called[-1]['end_date']=='2026-11-04'
    policy=result['fee_assumption'];assert policy['assumed'] and policy['source_day']=='2026-11-04' and policy['target_day']=='2026-11-05'
    p=result['contracts']['JM2701']['parameters'][0]
    assert p['date']=='2026-11-05' and p['long_margin_ratio']=='0.12' and p['open_commission']=='0.0003'
    assert policy['source_parameters'][0]['date']=='2026-11-04'
    assert json.loads((tmp_path/'previous-fees.json').read_text())['missing_fields']==[]
    assert result['fee_policy_version']=='current_complete_else_previous_trading_day_v1'
    evidence=json.loads((tmp_path/'current-parameters.json').read_text())
    assert evidence['rows'][0]['commission_type'] is None


@pytest.mark.parametrize('previous', [parameters(commission_type=float('nan')),parameters(trading_date=pd.Timestamp('2026-11-03')),parameters(order_book_id='JM2609')])
def test_bad_previous_day_fees_do_not_trigger_older_or_other_contract_search(tmp_path,previous):
    def get(contract,**kwargs):
        return previous if 'start_date' in kwargs else parameters(commission_type=float('nan'))
    api=NS(instruments=lambda _:NS(order_book_id='JM2701',tick_size=.5,contract_multiplier=60),futures=NS(get_trading_parameters=get),current_snapshot=lambda _:quote())
    with pytest.raises(FactsCaptureError):collect(api,lambda _,fn:fn(),'JM2701',DAY,WINDOWS,tmp_path,date(2026,11,4))
    assert not (tmp_path/'jm.json').exists()


@pytest.mark.parametrize('changes',[dict(long_margin_ratio=0),dict(long_margin_ratio=float('nan')),dict(short_margin_ratio=1.1),dict(open_commission=-1),dict(commission_type='unknown')])
def test_invalid_current_facts_are_not_replaced_with_old_facts(tmp_path,changes):
    def get(contract,**kwargs):
        assert 'start_date' not in kwargs
        return parameters(**changes)
    api=NS(instruments=lambda _:NS(order_book_id='JM2701',tick_size=.5,contract_multiplier=60),futures=NS(get_trading_parameters=get),current_snapshot=lambda _:quote())
    with pytest.raises(FactsCaptureError):collect(api,lambda _,fn:fn(),'JM2701',DAY,WINDOWS,tmp_path,date(2026,11,4))


def test_wrong_current_effective_day_rejected(tmp_path):
    api=NS(instruments=lambda _:NS(order_book_id='JM2701',tick_size=.5,contract_multiplier=60),futures=NS(get_trading_parameters=lambda *a,**k:parameters(trading_date=pd.Timestamp('2026-11-04'))),current_snapshot=lambda _:quote())
    with pytest.raises(FactsCaptureError,match='PROVIDER_DATE_COVERAGE_MISMATCH'):collect(api,lambda _,fn:fn(),'JM2701',DAY,WINDOWS,tmp_path,date(2026,11,4))


def test_previous_trading_day_requires_complete_intervening_calendar():
    from scripts.research.subing_model_facts import previous_trading_day
    with pytest.raises(FactsCaptureError,match='CALENDAR_COVERAGE_MISSING'):
        previous_trading_day([(date(2026,11,3),True),(DAY,True)],DAY)
    assert previous_trading_day([(date(2026,11,3),True),(date(2026,11,4),False),(DAY,True)],DAY)==date(2026,11,3)
    with pytest.raises(FactsCaptureError):previous_trading_day([(date(2026,11,4),True),(DAY,False)],DAY)
