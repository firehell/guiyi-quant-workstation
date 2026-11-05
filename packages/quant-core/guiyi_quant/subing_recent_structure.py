"""Research-only recent swing envelope. No order or environment gate.

Fixed exploratory choices: strict 2-left/2-right pivots, last three highs
and lows. A pivot becomes usable at its confirmation bar, never backfilled.
Mixed structure is NOT established ground truth for ranging markets.
"""
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal as D

VERSION='subing_recent_structure_spike_v1'

@dataclass(frozen=True)
class Bar:
    at: datetime
    high: D
    low: D
    close: D

@dataclass(frozen=True)
class Pivot:
    side: str
    price: D
    at: datetime
    confirmed_at: datetime

@dataclass(frozen=True)
class State:
    contract: str
    bars: tuple=()
    pivots: tuple=()
    lower: D | None=None
    upper: D | None=None
    boundary_at: datetime | None=None
    pending_side: str | None=None
    count: int=0
    last_at: datetime | None=None


def step(s, b, *, contract, valid=True):
    if contract!=s.contract:raise ValueError('CONTRACT_CHANGED')
    if b.at.tzinfo is None or (s.last_at and b.at<=s.last_at):raise ValueError('TIME_INVALID')
    if not valid:return State(contract,last_at=b.at), {'phase':'UNKNOWN','reason':'GAP'}
    if not all(isinstance(x,D) and x.is_finite() and x>0 for x in (b.high,b.low,b.close)) or not b.low<=b.close<=b.high:
        raise ValueError('OHLC_INVALID')
    bars=(*s.bars,b)[-5:];pivots=s.pivots;new_pivot=False
    if len(bars)==5:
        mid=bars[2];others=(*bars[:2],*bars[3:])
        high=mid.high>max(x.high for x in others);low=mid.low<min(x.low for x in others)
        # An outside bar may be both extrema; intrabar ordering is unknown.
        if high != low:
            p=Pivot('HIGH' if high else 'LOW',mid.high if high else mid.low,mid.at,b.at)
            if pivots and pivots[-1].side==p.side:
                if (p.price>pivots[-1].price if high else p.price<pivots[-1].price):
                    pivots=(*pivots[:-1],p);new_pivot=True
            else:pivots=(*pivots,p);new_pivot=True
            pivots=pivots[-8:]
    n=replace(s,bars=bars,pivots=pivots,last_at=b.at)
    # Evaluate the current close using the boundary known BEFORE this bar.
    # A pivot confirmed now may update only if no breakout is pending/starting.
    side=('UP' if b.close>s.upper else 'DOWN' if b.close<s.lower else None) if s.lower is not None else None
    phase='UNKNOWN';reason='PIVOT_WARMUP'
    if s.count==4 and new_pivot and side==s.pending_side:
        highs=[p.price for p in pivots if p.side=='HIGH'][-3:]
        lows=[p.price for p in pivots if p.side=='LOW'][-3:]
        if len(highs)==len(lows)==3 and min(lows)<max(highs):
            n=replace(n,lower=min(lows),upper=max(highs),boundary_at=b.at if (min(lows),max(highs))!=(s.lower,s.upper) else s.boundary_at,pending_side=None,count=0)
            phase='STRUCTURE_UPDATED';reason=None
        else:
            n=replace(n,lower=None,upper=None,boundary_at=None,pending_side=None,count=0)
    elif s.pending_side:
        if side==s.pending_side:
            n=replace(n,count=min(4,s.count+1));phase='BREAK_CONFIRMED' if n.count==4 else 'BREAK_PENDING';reason=None
        elif side is not None:
            n=replace(n,lower=None,upper=None,boundary_at=None,pending_side=None,count=0)
            phase='UNKNOWN';reason='OPPOSITE_EDGE_CROSS'
        else:
            n=replace(n,pending_side=None,count=0)
            phase='REENTERED' if s.count==4 else 'BREAK_FAILED';reason=None
        # Frozen pending boundaries; no same-bar replacement on failure.
    elif side:
        n=replace(n,pending_side=side,count=1);phase='BREAK_PENDING';reason=None
    else:
        highs=[p.price for p in pivots if p.side=='HIGH'][-3:]
        lows=[p.price for p in pivots if p.side=='LOW'][-3:]
        if len(highs)==len(lows)==3 and (new_pivot or s.lower is None):
            lower,upper=min(lows),max(highs)
            if lower<upper:n=replace(n,lower=lower,upper=upper,boundary_at=b.at if (lower,upper)!=(s.lower,s.upper) else s.boundary_at)
        if n.lower is not None:phase='STRUCTURE_ENVELOPE';reason=None
    highs=[p.price for p in pivots if p.side=='HIGH'][-3:];lows=[p.price for p in pivots if p.side=='LOW'][-3:]
    if len(highs)<3 or len(lows)<3:direction='UNKNOWN'
    elif all(a<c for seq in (highs,lows) for a,c in zip(seq,seq[1:])):direction='UP'
    elif all(a>c for seq in (highs,lows) for a,c in zip(seq,seq[1:])):direction='DOWN'
    else:direction='MIXED'
    return n,dict(phase=phase,reason=reason,lower=n.lower,upper=n.upper,boundary_at=n.boundary_at,
                  break_side=n.pending_side,count=n.count,structure_direction=direction,
                  pivot_confirmed_now=new_pivot)
