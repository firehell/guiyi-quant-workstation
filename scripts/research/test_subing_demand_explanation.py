from test_subing_demand_account_candidate import fixture
from guiyi_quant.subing_demand_account_candidate import build_engine
from guiyi_quant.subing_decision import REGIME_PROFILE

def test_real_day_end_phase_survives_account_projection():
    xs,obs,cal=fixture()
    structures={x.bar.bar_end.isoformat():dict(phase='STRUCTURE_ENVELOPE',structure_direction='UP') for x in xs}
    eng,C,_=build_engine(xs,cal,structures=structures)
    r=eng.replay(xs,obs,'phase',execution_model='theoretical_open',regime_research_profile=REGIME_PROFILE)
    rows=C.restore(r['decision_checkpoint']).chain
    assert rows[3]['demand']=='RECORD_ONLY'
    assert rows[3]['phase']=='DAY_END'
    assert rows[3]['next_wait']=='NEXT_SESSION_OPEN_REVIEW'
    assert rows[4]['phase']=='NEXT_OPEN_AFTER_DAY_END'
    assert rows[4]['trigger_reasons']==['RANGE_OPEN_GROSS_LOSS']

import pytest
from decimal import Decimal as D
from guiyi_quant.subing_demand_explanation import explain

@pytest.mark.parametrize('phase,pnl,days,expected',[
 ('DAY_END','-1',3,'RECORD_ONLY'),('NEXT_OPEN_AFTER_DAY_END','1',3,'HOLD_NO_ADD'),
 ('NEXT_OPEN_AFTER_DAY_END','-1',0,'EXIT_REQUIRED'),('NEXT_OPEN_AFTER_DAY_END','0',3,'EXIT_REQUIRED')])
def test_phase_pnl_and_streak(phase,pnl,days,expected):
    state=dict(side='LONG',quantity=1,clear_reasons=[],exit_layers=[],pending=None,technical_ready=True,day_reconciled=True)
    d=explain(state=state,regime='RANGE',phase=phase,pending_break=None,gross=D(pnl),streak=days,actions=[])
    assert d['demand']==expected

@pytest.mark.parametrize('full',[False,True])
def test_exit_preserves_actual_reason_and_priority(full):
    reasons=['FIXED_STOP'] if full else ['ADD_PROTECTION']
    state=dict(side='LONG',quantity=2,clear_reasons=reasons if full else [],exit_layers=['l1'],pending=None,technical_ready=True,day_reconciled=True)
    d=explain(state=state,regime='RANGE',phase='DAY_END',pending_break=None,gross=D(100),streak=0,actions=[dict(kind='CLOSE',reasons=reasons)])
    assert d['trigger_reasons']==reasons and d['reason']==reasons[0]
    assert d['demand']==('EXIT_OBLIGATION' if full else 'REDUCE_OBLIGATION')
    assert d['next_wait']=='EXIT_EXECUTION'

def test_opening_review_is_not_recomputed_at_minute_close():
    state=dict(side='LONG',quantity=1,clear_reasons=[],exit_layers=[],pending=None,technical_ready=True,day_reconciled=True)
    d=explain(state=state,regime='RANGE',phase='NEXT_OPEN_AFTER_DAY_END',pending_break=None,gross=D(-10),streak=0,actions=[],opening_review=dict(demand='HOLD_NO_ADD',reason='REGIME_DISALLOWS_ADD',gross_remaining='10'))
    assert d['demand']=='HOLD_NO_ADD' and not d['trigger_reasons']
