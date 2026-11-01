"""Completed price/EMA21 facts, independent of position and execution policy."""
from dataclasses import dataclass
from decimal import Decimal

VERSION = 'subing_price_ema21_distance10_v1'


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
