from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from guiyi_quant.subing_decision import DecisionModel

BASE = datetime(2026, 7, 13, 1, 0, tzinfo=timezone.utc)


def observation(n, *, m30=False, **changes):
    e = dict(event_id=f'o{n}', kind='observe', at=(BASE+timedelta(minutes=n)).isoformat(),
        contract='JM2609', trading_day='2026-07-13', close='130', daily_direction='UP',
        daily_at=(BASE-timedelta(days=1)).isoformat(), day_end_window=False,
        admission=True, round_loss=False, day_loss=False, remaining_net='100', reconciled=True,
        m30=dict(near_zero_golden=False,minute_angle='2',above_ema=True,volume_effective=True,
            below_previous_low=False,high_death=False,below_ema=False,
            qualified_pullback=False,pullback_high=None,pullback_invalidated=False) if m30 else None)
    e.update(changes)
    return e


def frame(n, **changes):
    e = observation(n,m30=True)
    e['m30'].update(changes)
    return e


def ack(model,n, *, status='FILLED', price='110', targets=None):
    return dict(event_id=f'a{n}',kind='ack',at=(BASE+timedelta(minutes=n)).isoformat(),contract='JM2609',
        decision_id=model.pending['decision_id'],status=status,price=price,
        layer_ids=targets if targets is not None else list(model.pending['layer_ids']))


def opened():
    model = DecisionModel('JM2609','test')
    model.apply(frame(0,near_zero_golden=True))
    model.apply(ack(model,1))
    return model


def test_unknown_cannot_rearm_pullback_on_same_frame_or_revive_later():
    m = opened()
    m.apply(frame(30, qualified_pullback=True, pullback_high='112', near_zero_golden=None))
    assert m.pullback is None
    assert not m.technical_ready
    assert m.apply(frame(60))['actions'] == []
    assert m.pending is None


def test_pending_add_is_cancelled_on_reduction_signal_even_with_one_layer():
    m = opened()
    m.apply(frame(30, qualified_pullback=True, pullback_high='112'))
    m.apply(observation(31, close='113'))
    result = m.apply(frame(60, below_previous_low=True))
    assert result['actions'][0]['kind'] == 'CANCEL'
    assert len(m.layers) == 1
    assert m.pending['cancel_requested']


def three_layers():
    m = opened()
    m.apply(frame(30,qualified_pullback=True,pullback_high='112'))
    m.apply(observation(31,close='113'))
    m.apply(ack(m,32,price='114'))
    m.apply(frame(60,qualified_pullback=True,pullback_high='116'))
    m.apply(observation(61,close='117'))
    m.apply(ack(m,62,price='118'))
    return m


def test_intent_does_not_change_position_and_ack_is_strict_later():
    m=DecisionModel('JM2609','test')
    e=frame(0,near_zero_golden=True)
    result=m.apply(e)
    assert result['actions'][0]['kind']=='OPEN' and m.layers==[]
    snapshot=m.checkpoint()
    with pytest.raises(ValueError): m.apply(ack(m,0))
    assert m.checkpoint()==snapshot
    m.apply(ack(m,1))
    assert len(m.layers)==1


def test_new_pullbacks_add_to_three_and_max_rejection_consumes():
    m=three_layers()
    assert [x['kind'] for x in m.layers]==['OPEN','ADD','ADD']
    m.apply(frame(90,qualified_pullback=True,pullback_high='120'))
    result=m.apply(observation(91,close='121'))
    assert result['actions'][0]['reasons']==['MAX_THREE_LAYERS']
    assert m.pullback is None and m.pending is None
    assert m.apply(observation(92,close='122'))['actions']==[]


def test_dual_reduction_lifo_and_pending_not_position():
    m=three_layers()
    result=m.apply({**frame(90,below_previous_low=True,high_death=True),'close':'130'})
    assert result['actions'][0]['layer_ids']==['test:3','test:2']
    assert len(m.layers)==3
    m.apply(ack(m,91,price='129'))
    assert [x['layer_id'] for x in m.layers]==['test:1']
    assert m.apply(frame(120,below_previous_low=True,high_death=True))['actions']==[]


def test_protection_then_reduction_never_duplicates_layer():
    m=three_layers()
    result=m.apply({**frame(90,below_previous_low=True,high_death=True),'close':'117'})
    targets=result['actions'][0]['layer_ids']
    assert targets==['test:3','test:2'] and len(set(targets))==2


def test_clear_dominates_and_partial_ack_keeps_obligation():
    m=three_layers()
    result=m.apply({**frame(90,below_ema=True,below_previous_low=True,high_death=True),'round_loss':True})
    assert result['actions'][0]['reasons']==['ROUND_LOSS','EMA_CLEAR']
    m.apply(ack(m,91,targets=['test:3']))
    assert len(m.layers)==2 and m.pending['layer_ids']==['test:1','test:2'] and m.cooldown==0
    m.apply(ack(m,92))
    assert len(m.layers)==0 and m.cooldown==10


def test_cooldown_tenth_bar_cannot_seed_early_golden():
    m=opened()
    m.apply(frame(30,below_ema=True)); m.apply(ack(m,31))
    for i in range(1,11):
        assert m.apply(frame(30+30*i,near_zero_golden=True))['after']['pending'] is None
    assert m.cooldown==0
    assert m.apply(frame(360))['actions']==[]
    assert m.apply(frame(390,near_zero_golden=True))['actions'][0]['kind']=='OPEN'


def test_clear_ack_same_time_as_m30_does_not_count_bar():
    m=opened(); m.apply(observation(29,round_loss=True)); m.apply(ack(m,30))
    m.apply(frame(30))
    assert m.cooldown==10


def test_entry_wait_window_uses_shared_factor_and_rejected_not_replayed():
    m=DecisionModel('JM2609','test')
    m.apply(frame(0,near_zero_golden=True,volume_effective=False))
    e=frame(30);e['admission']=None
    assert m.apply(e)['actions'][0]['kind']=='REJECT'
    assert m.apply(frame(60))['actions']==[]


def test_day_end_clears_nonpositive_and_blocks_adds():
    m=opened();m.apply(frame(30,qualified_pullback=True,pullback_high='112'))
    e=observation(31,close='113',day_end_window=True)
    assert m.apply(e)['actions'][0]['reasons']==['DAY_END_NO_OPEN']
    assert m.pullback is None
    result=m.apply(observation(32,day_end_window=True,remaining_net='0'))
    assert result['actions'][0]['kind']=='CLOSE'


def test_daily_down_only_blocks_new_actions():
    m=opened()
    assert m.apply(observation(2,daily_direction='DOWN'))['actions']==[]
    assert len(m.layers)==1
    m.apply(frame(30,qualified_pullback=True,pullback_high='112'))
    result=m.apply(observation(31,close='113',daily_direction='DOWN'))
    assert result['actions'][0]['reasons']==['DAILY_NOT_ALLOWED']


def test_exit_invalidates_old_pullback_and_ack_requires_new_one():
    m=three_layers();m.apply(frame(90,qualified_pullback=True,pullback_high='120'))
    m.apply({**frame(120,below_previous_low=True,qualified_pullback=True,pullback_high='140'),'close':'130'})
    assert m.pullback is None
    m.apply(ack(m,121,price='129'))
    assert m.apply(observation(122,close='150'))['actions']==[]


def test_pending_open_cancel_keeps_late_fill_and_forced_exit():
    m=DecisionModel('JM2609','test');m.apply(frame(0,near_zero_golden=True))
    result=m.apply(observation(1,day_loss=True))
    assert result['actions'][0]['kind']=='CANCEL' and m.layers==[]
    m.apply(ack(m,2))
    assert len(m.layers)==1
    assert m.apply(observation(3))['actions'][0]['kind']=='CLOSE'


def test_day_halt_does_not_reset_same_day_reconciliation():
    m=DecisionModel('JM2609','test')
    m.apply(observation(0,reconciled=False,day_loss=True))
    m.apply(observation(1,reconciled=True))
    assert m.day_halted
    m.apply(observation(1440,trading_day='2026-07-14',reconciled=False))
    assert m.day_halted
    m.apply(observation(1441,trading_day='2026-07-14',reconciled=True))
    assert not m.day_halted


def test_duplicate_checkpoint_and_conflict():
    m=three_layers();checkpoint=m.checkpoint()
    restored=DecisionModel.restore(checkpoint)
    assert restored.state()==m.state()
    e=observation(63,close='130')
    assert restored.apply(e)==m.apply(e)
    assert m.apply(e)==restored.apply(e)
    changed=deepcopy(e);changed['close']='131'
    with pytest.raises(ValueError,match='EVENT_ID_CONFLICT'):m.apply(changed)
    checkpoint['events'][0]['close']='999'
    with pytest.raises(ValueError,match='CHECKPOINT_INVALID'):DecisionModel.restore(checkpoint)


@pytest.mark.parametrize('changes',[{'close':110},{'close':'NaN'},{'daily_at':BASE.isoformat()},
    {'admission':1},{'contract':'JM2701'},{'daily_direction':'UP','daily_at':None}])
def test_invalid_input_rejected_atomically(changes):
    m=DecisionModel('JM2609','test');before=m.checkpoint()
    with pytest.raises((ValueError,TypeError)):m.apply(observation(0,**changes))
    assert m.checkpoint()==before


def test_older_event_and_nonpositive_price():
    m=opened()
    with pytest.raises(ValueError):m.apply(observation(-1))
    with pytest.raises(ValueError):m.apply(observation(2,close='0'))


def test_cancelled_close_keeps_exit_obligation():
    m=opened();m.apply(frame(30,below_ema=True))
    m.apply(ack(m,31,status='CANCELLED',price=None,targets=[]))
    assert len(m.layers)==1 and m.cooldown==0
    result=m.apply(observation(32))
    assert result['actions'][0]['kind']=='CLOSE'


def test_pending_add_late_fill_after_cancel_is_retained_and_cleared():
    m=opened();m.apply(frame(30,qualified_pullback=True,pullback_high='112'))
    m.apply(observation(31,close='113'))
    result=m.apply(observation(32,round_loss=True))
    assert result['actions'][0]['kind']=='CANCEL'
    m.apply(ack(m,33,price='114'))
    assert len(m.layers)==2
    assert m.apply(observation(34))['actions'][0]['layer_ids']==['test:1','test:2']


def test_future_prefix_does_not_change_earlier_decisions():
    m=opened();before=deepcopy(m.results)
    m.apply(frame(30,qualified_pullback=True,pullback_high='112'))
    m.apply(observation(31,close='113'));m.apply(ack(m,32,price='114'))
    for key,value in before.items(): assert m.results[key]==value
    restored=DecisionModel.restore(m.checkpoint())
    assert restored.results==m.results


def test_unknown_technical_condition_cancels_pending_open():
    m=DecisionModel('JM2609','test');m.apply(frame(0,near_zero_golden=True))
    result=m.apply(frame(30,below_previous_low=None))
    assert result['actions'][0]['kind']=='CANCEL'


def test_new_pullback_cannot_be_used_on_its_confirmation_bar():
    m=opened()
    result=m.apply({**frame(30,qualified_pullback=True,pullback_high='120'),'close':'130'})
    assert result['actions']==[] and m.pullback is not None
    assert m.apply(observation(31,close='120'))['actions']==[]
    assert m.apply(observation(32,close='121'))['actions'][0]['kind']=='ADD'


def test_pre_entry_pullback_does_not_arm_position():
    m=DecisionModel('JM2609','test')
    m.apply(frame(0,near_zero_golden=True,qualified_pullback=True,pullback_high='112'))
    m.apply(ack(m,1))
    assert m.pullback is None
    assert m.apply(observation(2,close='150'))['actions']==[]


def test_missing_field_and_unknown_kind_are_atomic():
    m=DecisionModel('JM2609','test');before=m.checkpoint()
    e=observation(0);del e['reconciled']
    with pytest.raises(ValueError):m.apply(e)
    e=observation(0);e['kind']='surprise'
    with pytest.raises(ValueError):m.apply(e)
    assert m.checkpoint()==before


def test_current_unreconciled_observation_blocks_despite_earlier_success():
    m=DecisionModel('JM2609','test');m.apply(frame(0))
    e=frame(30,near_zero_golden=True);e['reconciled']=False
    result=m.apply(e)
    assert result['actions'][0]['kind']=='REJECT'
    assert 'RECONCILIATION_REQUIRED' in result['actions'][0]['reasons']
