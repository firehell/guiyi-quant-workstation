from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_iron_leg_visibility import bounds_for_later_opens, quote_clock_counts
from lms405_right_side_study import ONE, US, at


def test_quote_minute_separates_before_within_and_unavailable_completion():
    first = at("2026-10-27T21:21")
    ends = [first, first + ONE, first + 2 * ONE]

    assert quote_clock_counts(ends, first + US) == {
        "known_before_entire_quote_minute": 1, "known_during_quote_minute": 1,
        "not_known_before_quote_minute_end": 1,
    }
    assert quote_clock_counts(ends, None)["not_known_before_quote_minute_end"] == 3


def test_same_price_copy_cannot_be_fully_rebuilt_after_low_price_is_outside_window():
    def bar(end, low, high):
        b_end = at(f"2026-10-27T{end}")
        low, high = map(Decimal, (low, high))
        return Bar("I2701", b_end, high, high, low, high, start=b_end - ONE)

    noon = at("2026-10-27T11:30")
    close = at("2026-10-27T14:55")
    minutes = [bar("11:30", "660", "667"), bar("14:54", "663", "665"),
               bar("14:55", "663.5", "665"), bar("14:56", "660", "665")]
    result = bounds_for_later_opens(minutes, noon, close, Decimal("0.5"), 16, range(21227, 21228))

    assert result["last_possible_whole_rebuild"]["first_start"] == at("2026-10-27T14:53")
    assert result["last_possible_whole_rebuild"]["minimum_retained"] == 0
    assert result["next_minute_start"]["minimum_retained"] == 1
