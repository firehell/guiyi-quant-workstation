from datetime import datetime, timedelta, timezone
import math
import pytest
from guiyi_quant.indicators.subing_macd import cross_point, initial_state, step


@pytest.mark.parametrize('h,near', [(-5,True),(5,True),(-5.000001,False),(5.000001,False)])
def test_golden_height_bounds(h,near):
    p=cross_point((h-1,h),h+1,h)
    assert p.cross=='GOLDEN' and p.fraction==.5
    assert p.height==h and p.near_zero_golden is near and not p.high_death


@pytest.mark.parametrize('h,high', [(17,False),(17.000001,True),(-18,False)])
def test_death_height_bounds(h,high):
    p=cross_point((h+1,h),h-1,h)
    assert p.cross=='DEATH' and p.high_death is high and not p.near_zero_golden


def test_geometry_is_not_current_endpoint_or_average():
    p=cross_point((-8,-2),8,0)
    assert p.fraction==pytest.approx(3/7)
    assert p.height==pytest.approx(-8/7)
    assert p.near_zero_golden  # current DIF is outside [-5,5]


def test_equal_touch_and_departure():
    assert cross_point((-1,0),0,0).cross=='NONE'
    assert cross_point((0,0),0,0).cross=='NONE'
    p=cross_point((0,0),1,0)
    assert p.cross=='GOLDEN' and p.fraction==0
    assert cross_point((1,0),2,0).cross=='NONE'
    assert cross_point(None,1,0).near_zero_golden is None
    assert cross_point((0,0),math.nan,0).reason=='INPUT_INVALID'


def advance(state,closes,start=0):
    out=[]
    for i,c in enumerate(closes,start):
        state,p=step(state,contract='JM2701',frequency='30m',bar_end=datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(minutes=i*30),close=c)
        out.append(p)
    return state,out


def test_prefix_restart_future_and_shared_kernel():
    from guiyi_quant.indicators.macd import macd_series
    closes=[100+10*math.sin(i/5) for i in range(180)]
    state,prefix=advance(initial_state('JM2701','30m'),closes[:80])
    _,tail=advance(state,closes[80:],80)
    _,full=advance(initial_state('JM2701','30m'),closes)
    assert prefix+tail==full
    _,changed=advance(initial_state('JM2701','30m'),closes[:80]+[500]*100)
    assert changed[:80]==prefix
    kernel=macd_series(closes,12,26,9,ema_seed_policy='sma_window',histogram_scale=2)
    for i,p in enumerate(full):
        assert p.dif==kernel.dif.points[i].value
        assert p.dea==kernel.dea.points[i].value
    assert full[33].reason=='PREVIOUS_UNAVAILABLE'
    assert full[34].reason is None
    assert any(p.cross=='GOLDEN' for p in full)
    assert any(p.cross=='DEATH' for p in full)


def test_invalid_reset_and_identity_time():
    state,_=advance(initial_state('JM2701','30m'),[100]*40)
    kw=dict(contract='JM2701',frequency='30m',bar_end=state.last_end,close=100)
    with pytest.raises(ValueError,match='TIME'):step(state,**kw)
    kw.update(bar_end=state.last_end+timedelta(minutes=30),contract='JM2609')
    with pytest.raises(ValueError,match='IDENTITY'):step(state,**kw)
    state,out=advance(state,[float('nan')]+[100]*35,40)
    assert out[0].reason=='INPUT_INVALID'
    assert out[34].reason=='PREVIOUS_UNAVAILABLE'
    assert out[35].cross=='NONE'


def test_nonterminating_fraction_exact_height_boundary():
    p=cross_point((-15,-14),15,13)
    assert p.height==-5 and p.near_zero_golden is True
    p=cross_point((15,14),-15,-13)
    assert p.height==5 and p.high_death is False
    p=cross_point((27,26),-3,-1)
    assert p.height==17 and p.high_death is False
