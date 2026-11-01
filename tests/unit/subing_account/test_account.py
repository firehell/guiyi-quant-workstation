from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from guiyi_quant.new_subing import ExecutionBar, ExecutionFacts, StrategyBar
from guiyi_quant.paper import FeeSchedule
from guiyi_quant.subing_account import replay
from guiyi_quant.subing_decision import DecisionModel

BASE=datetime(2026,7,13,1,tzinfo=timezone.utc)
FEES=FeeSchedule(D('0'),D('2'),D('0'),D('3'),D('0'),D('4'),'test-fees')


def inputs(prices, *, frames=None):
    xs=[];obs={};frames=frames or {}
    for i,price in enumerate(prices):
        end=BASE+timedelta(minutes=i)
        p=D(str(price))
        facts=ExecutionFacts('JM2609',end.date(),D('.5'),D('60'),D('100'),D('.1'),D('.1'),D('500'),D('1'),FEES,'test-facts')
        bar=StrategyBar('jm','JM2609','1m',end,end.date(),p,p+D('1'),p-D('1'),p,D('100'),None,
            f'test-bar-{i}',end,True,BASE-timedelta(minutes=1),BASE+timedelta(hours=4))
        xs.append(ExecutionBar(bar,facts))
        m=None
        if i in frames:
            m=dict(near_zero_golden=False,minute_angle='2',above_ema=True,volume_effective=True,
                below_previous_low=False,high_death=False,below_ema=False,
                qualified_pullback=False,pullback_high=None,pullback_invalidated=False)
            m.update(frames[i])
        obs[end]=dict(event_id=f'o{i}',kind='observe',at=end.isoformat(),contract='JM2609',trading_day=end.date().isoformat(),
            close=str(p),daily_direction='UP',daily_at=(BASE-timedelta(days=1)).isoformat(),day_end_window=False,m30=m)
    return xs,obs


def test_open_then_clear_next_minute_fees_and_cash_reconcile():
    xs,obs=inputs([100,101,105,106],frames={0:dict(near_zero_golden=True),2:dict(below_ema=True)})
    r=replay(xs,obs,'r')
    assert [x['fill_at'] for x in r['fills']]==[xs[1].bar.bar_end.isoformat(),xs[3].bar.bar_end.isoformat()]
    assert [x['price'] for x in r['fills']]==['101.5','105.5']
    assert D(r['fees'])==D('6') and r['cash']=='100234.0' and r['equity']==r['cash']
    assert r['closed_rounds'][0]['net_pnl']=='234.0'
    assert r['fills'][1]['fee_kinds']==['close_today']
    assert DecisionModel.restore(r['decision_checkpoint']).state()==r['decision_state']


def test_terminal_open_is_marked_not_forced_closed():
    xs,obs=inputs([100,101,105],frames={0:dict(near_zero_golden=True)})
    r=replay(xs,obs,'r')
    assert r['status']=='OPEN' and len(r['fills'])==1 and r['closed_rounds']==[]
    assert r['unrealized']=='210.0' and r['net_pnl']=='208.0'
    assert r['open_round']['net_pnl']==r['net_pnl']


def test_signal_on_last_bar_is_pending_not_fill():
    xs,obs=inputs([100],frames={0:dict(near_zero_golden=True)})
    r=replay(xs,obs,'r')
    assert r['status']=='PENDING' and not r['fills']


@pytest.mark.parametrize('reason',['ZERO_VOLUME','SLIPPAGE_OUTSIDE_BAR','OPENING_CONTEXT_CHANGED','OPENING_FINANCIAL_RECHECK'])
def test_opening_recheck_cancels_and_does_not_replay_opportunity(reason):
    xs,obs=inputs([100,101,102],frames={0:dict(near_zero_golden=True)})
    if reason=='ZERO_VOLUME': xs[1]=replace(xs[1],bar=replace(xs[1].bar,volume=D('0')))
    if reason=='SLIPPAGE_OUTSIDE_BAR': xs[1]=replace(xs[1],bar=replace(xs[1].bar,high=D('101')))
    if reason=='OPENING_CONTEXT_CHANGED':obs[xs[1].bar.bar_end]['day_end_window']=True
    if reason=='OPENING_FINANCIAL_RECHECK':xs[1]=replace(xs[1],facts=replace(xs[1].facts,long_margin_ratio=D('20')))
    r=replay(xs,obs,'r')
    assert not r['fills'] and r['execution_events'][0]['reason']==reason
    assert r['pending'] is None


def test_close_failure_keeps_position_and_retries():
    xs,obs=inputs([100,101,105,106,107],frames={0:dict(near_zero_golden=True),2:dict(below_ema=True)})
    xs[3]=replace(xs[3],bar=replace(xs[3].bar,volume=D('0')))
    r=replay(xs,obs,'r')
    assert r['execution_events'][0]['kind']=='UNFILLED'
    assert r['fills'][-1]['fill_at']==xs[4].bar.bar_end.isoformat()
    assert r['status']=='COMPLETED'


def test_round_loss_uses_equity_including_fees():
    xs,obs=inputs([100,101,60,59],frames={0:dict(near_zero_golden=True)})
    r=replay(xs,obs,'r')
    assert r['fills'][-1]['reasons']==['ROUND_LOSS']
    assert D(r['closed_rounds'][0]['net_pnl']) < D('-2000')


def test_day_end_net_unrealized_includes_open_and_estimated_close_fee():
    xs,obs=inputs([100,100,100,100],frames={0:dict(near_zero_golden=True)})
    obs[xs[2].bar.bar_end]['day_end_window']=True
    obs[xs[3].bar.bar_end]['day_end_window']=True
    r=replay(xs,obs,'r')
    assert r['fills'][-1]['reasons']==['DAY_END_NONPOSITIVE']
    assert r['closed_rounds'][0]['net_pnl']=='-66.0'


def test_adding_and_protection_uses_specific_layer_price():
    xs,obs=inputs([100,101,103,104,105,104,103],frames={0:dict(near_zero_golden=True),2:dict(qualified_pullback=True,pullback_high='103')})
    r=replay(xs,obs,'r')
    assert [x['action'] for x in r['fills']]==['OPEN','ADD','CLOSE']
    assert r['fills'][-1]['layer_ids']==[r['fills'][1]['decision_id']]
    assert r['open_layers'][0]['layer_id']==r['fills'][0]['decision_id']


def test_mismatched_coverage_and_financial_overrides_rejected():
    xs,obs=inputs([100,101])
    extra=dict(obs);extra[xs[0].bar.bar_end]=dict(extra[xs[0].bar.bar_end],admission=True)
    with pytest.raises(ValueError,match='OBSERVATION_FIELDS'):replay(xs,extra,'r')
    with pytest.raises(ValueError):replay(xs,{xs[0].bar.bar_end:obs[xs[0].bar.bar_end]},'r')
    with pytest.raises(ValueError):replay([xs[1],xs[0]],obs,'r')


def test_no_cross_contract_or_unconfirmed_replay():
    xs,obs=inputs([100,101])
    xs[1]=replace(xs[1],bar=replace(xs[1].bar,confirmed_at=xs[1].bar.bar_end+timedelta(seconds=1)))
    with pytest.raises(ValueError,match='CONFIRMATION'):replay(xs,obs,'r')


def test_prefix_fills_invariant():
    xs,obs=inputs([100,101,105,106],frames={0:dict(near_zero_golden=True),2:dict(below_ema=True)})
    short=replay(xs[:2],{x.bar.bar_end:obs[x.bar.bar_end] for x in xs[:2]},'r')
    full=replay(xs,obs,'r')
    assert full['fills'][:len(short['fills'])]==short['fills']


def test_next_trading_day_uses_previous_equity_and_close_yesterday_fee():
    xs,obs=inputs([100,101,105,106],frames={0:dict(near_zero_golden=True),2:dict(below_ema=True)})
    for i in (2,3):
        old=xs[i];end=old.bar.bar_end+timedelta(days=1);day=end.date()
        b=replace(old.bar,bar_end=end,confirmed_at=end,trading_day=day,
            session_open_at=BASE+timedelta(days=1)-timedelta(minutes=1),session_close_at=BASE+timedelta(days=1,hours=4))
        xs[i]=ExecutionBar(b,replace(old.facts,trading_day=day))
        o=obs.pop(old.bar.bar_end);o.update(at=end.isoformat(),trading_day=day.isoformat());obs[end]=o
    r=replay(xs,obs,'r')
    assert r['fills'][-1]['fee_kinds']==['close']
    assert D(r['fees'])==D('5')
    assert r['daily_equity'][1]['day_start_equity']==r['daily_equity'][0]['equity']
    assert D(r['closed_rounds'][0]['net_pnl'])==D('235')


def test_day_loss_halts_after_final_fill():
    xs,obs=inputs([100,101,10,9],frames={0:dict(near_zero_golden=True)})
    r=replay(xs,obs,'r')
    assert r['fills'][-1]['reasons']==['DAY_LOSS','ROUND_LOSS']
    assert r['decision_state']['day_halted'] is True
    assert r['summary']['open_quantity']==0


def test_insufficient_minute_volume_partially_closes_then_continues():
    xs,obs=inputs([100,101,103,104,105,106,107,108,109],frames={
        0:dict(near_zero_golden=True),2:dict(qualified_pullback=True,pullback_high='103'),
        5:dict(below_ema=True)})
    xs[6]=replace(xs[6],bar=replace(xs[6].bar,volume=D('1')))
    r=replay(xs,obs,'r')
    assert [x['quantity'] for x in r['fills']]==[1,1,1,1]
    assert r['fills'][-1]['decision_id']==r['fills'][-2]['decision_id']
    assert r['decision_state']['cooldown']==10


def test_unknown_daily_prevents_pending_open_execution():
    xs,obs=inputs([100,101],frames={0:dict(near_zero_golden=True)})
    obs[xs[1].bar.bar_end].update(daily_direction='UNKNOWN',daily_at=None)
    r=replay(xs,obs,'r')
    assert not r['fills'] and r['execution_events'][0]['reason']=='OPENING_CONTEXT_CHANGED'


@pytest.mark.parametrize('exit_key',['below_ema','below_previous_low','high_death'])
def test_new_exit_fact_at_execution_cancels_pending_add(exit_key):
    xs,obs=inputs([100,101,103,104,105,106],frames={0:dict(near_zero_golden=True),
        2:dict(qualified_pullback=True,pullback_high='103'),4:{exit_key:True}})
    r=replay(xs,obs,'r')
    assert all(x['action']!='ADD' for x in r['fills'])
    assert any(x['reason']=='EXIT_PRIORITY_AT_EXECUTION' for x in r['execution_events'])


def test_future_price_perturbation_does_not_change_prefix():
    xs,obs=inputs([100,101,105,106],frames={0:dict(near_zero_golden=True),2:dict(below_ema=True)})
    first=replay(xs,obs,'r')
    xs[3]=replace(xs[3],bar=replace(xs[3].bar,open=D('200'),close=D('200'),high=D('201'),low=D('199')))
    obs[xs[3].bar.bar_end]['close']='200'
    second=replay(xs,obs,'r')
    assert first['fills'][0]==second['fills'][0]
    cutoff=xs[2].bar.bar_end
    assert [x for x in first['trace'] if datetime.fromisoformat(x['facts']['at']) <=cutoff]==[x for x in second['trace'] if datetime.fromisoformat(x['facts']['at']) <=cutoff]


def test_add_fill_minute_does_not_reuse_prefill_close_for_protection():
    xs,obs=inputs([100,101,103,104,105,106],frames={0:dict(near_zero_golden=True),2:dict(qualified_pullback=True,pullback_high='103')})
    r=replay(xs,obs,'r')
    assert [x['action'] for x in r['fills']]==['OPEN','ADD']
    assert r['summary']['open_quantity']==2 and r['pending'] is None
    add_at=r['fills'][-1]['fill_at']
    same=[x for x in r['trace'] if x['facts']['at']==add_at and x['facts']['kind']=='observe']
    assert not same or all(not x['actions'] for x in same)
