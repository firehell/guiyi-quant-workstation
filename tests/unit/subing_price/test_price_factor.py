from decimal import Decimal
import pytest
from guiyi_quant.indicators.subing_price import price_point


@pytest.mark.parametrize('close,relation,near',[
    ('99.999999','BELOW',False),('100','ON',False),('100.000001','ABOVE',True),
    ('109.999999','ABOVE',True),('110','ABOVE',False),('110.000001','ABOVE',False),
])
def test_price_distance_boundaries(close,relation,near):
    p=price_point(Decimal(close),Decimal('100'))
    assert p.relation==relation and p.near_above_ema is near
    assert p.above_ema is (relation=='ABOVE')
    assert p.below_ema is (relation=='BELOW')
    assert p.distance==Decimal(close)-Decimal('100')


def test_warmup_and_invalid_are_unknown():
    p=price_point(Decimal('100'),None)
    assert p.reason=='WARMUP' and p.above_ema is None
    for close,ema in [(Decimal('NaN'),Decimal('100')),(Decimal('100'),Decimal('Infinity')),(Decimal('0'),Decimal('100'))]:
        p=price_point(close,ema)
        assert p.reason=='INPUT_INVALID' and p.near_above_ema is None

from datetime import datetime, timedelta, timezone
from guiyi_quant.indicators.subing_price import PullbackState, observe


def tick(state, i, low='99', close='101', high='105', ema='100', atr='10'):
    return observe(state, contract='JM2701', bar_end=datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(minutes=30*i),
                   high=Decimal(high), low=Decimal(low), close=Decimal(close),
                   ema21=Decimal(ema), atr14=Decimal(atr))


@pytest.mark.parametrize('low,touch', [('98',True),('102',True),('97.999',False),('102.001',False)])
def test_zone_boundaries(low,touch):
    _, p=tick(PullbackState('JM2701'),0,low=low,close='104')
    assert p['touch'] is touch and p['hold'] is touch
    assert p['breakout'] is False


def test_replacement_consumption_and_close_invalidation():
    s,p=tick(PullbackState('JM2701'),0)
    s,p=tick(s,1,high='104')
    assert p['replaced'] and s.armed_high==Decimal('104')
    s,p=tick(s,2,low='103',close='105',high='106')
    assert p['breakout'] and p['breakout_high']==Decimal('104') and s.armed_at is None
    s,p=tick(s,3,low='103',close='105',high='106')
    assert not p['breakout']
    s,p=tick(s,4)
    s,p=tick(s,5,close='100',high='104')
    assert p['invalidated'] and s.armed_at is None and not p['hold']


def test_breakout_and_invalidation_are_separate_facts():
    s,_=tick(PullbackState('JM2701'),0)
    s,p=tick(s,1,close='100',high='106')
    assert p['breakout'] and p['invalidated'] and s.armed_at is None


def test_equal_high_no_breakout_and_new_hold_starts_next_bar():
    s,_=tick(PullbackState('JM2701'),0)
    s,p=tick(s,1)
    assert not p['breakout']
    s,p=tick(s,2,high='106')
    assert p['breakout'] and p['hold'] and s.armed_high==Decimal('106')
    s,p=tick(s,3,low='103',close='104',high='106')
    assert not p['breakout']


def test_prefix_restart_and_bad_input_reset():
    import pickle
    s,_=tick(PullbackState('JM2701'),0)
    restored=pickle.loads(pickle.dumps(s))
    assert tick(s,1)==tick(restored,1)
    _,p=tick(s,1,atr='0')
    assert p['reason']=='INPUT_INVALID' and p['armed_at'] is None
    with pytest.raises(ValueError): tick(s,0)
    with pytest.raises(ValueError): tick(PullbackState('OTHER'),1)
