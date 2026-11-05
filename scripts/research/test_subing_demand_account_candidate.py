from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import pytest
from test_account import inputs,BASE
from subing_demand_account_candidate import build_engine
from guiyi_quant.subing_account import replay
from guiyi_quant.subing_decision import REGIME_PROFILE

def fixture():
    xs,old=inputs([100,101,102,102,100,100,100,100],frames={0:dict(near_zero_golden=True,regime='TREND_UP'),3:dict(regime='RANGE')})
    obs={}
    for i,x in enumerate(xs):
        if i>=4:
            end=BASE+timedelta(days=1,minutes=i-4)
            xs[i]=replace(x,bar=replace(x.bar,bar_end=end,trading_day=end.date(),confirmed_at=end,session_open_at=BASE+timedelta(days=1,minutes=-1),session_close_at=BASE+timedelta(days=1,minutes=3)),facts=replace(x.facts,trading_day=end.date()))
        else:xs[i]=replace(x,bar=replace(x.bar,session_close_at=BASE+timedelta(minutes=3)))
        e=dict(old[x.bar.bar_end]);e['at']=xs[i].bar.bar_end.isoformat();e['trading_day']=xs[i].bar.trading_day.isoformat();e['day_end_window']=i in (3,7)
        obs[xs[i].bar.bar_end]=e
    schedule={}
    for first,last in ((0,3),(4,7)):
        b=xs[first].bar;day=b.trading_day
        schedule[str(day)]={'previous':str(day-timedelta(days=1)),'first_open':b.session_open_at.isoformat(),'day_end':xs[last].bar.bar_end.isoformat(),'next_open':(xs[4].bar.session_open_at if first==0 else b.session_open_at+timedelta(days=1)).isoformat()}
    return xs,obs,schedule

def test_candidate_exits_after_open_check_not_at_same_open():
    xs,obs,schedule=fixture();module,Candidate,_=build_engine(xs,schedule)
    kw=dict(execution_model='theoretical_open',regime_research_profile=REGIME_PROFILE)
    original=replay(xs,obs,'original',**kw);candidate=module.replay(xs,obs,'candidate',**kw)
    assert original['fills'][-1]['reasons']==['DAY_END_NONPOSITIVE']
    assert candidate['fills'][-1]['reasons']==['RANGE_OPEN_GROSS_LOSS']
    assert candidate['fills'][-1]['fill_at']>xs[4].bar.bar_end.isoformat()
    assert candidate['fills'][-1]['fill_at']>original['fills'][-1]['fill_at']
    restored=Candidate.restore(candidate['decision_checkpoint'])
    assert restored.state()==candidate['decision_state']

def test_changed_close_rejects_old_checkpoint():
    xs,_,schedule=fixture();_,Candidate,_=build_engine(xs,schedule)
    checkpoint=Candidate('JM2609','identity',regime_research_profile=REGIME_PROFILE).checkpoint()
    changed=list(xs);changed[5]=replace(xs[5],bar=replace(xs[5].bar,close=xs[5].bar.close+D('.5')))
    _,Other,_=build_engine(changed,schedule)
    with pytest.raises(ValueError,match='CHECKPOINT_INVALID'):Other.restore(checkpoint)

def test_exit_only_identity_is_distinct_and_formal_module_unchanged():
    from guiyi_quant import subing_account
    before=subing_account.DecisionModel
    xs,_,schedule=fixture()
    _,Full,_=build_engine(xs,schedule)
    _,ExitOnly,_=build_engine(xs,schedule,gate_first_entry=False)
    c=Full('JM2609','identity',regime_research_profile=REGIME_PROFILE).checkpoint()
    with pytest.raises(ValueError,match='CHECKPOINT_INVALID'):ExitOnly.restore(c)
    assert subing_account.DecisionModel is before

def single_day(prices,frames):
    xs,obs=inputs(prices,frames=frames)
    b=xs[0].bar
    schedule={str(b.trading_day):dict(previous=str(b.trading_day-timedelta(days=1)),first_open=b.session_open_at.isoformat(),day_end=b.session_close_at.isoformat(),next_open=(b.session_close_at+timedelta(days=1)).isoformat())}
    return xs,obs,schedule

def test_blocked_cross_waits_and_rechecks_current_volume():
    xs,obs,cal=single_day([100]*7,{0:dict(near_zero_golden=True,regime='RANGE'),1:dict(regime='RANGE'),2:dict(regime='TREND_UP',volume_effective=False),3:dict(regime='TREND_UP',volume_effective=True)})
    eng,Candidate,_=build_engine(xs,cal)
    r=eng.replay(xs,obs,'retained',execution_model='theoretical_open',regime_research_profile=REGIME_PROFILE)
    assert r['fills'][0]['decision_at']==xs[3].bar.bar_end.isoformat()
    assert r['fills'][0]['fill_at']>r['fills'][0]['decision_at']
    first=next(t for t in r['trace'] if t['event_id']=='o0')
    assert first['after']['entry_windows']['LONG']['source_end']==xs[0].bar.bar_end.isoformat()
    assert first['after']['entry_windows']['LONG']['age']==0
    assert Candidate.restore(r['decision_checkpoint']).state()==r['decision_state']

def test_environment_wait_does_not_extend_five_bar_window():
    frames={i:dict(regime='RANGE',near_zero_golden=i==0) for i in range(6)}
    frames[6]=dict(regime='TREND_UP')
    xs,obs,cal=single_day([100]*9,frames)
    eng,_,_=build_engine(xs,cal)
    r=eng.replay(xs,obs,'expired',execution_model='theoretical_open',regime_research_profile=REGIME_PROFILE)
    assert not r['fills']
    last=next(t for t in r['trace'] if t['event_id']=='o6')
    assert last['after']['entry_windows']['LONG']['source_end'] is None

def test_new_cross_replaces_old_source_without_freezing_clock():
    frames={0:dict(regime='RANGE',near_zero_golden=True),1:dict(regime='RANGE'),2:dict(regime='RANGE',near_zero_golden=True),3:dict(regime='RANGE')}
    xs,obs,cal=single_day([100]*5,frames)
    eng,_,_=build_engine(xs,cal)
    r=eng.replay(xs,obs,'newcross',execution_model='theoretical_open',regime_research_profile=REGIME_PROFILE)
    assert r['decision_state']['entry_windows']['LONG']['source_end']==xs[2].bar.bar_end.isoformat()
    assert r['decision_state']['entry_windows']['LONG']['age']==1

def test_age_five_is_last_eligible_bar_and_risk_rejection_not_restored():
    frames={i:dict(regime='RANGE',near_zero_golden=i==0) for i in range(5)}
    frames[5]=dict(regime='TREND_UP')
    xs,obs,cal=single_day([100]*9,frames)
    eng,Candidate,_=build_engine(xs,cal)
    r=eng.replay(xs,obs,'agefive',execution_model='theoretical_open',regime_research_profile=REGIME_PROFILE)
    assert r['fills'][0]['decision_at']==xs[5].bar.bar_end.isoformat()
    first=r['decision_checkpoint']['events'][0].copy();first['admission']=False
    m=Candidate('JM2609','risk',regime_research_profile=REGIME_PROFILE);m.apply(first)
    assert m.state()['entry_windows']['LONG']['source_end'] is None
