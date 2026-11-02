"""One causal structural-label candidate, isolated from displayed v2 and Runtime.

Fixed exploratory parameters; this module is not an accepted training truth.
"""
from dataclasses import dataclass, replace
from datetime import datetime
import math

from scripts.research.regime_learning_core import reference_label, regression

VERSION = 'structure_hold_reference_candidate_v2'


@dataclass(frozen=True)
class Bar:
    index: int
    time: datetime
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Pivot:
    index: int
    price: float
    confirmed_at: datetime


@dataclass(frozen=True)
class State:
    contract: str
    frequency: str
    index: int = -1
    window: tuple[Bar, ...] = ()
    highs: tuple[Pivot, ...] = ()
    lows: tuple[Pivot, ...] = ()
    regime: str = 'DISPUTED'
    protection: float | None = None
    protection_buffer: float = 0.0
    protection_index: int = -1
    setup_side: str | None = None
    setup_count: int = 0
    break_count: int = 0
    range_count: int = 0
    last_time: datetime | None = None


@dataclass(frozen=True)
class Point:
    regime: str
    reason: str
    protection: float | None = None
    pivot_confirmed_at: datetime | None = None


def initial_state(contract: str, frequency: str) -> State:
    if not contract or frequency not in ('1d','30m','60m'):
        raise ValueError('STRUCTURAL_IDENTITY_INVALID')
    return State(contract,frequency)


def step(state: State, *, contract: str, frequency: str, time: datetime,
         high: float, low: float, close: float, atr: float | None,
         completed: bool = True, coverage_ok: bool = True) -> tuple[State,Point]:
    if (contract,frequency)!=(state.contract,state.frequency) or not completed:
        raise ValueError('STRUCTURAL_IDENTITY_OR_COMPLETION_INVALID')
    if time.tzinfo is None or time.utcoffset() is None or (state.last_time and time<=state.last_time):
        raise ValueError('STRUCTURAL_TIME_INVALID')
    clean=replace(initial_state(contract,frequency),last_time=time)
    if not coverage_ok or not all(math.isfinite(x) and x>0 for x in (high,low,close)) or not low<=close<=high:
        return clean,Point('UNKNOWN','INPUT_OR_COVERAGE_INVALID')
    index=state.index+1
    window=(*state.window,Bar(index,time,high,low,close))[-40:]
    highs=tuple(p for p in state.highs if index-p.index<=64)
    lows=tuple(p for p in state.lows if index-p.index<=64)
    confirmation=None
    if len(window)>=5:
        five=window[-5:]
        center=five[2]
        others=(*five[:2],*five[3:])
        if all(center.high>b.high for b in others):
            highs=(*highs,Pivot(center.index,center.high,time))[-2:]
            confirmation=time
        if all(center.low<b.low for b in others):
            lows=(*lows,Pivot(center.index,center.low,time))[-2:]
            confirmation=time
    new=replace(state,index=index,window=window,highs=highs,lows=lows,last_time=time)
    if atr is None:
        return replace(new,regime='DISPUTED',protection=None,setup_side=None,setup_count=0,break_count=0,range_count=0),Point('UNKNOWN','ATR_UNAVAILABLE')
    if not math.isfinite(atr) or atr<=0:
        return clean,Point('UNKNOWN','ATR_INVALID')
    if len(window)<40:
        return new,Point('UNKNOWN','WARMUP',pivot_confirmed_at=confirmation)
    prices=[b.close for b in window]
    recent=prices[-20:]
    center=(max(recent)+min(recent))/2
    signs=[1 if p>center+.25*atr else -1 if p<center-.25*atr else 0 for p in recent]
    nonzero=[s for s in signs if s]
    crosses=sum(a!=b for a,b in zip(nonzero,nonzero[1:]))
    flat=max(recent)-min(recent)<=.5*atr
    range_evidence=(abs(recent[-1]-recent[0])<=atr and regression(recent)['r2']<=.2
                    and (crosses>=3 or flat))
    range_count=min(3,state.range_count+1) if range_evidence else 0
    setup=None
    if len(highs)==2 and len(lows)==2:
        if highs[-1].price-highs[-2].price>.2*atr and lows[-1].price-lows[-2].price>.2*atr:
            setup='TREND_UP'
        elif highs[-2].price-highs[-1].price>.2*atr and lows[-2].price-lows[-1].price>.2*atr:
            setup='TREND_DOWN'
    # A monotone path need not contain local extrema: use the independent price-path evidence.
    path_label=reference_label(prices,atr)['label']
    if setup is None and path_label in ('TREND_UP','TREND_DOWN'):
        setup=path_label
    if range_evidence:
        setup=None
    if setup=='TREND_UP' and lows and close<lows[-1].price-.2*atr:
        setup=None
    if setup=='TREND_DOWN' and highs and close>highs[-1].price+.2*atr:
        setup=None
    count=min(2,state.setup_count+1) if setup and setup==state.setup_side else int(setup is not None)
    regime=state.regime
    protection,buffer,protection_index=state.protection,state.protection_buffer,state.protection_index
    if regime=='TREND_UP' and lows and lows[-1].index>protection_index and (protection is None or lows[-1].price>protection):
        protection,buffer,protection_index=lows[-1].price,.2*atr,lows[-1].index
    if regime=='TREND_DOWN' and highs and highs[-1].index>protection_index and (protection is None or highs[-1].price<protection):
        protection,buffer,protection_index=highs[-1].price,.2*atr,highs[-1].index
    broken=protection is not None and ((regime=='TREND_UP' and close<protection-buffer)
                                      or (regime=='TREND_DOWN' and close>protection+buffer))
    breaks=min(2,state.break_count+1) if broken else 0
    reason='STRUCTURE_HELD' if regime.startswith('TREND_') else 'UNRESOLVED'
    if range_count>=3:
        regime,reason='RANGE','RANGE_CONFIRMED'
        protection=None
        breaks=0
    elif breaks>=2:
        regime,reason='DISPUTED','STRUCTURE_BROKEN'
        protection=None
        count=0
    elif setup and count>=2 and setup!=regime and not regime.startswith('TREND_'):
        regime,reason=setup,'DIRECTION_CONFIRMED'
        pivots=lows if setup=='TREND_UP' else highs
        protection=(pivots[-1].price if pivots else min(b.low for b in window[-20:]) if setup=='TREND_UP' else max(b.high for b in window[-20:]))
        protection_index=pivots[-1].index if pivots else index
        buffer=.2*atr
        breaks=0
    elif regime=='RANGE' and not range_evidence:
        regime,reason='DISPUTED','RANGE_EVIDENCE_LOST'
    new=replace(new,regime=regime,protection=protection,protection_buffer=buffer,protection_index=protection_index,
                setup_side=setup,setup_count=count,break_count=breaks,range_count=range_count)
    return new,Point(regime,reason,protection,confirmation)
