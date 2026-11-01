"""Completed price/EMA21 facts, independent of position and execution policy."""
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

VERSION = 'subing_price_ema21_atr02_context_v4'


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
    last_end: datetime | None = None
    armed_at: str | None = None
    armed_high: Decimal | None = None
    background_at: str | None = None
    background_close: Decimal | None = None
    side: str = "LONG"


def observe(state, *, contract, bar_end, high, low, close, ema21, atr14, trend_direction, side="LONG"):
    """Completed-bar evidence; never an intrabar fill or trade instruction.

    Prior qualification is checked against this bar's high before close-time
    invalidation/replacement. A newly confirmed candle cannot break itself.
    """
    if side not in ('LONG', 'SHORT'):
        raise ValueError('PRICE_SIDE_INVALID')
    sign = Decimal(1 if side == 'LONG' else -1)
    if not contract or contract != state.contract or state.side != side:
        raise ValueError('PRICE_IDENTITY_CHANGED')
    if bar_end.tzinfo is None or (state.last_end is not None and bar_end <= state.last_end):
        raise ValueError('PRICE_TIME_INVALID')
    fresh = PullbackState(contract, bar_end, side=side)
    result = dict(touch=None, hold=None, breakout=None, breakout_source=None,
                  breakout_high=None, invalidated=False, replaced=False,
                  armed_at=None, armed_high=None, lower=None, upper=None, reason=None, qualified_hold=None,
                  background_at=None, background_close=None, from_above=None,
                  trend_direction=trend_direction, background_reset=False)
    values = (high, low, close, ema21, atr14)
    if ema21 is None or atr14 is None:
        result['reason'] = 'WARMUP'
        return fresh, result
    if (not all(isinstance(v, Decimal) and v.is_finite() and v > 0 for v in values)
            or not low <= close <= high):
        result['reason'] = 'INPUT_INVALID'
        return fresh, result
    lower, upper = ema21 - Decimal('0.2') * atr14, ema21 + Decimal('0.2') * atr14
    touch_price = low if side == 'LONG' else high
    trigger_price = high if side == 'LONG' else low
    adverse_trend = 'DOWN' if side == 'LONG' else 'UP'
    favorable_trend = 'UP' if side == 'LONG' else 'DOWN'
    touch = lower <= touch_price <= upper
    hold = touch and sign * (close - ema21) > 0
    result.update(touch=touch, hold=hold, lower=lower, upper=upper)
    if trend_direction not in ('UP', 'NEUTRAL', 'DOWN'):
        result['reason'] = 'TREND_UNKNOWN'
        return fresh, result
    background_at, background_close = state.background_at, state.background_close
    from_above = background_at is not None and sign * (touch_price - background_close) < 0
    qualified_hold = hold and from_above and trend_direction != adverse_trend
    breakout = state.armed_high is not None and sign * (trigger_price - state.armed_high) > 0
    result.update(touch=touch, hold=hold, breakout=breakout, lower=lower, upper=upper,
                  breakout_source=state.armed_at if breakout else None,
                  breakout_high=state.armed_high if breakout else None,
                  invalidated=state.armed_at is not None and (sign * (close - ema21) <= 0 or trend_direction == adverse_trend),
                  qualified_hold=qualified_hold, from_above=from_above,
                  background_at=background_at, background_close=background_close,
                  background_reset=background_at is not None and trend_direction == adverse_trend)
    armed_at, armed_high = state.armed_at, state.armed_high
    if breakout or sign * (close - ema21) <= 0 or trend_direction == adverse_trend:
        armed_at, armed_high = None, None
    if qualified_hold:
        result['replaced'] = armed_at is not None
        armed_at, armed_high = bar_end.isoformat(), trigger_price
    result.update(armed_at=armed_at, armed_high=armed_high)
    # Context and qualification are distinct: a below-EMA close cancels only
    # qualification. A DOWN trend cancels the older upward context as well.
    if trend_direction == adverse_trend:
        background_at, background_close = None, None
    elif trend_direction == favorable_trend and sign * (close - ema21) > Decimal('0.2') * atr14:
        background_at, background_close = bar_end.isoformat(), close
    result.update(next_background_at=background_at, next_background_close=background_close)
    return PullbackState(contract, bar_end, armed_at, armed_high, background_at, background_close, side), result
