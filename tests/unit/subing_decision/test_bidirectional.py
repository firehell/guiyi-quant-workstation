from copy import deepcopy
from decimal import Decimal as D

import pytest

from guiyi_quant.subing_decision import DecisionModel
from tests.unit.subing_decision.test_core import ack, frame, observation, three_layers


def mirror(e):
    e = deepcopy(e)
    def price(x):
        return None if x is None else str(D('500')-D(x))
    if e['kind'] == 'ack':
        e['price'] = price(e['price'])
        return e
    e['close'] = price(e['close'])
    e['daily_direction'] = {'UP':'DOWN','DOWN':'UP'}.get(e['daily_direction'],e['daily_direction'])
    m=e['m30']
    if m:
        for a,b in [('near_zero_golden','near_zero_death'),('high_death','low_golden'),
                    ('above_ema','below_ema'),('below_previous_low','above_previous_high'),
                    ('qualified_pullback','qualified_rebound'),('pullback_invalidated','rebound_invalidated')]:
            m[a],m[b]=m[b],m[a]
        m['low'],m['high']=price(m['high']),price(m['low'])
        m['pullback_high'],m['rebound_low']=price(m['rebound_low']),price(m['pullback_high'])
        m['ema21']=price(m['ema21'])
        m['minute_angle']=None if m['minute_angle'] is None else str(-D(m['minute_angle']))
    return e


def test_short_three_layers_protection_reduction_and_checkpoint_mirror():
    long=three_layers()
    long.apply(frame(90, below_previous_low=True, high_death=True))
    long.apply(ack(long,91,price='129',targets=['test:3']))
    long.apply(observation(92,close='130',round_loss=True))
    long.apply(ack(long,93,price='128'))
    short=DecisionModel('JM2609','test')
    for e in long.events:
        result=short.apply(mirror(e))
        original=long.results[e['event_id']]
        assert result['after']['quantity']==original['after']['quantity']
        assert [a['kind'] for a in result['actions']]==[a['kind'] for a in original['actions']]
        for a,b in zip(result['actions'],original['actions']):
            assert a.get('reasons')==b.get('reasons')
            assert a.get('layer_ids')==b.get('layer_ids')
    assert short.side is None
    assert DecisionModel.restore(short.checkpoint()).state()==short.state()
    assert all(r['after']['side']=='SHORT' for r in short.results.values() if r['after']['quantity'])


@pytest.mark.parametrize('fast,expected',[(True,2),(False,1)])
def test_short_one_r_exits_newest_profitable_adds_and_retains_base(fast,expected):
    long=three_layers()
    short=DecisionModel('JM2609','test')
    for e in long.events:short.apply(mirror(e))
    assert short.initial_stop==D('483')
    assert short.risk_distance==D('93') and short.profit_target==D('297')
    if not fast:short.apply(mirror(frame(90)))
    hit=observation(91,close='203',layer_nets={l['layer_id']:'20' for l in short.layers})
    r=short.apply(mirror(hit))
    assert r['actions'][0]['reasons']==['PROFIT_1R']
    assert len(r['actions'][0]['layer_ids'])==expected
    assert 'test:1' not in r['actions'][0]['layer_ids']


def test_short_stop_is_max_signal_extreme_plus_13_and_fill_based_r():
    m=DecisionModel('JM2609','short')
    e=mirror(frame(0,near_zero_golden=True,ema21='100',low='99'))
    e['close']='390'
    m.apply(e)
    assert m.pending['initial_stop']==D('414')
    m.apply(ack(m,1,price='390'))
    assert m.profit_target==D('366')
    assert m.apply(observation(2,close='413.9',daily_direction='DOWN'))['actions']==[]
    assert m.apply(observation(3,close='414',daily_direction='DOWN'))['actions'][0]['reasons']==['FIXED_STOP']


def test_short_daily_up_rejected_and_neutral_allowed():
    for daily,opened in [('UP',False),('NEUTRAL',True),('DOWN',True)]:
        m=DecisionModel('JM2609','s')
        e=mirror(frame(0,near_zero_golden=True));e['daily_direction']=daily
        r=m.apply(e)
        assert bool(r['actions'] and r['actions'][0]['kind']=='OPEN')==opened


def test_clearing_does_not_reverse_in_same_observation():
    m=three_layers()
    e=mirror(frame(90,near_zero_golden=True)); e['close']='130'
    r=m.apply(e)
    assert len(r['actions'])==1 and r['actions'][0]['kind']=='CLOSE'
    m.apply(ack(m,91,price='129'))
    assert m.apply(mirror(frame(120)))['actions']==[]
    assert m.apply(mirror(frame(150,near_zero_golden=True)))['actions'][0]['side']=='SHORT'
