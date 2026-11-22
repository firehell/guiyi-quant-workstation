"""Versioned chart and reference pricing for the public Newow page."""

from decimal import Decimal
from math import isfinite

GAP_FILL_PRICE_POLICY = "newow_gap_fill_price_v1"


def adjust_reference_price(
    threshold: Decimal, open_price: Decimal | None, *, buy: bool,
) -> Decimal:
    """Use the opening price only if it has strictly crossed the threshold."""
    if (
        not threshold.is_finite()
        or not isfinite(float(threshold))
        or open_price is None
        or not open_price.is_finite()
        or not isfinite(float(open_price))
        or open_price <= 0
    ):
        return threshold
    return max(threshold, open_price) if buy else min(threshold, open_price)


def has_gap_fill(formula_versions) -> bool:
    return GAP_FILL_PRICE_POLICY in formula_versions
