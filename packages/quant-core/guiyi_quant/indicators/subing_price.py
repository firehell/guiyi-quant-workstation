"""Completed price/EMA21 facts, independent of position and execution policy."""
from dataclasses import dataclass
from decimal import Decimal

VERSION = 'subing_price_ema21_atr02_pullback_v2'


@dataclass(frozen=True)
class PricePoint:
    close: Decimal | None = None
    ema21: Decimal | None = None
    distance: Decimal | None = None
    relation: str = 'UNKNOWN'
    above_ema: bool | None = None
    below_ema: bool | None = None
    near_above_ema: bool | None = None
    reason: str | None = 'WARMUP'


def price_point(close: Decimal, ema21: Decimal | None) -> PricePoint:
    """Reuse caller's shared completed EMA; no second indicator algorithm."""
    if not isinstance(close, Decimal) or not close.is_finite() or close <= 0:
        return PricePoint(reason='INPUT_INVALID')
    if ema21 is None:
        return PricePoint(close=close)
    if not isinstance(ema21, Decimal) or not ema21.is_finite() or ema21 <= 0:
        return PricePoint(close=close, reason='INPUT_INVALID')
    distance = close - ema21
    return PricePoint(close, ema21, distance,
                      'ABOVE' if distance > 0 else 'BELOW' if distance < 0 else 'ON',
                      distance > 0, distance < 0, 0 < distance < 10, None)


@dataclass(frozen=True)
class PullbackState:
    contract: str
    last_end: object = None
    armed_at: str | None = None
    armed_high: Decimal | None = None


def observe(state, *, contract, bar_end, high, low, close, ema21, atr14):
    """Completed-bar evidence; never an intrabar fill or trade instruction.

    Prior qualification is checked against this bar's high before close-time
    invalidation/replacement. A newly confirmed candle cannot break itself.
    """
    if not contract or contract != state.contract:
        raise ValueError('PRICE_IDENTITY_CHANGED')
    if bar_end.tzinfo is None or (state.last_end is not None and bar_end <= state.last_end):
        raise ValueError('PRICE_TIME_INVALID')
    fresh = PullbackState(contract, bar_end)
    result = dict(touch=None, hold=None, breakout=None, breakout_source=None,
                  breakout_high=None, invalidated=False, replaced=False,
                  armed_at=None, armed_high=None, lower=None, upper=None, reason=None)
    values = (high, low, close, ema21, atr14)
    if ema21 is None or atr14 is None:
        result['reason'] = 'WARMUP'
        return fresh, result
    if (not all(isinstance(v, Decimal) and v.is_finite() and v > 0 for v in values)
            or not low <= close <= high):
        result['reason'] = 'INPUT_INVALID'
        return fresh, result
    lower, upper = ema21 - Decimal('0.2') * atr14, ema21 + Decimal('0.2') * atr14
    touch = lower <= low <= upper
    hold = touch and close > ema21
    breakout = state.armed_high is not None and high > state.armed_high
    result.update(touch=touch, hold=hold, breakout=breakout, lower=lower, upper=upper,
                  breakout_source=state.armed_at if breakout else None,
                  breakout_high=state.armed_high if breakout else None,
                  invalidated=state.armed_at is not None and close <= ema21)
    armed_at, armed_high = state.armed_at, state.armed_high
    if breakout or close <= ema21:
        armed_at, armed_high = None, None
    if hold:
        result['replaced'] = armed_at is not None
        armed_at, armed_high = bar_end.isoformat(), high
    result.update(armed_at=armed_at, armed_high=armed_high)
    return PullbackState(contract, bar_end, armed_at, armed_high), result
