from datetime import datetime, timedelta, timezone
import math
import pytest
from guiyi_quant.indicators.subing_trend import initial_state, slope_point, step


def test_ols_uses_middle_points():
    p = slope_point((10, 11, 12, 19, 14), 2)
    assert p.slope == pytest.approx(1.6)
    assert p.angle == pytest.approx(math.degrees(math.atan(.8)))
    assert p.direction == 'UP'


@pytest.mark.parametrize('angle,direction', [(5,'NEUTRAL'),(-5,'NEUTRAL'),(5.01,'UP'),(-5.01,'DOWN'),(4.99,'NEUTRAL'),(-4.99,'NEUTRAL'),(10,'UP'),(-10,'DOWN'),(0,'NEUTRAL')])
def test_boundaries(angle, direction):
    b = math.tan(math.radians(angle))
    assert slope_point(tuple(i*b for i in range(5)), 1).direction == direction


def test_scale_and_translation_invariance():
    a = slope_point((10, 11, 12, 13, 14), 3)
    b = slope_point((120, 122, 124, 126, 128), 6)
    assert a.angle == pytest.approx(b.angle)
    assert slope_point((10, 11, 12, 13, 14), 6).angle < a.angle
    assert slope_point((10,)*5, 0).direction == 'UNKNOWN'


def run(n, state=None):
    state = state or initial_state('JM2701','30m')
    out = []
    for i in range(n):
        t = (state.last_end or datetime(2026,1,1,tzinfo=timezone.utc))+timedelta(minutes=30)
        c = 100 + t.day + t.hour*.1 + t.minute*.001
        state, p = step(state, contract='JM2701',frequency='30m',bar_end=t,high=c+2,low=c-2,close=c)
        out.append(p)
    return state, out


def test_prefix_and_incremental_parity():
    state, prefix = run(40)
    _, tail = run(20, state)
    _, full = run(60)
    assert prefix + tail == full
    assert all(p.reason == 'WARMUP' for p in full[:24])
    assert full[24].reason is None


def test_identity_time_invalid_and_rewarm():
    state, _ = run(40)
    kw = dict(contract='JM2701',frequency='30m',bar_end=state.last_end,high=103,low=99,close=100)
    with pytest.raises(ValueError, match='TIME'):
        step(state, **kw)
    kw.update(contract='JM2609',bar_end=state.last_end+timedelta(minutes=30))
    with pytest.raises(ValueError, match='IDENTITY'):
        step(state, **kw)
    kw.update(contract='JM2701',close=float('nan'))
    clean, p = step(state, **kw)
    assert p.reason == 'INPUT_INVALID'
    _, out = run(25, clean)
    assert all(p.reason == 'WARMUP' for p in out[:24])
    assert out[24].reason is None
