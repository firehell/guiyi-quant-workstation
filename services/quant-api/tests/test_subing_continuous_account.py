from datetime import timedelta
from dataclasses import replace
import pytest
from app.subing_model.account import ContinuousAccount,encode_execution
from tests.unit.subing_account.test_account import inputs,BASE

def packets():
    xs,obs=inputs([100,101,102,102,101,101],frames={0:dict(regime='TREND_UP',near_zero_golden=True)})
    for x in xs:
        b=x.bar
        yield dict(event_id=obs[b.bar_end]['event_id'],contract=b.physical_contract,expected_end=b.bar_end.isoformat(),observed_at=(b.bar_end+timedelta(seconds=1)).isoformat(),
            execution=encode_execution(replace(x,bar=replace(b,confirmed_at=b.bar_end+timedelta(seconds=1)))),technical=obs[b.bar_end],
            schedule=dict(previous=str(b.trading_day-timedelta(days=1)),first_open=b.session_open_at.isoformat(),day_end=b.session_close_at.isoformat(),next_open=(b.session_close_at+timedelta(days=1)).isoformat()),
            structure=dict(phase='STRUCTURE_ENVELOPE',structure_direction='UP',base_regime='TREND_UP'))

def test_restart_exact_duplicate_and_knowledge_clock():
    ps=list(packets());a=ContinuousAccount('JM2609','run',BASE-timedelta(minutes=1));b=ContinuousAccount('JM2609','run',BASE-timedelta(minutes=1))
    for p in ps[:3]:a.apply(p);b.apply(p)
    for p in ps[3:]:a.apply(p);b.apply(p)
    assert a.state()==b.state()
    assert a.engine.fills
    assert a.apply(ps[-1]) is False
    assert all(f['fill_bar_end']>f['decision_at'] for f in a.engine.fills)
    changed=dict(ps[-1],expected_end='bad')
    with pytest.raises(ValueError,match='OBSERVATION_ID_CONFLICT'):a.apply(changed)

def test_rollover_retains_state():
    p=next(packets());a=ContinuousAccount('JM2609','run',BASE-timedelta(minutes=1));a.apply(p);before=a.engine.model.state()
    with pytest.raises(ValueError,match='ROLLOVER_WAIT'):a.apply(dict(p,event_id='roll',contract='JM2701'))
    assert a.engine.model.state()==before and a.halted=='ROLLOVER_WAIT'

def test_missing_facts_keep_known_full_and_partial_protection_without_fills():
    from decimal import Decimal as D
    from types import SimpleNamespace
    a=ContinuousAccount('JM2609','run',BASE-timedelta(minutes=1))
    for p in packets():a.apply(p)
    model=a.engine.model;before=list(a.engine.fills)
    model.layers=[dict(layer_id='base',kind='OPEN',at=BASE,price=D('100')),
                  dict(layer_id='add',kind='ADD',at=BASE,price=D('105'))]
    model.initial_stop=D('90');model.side='LONG';model.exit_layers=[];model.clear_reasons=[]
    b=SimpleNamespace(bar_end=BASE+timedelta(minutes=10),close=D('102'))
    a.hold_for_facts(b,None,b.bar_end,'EXECUTION_FACTS_INTERRUPTED_REVIEW_REQUIRED')
    assert model.exit_layers==['add'] and a.protection_observation['demand']=='REDUCE_OBLIGATION'
    b.close=D('89');a.hold_for_facts(b,None,b.bar_end,'EXECUTION_FACTS_INTERRUPTED_REVIEW_REQUIRED')
    assert model.exit_layers==['base','add'] and model.clear_reasons==['FIXED_STOP']
    assert a.protection_observation['demand']=='EXIT_OBLIGATION' and a.engine.fills==before
    with pytest.raises(ValueError,match='EXECUTION_FACTS_INTERRUPTED_REVIEW_REQUIRED'):a.apply(dict(next(packets()),event_id='new'))
