from dataclasses import replace
from decimal import Decimal as D

from guiyi_quant.subing_account import replay
from guiyi_quant.subing_decision import DecisionModel
from tests.unit.subing_account.test_account import inputs
from tests.unit.subing_decision.test_bidirectional import mirror


def mirror_inputs(xs,obs):
    result=[]; observations={}
    for x in xs:
        b=x.bar; f=x.facts
        result.append(replace(x,bar=replace(b,open=D('500')-b.open,close=D('500')-b.close,
            high=D('500')-b.low,low=D('500')-b.high),
            facts=replace(f,prev_settlement=D('500')-f.prev_settlement,
                limit_up=D('499'),limit_down=D('1'))))
        observations[b.bar_end]=mirror(obs[b.bar_end])
    return result,observations


def test_account_short_cash_fees_fills_and_equity_mirror():
    xs,obs=inputs([100,101,103,104,105,108,109,110],frames={0:dict(near_zero_golden=True),
        2:dict(qualified_pullback=True,pullback_high='103'),6:dict(below_ema=True)})
    long=replay(xs,obs,'r')
    sx,so=mirror_inputs(xs,obs); short=replay(sx,so,'r')
    assert short['cash']==long['cash'] and short['fees']==long['fees']
    assert short['gross_realized']==long['gross_realized']
    assert [x['equity'] for x in short['daily_equity']]==[x['equity'] for x in long['daily_equity']]
    for a,b in zip(long['fills'],short['fills'],strict=True):
        assert a['action']==b['action'] and a['quantity']==b['quantity'] and a['fill_at']==b['fill_at']
        assert D(a['price'])+D(b['price'])==D('500')
        assert b['side']=='SHORT' and a['order_side']!=b['order_side']
        assert b['gross_realized']==a['gross_realized']
    assert short['closed_rounds'][0]['side']=='SHORT'
    assert DecisionModel.restore(short['decision_checkpoint']).state()==short['decision_state']


def test_short_uses_short_margin_at_decision_and_execution():
    xs,obs=mirror_inputs(*inputs([100,101],frames={0:dict(near_zero_golden=True)}))
    rejected=[replace(x,facts=replace(x.facts,short_margin_ratio=D('20'))) for x in xs]
    assert not replay(rejected,obs,'s')['fills']
    # A high LONG rate must not reject SHORT.
    allowed=[replace(x,facts=replace(x.facts,long_margin_ratio=D('20'))) for x in xs]
    result=replay(allowed,obs,'s')
    assert len(result['fills'])==1
    rejected[0]=xs[0]
    result=replay(rejected,obs,'s')
    assert result['execution_events'][0]['reason']=='OPENING_FINANCIAL_RECHECK'


def test_short_unrealized_and_prefix_invariance():
    xs,obs=mirror_inputs(*inputs([100,101,105,106],frames={0:dict(near_zero_golden=True)}))
    r=replay(xs,obs,'r')
    assert r['unrealized']=='270.0' and r['net_pnl']=='268.0'
    assert r['open_layers'][0]['side']=='SHORT'
    prefix=replay(xs[:2],{x.bar.bar_end:obs[x.bar.bar_end] for x in xs[:2]},'r')
    assert prefix['fills']==r['fills']


def test_short_add_execution_rechecks_breakdown_and_base_net():
    xs,obs=inputs([100,101,103,104,102],frames={0:dict(near_zero_golden=True),2:dict(qualified_pullback=True,pullback_high='103')})
    xs,obs=mirror_inputs(xs,obs)
    r=replay(xs,obs,'s')
    assert [f['action'] for f in r['fills']]==['OPEN']
    assert r['execution_events'][0]['reason']=='PULLBACK_BREAKOUT_LOST_AT_EXECUTION'


def test_close_fill_cannot_create_reverse_intent_at_same_timestamp():
    xs,obs=inputs([100,101,102,103,104],frames={0:dict(near_zero_golden=True),2:dict(below_ema=True),
        3:dict(near_zero_death=True,minute_angle='-2',above_ema=False,below_ema=True,ema21='110',high='115')})
    for x in xs[3:]:obs[x.bar.bar_end]['daily_direction']='DOWN'
    r=replay(xs,obs,'r')
    assert [f['action'] for f in r['fills']]==['OPEN','CLOSE']
    rejects=[a for t in r['trace'] for a in t['actions'] if a['kind']=='REJECT']
    assert rejects[0]['reasons']==['SAME_OBSERVATION_AS_CLEAR']
