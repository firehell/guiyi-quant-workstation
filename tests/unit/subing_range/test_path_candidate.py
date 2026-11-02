from datetime import datetime, timedelta, timezone
import pickle

import pytest

from scripts.research.regime_path_candidate import initial_state, step


def replay(prices, state=None, start=0):
    state=state or initial_state('AG1','60m')
    points=[]
    for i,price in enumerate(prices,start):
        state,point=step(state,contract='AG1',frequency='60m',time=datetime(2024,1,1,tzinfo=timezone.utc)+timedelta(hours=i),close=price,atr=1.)
        points.append(point)
    return state,points


def test_direction_and_sustained_plateau_not_single_pause():
    for sign,side in ((1,'TREND_UP'),(-1,'TREND_DOWN')):
        trend=[100+sign*i*.5 for i in range(60)]
        _,points=replay(trend+[trend[-1]]*20)
        assert points[59]['label']==side
        assert points[60]['label']==side
        assert points[-1]['label']=='RANGE'
        assert points[-1]['reason']=='SUSTAINED_PLATEAU'
        first=next(i for i,p in enumerate(points) if p.get('plateau_count')==3)
        assert points[first-1]['plateau_count']==2
        assert points[first-2]['plateau_count']==1


def test_prefix_future_restart_batch_incremental_and_bounded_state():
    prices=[100+i*.1+(i%7)*.2 for i in range(140)]
    final,full=replay(prices)
    assert len(final.closes)==64
    for cut in (20,40,64,100):
        state,prefix=replay(prices[:cut])
        assert prefix==full[:cut]
        _,changed=replay(prices[:cut]+[10000.]*20)
        assert changed[:cut]==prefix
        restored=pickle.loads(pickle.dumps(state))
        end,tail=replay(prices[cut:],restored,cut)
        assert end==final and prefix+tail==full


def test_contract_gap_preview_and_atr_recovery():
    state,_=replay([100+i*.2 for i in range(50)])
    kwargs=dict(contract='AG1',frequency='60m',time=state.last_time+timedelta(hours=1),close=110.,atr=1.)
    for changes in ({'contract':'AG2'},{'completed':False},{'time':state.last_time}):
        with pytest.raises(ValueError):
            step(state,**(kwargs|changes))
    for changes in ({'coverage_ok':False},{'close':float('nan')},{'atr':0.}):
        clean,p=step(state,**(kwargs|changes))
        assert p['label']=='UNKNOWN' and not clean.closes
    clean,p=step(state,**(kwargs|{'atr':None}))
    assert p['label']=='UNKNOWN' and clean.plateau_count==0
    _,p=step(clean,**(kwargs|{'time':clean.last_time+timedelta(hours=1)}))
    assert p['label']!='UNKNOWN'


def test_progress_only_resolves_disputed_after_two_confirmations():
    values=[120-i for i in range(20)]+[100+i*.5 for i in range(24)]
    for sign,side in ((1,'TREND_UP'),(-1,'TREND_DOWN')):
        _,points=replay([200+sign*v for v in values])
        triggered=[(i,p) for i,p in enumerate(points) if p.get('reason')=='DIRECTION_PROGRESS']
        assert triggered
        i,p=triggered[0]
        assert p['label']==side and p['reference']=='DISPUTED'
        assert p['direction_count']==2 and points[i-1]['direction_count']==1
        assert points[i-1]['reason']!='DIRECTION_PROGRESS'


def test_progress_direction_change_resets_confirmation_and_preserves_clear_reference():
    from dataclasses import replace
    prices=[120-i for i in range(20)]+[100+i*.5 for i in range(22)]
    state,_=replay(prices)
    state=replace(state,direction='TREND_DOWN',direction_count=2)
    state,points=replay([111.],state,len(prices))
    assert points[0]['direction']=='TREND_UP'
    assert points[0]['direction_count']==1
    assert points[0]['reason']=='PRICE_PATH_REFERENCE'
    _,points=replay([100+i for i in range(60)])
    assert points[-1]['direction_count']==2
    assert points[-1]['reference']=='TREND_UP'
    assert points[-1]['reason']=='PRICE_PATH_REFERENCE'
