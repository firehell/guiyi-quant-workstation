from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
import pytest
from guiyi_quant.indicators import subing_trend as trend, subing_macd as cross
from guiyi_quant.indicators.ema import initial_ema_state, step_ema
from guiyi_quant.indicators.macd import initial_macd_state, step_macd
from scripts.research.subing_trend import PERIOD_PROFILES, load
from test_export import Market


@pytest.mark.parametrize('period', [19,21,23])
def test_trend_period_uses_canonical_ema_and_survives_reset(period):
    state=trend.initial_state('JM2701','30m',ema_period=period)
    reference=initial_ema_state(period)
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    points=[]
    for i in range(90):
        t=start+timedelta(minutes=30*i);price=100+math.sin(i/3)*4+i/10
        reference,p=step_ema(reference,price,bar_end=t.isoformat())
        state,q=trend.step(state,contract='JM2701',frequency='30m',bar_end=t,high=price+2,low=price-2,close=price)
        assert q.ema21==p.value
        points.append(q)
        if i==40: saved=state
    resumed=saved
    for i in range(41,90):
        t=start+timedelta(minutes=30*i);price=100+math.sin(i/3)*4+i/10
        resumed,q=trend.step(resumed,contract='JM2701',frequency='30m',bar_end=t,high=price+2,low=price-2,close=price)
        assert q==points[i]
    assert resumed==state
    clean,q=trend.step(state,contract='JM2701',frequency='30m',bar_end=start+timedelta(minutes=2700),high=102,low=98,close=float('nan'))
    assert q.reason=='INPUT_INVALID' and clean.ema.period==period and clean.ema.count==0


@pytest.mark.parametrize('periods', sorted({v[2] for v in PERIOD_PROFILES.values()}))
def test_macd_periods_use_canonical_sma_seed_and_cross_geometry(periods):
    state=cross.initial_state('JM2701','30m',periods=periods)
    ref=initial_macd_state(*periods,ema_seed_policy='sma_window',histogram_scale=2)
    start=datetime(2026,1,1,tzinfo=timezone.utc);previous=None;points=[]
    for i in range(150):
        t=start+timedelta(minutes=30*i);price=100+math.sin(i/5)*12
        ref,(d,e,h)=step_macd(ref,price,bar_end=t.isoformat())
        state,p=cross.step(state,contract='JM2701',frequency='30m',bar_end=t,close=price)
        assert p.dif==d.value and p.dea==e.value
        if all(x.ready and x.valid and x.value is not None for x in (d,e,h)):
            assert p==replace(cross.cross_point(previous,d.value,e.value),histogram=h.value)
            previous=(d.value,e.value)
        points.append(p)
        if i==70:saved=state
    for i in range(71,150):
        saved,p=cross.step(saved,contract='JM2701',frequency='30m',bar_end=start+timedelta(minutes=30*i),close=100+math.sin(i/5)*12)
        assert p==points[i]
    assert saved==state
    clean,p=cross.step(state,contract='JM2701',frequency='30m',bar_end=start+timedelta(minutes=4500),close=0)
    assert (clean.macd.fast.period,clean.macd.slow.period,clean.macd.signal.period)==periods
    assert clean.previous is None and p.reason=='INPUT_INVALID'


@pytest.mark.parametrize('bad', [True,19.0,0,20,'19',None])
def test_invalid_ema_period_rejected(bad):
    with pytest.raises(ValueError):trend.initial_state('JM2701','30m',ema_period=bad)


@pytest.mark.parametrize('bad', [(True,26,9),(12,26,9.0),(12,26),[12,26,9],(10,24,9),None])
def test_invalid_macd_period_rejected(bad):
    with pytest.raises(ValueError):cross.initial_state('JM2701','30m',periods=bad)


@pytest.mark.parametrize('profile', list(PERIOD_PROFILES))
def test_export_profile_identity_source_and_unchanged_market_facts(profile):
    m=Market()
    base=load(m,m.day,m.day,include_joint=True)
    candidate=load(m,m.day,m.day,include_joint=True,research_profile=profile)
    assert 'research_profile' not in base
    assert candidate['research_profile']==profile
    assert candidate['research_version']=='subing_factor_period_stability_v1'
    assert candidate['sources']==base['sources'] and candidate['input_hash']==base['input_hash']
    fields=('contract','frequency','time','day','open','high','low','close','owned','volume_factor')
    for a,b in zip(base['rows'],candidate['rows']):
        assert {k:a[k] for k in fields}=={k:b[k] for k in fields}
        if profile.startswith('daily') and a['frequency']=='30m':
            assert a['ema21']==b['ema21'] and a['macd']==b['macd']
        if not profile.startswith('daily') and a['frequency']=='1d':assert a==b
    with pytest.raises(ValueError):load(m,m.day,m.day,research_profile=profile)


@pytest.mark.parametrize('bad', ['bad',1,[],True])
def test_export_rejects_unknown_profile_before_market_access(bad):
    with pytest.raises(ValueError):load(None,None,None,include_joint=True,research_profile=bad)
