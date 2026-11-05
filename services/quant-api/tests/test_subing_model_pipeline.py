from datetime import UTC,datetime,timedelta
from types import SimpleNamespace
import pytest
from app.subing_model.pipeline import Pipeline
from app.subing_model.factors import Factors

AT=datetime(2026,11,5,1,tzinfo=UTC)

def pipeline():
    p=Pipeline.__new__(Pipeline);p.started=AT-timedelta(hours=1);p.identity=dict(run_id='test',started_at=p.started.isoformat());p.factors={s:Factors(c) for s,c in [('jm','JM2701'),('ec','EC2612')]}
    p.products={s:dict(contract=f.contract,status='OBSERVING',warmup_errors={},execution_enabled=False) for s,f in p.factors.items()}
    p.last={};p.chart={s:[] for s in p.factors};p.account=SimpleNamespace(halted=None)
    p.account.hold_for_facts=lambda b,frame,observed_at,reason:setattr(p.account,'halted',reason)
    return p

def row(symbol,freq,at=AT,contract=None):
    return dict(channel=f'live:bar:{symbol}:{freq}',confirmed_at=at.isoformat(),data=dict(contract=contract or {'jm':'JM2701','ec':'EC2612'}[symbol],bar_end=at.isoformat(),trading_day='2026-11-05',open='100',high='102',low='98',close='101',volume='10',turnover=None,open_interest='10'))

def context(symbol,contract=None):
    return dict(contract=contract or {'jm':'JM2701','ec':'EC2612'}[symbol],first_open=(AT-timedelta(minutes=1)).isoformat(),expected_1m=[AT.isoformat()],expected_30m=[AT.isoformat()],expected_60m=[AT.isoformat()])

def test_other_product_rollover_cannot_halt_jm_and_keeps_stream_watermark():
    p=pipeline();p._row(row('ec','1m',contract='EC2702'),{'ec':context('ec','EC2702')},None,AT)
    assert p.account.halted is None and p.products['ec']['status']=='ROLLOVER_WAIT'
    assert p.last[('ec','1m')]==AT

def test_missing_derived_endpoint_rejected():
    p=pipeline()
    with pytest.raises(ValueError,match='DERIVED_OBSERVATION_GAP'):p._row(row('jm','1m'),{'jm':context('jm')},None,AT)

def test_derived_frequency_gap_rejected_before_indicator_update():
    p=pipeline();p.last[('jm','30m')]=AT-timedelta(hours=2)
    ctx=context('jm');ctx['expected_30m']=[(AT-timedelta(minutes=90)).isoformat(),AT.isoformat()]
    with pytest.raises(ValueError,match='OBSERVATION_GAP'):p._row(row('jm','30m'),{'jm':ctx},None,AT)
    assert p.factors['jm'].previous is None

def test_execution_fact_interruption_latches_account_without_silent_resume():
    p=pipeline();p.factors['jm'].daily=[dict(time='2026-11-04T07:00:00+00:00',direction='UP')]
    ctx=context('jm');ctx.update(previous='2026-11-04',expected_30m=[],expected_60m=[])
    p._row(row('jm','1m'),{'jm':ctx},None,AT)
    assert p.account.halted=='EXECUTION_FACTS_INTERRUPTED_REVIEW_REQUIRED'
    assert not p.products['jm']['execution_enabled']


def test_daily_update_enters_shared_factor_before_next_observation():
    p=pipeline();p.sequence=0;p.account=None
    r=row('jm','1m')['data'];r=dict(r,bar_end='2026-11-04T07:00:00+00:00',trading_day='2026-11-04')
    p.apply(dict(observed_at=AT.isoformat(),daily_updates={'jm':[r]},observations=[],contexts={},cursor='1-0',source_day='2026-11-05'))
    assert p.factors['jm'].daily[-1]['time']==r['bar_end']

def test_stale_and_future_warmup_cannot_start():
    from datetime import date
    from app.subing_model.worker import validate_warmup_boundary
    with pytest.raises(ValueError,match='WARMUP_NOT_CURRENT'):validate_warmup_boundary(date(2026,11,4),date(2026,11,6),AT-timedelta(days=1),AT)
    with pytest.raises(ValueError,match='FUTURE_WARMUP'):validate_warmup_boundary(date(2026,11,4),date(2026,11,4),AT+timedelta(seconds=1),AT)

def test_persisted_outcome_must_match_reconstructed_decisions_and_state():
    from copy import deepcopy
    p=pipeline();p.sequence=0;p.account=None
    event=dict(observed_at=AT.isoformat(),observations=[],contexts={},cursor='1-0',source_day='2026-11-05')
    p.apply(event);outcome=deepcopy(p.last_outcome)
    q=pipeline();q.sequence=0;q.account=None
    q.apply(dict(event,outcome=outcome))
    assert q.state()==p.state()
    outcome['model_fills']=[{'fill_id':'invented'}]
    r=pipeline();r.sequence=0;r.account=None
    with pytest.raises(ValueError,match='MODEL_OUTCOME_REPLAY_CONFLICT'):r.apply(dict(event,outcome=outcome))
