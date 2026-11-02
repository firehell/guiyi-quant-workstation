"""Causal research regime and bounded boxes; never an execution permission."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
import math

VERSION = 'subing_dynamic_range_v1'
D = Decimal


@dataclass(frozen=True)
class Profile:
    name: str = 'bounded_confirmed'
    window: int = 20
    formation_bars: int = 2
    break_bars: int = 2
    expansion: Decimal = D('0.25')
    initial_width: Decimal = D('3')
    max_width: Decimal = D('4')
    buffer: Decimal = D('0.2')
    range_er: Decimal = D('0.35')
    trend_er: Decimal = D('0.55')
    chop_min: float = 61.8


PROFILES = {
    'fixed': Profile(name='fixed', break_bars=1, expansion=D(0)),
    'bounded': Profile(name='bounded', break_bars=1),
    'bounded_confirmed': Profile(),
}


@dataclass(frozen=True)
class Sample:
    high: Decimal
    low: Decimal
    close: Decimal
    tr: Decimal


@dataclass(frozen=True)
class Box:
    box_id: str
    confirmed_at: datetime
    lower: Decimal
    upper: Decimal
    atr_reference: Decimal
    revision: int = 0


@dataclass(frozen=True)
class Point:
    at: datetime
    regime: str = 'UNKNOWN'
    phase: str = 'SEARCHING'
    reason: str | None = 'WARMUP'
    er: Decimal | None = None
    chop: float | None = None
    box: Box | None = None
    break_side: str | None = None
    trend_candidate: bool = False


@dataclass(frozen=True)
class State:
    identity: tuple[str, str]
    profile: str = 'bounded_confirmed'
    samples: tuple[Sample, ...] = ()
    last_end: datetime | None = None
    forming: int = 0
    box: Box | None = None
    pending_side: str | None = None
    pending_count: int = 0
    directional_side: str | None = None
    directional_count: int = 0
    retired: bool = False


def initial_state(contract: str, frequency: str, *, profile: str = 'bounded_confirmed') -> State:
    if not contract or frequency not in ('1d', '30m') or profile not in PROFILES:
        raise ValueError('RANGE_IDENTITY_INVALID')
    return State((contract, frequency), profile)


def step(state: State, *, contract: str, frequency: str, bar_end: datetime,
         high: Decimal, low: Decimal, close: Decimal, atr: Decimal | None,
         trend_direction: str, completed: bool = True, coverage_ok: bool = True) -> tuple[State, Point]:
    """Caller verifies authoritative session coverage and supplies shared ATR/EMA direction.

    Reject previews, identities and nonmonotonic times before mutation. Invalid
    prices/coverage reset the window. Missing trend/ATR never defaults to range.
    """
    if (contract, frequency) != state.identity:
        raise ValueError('RANGE_IDENTITY_CHANGED')
    if not completed:
        raise ValueError('RANGE_BAR_NOT_COMPLETED')
    if bar_end.tzinfo is None or bar_end.utcoffset() is None or (state.last_end and bar_end <= state.last_end):
        raise ValueError('RANGE_TIME_INVALID')
    clean = replace(initial_state(contract, frequency, profile=state.profile), last_end=bar_end)
    if not coverage_ok:
        return clean, Point(bar_end, reason='COVERAGE_INVALID')
    if (not all(isinstance(v, Decimal) and v.is_finite() and v > 0 for v in (high, low, close))
            or not low <= close <= high):
        return clean, Point(bar_end, reason='INPUT_INVALID')
    cfg = PROFILES[state.profile]
    prev = state.samples[-1].close if state.samples else close
    tr = max(high-low, abs(high-prev), abs(low-prev))
    samples = (*state.samples, Sample(high, low, close, tr))[-(cfg.window+1):]
    new = replace(state, samples=samples, last_end=bar_end)
    if (atr is None or trend_direction == 'UNKNOWN' or len(samples) < cfg.window+1):
        return replace(new, box=None, forming=0, pending_side=None, pending_count=0,
                       directional_side=None, directional_count=0, retired=False), Point(bar_end)
    if not isinstance(atr, Decimal) or not atr.is_finite() or atr <= 0 or trend_direction not in ('UP', 'DOWN', 'NEUTRAL'):
        return clean, Point(bar_end, reason='FACTOR_INPUT_INVALID')
    window = samples[-cfg.window:]
    travel = sum((abs(b.close-a.close) for a, b in zip(samples, samples[1:])), D(0))
    displacement = close-samples[0].close
    er = abs(displacement)/travel if travel else D(0)
    lower, upper = min(b.low for b in window), max(b.high for b in window)
    width = upper-lower
    # Flat prices are a degenerate range once a positive ATR exists; no log(0).
    chop = 100.0 if width == 0 else max(0.0, min(100.0,
        100 * math.log10(float(sum((b.tr for b in window), D(0))/width))/math.log10(cfg.window)))
    side = ('UP' if displacement > 0 else 'DOWN') if displacement else None
    directional = side if er >= cfg.trend_er and trend_direction == side else None
    count = state.directional_count+1 if directional and directional == state.directional_side else int(directional is not None)
    new = replace(new, directional_side=directional, directional_count=count)
    regime = ('TREND_'+directional) if directional and count >= 2 else 'RANGE'
    point = Point(bar_end, regime=regime, reason=None, er=er, chop=chop,
                  trend_candidate=regime.startswith('TREND_'))
    box = None if state.retired else state.box
    if box is None:
        qualifies = er <= cfg.range_er and chop >= cfg.chop_min and width <= cfg.initial_width*atr
        forming = state.forming+1 if qualifies else 0
        new = replace(new, forming=forming, box=None, retired=False, pending_side=None, pending_count=0)
        if forming >= cfg.formation_bars:
            box = Box(f'{contract}:{frequency}:{state.profile}:{bar_end.isoformat()}', bar_end, lower, upper, atr)
            return replace(new, box=box, forming=0), replace(point, phase='RANGE_ACTIVE', box=box, trend_candidate=False)
        return new, replace(point, phase='FORMING' if forming else 'SEARCHING',
                            trend_candidate=point.trend_candidate and not forming)
    # All breakout tests use the previous immutable boundary BEFORE expansion.
    breakout = ('UP' if close > box.upper+cfg.buffer*box.atr_reference else
                'DOWN' if close < box.lower-cfg.buffer*box.atr_reference else None)
    if state.pending_side:
        if breakout == state.pending_side:
            n = state.pending_count+1
            confirmed = n >= cfg.break_bars
            return replace(new, pending_count=n, retired=confirmed), replace(point,
                box=box, break_side=breakout,
                phase='BREAK_CONFIRMED' if confirmed else 'BREAK_PENDING',
                trend_candidate=confirmed and directional == breakout and count >= 2)
        return replace(new, pending_side=None, pending_count=0), replace(point,
            phase='BREAK_FAILED', box=box, break_side=state.pending_side, trend_candidate=False)
    if breakout:
        confirmed = cfg.break_bars == 1
        return replace(new, pending_side=breakout, pending_count=1, retired=confirmed), replace(point,
            box=box, break_side=breakout,
            phase='BREAK_CONFIRMED' if confirmed else 'BREAK_PENDING',
            trend_candidate=confirmed and directional == breakout and count >= 2)
    # A close just outside the boundary is a test, never absorbed into the box.
    if not box.lower <= close <= box.upper:
        return new, replace(point, phase='BOUNDARY_TEST', box=box, trend_candidate=False)
    lo, hi = min(low, box.lower), max(high, box.upper)
    if lo != box.lower or hi != box.upper:
        if hi-lo > cfg.max_width*box.atr_reference:
            return replace(new, box=None, forming=0), replace(point, regime='UNKNOWN',
                phase='SEARCHING', reason='BOX_WIDTH_EXCEEDED', box=box, trend_candidate=False)
        can_expand = (box.lower-lo <= cfg.expansion*box.atr_reference and
                      hi-box.upper <= cfg.expansion*box.atr_reference and
                      er <= cfg.range_er and directional is None)
        if can_expand:
            box = replace(box, lower=lo, upper=hi, revision=box.revision+1)
            return replace(new, box=box), replace(point, phase='RANGE_EXPANDING', box=box, trend_candidate=False)
    return new, replace(point, phase='RANGE_ACTIVE', box=box, trend_candidate=False)
