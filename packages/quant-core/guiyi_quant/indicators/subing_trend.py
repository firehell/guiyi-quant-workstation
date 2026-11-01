"""Independent SuBing trend candidate. No order, signal or active formula mutation."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import math

from .atr import initial_atr_state, step_atr
from .ema import initial_ema_state, step_ema
from .models import AtrState, EmaState

VERSION = 'subing_ema21_ols5_atr14_v2'


@dataclass(frozen=True)
class TrendPoint:
    ema21: float | None = None
    atr14: float | None = None
    slope: float | None = None
    normalized_slope: float | None = None
    angle: float | None = None
    direction: str = 'UNKNOWN'
    reason: str | None = 'WARMUP'


def slope_point(values: tuple[float, ...], atr: float) -> TrendPoint:
    """OLS on x=0..4: centered denominator=10, one bar / one ATR axes."""
    if len(values) != 5 or not all(math.isfinite(v) for v in (*values, atr)):
        return TrendPoint(reason='INPUT_INVALID')
    if atr <= 0:
        return TrendPoint(ema21=values[-1], atr14=atr, reason='ATR_NOT_POSITIVE')
    mean = sum(values) / 5
    slope = sum((i - 2) * (v - mean) for i, v in enumerate(values)) / 10
    normalized = slope / atr
    angle = math.degrees(math.atan(normalized))
    # Compare unrounded angle: exactly +/-5 belongs to the neutral interval.
    direction = 'UP' if angle > 5 else 'DOWN' if angle < -5 else 'NEUTRAL'
    return TrendPoint(values[-1], atr, slope, normalized, angle, direction, None)


@dataclass(frozen=True)
class TrendState:
    identity: tuple[str, str]
    ema: EmaState
    atr: AtrState
    values: tuple[float, ...] = ()
    last_end: datetime | None = None


def initial_state(contract: str, frequency: str) -> TrendState:
    if not contract or frequency not in ('30m', '1d'):
        raise ValueError('TREND_IDENTITY_INVALID')
    return TrendState((contract, frequency), initial_ema_state(21),
                      initial_atr_state(14, smoothing_policy='wilder_sma_seed'))


def step(state: TrendState, *, contract: str, frequency: str, bar_end: datetime,
         high: float, low: float, close: float) -> tuple[TrendState, TrendPoint]:
    """Caller supplies validated completed physical bars, gaps must fail upstream."""
    if (contract, frequency) != state.identity:
        raise ValueError('TREND_IDENTITY_CHANGED')
    if bar_end.tzinfo is None or (state.last_end is not None and bar_end <= state.last_end):
        raise ValueError('TREND_TIME_INVALID')
    if not all(math.isfinite(v) and v > 0 for v in (high, low, close)) or not low <= close <= high:
        clean = replace(initial_state(contract, frequency), last_end=bar_end)
        return clean, TrendPoint(reason='INPUT_INVALID')
    ema, ep = step_ema(state.ema, close, bar_end=bar_end.isoformat())
    atr, ap = step_atr(state.atr, high=high, low=low, close=close, bar_end=bar_end.isoformat())
    values = (*state.values, ep.value)[-5:] if ep.ready and ep.value is not None else ()
    new = TrendState(state.identity, ema, atr, values, bar_end)
    point = (slope_point(values, ap.value) if len(values) == 5 and ap.ready and ap.value is not None
             else TrendPoint(ema21=ep.value, atr14=ap.value))
    return new, point
