from copy import deepcopy
import pytest
from test_subing_demand_account_candidate import single_day
from guiyi_quant.subing_demand_account_candidate import build_engine
from guiyi_quant.subing_decision import REGIME_PROFILE

def run(frames,phases):
    xs,obs,cal=single_day([100]*9,frames)
    structures={x.bar.bar_end.isoformat():dict(phase=phases.get(i,'STRUCTURE_ENVELOPE'),break_side='UP',structure_direction='UP',count=1) for i,x in enumerate(xs)}
    eng,C,_=build_engine(xs,cal,structures=structures)
    result=eng.replay(xs,obs,'unified',execution_model='theoretical_open',regime_research_profile=REGIME_PROFILE)
    return xs,result,C,structures,cal

def test_pending_break_preserves_window_and_blocks_entry_until_confirmation():
    xs,r,C,_,_=run({0:dict(regime='TREND_UP',near_zero_golden=True),1:dict(regime='TREND_UP'),2:dict(regime='TREND_UP')},{0:'BREAK_PENDING',1:'BREAK_PENDING'})
    assert r['fills'][0]['decision_at']==xs[2].bar.bar_end.isoformat()
    assert r['fills'][0]['fill_at']>r['fills'][0]['decision_at']
    m=C.restore(r['decision_checkpoint'])
    assert m.chain[0]['demand']=='WAIT_CONFIRMATION'
    assert m.chain[0]['conditions']['entry_windows']['LONG']['age']==0
    assert m.state()==r['decision_state']

def test_confirmed_break_does_not_override_v2_range():
    _,r,C,_,_=run({0:dict(regime='RANGE',near_zero_golden=True)},{0:'BREAK_CONFIRMED'})
    assert not r['fills']
    assert C.restore(r['decision_checkpoint']).chain[0]['conflict']

def test_changed_structure_rejects_checkpoint():
    xs,r,_,structures,cal=run({0:dict(regime='TREND_UP',near_zero_golden=True)},{0:'BREAK_PENDING'})
    structures=deepcopy(structures);structures[xs[0].bar.bar_end.isoformat()]['phase']='BREAK_CONFIRMED'
    _,Other,_=build_engine(xs,cal,structures=structures)
    with pytest.raises(ValueError,match='CHECKPOINT_INVALID'):Other.restore(r['decision_checkpoint'])

def test_break_confirmation_cannot_arm_pullback_on_recovery_bar():
    frames={0:dict(regime='TREND_UP',near_zero_golden=True),3:dict(regime='TREND_UP',qualified_pullback=True,pullback_high='100'),4:dict(regime='TREND_UP',qualified_pullback=True,pullback_high='100')}
    _,r,C,_,_=run(frames,{3:'BREAK_PENDING'})
    chain=C.restore(r['decision_checkpoint']).chain
    assert chain[3]['position']['pullback'] is None
    assert chain[4]['position']['pullback'] is None

def test_accepted_open_explains_eligibility_not_pending():
    _,r,C,_,_=run({0:dict(regime='TREND_UP',near_zero_golden=True)},{})
    row=C.restore(r['decision_checkpoint']).chain[0]
    assert row['demand']=='CHECK_ENTRY_ELIGIBILITY'
    assert row['reason']=='ORIGINAL_ENTRY_FACTS_READY'

def test_preheated_regime_available_before_first_owned_m30():
    xs,obs,cal=single_day([100]*5,{})
    for o in obs.values():o['m30']=None
    structures={x.bar.bar_end.isoformat():dict(base_regime='RANGE',phase='STRUCTURE_ENVELOPE',structure_direction='MIXED') for x in xs}
    eng,C,_=build_engine(xs,cal,structures=structures)
    r=eng.replay(xs,obs,'preheated',execution_model='theoretical_open',regime_research_profile=REGIME_PROFILE)
    assert C.restore(r['decision_checkpoint']).chain[0]['regime']=='RANGE'
