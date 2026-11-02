from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pickle

import pytest
from scripts.research import regime_structural_labels as k

START=datetime(2020,1,1,tzinfo=timezone.utc)


def observe(state,price,**kwargs):
    args=dict(contract='TEST',frequency='30m',time=(state.last_time or START)+timedelta(minutes=30),
        high=price+.2,low=price-.2,close=price,atr=1.)
    args.update(kwargs)
    return k.step(state,**args)


def trend(side=1):
    state=k.initial_state('TEST','30m')
    for i in range(50):
        state,p=observe(state,100+side*.3*i)
    assert p.regime==('TREND_UP' if side==1 else 'TREND_DOWN')
    return state


@pytest.mark.parametrize('side',[1,-1])
def test_pause_keeps_trend_until_independent_range_confirmation(side):
    state=trend(side)
    original=state.regime
    price=state.window[-1].close
    for _ in range(4):
        state,p=observe(state,price)
        assert p.regime==original
    for _ in range(25):
        state,p=observe(state,price)
    assert p.regime=='RANGE' and p.reason=='RANGE_CONFIRMED'


@pytest.mark.parametrize('side',[1,-1])
def test_structure_break_requires_two_closes_and_never_backfills(side):
    state=trend(side)
    original=state
    price=state.protection-1 if side==1 else state.protection+1
    state,first=observe(state,price)
    assert first.regime==original.regime
    state,second=observe(state,price)
    assert second.regime=='DISPUTED' and second.reason=='STRUCTURE_BROKEN'
    assert first.regime==original.regime and original.regime.startswith('TREND_')


def test_pivot_is_available_only_after_two_right_bars():
    state=k.initial_state('TEST','30m')
    for p in [100.,101.,105.,102.]:
        state,point=observe(state,p)
        assert not state.highs
    state,point=observe(state,101.)
    assert state.highs[-1].index==2
    assert state.highs[-1].confirmed_at==state.last_time==point.pivot_confirmed_at


def test_prefix_future_perturbation_stream_and_restart():
    prices=[100+i*.25+(i%5)*.1 for i in range(55)]+[114.]*25+[114-i*.3 for i in range(50)]
    def run(prices,state=None):
        state=state or k.initial_state('TEST','30m')
        out=[]
        for p in prices:
            state,point=observe(state,p)
            out.append(point)
        return state,out
    final,full=run(prices)
    for cut in (1,5,20,39,40,41,50,60,80,100,129):
        state,prefix=run(prices[:cut])
        end,tail=run(prices[cut:],pickle.loads(pickle.dumps(state)))
        assert prefix==full[:cut] and prefix+tail==full and final==end
        _,altered=run(prices[:cut]+[1000.]*50)
        assert altered[:cut]==prefix
    assert len(final.window)<=40 and len(final.highs)<=2 and len(final.lows)<=2


def test_fail_closed_on_preview_identity_time_and_data_gap():
    state=trend()
    for kw in ({'completed':False},{'contract':'OTHER'},{'time':state.last_time}):
        with pytest.raises(ValueError):
            observe(state,110.,**kw)
    for kw in ({'coverage_ok':False},{'close':float('nan')},{'atr':0.}):
        clean,p=observe(state,110.,**kw)
        assert p.regime=='UNKNOWN' and not clean.window and clean.protection is None


def test_last_pivot_protection_never_widens_when_volatility_increases():
    state=trend()
    old_buffer=state.protection_buffer
    # No new confirmed pivot: a larger ATR cannot retroactively widen the stop buffer.
    state=replace(state,highs=(),lows=())
    state,p=observe(state,state.window[-1].close,atr=100.)
    assert state.protection_buffer==old_buffer


@pytest.mark.parametrize("side", [1,-1])
def test_opposite_setup_cannot_reverse_an_unbroken_established_trend(side):
    state=trend(side)
    original=state.regime
    state=replace(state,protection=80. if side==1 else 120.,protection_buffer=.2,highs=(),lows=())
    for i in range(45):
        # Monotone reversal supplies opposite regression evidence, but never breaks protection.
        state,p=observe(state,100+side*14.7-side*i*.3)
        assert p.regime==original
        assert p.reason=='STRUCTURE_HELD'
    assert state.setup_side==('TREND_DOWN' if side==1 else 'TREND_UP') and state.setup_count==2



def test_atr_missing_then_recovered_never_restores_an_old_confirmed_state():
    state=k.initial_state('TEST','30m')
    for i in range(30):
        state,p=observe(state,100+i*.3,atr=None)
        assert p.regime=='UNKNOWN'
    for i in range(30,50):
        state,p=observe(state,100+i*.3)
    assert p.regime=='TREND_UP'
    state,p=observe(state,115.,atr=None)
    assert p.regime=='UNKNOWN' and state.regime=='DISPUTED' and state.protection is None
    state,p=observe(state,115.3)
    assert p.regime=='DISPUTED'
    state,p=observe(state,115.6)
    assert p.regime=='TREND_UP'
