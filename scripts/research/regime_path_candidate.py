"""Frozen development hypothesis; not an accepted training label or active factor."""
from dataclasses import dataclass, replace
from datetime import datetime
import math

from scripts.research.regime_learning_core import reference_label, regression

VERSION = 'path_progress_plateau_ablation_v2'
VARIANTS = ('original', 'no_overlap', 'confirm_exit', 'combined')
POLICY = dict(window=64, plateau_window=12, plateau_confirm=3, plateau_r2_max=.2,
              plateau_displacement_atr_max=1., half_overlap_min=.6,
              short_windows=[8, 20], short_r2_min=.4, short_displacement_atr_min=2.,
              direction_confirm=2, transition_confirm=3, variants=VARIANTS)


@dataclass(frozen=True)
class State:
    contract: str
    frequency: str
    variant: str = 'original'
    confirmed_label: str = 'UNKNOWN'
    pending_label: str | None = None
    pending_count: int = 0
    closes: tuple[float, ...] = ()
    last_time: datetime | None = None
    plateau_count: int = 0
    direction: str | None = None
    direction_count: int = 0


def initial_state(contract, frequency, variant='original'):
    if not contract or frequency not in ('1d', '30m', '60m') or variant not in VARIANTS:
        raise ValueError('PATH_IDENTITY_INVALID')
    return State(contract, frequency, variant)


def evidence(closes, atr, variant='original'):
    reference = reference_label(list(closes), atr)['label']
    recent = list(closes[-12:])
    first, last = recent[:6], recent[6:]
    width = max(recent)-min(recent)
    overlap = max(0., min(max(first), max(last))-max(min(first), min(last)))
    ratio = overlap/width if width else 1.
    path = regression(recent)
    plateau = path['r2'] <= .2 and abs(path['displacement']) <= atr and (ratio >= .6 or variant in ('no_overlap','combined'))
    direction = None
    short = [regression(list(closes[-n:])) for n in (8, 20)]
    for side, sign in (('TREND_UP', 1), ('TREND_DOWN', -1)):
        if all(p['r2'] >= .4 and sign*p['slope'] > 0 and sign*p['displacement'] >= 2*atr for p in short):
            direction = side
    return dict(reference=reference, plateau=plateau, overlap=ratio,
                recent_r2=path['r2'], displacement_atr=path['displacement']/atr,
                direction=direction)


def step(state, *, contract, frequency, time, close, atr, completed=True, coverage_ok=True):
    if (contract, frequency) != (state.contract, state.frequency) or not completed:
        raise ValueError('PATH_IDENTITY_OR_COMPLETION_INVALID')
    if time.tzinfo is None or time.utcoffset() is None or (state.last_time and time <= state.last_time):
        raise ValueError('PATH_TIME_INVALID')
    clean = replace(initial_state(contract, frequency, state.variant), last_time=time)
    if not coverage_ok or not math.isfinite(close) or close <= 0:
        return clean, dict(label='UNKNOWN', reason='INPUT_OR_COVERAGE_INVALID')
    closes = (*state.closes, close)[-64:]
    new = replace(state, closes=closes, last_time=time)
    if atr is not None and (not math.isfinite(atr) or atr <= 0):
        return clean, dict(label='UNKNOWN', reason='ATR_INVALID')
    if atr is None or len(closes) < 40:
        return replace(new, plateau_count=0, direction=None, direction_count=0, confirmed_label='UNKNOWN', pending_label=None, pending_count=0), dict(label='UNKNOWN', reason='WARMUP')
    facts = evidence(closes, atr, state.variant)
    count = min(3, state.plateau_count+1) if facts['plateau'] else 0
    side = facts['direction']
    confirms = min(2, state.direction_count+1) if side and side == state.direction else int(side is not None)
    label, reason = facts['reference'], 'PRICE_PATH_REFERENCE'
    if count >= 3:
        label, reason = 'RANGE', 'SUSTAINED_PLATEAU'
    elif label == 'DISPUTED' and confirms >= 2:
        label, reason = side, 'DIRECTION_PROGRESS'
    raw_label = label
    pending_count, pending_label = state.pending_count, state.pending_label
    if state.variant in ('confirm_exit', 'combined'):
        pending_count = min(3, pending_count+1) if pending_label == raw_label else 1
        pending_label = raw_label
        if pending_count < 3:
            label = state.confirmed_label
            reason = 'TRANSITION_PENDING'
    new = replace(new, plateau_count=count, direction=side, direction_count=confirms,
                  confirmed_label=label, pending_label=pending_label, pending_count=pending_count)
    return new, dict(label=label, raw_label=raw_label, reason=reason, **facts,
                    plateau_count=count, direction_count=confirms, pending_count=pending_count)
