from decimal import Decimal

import pytest
from guiyi_quant.lms405 import Bar
from lms405_jm_gap_protection import CONTRACT, LOWER, POST, UPPER, adjacent_prices, opening_gap, path
from lms405_right_side_study import ONE, US


def minute(start, open_price, close_price):
    open_price, close_price = Decimal(open_price), Decimal(close_price)
    return Bar(CONTRACT, start + ONE, open_price, max(open_price, close_price),
               min(open_price, close_price), close_price, start=start)


def test_band_jump_requires_strict_endpoints_and_contiguous_minutes():
    first = minute(POST, UPPER + 1, UPPER + 1)
    second = minute(POST + ONE, LOWER - 1, LOWER)
    third = minute(POST + 2 * ONE, UPPER + 1, UPPER + 1)
    after_break = minute(POST + 5 * ONE, LOWER - 1, LOWER - 1)
    result = adjacent_prices([first, second, third, after_break])
    assert result["contiguous_pairs"] == 2
    assert result["whole_band_down_jumps"] == [second.start]
    assert result["whole_band_up_jumps"] == []
    assert opening_gap([after_break], after_break.start, third)["skipped_band_on_open_down"] is True
    with pytest.raises(ValueError, match="JM_GAP_OPENING_IDENTITY_UNVERIFIED"):
        opening_gap([second], second.start, first)


def test_report_excludes_minutes_straddling_uncertain_publication():
    rows = [minute(POST + n * ONE, 1670 if n == -1 else 1675, 1670 if n == -1 else 1675)
            for n in range(-4, 4)]
    series = {1: rows, 5: [], 15: []}
    earlier = path(series, rows[0].start, POST)
    later = path(series, POST + ONE, rows[-1].end + 2 * US)
    assert earlier["minutes"] == later["minutes"] == 3
    assert earlier["first_band_overlap"] == POST - 3 * ONE
    assert later["first_band_overlap"] == POST + 2 * ONE
