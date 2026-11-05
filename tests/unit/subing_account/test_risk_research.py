from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import pytest
from test_account import inputs
from test_account_bidirectional import mirror_inputs
from guiyi_quant.subing_account import replay
from guiyi_quant.subing_decision import DecisionModel, RISK_RESEARCH_PROFILES, _digest


def run(xs,obs,p):return replay(xs,obs,'risk-test',execution_model='theoretical_open',risk_research_profile=p)


@pytest.mark.parametrize('profile',RISK_RESEARCH_PROFILES)
def test_risk_identity_restore_and_short_symmetry(profile):
    xs,obs=inputs([100,101,102,75,74,73],frames={0:dict(near_zero_golden=True)})
    r=run(xs,obs,profile);m=DecisionModel.restore(r['decision_checkpoint'])
    assert m.state()==r['decision_state'] and m.checkpoint()==r['decision_checkpoint']
    a,b,c,d=RISK_RESEARCH_PROFILES[profile]
    assert r['research_parameters']==dict(round_loss_limit=str(a),day_loss_limit=str(b),margin_fraction=str(c),add_protection=d)
    assert m.add_protection==d
    assert r['risk_research_profile']==profile
    sx,so=mirror_inputs(xs,obs);short=run(sx,so,profile)
    assert short['net_pnl']==r['net_pnl']
    events=r['decision_checkpoint']['events'];partial=DecisionModel('JM2609','risk-test',risk_research_profile=profile)
    for e in events[:3]:partial.apply(e)
    restored=DecisionModel.restore(partial.checkpoint())
    for e in events[3:]:restored.apply(e)
    assert restored.checkpoint()==r['decision_checkpoint']
    changed=deepcopy(r['decision_checkpoint']);del changed['risk_research_profile'];changed['sha256']=_digest({k:v for k,v in changed.items() if k!='sha256'})
    with pytest.raises(ValueError):DecisionModel.restore(changed)


def test_round_threshold_changes_actual_exit_not_only_identity():
    xs,obs=inputs([100,101,102,75,74,73],frames={0:dict(near_zero_golden=True)})
    tight=run(xs,obs,'round1500');loose=run(xs,obs,'round2500')
    assert tight['fills'][-1]['action']=='CLOSE' and 'ROUND_LOSS' in tight['fills'][-1]['reasons']
    assert len(loose['fills'])==1 and loose['status']=='OPEN'


@pytest.mark.parametrize('ratio,decision_rejected', [('10.5',True),('0.1',False)])
def test_margin_threshold_used_at_decision(ratio,decision_rejected):
    xs,obs=inputs([100,101,102],frames={0:dict(near_zero_golden=True)})
    xs=[replace(x,facts=replace(x.facts,long_margin_ratio=D(ratio))) for x in xs]
    tight=run(xs,obs,'margin60');loose=run(xs,obs,'margin80')
    assert bool(tight['fills']) is not decision_rejected
    assert len(loose['fills'])==1


def test_margin_threshold_rechecked_at_open():
    xs,obs=inputs([100,101,102],frames={0:dict(near_zero_golden=True)})
    xs[2]=replace(xs[2],facts=replace(xs[2].facts,long_margin_ratio=D('10.5')))
    tight=run(xs,obs,'margin60');loose=run(xs,obs,'margin80')
    assert not tight['fills'] and tight['execution_events'][-1]['reason']=='OPENING_FINANCIAL_RECHECK'
    assert len(loose['fills'])==1


def test_disabling_add_protection_preserves_other_exits():
    xs,obs=inputs([100,101,103,104,105,106,104,103,102,101,100,99,98],frames={0:dict(near_zero_golden=True),3:dict(qualified_pullback=True,pullback_high='103'),10:dict(below_ema=True)})
    baseline=run(xs,obs,None);disabled=run(xs,obs,'without_add_protection')
    assert any('ADD_PROTECTION' in f['reasons'] for f in baseline['fills'])
    assert not any('ADD_PROTECTION' in f['reasons'] for f in disabled['fills'])
    assert disabled['fills'][-1]['action']=='CLOSE' and len(disabled['fills'][-1]['layer_ids'])==2
    assert disabled['status']=='COMPLETED'


@pytest.mark.parametrize('bad',[True,{},'bad',1])
def test_invalid_risk_profile(bad):
    xs,obs=inputs([100])
    with pytest.raises(ValueError):run(xs,obs,bad)


def test_profile_combinations_and_close_model_rejected():
    xs,obs=inputs([100])
    with pytest.raises(ValueError):replay(xs,obs,'r',risk_research_profile='round1500')
    with pytest.raises(ValueError):replay(xs,obs,'r',execution_model='theoretical_open',risk_research_profile='round1500',research_profile='window4')


def test_daily_threshold_changes_halt_reason_on_gap():
    xs,obs=inputs([100,101,102,30,29,28],frames={0:dict(near_zero_golden=True)})
    tight=run(xs,obs,'day4000');loose=run(xs,obs,'day6000')
    assert 'DAY_LOSS' in tight['fills'][-1]['reasons']
    assert 'DAY_LOSS' not in loose['fills'][-1]['reasons']
    assert 'ROUND_LOSS' in loose['fills'][-1]['reasons']
