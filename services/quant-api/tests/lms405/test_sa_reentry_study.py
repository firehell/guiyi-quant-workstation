from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from lms405_fg_sa_case import at
from lms405_sa_reentry_study import price_compatibility


def test_multifill_average_can_be_compatible_without_a_single_minute_containing_it():
    trading_day = date(2026, 10, 26)
    rows = [
        SimpleNamespace(bar_end=at(f"23T{minute}"), trading_day=day, low=Decimal(lo), high=Decimal(hi))
        for minute, day, lo, hi in (
            ("21:00", trading_day, 963, 963),
            ("21:01", trading_day, 959, 962),
            ("21:02", date(2026, 10, 23), 963, 963),
            ("21:03", trading_day, 964, 965),
            ("21:04", trading_day, 963, 963),
        )
    ]
    result = price_compatibility(rows, trading_day, at("23T21:00"), at("23T21:04"), "963")
    assert result["bars"] == 2
    assert result["range"] == ["959", "965"]
    assert result["average_range_compatible"]
    assert result["single_price_compatible_minutes"] == []

    after_signal = price_compatibility(rows, trading_day, at("23T21:01"), at("23T21:04"), "963")
    assert after_signal["range"] == ["964", "965"]
    assert not after_signal["average_range_compatible"]
