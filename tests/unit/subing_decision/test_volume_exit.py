from decimal import Decimal as D

import pytest

from guiyi_quant.subing_decision import DecisionModel
from tests.unit.subing_decision.test_core import ack, frame, observation
from tests.unit.subing_decision.test_bidirectional import mirror


def opened_tier(tier='TIER_1', short=False, layers=1):
    m=DecisionModel('JM2609','v')
    transform=mirror if short else lambda e:e
    m.apply(transform({**frame(0,near_zero_golden=True,ema21='100',low='99',volume_tier=tier),'close':'110'}))
    m.apply(transform(ack(m,1,price='110')))
    if layers>1:
        m.apply(transform({**frame(30,qualified_pullback=True,pullback_high='112',volume_tier='TIER_3'),'close':'112'}))
        m.apply(transform(observation(31,close='113')))
        m.apply(transform(ack(m,32,price='113')))
    if layers>2:
        m.apply(transform({**frame(60,qualified_pullback=True,pullback_high='115',volume_tier='TIER_2'),'close':'115'}))
        m.apply(transform(observation(61,close='116')))
        m.apply(transform(ack(m,62,price='116')))
    return m,transform


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('layers',[1,3])
@pytest.mark.parametrize('fast',[False,True])
def test_first_tier_clears_every_layer_regardless_speed_or_layer_net(short,layers,fast):
    m,tx=opened_tier(short=short,layers=layers)
    if not fast:
        for n in (90,120,150):m.apply(tx({**frame(n),'close':'130'}))
    n=160 if not fast else 63
    e=observation(n,close='134',layer_nets={l['layer_id']:'-10' for l in m.layers})
    r=m.apply(tx(e))
    assert r['actions'][0]['reasons']==['PROFIT_1R_TIER1_CLEAR']
    assert r['actions'][0]['layer_ids']==[l['layer_id'] for l in m.layers]
    restored=DecisionModel.restore(m.checkpoint())
    assert restored.state()==m.state()
    m.apply(tx(ack(m,n+1,price='133',targets=[m.layers[-1]['layer_id']])))
    if layers>1:
        assert m.entry_volume_tier=='TIER_1'
        m.apply(tx(ack(m,n+2,price='132')))
    assert m.entry_volume_tier is None and m.side is None


@pytest.mark.parametrize('tier',['TIER_2','TIER_3'])
@pytest.mark.parametrize('short',[False,True])
def test_higher_entry_tier_retains_base_even_when_hit_bar_is_lowest(tier,short):
    m,tx=opened_tier(tier,short)
    r=m.apply(tx({**frame(30,volume_tier='TIER_1'),'close':'134'}))
    assert r['actions']==[] and m.profit_taken
    assert len(m.layers)==1 and m.entry_volume_tier==tier


def test_tier_is_actual_open_signal_not_cross_origin_or_fill_frame():
    m=DecisionModel('JM2609','v')
    m.apply({**frame(0,near_zero_golden=True,above_ema=False,volume_tier='TIER_3'),'close':'100'})
    r=m.apply({**frame(30,ema21='100',low='99',volume_tier='TIER_1'),'close':'110'})
    assert r['actions'][0]['entry_volume_tier']=='TIER_1'
    m.apply({**frame(60,volume_tier='TIER_2'),'close':'110'})
    assert m.pending['entry_volume_tier']=='TIER_1'
    m.apply(ack(m,61,price='110'))
    assert m.entry_volume_tier=='TIER_1'
    assert m.apply(observation(62,close='134'))['actions'][0]['reasons']==['PROFIT_1R_TIER1_CLEAR']


@pytest.mark.parametrize('tier',[None,'ZERO_BASELINE','NOT_EXPANDED'])
def test_unclassified_entry_tier_is_rejected_not_assumed_low_or_high(tier):
    m=DecisionModel('JM2609','v')
    r=m.apply(frame(0,near_zero_golden=True,volume_tier=tier))
    assert r['actions'][0]['reasons']==['ENTRY_VOLUME_TIER_NOT_PROVEN']
    assert m.pending is None


def test_full_exit_upgrades_pending_partial_reduction_and_restores():
    m,tx=opened_tier(layers=3)
    m.apply({**frame(90,below_previous_low=True),'close':'130'})
    old=m.pending['decision_id']
    r=m.apply(observation(91,close='134'))
    assert r['actions'][0]['supersedes_decision_id']==old
    assert len(m.pending['layer_ids'])==3
    m.apply(ack(m,92,price='133',targets=[m.layers[-1]['layer_id']]))
    restored=DecisionModel.restore(m.checkpoint())
    assert restored.state()==m.state()
    assert len(restored.pending['layer_ids'])==2
    assert restored.entry_volume_tier=='TIER_1'


def test_pending_add_is_cancelled_at_target_and_late_fill_still_gets_cleared():
    m,tx=opened_tier()
    m.apply({**frame(30,qualified_pullback=True,pullback_high='112'),'close':'112'})
    m.apply(observation(31,close='113'))
    r=m.apply(observation(32,close='134'))
    assert r['actions'][0]['kind']=='CANCEL'
    m.apply(ack(m,33,price='135'))
    r=m.apply(observation(34,close='133'))
    assert len(r['actions'][0]['layer_ids'])==2
    assert r['actions'][0]['reasons']==['PROFIT_1R_TIER1_CLEAR']


def test_other_clear_causes_are_not_lost_and_next_round_freezes_new_tier():
    m,tx=opened_tier()
    r=m.apply(observation(2,close='134',day_loss=True))
    assert r['actions'][0]['reasons']==['DAY_LOSS','PROFIT_1R_TIER1_CLEAR']
    m.apply(ack(m,3,price='133'))
    assert m.entry_volume_tier is None and m.day_halted
    e=frame(1440,near_zero_golden=True,volume_tier='TIER_3');e['trading_day']='2026-07-14'
    m.apply(e);m.apply(ack(m,1441,price='130'))
    assert m.entry_volume_tier=='TIER_3' and m.risk_distance==D('113')
