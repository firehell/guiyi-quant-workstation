from copy import deepcopy
from decimal import Decimal as D

import pytest

from guiyi_quant.subing_decision import DecisionModel
from tests.unit.subing_decision.test_core import ack, frame, observation


def position():
    m = DecisionModel('JM2609', 'profit')
    m.apply({**frame(0, near_zero_golden=True, ema21='100', low='99'), 'close':'110'})
    m.apply(ack(m, 1, price='110'))
    return m


def layered():
    m = position()
    m.apply({**frame(30, qualified_pullback=True, pullback_high='112'), 'close':'112'})
    m.apply(observation(31, close='113'))
    m.apply(ack(m,32,price='113'))
    m.apply({**frame(60, qualified_pullback=True, pullback_high='115'), 'close':'115'})
    m.apply(observation(61,close='116'))
    m.apply(ack(m,62,price='116'))
    return m


def net_event(m, n, *, m30=False, close='134', **changes):
    e = frame(n) if m30 else observation(n)
    e.update(close=close, layer_nets={l['layer_id']:'100' for l in m.layers})
    e.update(changes)
    return e


def test_stop_uses_signal_low_or_ema_min_and_fixed_actual_fill_r():
    m = position()
    assert (m.initial_stop,m.risk_distance,m.profit_target)==(D('86'),D('24'),D('134'))
    m.apply({**frame(30,ema21='120',low='119'),'close':'125'})
    assert (m.initial_stop,m.risk_distance,m.profit_target)==(D('86'),D('24'),D('134'))
    assert not m.apply(observation(31,close='86.01'))['actions']
    r = m.apply(observation(32,close='86'))
    assert r['actions'][0]['reasons']==['FIXED_STOP']
    assert len(m.layers)==1
    m.apply(ack(m,33,price='85'))
    assert m.initial_stop is None and m.profit_target is None


def test_stop_uses_ema_when_lower_and_missing_stop_fails_closed():
    for ema,low,expected in [('98','99','85'),('100','99','86')]:
        m = DecisionModel('JM2609','r')
        m.apply({**frame(0,near_zero_golden=True,ema21=ema,low=low),'close':'110'})
        assert m.pending['initial_stop']==D(expected)
    m = DecisionModel('JM2609','r')
    result=m.apply(frame(0,near_zero_golden=True,ema21=None))
    assert 'INITIAL_STOP_NOT_PROVEN' in result['actions'][0]['reasons']


def test_nonpositive_r_fill_rejected_atomically():
    m = DecisionModel('JM2609','r')
    m.apply({**frame(0,near_zero_golden=True,ema21='100',low='99'),'close':'110'})
    before=m.checkpoint()
    with pytest.raises(ValueError,match='INITIAL_STOP_INVALID_AT_FILL'):
        m.apply(ack(m,1,price='86'))
    assert m.checkpoint()==before


@pytest.mark.parametrize('net',[None,'0','-1'])
def test_base_profit_gate_consumes_breakout(net):
    m=position();m.apply({**frame(30,qualified_pullback=True,pullback_high='112'),'close':'112'})
    result=m.apply(observation(31,close='113',base_net=net))
    assert result['actions'][0]['reasons']==['BASE_NET_NOT_POSITIVE']
    assert m.pullback is None
    assert m.apply(observation(32,close='114',base_net='100'))['actions']==[]


def test_pending_add_cancels_on_base_loss_or_breakout_equal():
    for changes in ({'base_net':'0'}, {'close':'112'}):
        m=position();m.apply({**frame(30,qualified_pullback=True,pullback_high='112'),'close':'112'})
        m.apply(observation(31,close='113'))
        result=m.apply(observation(32,close='114',**changes) if 'close' not in changes else observation(32,**changes))
        assert result['actions'][0]['kind']=='CANCEL'
        assert m.pending['breakout_high']==D('112')


def test_fast_third_bar_inclusive_lifo_partial_restore_once():
    m=layered()
    r=m.apply(net_event(m,90,m30=True))
    assert r['actions'][0]['layer_ids']==['profit:3','profit:2']
    assert r['actions'][0]['reasons']==['PROFIT_1R']
    assert m.profit_taken
    m.apply(ack(m,91,price='135',targets=['profit:3']))
    restored=DecisionModel.restore(m.checkpoint())
    assert restored.state()==m.state()
    e=ack(m,92,price='136');m.apply(e);restored.apply(e)
    assert restored.state()==m.state()
    assert [x['kind'] for x in m.layers]==['OPEN']
    m.apply({**frame(120,qualified_pullback=True,pullback_high='136'),'close':'136'})
    m.apply(observation(121,close='137'));m.apply(ack(m,122,price='138'))
    assert m.apply(net_event(m,123,close='139'))['actions']==[]
    assert len(m.layers)==2


def test_minute_after_third_bar_is_slow_only_one_layer():
    m=layered();m.apply(net_event(m,90,m30=True,close='133'))
    r=m.apply(net_event(m,91))
    assert r['actions'][0]['layer_ids']==['profit:3']


def test_unknown_or_nonprofitable_layers_not_targeted_but_trigger_consumed():
    m=layered()
    r=m.apply(net_event(m,63,layer_nets={'profit:1':'100','profit:2':'0','profit:3':None}))
    assert r['actions']==[] and m.profit_taken
    assert m.apply(net_event(m,64))['actions']==[]


def test_one_layer_target_hit_is_consumed_and_does_not_clear():
    m=position()
    assert m.apply(net_event(m,2))['actions']==[]
    assert m.profit_taken and len(m.layers)==1


def test_profit_and_ordinary_reduction_same_bar_do_not_double_reduce():
    m=layered();m.apply(net_event(m,90,m30=True,close='133'))
    e=net_event(m,120,m30=True);e['m30']['below_previous_low']=True
    r=m.apply(e)
    assert r['actions'][0]['layer_ids']==['profit:3']
    assert set(r['actions'][0]['reasons'])=={'PROFIT_1R','ORDINARY_REDUCTION'}


def test_clear_overrides_profit_and_pending_profit_upgrades():
    m=layered();e=net_event(m,90,m30=True);e['m30']['below_ema']=True
    r=m.apply(e)
    assert set(r['actions'][0]['layer_ids'])=={'profit:1','profit:2','profit:3'}
    assert r['actions'][0]['reasons']==['EMA_CLEAR']
    m=layered();m.apply(net_event(m,63));old=m.pending['decision_id']
    r=m.apply(net_event(m,64,close='86'))
    assert r['actions'][0]['supersedes_decision_id']==old
    assert r['actions'][0]['reasons']==['FIXED_STOP']
    assert len(m.pending['layer_ids'])==3


def test_profit_obligation_survives_cancel_and_prefix_is_immutable():
    m=layered();before=deepcopy(m.results)
    m.apply(net_event(m,63));m.apply(ack(m,64,status='CANCELLED',price=None,targets=[]))
    r=m.apply(net_event(m,65,close='133'))
    assert r['actions'][0]['reasons']==['PROFIT_1R']
    assert r['actions'][0]['layer_ids']==['profit:3','profit:2']
    assert all(m.results[k]==v for k,v in before.items())


def test_pending_ordinary_exit_is_not_duplicated_and_same_bar_fast_unions_targets():
    m=layered()
    e=net_event(m,63,m30=True,close='133');e['m30']['below_previous_low']=True
    m.apply(e);old=m.pending['decision_id']
    # Third bar was at 63: this minute is slow, so no extra target.
    assert m.apply(net_event(m,64))['actions']==[]
    assert m.pending['decision_id']==old
    # Construct same-bar ordinary and fast profit triggers from explicit facts.
    m=position()
    m.apply({**frame(30,qualified_pullback=True,pullback_high='112'),'close':'112'})
    m.apply(observation(31,close='113'));m.apply(ack(m,32,price='113'))
    m.apply({**frame(40,qualified_pullback=True,pullback_high='115'),'close':'115'})
    m.apply(observation(41,close='116'));m.apply(ack(m,42,price='116'))
    # At third completed frame, ordinary and profit together expand to both adds.
    e=net_event(m,60,m30=True);e['m30']['below_previous_low']=True
    r=m.apply(e)
    assert set(r['actions'][0]['layer_ids'])=={'profit:2','profit:3'}


def test_single_base_target_hit_allows_later_new_add_without_repeat_profit_exit():
    m=position()
    m.apply(net_event(m,2))
    m.apply({**frame(30,qualified_pullback=True,pullback_high='135'),'close':'135'})
    assert m.apply(observation(31,close='136'))['actions'][0]['kind']=='ADD'
    m.apply(ack(m,32,price='137'))
    assert m.apply(net_event(m,33,close='138'))['actions']==[]
    assert len(m.layers)==2 and m.profit_taken


def test_completed_frame_at_fill_time_not_counted_as_postfill_bar():
    m=position()
    m.apply({**frame(1),'close':'111'})
    assert m.completed_m30==0
    m.apply({**frame(30),'close':'112'})
    assert m.completed_m30==1
