from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import pickle

import pytest
from guiyi_quant.indicators.subing_range import initial_state, step

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def tick(state, close='100', high='101', low='99', **kw):
    args = dict(contract='JM2701', frequency='30m', bar_end=(state.last_end or START)+timedelta(minutes=30),
                close=D(close), high=D(high), low=D(low), atr=D('2'), trend_direction='NEUTRAL')
    args.update(kw)
    return step(state, **args)


def box(profile='bounded_confirmed'):
    state = initial_state('JM2701', '30m', profile=profile)
    points = []
    for i in range(24):
        state, p = tick(state, close='100.2' if i % 2 else '99.8')
        points.append(p)
    assert points[-1].phase == 'RANGE_ACTIVE'
    return state, points


def test_confirmation_visibility_and_immutable_expansion():
    state, points = box()
    assert all(p.box is None for p in points[:21])
    assert points[20].phase == 'FORMING'
    assert points[21].box.confirmed_at == points[21].at
    old = points[-1].box
    state, p = tick(state, high='101.3')
    assert p.phase == 'RANGE_EXPANDING'
    assert old.upper == D('101') and p.box.upper == D('101.3')
    assert p.box.box_id == old.box_id and p.box.revision == old.revision+1
    assert p.box.atr_reference == old.atr_reference


@pytest.mark.parametrize('side,close,high,low', [('UP','102','103','100'),('DOWN','98','100','97')])
def test_breakout_first_freeze_and_confirm(side, close, high, low):
    state, _ = box()
    old = state.box
    state, p = tick(state, close, high, low, trend_direction=side)
    assert p.phase == 'BREAK_PENDING' and p.break_side == side and not p.trend_candidate
    state, p = tick(state, close, high, low, trend_direction=side)
    assert p.phase == 'BREAK_CONFIRMED' and p.box == old and state.retired
    state, p = tick(state)
    assert state.box is None and p.box is None


def test_failed_break_and_boundary_test_do_not_change_old_standard():
    state, _ = box()
    old = state.box
    state, p = tick(state, '101.2','101.3','100')
    assert p.phase == 'BOUNDARY_TEST' and p.box == old
    state, p = tick(state,'102','102','100')
    assert p.phase == 'BREAK_PENDING'
    state, p = tick(state)
    assert p.phase == 'BREAK_FAILED' and p.box == old and not p.trend_candidate
    state, p = tick(state)
    assert p.phase == 'RANGE_ACTIVE'


def test_fixed_and_single_confirmation_profiles():
    for profile in ('fixed', 'bounded'):
        state, _ = box(profile)
        state, p = tick(state, high='101.3')
        assert p.phase == ('RANGE_ACTIVE' if profile == 'fixed' else 'RANGE_EXPANDING')
        state, p = tick(state,'103','103','100')
        assert p.phase == 'BREAK_CONFIRMED'


def test_expansion_limits_reference_atr_and_wide_invalid():
    state, _ = box()
    old = state.box
    state, p = tick(state, high='101.6', atr=D('100'))
    assert p.box == old  # no growing volatility budget
    _, p = tick(state, high='110')
    assert p.regime == 'RANGE' and p.reason == 'BOX_WIDTH_EXCEEDED'


def test_broad_disorder_is_range_without_box():
    state = initial_state('JM2701','30m')
    for i in range(80):
        state, p = tick(state, close='110' if i % 2 else '90', high='111',low='89')
    assert p.regime == 'RANGE' and p.box is None and p.er == 0


def test_direct_trend_and_slow_breakout_cannot_be_swallowed():
    state, _ = box()
    points = []
    for i in range(1,61):
        close=D('100')+D(i)/5
        state, p = tick(state,str(close),str(close+D('.1')),str(close-D('.1')),trend_direction='UP')
        points.append(p)
    assert any(p.phase == 'BREAK_CONFIRMED' for p in points)
    assert points[-1].regime == 'TREND_UP' and points[-1].trend_candidate
    state = initial_state('JM2701','30m')
    for i in range(50):
        c=D(100)-D(i)/2
        state,p=tick(state,str(c),str(c+1),str(c-1),trend_direction='DOWN')
    assert p.regime=='TREND_DOWN' and p.box is None


def test_direction_is_independent_of_efficiency_but_candidate_is_not():
    state=initial_state('JM2701','30m')
    for i in range(30):
        state,p=tick(state,str(100+i),str(101+i),str(99+i),trend_direction='DOWN')
    assert p.regime=='TREND_DOWN' and not p.trend_candidate
    state,p=tick(state,'130','131','129',trend_direction='UP')
    assert p.regime=='TREND_DOWN'
    state,p=tick(state,'131','132','130',trend_direction='UP')
    assert p.regime=='TREND_UP'


def test_prefix_stream_restart_and_bounded_memory():
    def run(n, state=None, offset=0):
        state=state or initial_state('JM2701','30m')
        out=[]
        for i in range(offset, offset+n):
            c=D(100)+D(i%13)/10
            state,p=tick(state,str(c),str(c+1),str(c-1))
            out.append(p)
        return state,out
    full_state,full=run(160)
    for n in (1,20,21,22,30,70,159):
        state,prefix=run(n)
        restored=pickle.loads(pickle.dumps(state))
        end,tail=run(160-n,restored,n)
        assert prefix == full[:n] and prefix+tail == full and end==full_state
    assert len(full_state.samples)==21


def test_preview_identity_time_and_reset():
    state,_=box()
    for kw, code in [({'completed':False},'NOT_COMPLETED'),({'contract':'JM2609'},'IDENTITY'),
                     ({'bar_end':state.last_end},'TIME'),({'bar_end':START.replace(tzinfo=None)},'TIME')]:
        with pytest.raises(ValueError,match=code):
            tick(state,**kw)
    for kw,code in [({'coverage_ok':False},'COVERAGE_INVALID'),({'close':D('NaN')},'INPUT_INVALID'),
                    ({'atr':D(0)},'FACTOR_INPUT_INVALID')]:
        clean,p=tick(state,**kw)
        assert not clean.samples and clean.box is None and p.regime=='UNKNOWN' and p.reason==code
    clean,p=tick(state,trend_direction='UNKNOWN')
    assert clean.box is None and p.regime=='UNKNOWN'
    assert state.box is not None


def test_flat_window_with_positive_atr_does_not_log_zero():
    state=initial_state('JM2701','30m')
    for _ in range(30):
        state,p=tick(state,'100','100','100')
    assert p.regime=='RANGE' and p.chop==100 and p.er==0


def test_direction_inside_old_box_is_visible_but_candidate_stays_closed():
    from guiyi_quant.indicators import subing_trend
    state = initial_state('JM2701','30m')
    trend = subing_trend.initial_state('JM2701','30m')
    for i in range(85):
        c = (D('99.5') if i % 2 else D('100.5')) if i < 30 else D('99.3')+D('.03')*(i-30)
        hi,lo = (D('101'),D('99')) if i < 30 else (c+D('.02'),c-D('.02'))
        t=START+timedelta(minutes=30*(i+1))
        trend,tp=subing_trend.step(trend,contract='JM2701',frequency='30m',bar_end=t,
                                   high=float(hi),low=float(lo),close=float(c))
        state,p=step(state,contract='JM2701',frequency='30m',bar_end=t,high=hi,low=lo,close=c,
                     atr=D(str(tp.atr14)) if tp.atr14 is not None else None,trend_direction=tp.direction)
    assert p.regime=='TREND_UP' and p.phase=='RANGE_ACTIVE'
    assert not p.trend_candidate


def test_restart_at_every_mixed_lifecycle_boundary():
    state, _ = box()
    sequence=[('100','101.3','99'),('102','103','100'),('100','101','99'),
              ('102','103','100'),('103','104','101')]+[('100','101','99')]*25+[
              ('100','110','99')]+[('100','101','99')]*25
    states=[state]
    out=[]
    for c,h,low in sequence:
        state,p=tick(state,c,h,low)
        states.append(state)
        out.append(p)
    assert {'RANGE_EXPANDING','BREAK_PENDING','BREAK_FAILED','BREAK_CONFIRMED'} <= {p.phase for p in out}
    assert any(p.reason=='BOX_WIDTH_EXCEEDED' for p in out)
    for i in range(len(sequence)):
        restored=pickle.loads(pickle.dumps(states[i]))
        tail=[]
        for c,h,low in sequence[i:]:
            restored,p=tick(restored,c,h,low)
            tail.append(p)
        assert tail==out[i:] and restored==state


@pytest.mark.parametrize('direction', ['UP', 'DOWN'])
def test_low_efficiency_direction_neutral_exit_and_reversal(direction):
    state, _ = box()
    opposite = 'DOWN' if direction == 'UP' else 'UP'
    state, first = tick(state, trend_direction=direction)
    state, confirmed = tick(state, trend_direction=direction)
    assert first.regime == 'RANGE'
    assert confirmed.regime == 'TREND_'+direction and confirmed.er < D('.55')
    assert not confirmed.trend_candidate
    for _ in range(2):
        state, p = tick(state)
        assert p.regime == confirmed.regime
    state, p = tick(state, trend_direction=direction)
    assert p.regime == confirmed.regime and state.neutral_count == 0
    state, p = tick(state, trend_direction=opposite)
    assert p.regime == confirmed.regime
    state, p = tick(state, trend_direction=opposite)
    assert p.regime == 'TREND_'+opposite
    for _ in range(3):
        state, p = tick(state)
    assert p.regime == 'RANGE' and state.confirmed_side is None


def test_alternating_direction_does_not_confirm_and_invalid_resets_hold():
    state, _ = box()
    for i in range(20):
        state, p = tick(state, trend_direction='UP' if i % 2 else 'DOWN')
        assert p.regime == 'RANGE'
    for _ in range(2):
        state, p = tick(state, trend_direction='DOWN')
    assert p.regime == 'TREND_DOWN'
    state, p = tick(state, trend_direction='UNKNOWN')
    assert p.regime == 'UNKNOWN' and state.confirmed_side is None
    state, p = tick(state, trend_direction='DOWN')
    assert p.regime == 'RANGE'


def test_directional_prefix_and_restart_at_every_transition():
    initial, _ = box()
    sequence = ['UP']*4 + ['NEUTRAL']*2 + ['DOWN'] + ['UP'] + ['DOWN']*3 + ['NEUTRAL']*3 + ['UP']*3
    def run(state, directions):
        out = []
        for direction in directions:
            state, p = tick(state, trend_direction=direction)
            out.append(p)
        return state, out
    final, full = run(initial, sequence)
    for cut in range(len(sequence)+1):
        state, prefix = run(initial, sequence[:cut])
        restored, tail = run(pickle.loads(pickle.dumps(state)), sequence[cut:])
        assert prefix == full[:cut] and prefix+tail == full and restored == final
