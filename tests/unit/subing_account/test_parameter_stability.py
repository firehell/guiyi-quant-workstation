from datetime import timedelta
from decimal import Decimal as D
from copy import deepcopy
import pytest
from test_account import inputs, BASE
from test_account_bidirectional import mirror_inputs
from guiyi_quant.subing_account import replay
from guiyi_quant.subing_decision import DecisionModel, RESEARCH_PROFILES, _digest
from guiyi_quant.indicators.subing_conditions import EntryWindow, observe_entry


def run(xs,obs,profile):
    return replay(xs,obs,'parameter-test',execution_model='theoretical_open',research_profile=profile)


@pytest.mark.parametrize('profile',RESEARCH_PROFILES)
def test_profile_changes_only_declared_geometry_and_restores(profile):
    xs,obs=inputs([100,101,102],frames={0:dict(near_zero_golden=True,volume_tier='TIER_1')})
    r=run(xs,obs,profile);age,buffer,target=RESEARCH_PROFILES[profile]
    state=r['decision_state'];entry=D(r['fills'][0]['price']);stop=D(80)-buffer
    assert D(state['initial_stop'])==stop
    assert D(state['risk_distance'])==entry-stop
    assert D(state['profit_target'])==entry+(entry-stop)*target
    assert r['research_parameters']==dict(window_max_age=age,stop_buffer=str(buffer),target_r=str(target))
    assert DecisionModel.restore(r['decision_checkpoint']).state()==state
    sx,so=mirror_inputs(xs,obs);short=run(sx,so,profile)
    assert short['net_pnl']==r['net_pnl']
    assert D(short['decision_state']['profit_target'])==D(500)-D(state['profit_target'])
    altered=deepcopy(r['decision_checkpoint']);altered['research_profile']='unrecognized'
    altered['sha256']=_digest({k:v for k,v in altered.items() if k!='sha256'})
    with pytest.raises(ValueError,match='DECISION_RESEARCH_PROFILE_INVALID'):DecisionModel.restore(altered)


@pytest.mark.parametrize('max_age',[4,5,6])
def test_window_last_eligible_bar_and_expiry(max_age):
    for eligible_age in (max_age,max_age+1):
        state=EntryWindow('JM2609')
        for age in range(eligible_age+1):
            state,out=observe_entry(state,contract='JM2609',bar_end=BASE+timedelta(minutes=30*age),
                near_zero_golden=age==0,daily_direction='UP',minute_angle=D(2),above_ema=True,
                volume_effective=age==eligible_age,max_age=max_age)
        assert out['met']==(eligible_age==max_age)
        assert state.source_end is None


def test_target_changes_trigger_time_and_labels_not_only_report():
    xs,obs=inputs([100,101,102,131,132,133],frames={0:dict(near_zero_golden=True,volume_tier='TIER_1')})
    early=run(xs,obs,'target0_8');later=run(xs,obs,'target1_2')
    assert early['fills'][-1]['action']=='CLOSE'
    assert early['fills'][-1]['reasons']==['PROFIT_0_8R_TIER1_CLEAR']
    assert early['fills'][-1]['decision_at']==xs[3].bar.bar_end.isoformat()
    assert early['fills'][-1]['fill_at']==(xs[5].bar.bar_end-timedelta(minutes=1)).isoformat()
    assert len(later['fills'])==1 and later['status']=='OPEN'


@pytest.mark.parametrize('profile',[True,1,'unknown',{},[]])
def test_invalid_profile_rejected(profile):
    xs,obs=inputs([100])
    with pytest.raises(ValueError,match='DECISION_RESEARCH_PROFILE_INVALID'):run(xs,obs,profile)


def test_research_profile_cannot_modify_default_close_model():
    xs,obs=inputs([100])
    with pytest.raises(ValueError,match='ACCOUNT_RESEARCH_PROFILE_REQUIRES_THEORETICAL_OPEN'):
        replay(xs,obs,'r',research_profile='window4')


def test_default_checkpoint_identity_preserved_and_profile_cannot_be_dropped():
    xs,obs=inputs([100,101,102],frames={0:dict(near_zero_golden=True)})
    default=replay(xs,obs,'r',execution_model='theoretical_open')
    assert 'research_profile' not in default['decision_checkpoint']
    assert 'research_profile' not in default['decision_state']
    altered=deepcopy(run(xs,obs,'window4')['decision_checkpoint']);del altered['research_profile']
    altered['sha256']=_digest({k:v for k,v in altered.items() if k!='sha256'})
    with pytest.raises(ValueError,match='CHECKPOINT_INVALID'):DecisionModel.restore(altered)


@pytest.mark.parametrize('profile',RESEARCH_PROFILES)
def test_profile_restart_and_duplicate_event_parity(profile):
    xs,obs=inputs([100,101,102,131,132,133],frames={0:dict(near_zero_golden=True,volume_tier='TIER_1')})
    full=run(xs,obs,profile);events=full['decision_checkpoint']['events']
    partial=DecisionModel('JM2609','parameter-test',research_profile=profile)
    for event in events[:4]:partial.apply(event)
    resumed=DecisionModel.restore(partial.checkpoint())
    assert resumed.apply(events[3])==partial.apply(events[3])
    for event in events[4:]:resumed.apply(event)
    assert resumed.checkpoint()==full['decision_checkpoint']
    assert resumed.state()==full['decision_state']
