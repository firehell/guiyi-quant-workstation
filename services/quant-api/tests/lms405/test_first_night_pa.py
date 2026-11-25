from datetime import timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_first_night_pa import START, documented_price_events


def test_gap_and_ambiguous_wick_are_distinct_from_proven_upward_excursion():
    def bar(offset, open_, high, low, close):
        start = START + timedelta(minutes=offset)
        return Bar("SA2701", start + timedelta(minutes=1), *map(Decimal, (open_, high, low, close)), start=start)

    first = bar(0, 939, 940, 933, 933)
    second = bar(1, 933, 938, 932, 937)
    result = documented_price_events({1: [first, second]}, Decimal(936), Decimal(935))

    assert result["opening_gap_from_at_or_below"]
    assert result["first_high_strictly_above"] == first
    assert result["first_known_upward_excursion_inside_minute"] == second
    assert result["first_close_strictly_above"]["1m"] == second
