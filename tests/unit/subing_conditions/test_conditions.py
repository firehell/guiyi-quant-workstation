from decimal import Decimal as D
import pytest
from guiyi_quant.indicators.subing_conditions import entry_conditions, exit_facts


def entry(**kwargs):
    values=dict(daily_direction='UP', minute_angle=D('1'), above_ema=True,
                golden_window=True, volume_effective=True)
    return entry_conditions(**(values | kwargs))


@pytest.mark.parametrize('daily,met', [('UP',True),('NEUTRAL',True),('DOWN',False),('UNKNOWN',None)])
def test_daily_permission(daily,met):
    assert entry(daily_direction=daily)['met'] is met


@pytest.mark.parametrize('key,value', [('minute_angle',D('0')),('above_ema',False),
                                     ('golden_window',False),('volume_effective',False)])
def test_each_gate_is_required_on_same_bar(key,value):
    assert entry(**{key:value})['met'] is False
    assert entry()['met'] is True
    assert entry(golden_window=False)['met'] is False  # no valid window


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


from datetime import datetime, timedelta, timezone
from guiyi_quant.indicators.subing_conditions import EntryWindow, observe_entry


def step(state, n, **kw):
    args=dict(contract='JM2701',bar_end=datetime(2026,8,26,15,tzinfo=timezone.utc)+timedelta(minutes=30*n),
              near_zero_golden=False,daily_direction='UP',minute_angle=D('1'),above_ema=True,volume_effective=True)
    return observe_entry(state, **(args|kw))


def test_cross_bar_consumes_once():
    s,p=step(EntryWindow('JM2701'),0,near_zero_golden=True)
    assert p['met'] and p['window']['age']==0 and p['window']['consumed']
    s,p=step(s,1)
    assert p['met'] is False and s.source_end is None


def test_fifth_later_bar_allowed_sixth_not_allowed():
    s=EntryWindow('JM2701')
    for n in range(5):s,p=step(s,n,near_zero_golden=n==0,minute_angle=D('0'))
    checkpoint=s
    s,p=step(s,5)
    assert p['met'] and p['window']['age']==5
    s,p=step(checkpoint,5,volume_effective=False)
    assert not p['met'] and p['window']['expired_after_bar'] and s.source_end is None
    s,p=step(s,6)
    assert not p['met']


def test_waiting_volume_price_and_daily_failure_do_not_consume():
    s,p=step(EntryWindow('JM2701'),0,near_zero_golden=True,minute_angle=D('-0.86'))
    s,p=step(s,1,volume_effective=False,above_ema=False,daily_direction='DOWN')
    assert not p['met'] and s.source_end is not None
    s,p=step(s,2,volume_effective=None)
    assert p['met'] is None and s.source_end is not None
    s,p=step(s,3)
    assert p['met'] and p['window']['age']==3


def test_new_cross_replaces_window_and_macd_unknown_clears():
    s,p=step(EntryWindow('JM2701'),0,near_zero_golden=True,volume_effective=False)
    s,p=step(s,3,near_zero_golden=True,volume_effective=False)
    assert p['window']['replaced'] and p['window']['age']==0
    s,p=step(s,4,near_zero_golden=None)
    assert p['met'] is None and s.source_end is None
    s,p=step(s,5)
    assert not p['met']


def test_identity_time_restart_prefix_and_session_gap():
    import pickle
    s,_=step(EntryWindow('JM2701'),0,near_zero_golden=True,volume_effective=False)
    assert step(s,1)==step(pickle.loads(pickle.dumps(s)),1)
    with pytest.raises(ValueError):step(s,0)
    with pytest.raises(ValueError):step(s,1,contract='JM2609')
    with pytest.raises(ValueError):step(s,1,bar_end=datetime(2026,8,27))
    # Overnight gap advances by one completed bar, not elapsed half hours.
    _,p=step(s,1,bar_end=datetime(2026,8,27,1,30,tzinfo=timezone.utc))
    assert p['window']['age']==1
    def replay(count):
        state=EntryWindow('JM2701');out=[]
        for n in range(count):
            state,p=step(state,n,near_zero_golden=n==0,volume_effective=n>=4)
            out.append(p)
        return out
    full=replay(9)
    for n in range(1,10):assert replay(n)==full[:n]
