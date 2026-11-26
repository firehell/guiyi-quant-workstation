from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_cross_date_protection import common_bound, quote_bar_lots, quote_prefix
from lms405_right_side_study import ONE, at


def test_quote_cutoffs_keep_unknown_preceding_close_separate_from_quote_bar():
    start = at("2026-10-22T22:05")
    price = Decimal(1)
    bars = [Bar("FG2701", start + (n + 1) * ONE, price, price, price, price, start=start + n * ONE)
            for n in range(3)]
    quote = start + 3 * ONE
    assert quote_prefix(bars, quote, "strict_before_quote_start") == bars[:1]
    assert quote_prefix(bars, quote, "exclude_quote_bar_by_end_label") == bars[:2]
    assert quote_prefix(bars, quote, "include_whole_quote_bar_sensitivity") == bars


def test_common_deadline_requires_price_support_from_every_leg():
    earlier, later = at("2026-10-22T21:01"), at("2026-10-22T21:04")
    both = common_bound({"FG2701": earlier, "SH2701": later, "SA2701": earlier})
    assert both == dict(deadline_exclusive=earlier, full_window_incompatible_legs=[],
                        binding_legs=["FG2701", "SA2701"])
    no_common = common_bound({"FG2701": earlier, "SH2701": None})
    assert no_common == dict(deadline_exclusive=None, full_window_incompatible_legs=["SH2701"], binding_legs=[])


def test_quote_minute_lot_bound_ignores_prices_after_the_quote():
    start = at("2026-10-22T22:06")
    bars = [Bar("SH2701", start + (i + 1) * ONE, *([Decimal(price)] * 4), start=start + i * ONE)
            for i, price in enumerate((1490, 1492, 1494))]
    assert quote_bar_lots(bars, start + 2 * ONE, tick=Decimal(1), lots=2, totals=range(2982, 2983)) == 1
