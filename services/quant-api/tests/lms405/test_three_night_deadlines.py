from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_oi_ru_signal_deadlines import quote_combinations, strict_row_quote_check
from lms405_right_side_study import ONE, at


def test_minimum_three_row_quote_spread_without_a_common_minute():
    start = at("2026-10-27T22:05")
    ends = ({start + 2 * ONE, start + 5 * ONE}, {start, start + 2 * ONE}, {start})
    result = quote_combinations(ends)
    assert result == dict(count=4, same_label_count=0, min_spread_minutes=2,
                          example_end_labels=(start + 2 * ONE, start, start))
    assert quote_combinations((*ends[:2], set()))["min_spread_minutes"] is None


def test_quote_cut_excludes_bars_still_unknown_at_quote_minute_start():
    start = at("2026-10-27T21:00")
    bars = [Bar("SH2701", start + (i + 1) * ONE, *([Decimal(price)] * 4), start=start + i * ONE)
            for i, price in enumerate((1490, 1492, 1492))]
    check = strict_row_quote_check(bars, start + 3 * ONE, start + 2 * ONE,
                                   tick=Decimal(1), lots=1, totals=range(1492, 1493))
    assert not check["candidate_ready_at_boundary"]
    assert not check["price_compatible"]
