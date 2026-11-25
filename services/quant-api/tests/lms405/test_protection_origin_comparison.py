from decimal import Decimal

import pytest
from guiyi_quant.lms405 import Bar
from lms405_protection_origin_comparison import quote_minute_bounds
from lms405_right_side_study import ONE, US, at


def test_quote_prefix_distinguishes_touch_minute_from_completed_information():
    def make(minute, low, high):
        end = at(f"2026-10-27T21:{minute:02d}")
        lo, hi = Decimal(low), Decimal(high)
        return Bar("OI2701", end, lo, hi, lo, lo, start=end - ONE)

    quote = make(3, 105, 106)
    prefix = [make(1, 100, 102), make(2, 100, 102), quote]
    params = dict(gates={"overlap": quote.start, "known": quote.end + US}, tick=Decimal(1), lots=4,
                  average=Decimal("103.0"), band=(Decimal(105), Decimal(110)))
    row = quote_minute_bounds(prefix, quote.end, **params)
    assert row["timing"]["overlap"]["minimum_prior_lots"] == 2
    assert row["timing"]["known"]["minimum_prior_lots"] == 4
    assert row["price"]["minimum_lots_outside_on_that_side"] == 2
    assert quote_minute_bounds(prefix + [make(4, 98, 104)], quote.end, **params) == row

    with pytest.raises(ValueError, match="OI_CONDITIONAL_QUOTE_BAR_MISSING"):
        quote_minute_bounds(prefix[:-1], quote.end, **params)
