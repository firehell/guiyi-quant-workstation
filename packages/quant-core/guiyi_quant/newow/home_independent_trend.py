"""Guiyi display-only MA60 approximation; not the unidentified Newow formula."""
from decimal import Decimal

from .product_contracts import ProductBar, ProductFrequency, lifecycle_input_sha256

HOME_TREND_VERSION = 'guiyi_home_close_ma60_v1'


def calculate_home_trend(bars: tuple[ProductBar, ...], anchor: ProductBar):
    """Read the completed D1 owner suffix through anchor, never future/foreign bars.

    Input completion and continuity come from the existing authoritative reader.
    A physical or calculation owner change resets warmup; strategy stages play no role.
    """
    if anchor.frequency is not ProductFrequency.DAILY:
        return None
    def owner(value):
        return (value.bar.product, value.bar.physical_contract, value.bar.segment_id,
                value.calculation_segment_id, value.frequency)
    result = dict(status='unavailable', direction=None, formula_version=HOME_TREND_VERSION,
                  frequency='1d', bar_end=anchor.bar.bar_end,
                  physical_contract=anchor.bar.physical_contract,
                  segment_id=anchor.bar.segment_id,
                  calculation_segment_id=anchor.calculation_segment_id,
                  approximate=True, page_parity=False, executable=False,
                  sample_count=0, ma60=None, close=None, input_sha256=None)
    prefix = tuple(value for value in bars if value.bar.bar_end <= anchor.bar.bar_end)
    if not prefix or prefix[-1] != anchor:
        return result
    window = []
    for value in reversed(prefix):
        if owner(value) != owner(anchor):
            break
        window.append(value)
        if len(window) == 60:
            break
    window.reverse()
    if any(not value.bar.completed or not value.bar.close.is_finite() or value.bar.close <= 0
           for value in window) or any(a.bar.bar_end >= b.bar.bar_end for a,b in zip(window,window[1:])):
        return result
    result.update(status='warming', sample_count=len(window),
                  input_sha256=lifecycle_input_sha256(tuple(window)))
    if len(window) < 60:
        return result
    # Compare scaled sums: avoid division rounding at the equality boundary.
    total = sum((value.bar.close for value in window), Decimal(0))
    close = anchor.bar.close
    result.update(status='ready', direction='bull' if close * 60 >= total else 'bear',
                  ma60=total / 60, close=close)
    return result
