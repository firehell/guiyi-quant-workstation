from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import pytest
from test_account import inputs
from guiyi_quant.subing_account import replay


def run(xs, obs, ticks=1):
    return replay(xs, obs, 'open-test', slippage_ticks=ticks, execution_model='theoretical_open')


@pytest.mark.parametrize('ticks', [1, 2, 3])
def test_strict_start_and_open_price(ticks):
    xs, obs = inputs([100,101,102,103,104,105], frames={0:dict(near_zero_golden=True),3:dict(below_ema=True)})
    r = run(xs,obs,ticks)
    assert [f['fill_at'] for f in r['fills']] == [(xs[i].bar.bar_end-timedelta(minutes=1)).isoformat() for i in (2,5)]
    assert [D(f['price']) for f in r['fills']] == [D(102)+D('.5')*ticks,D(105)-D('.5')*ticks]
    assert D(r['net_pnl']) == (D(3)-ticks)*60-6
    assert 'liquidity unverified' in r['assumptions']


def test_future_ohlcv_and_technical_cannot_change_open_fill():
    xs,obs=inputs([100,101,102],frames={0:dict(near_zero_golden=True)})
    base=run(xs,obs)
    altered=list(xs);other=deepcopy(obs)
    altered[2]=replace(xs[2],bar=replace(xs[2].bar,close=D(80),high=D(102),low=D(80),volume=D(0)))
    other[xs[2].bar.bar_end]['close']='80'
    other[xs[2].bar.bar_end]['day_end_window']=True
    assert run(altered,other)['fills'] == base['fills']
    assert base['fills'][0]['price']=='102.5'  # may exceed realized high; explicit assumption


def test_prior_completed_cancellation_applies_before_open():
    xs,obs=inputs([100,101,102],frames={0:dict(near_zero_golden=True)})
    obs[xs[1].bar.bar_end]['day_end_window']=True
    assert not run(xs,obs)['fills']


def test_short_mirrors_long():
    from test_account_bidirectional import mirror_inputs
    xs,obs=inputs([100,101,102,103,104,105],frames={0:dict(near_zero_golden=True),3:dict(below_ema=True)})
    sx,so=mirror_inputs(xs,obs)
    assert run(sx,so)['net_pnl']==run(xs,obs)['net_pnl']


def test_limit_failure_retains_close_obligation():
    xs,obs=inputs([100,101,102,103,104,104,105],frames={0:dict(near_zero_golden=True),3:dict(below_ema=True)})
    xs[5]=replace(xs[5],bar=replace(xs[5].bar,open=D(1),low=D(1)))
    r=run(xs,obs)
    assert r['execution_events'][0]['kind']=='UNFILLED'
    assert r['execution_events'][0]['reason']=='EXCHANGE_LIMIT'
    assert r['fills'][-1]['fill_at']==(xs[6].bar.bar_end-timedelta(minutes=1)).isoformat()


def test_cross_day_gap_uses_start_and_close_yesterday_fee():
    xs,obs=inputs([100,101,102,103,104],frames={0:dict(near_zero_golden=True),3:dict(below_ema=True)})
    old=xs[4].bar; end=old.bar_end+timedelta(days=1)
    xs[4]=replace(xs[4],bar=replace(old,bar_end=end,confirmed_at=end,trading_day=end.date(),
        session_open_at=end-timedelta(minutes=1),session_close_at=end+timedelta(hours=1)),
        facts=replace(xs[4].facts,trading_day=end.date()))
    o=obs.pop(old.bar_end);o.update(at=end.isoformat(),trading_day=end.date().isoformat());obs[end]=o
    r=run(xs,obs)
    assert r['fills'][-1]['fill_at']==(end-timedelta(minutes=1)).isoformat()
    assert r['fills'][-1]['fee_kinds']==['close']
    assert D(r['fills'][-1]['fee'])==D(3)


def test_1450_clock_blocks_open_even_before_completed_observation():
    xs,obs=inputs([100,101,102],frames={0:dict(near_zero_golden=True)})
    delta=timedelta(hours=5,minutes=49)
    moved=[]; observations={}
    for x in xs:
        b=x.bar; end=b.bar_end+delta
        moved.append(replace(x,bar=replace(b,bar_end=end,confirmed_at=end,
            session_open_at=b.session_open_at+delta,session_close_at=b.session_close_at+delta)))
        o=deepcopy(obs[b.bar_end]);o['at']=end.isoformat();observations[end]=o
    r=run(moved,observations)
    assert not r['fills']
    assert r['execution_events'][0]['reason']=='OPENING_CONTEXT_CHANGED'


def test_invalid_execution_model_rejected():
    xs,obs=inputs([100])
    with pytest.raises(ValueError,match='ACCOUNT_EXECUTION_MODEL_INVALID'):
        replay(xs,obs,'r',execution_model='open')


def test_consumed_exit_event_is_not_reapplied_at_gap_open():
    xs,obs=inputs([100,101],frames={0:dict(near_zero_golden=True,below_previous_low=True)})
    old=xs[1].bar; end=old.bar_end+timedelta(hours=1)
    xs[1]=replace(xs[1],bar=replace(old,bar_end=end,confirmed_at=end,
        session_open_at=end-timedelta(minutes=1),session_close_at=end+timedelta(hours=1)))
    o=obs.pop(old.bar_end);o['at']=end.isoformat();obs[end]=o
    r=run(xs,obs)
    assert len(r['fills'])==1
    assert r['fills'][0]['action']=='OPEN'
    assert 'theoretical_open_v2' in r['version']


def test_new_completed_exit_event_still_cancels_pending_entry():
    xs,obs=inputs([100,101,102],frames={0:dict(near_zero_golden=True),1:dict(below_ema=True)})
    r=run(xs,obs)
    assert not r['fills']
    assert r['execution_events'][0]['reason']=='CANCEL_REQUESTED'
