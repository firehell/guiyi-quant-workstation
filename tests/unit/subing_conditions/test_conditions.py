from decimal import Decimal as D
import pytest
from guiyi_quant.indicators.subing_conditions import entry_conditions, exit_facts


def entry(**kwargs):
    values=dict(daily_direction='UP', minute_angle=D('1'), above_ema=True,
                near_zero_golden=True, volume_effective=True)
    return entry_conditions(**(values | kwargs))


@pytest.mark.parametrize('daily,met', [('UP',True),('NEUTRAL',True),('DOWN',False),('UNKNOWN',None)])
def test_daily_permission(daily,met):
    assert entry(daily_direction=daily)['met'] is met


@pytest.mark.parametrize('key,value', [('minute_angle',D('0')),('above_ema',False),
                                     ('near_zero_golden',False),('volume_effective',False)])
def test_each_gate_is_required_on_same_bar(key,value):
    assert entry(**{key:value})['met'] is False
    assert entry()['met'] is True
    assert entry(near_zero_golden=False)['met'] is False  # no old cross reused


def test_missing_does_not_become_permission_or_known_false():
    r=entry(daily_direction='UNKNOWN',volume_effective=False)
    assert r['met'] is None and r['missing']==['daily_allows_long']
    assert r['failed']==['volume_expanded']
    assert entry(volume_effective=1)['met'] is None


@pytest.mark.parametrize('close,prev,ema,below_prev,below_ema',[
    ('99','100','100',True,True),('100','100','100',False,False),
    ('100.000001','100','100',False,False),('99','98','100',False,True),
])
def test_strict_exit_levels(close,prev,ema,below_prev,below_ema):
    r=exit_facts(close=D(close),previous_low=D(prev),ema21=D(ema),high_death=True)
    assert r['below_previous_low'] is below_prev and r['below_ema'] is below_ema
    assert r['high_death'] is True
    # Simultaneous/repeated facts remain facts; no position-dependent suppression.
    assert exit_facts(close=D(close),previous_low=D(prev),ema21=D(ema),high_death=True)==r


def test_missing_or_invalid_facts_stay_independent():
    r=exit_facts(close=D('99'),previous_low=None,ema21=D('100'),high_death=None)
    assert r['below_previous_low'] is None and r['below_ema'] is True
    r=exit_facts(close=D('NaN'),previous_low=D('100'),ema21=D('100'),high_death=True)
    assert r['below_previous_low'] is None and r['below_ema'] is None and r['high_death'] is True


@pytest.mark.parametrize('angle,met', [('-0.860449',False),('-0.000001',False),('0',False),('0.000001',True),('4.99',True),('5',True),('NaN',None),('Infinity',None)])
def test_minute_entry_angle_zero_boundary(angle,met):
    assert entry(minute_angle=D(angle))['met'] is met


def test_missing_angle_is_unknown():
    assert entry(minute_angle=None)['met'] is None
