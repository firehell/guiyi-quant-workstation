"""Research-only completed-bar MACD cross geometry; no trading actions."""
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction
import math

from .macd import initial_macd_state, step_macd
from .models import MacdState

VERSION = 'subing_macd12_26_9_segment_cross_v3'


@dataclass(frozen=True)
class CrossPoint:
    dif: float | None = None
    dea: float | None = None
    histogram: float | None = None
    cross: str = 'UNKNOWN'
    height: float | None = None
    fraction: float | None = None
    near_zero_golden: bool | None = None
    high_death: bool | None = None
    near_zero_death: bool | None = None
    low_golden: bool | None = None
    reason: str | None = 'WARMUP'


def cross_point(previous: tuple[float, float] | None, dif: float, dea: float) -> CrossPoint:
    """Linear chart segments, not an intrabar observation or execution time."""
    if not all(math.isfinite(v) for v in (dif, dea, *(previous or ()))):
        return CrossPoint(reason='INPUT_INVALID')
    if previous is None:
        return CrossPoint(dif=dif, dea=dea, reason='PREVIOUS_UNAVAILABLE')
    p, q, d, e = map(lambda v: Fraction(str(v)), (*previous, dif, dea))
    a, b = p-q, d-e
    cross = 'GOLDEN' if a <= 0 < b else 'DEATH' if a >= 0 > b else 'NONE'
    if cross == 'NONE':
        return CrossPoint(dif=dif, dea=dea, cross=cross, near_zero_golden=False, high_death=False, near_zero_death=False, low_golden=False, reason=None)
    fraction = -a/(b-a)
    height = p + fraction*(d-p)
    return CrossPoint(dif=dif, dea=dea, cross=cross, height=float(height), fraction=float(fraction),
                      near_zero_golden=cross == 'GOLDEN' and -4 <= height <= 4,
                      high_death=cross == 'DEATH' and height > 17,
                      near_zero_death=cross == 'DEATH' and -4 <= height <= 4,
                      low_golden=cross == 'GOLDEN' and height < -17, reason=None)


@dataclass(frozen=True)
class CrossState:
    identity: tuple[str, str]
    macd: MacdState
    previous: tuple[float, float] | None = None
    last_end: datetime | None = None


def initial_state(contract: str, frequency: str, *, periods: tuple[int, int, int] = (12, 26, 9)) -> CrossState:
    if not contract or frequency != '30m':
        raise ValueError('MACD_FACTOR_IDENTITY_INVALID')
    if (type(periods) is not tuple or len(periods) != 3 or any(type(p) is not int for p in periods)
            or periods not in ((12,26,9), (10,26,9), (14,26,9), (12,24,9), (12,28,9), (12,26,7), (12,26,11))):
        raise ValueError("MACD_RESEARCH_PERIOD_INVALID")
    return CrossState((contract, frequency), initial_macd_state(*periods,
        ema_seed_policy='sma_window',histogram_scale=2))


def step(state: CrossState, *, contract: str, frequency: str, bar_end: datetime,
         close: float) -> tuple[CrossState, CrossPoint]:
    if state.identity != (contract,frequency):
        raise ValueError('MACD_FACTOR_IDENTITY_CHANGED')
    if bar_end.tzinfo is None or (state.last_end is not None and bar_end <= state.last_end):
        raise ValueError('MACD_FACTOR_TIME_INVALID')
    if not math.isfinite(close) or close <= 0:
        return replace(initial_state(contract,frequency, periods=(state.macd.fast.period, state.macd.slow.period, state.macd.signal.period)),last_end=bar_end), CrossPoint(reason='INPUT_INVALID')
    macd, (dif,dea,histogram) = step_macd(state.macd,close,bar_end=bar_end.isoformat())
    if not all(p.ready and p.valid and p.value is not None for p in (dif,dea,histogram)):
        return CrossState(state.identity,macd,None,bar_end), CrossPoint(dif=dif.value,dea=dea.value)
    point = cross_point(state.previous,dif.value,dea.value)
    return CrossState(state.identity,macd,(dif.value,dea.value),bar_end), replace(point,histogram=histogram.value)
