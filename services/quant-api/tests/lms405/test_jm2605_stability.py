from datetime import timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_jm2605_stability import compare_after_lock, stability_context
from lms405_right_side_study import US, at


def test_stability_uses_only_completed_ranges_on_each_side_of_confirmation():
    def candle(clock, spread):
        end = at(f"2026-01-07T{clock}")
        return Bar("JM2605", end, Decimal(100), Decimal(100 + spread), Decimal(100), Decimal(100),
                   start=end - timedelta(minutes=15))

    bars = [candle("21:15", 25), candle("21:30", 11), candle("21:45", 19), candle("22:00", 27)]
    assert stability_context(bars, bars[0].end + US) is None
    assert stability_context(bars, bars[1].end + 2 * US)["strict_two_in_sequence"] is None
    lock = {"available_at": at("2026-01-07T21:32") + US}
    shape_start, confirm = at("2026-01-07T22:00"), at("2026-01-07T22:05")
    signal = {"shape_start": shape_start, "confirmed_at": confirm, "available_at": confirm + US}
    row, = compare_after_lock({15: bars}, {"5m_to_1m": [signal]}, lock)["5m_to_1m"]
    assert row["fresh_shape_after_hypothetical_lock"] is True
    assert row["context_before_shape"]["latest_narrower_than_opening"] is True
    assert row["context_before_confirmation"]["latest_narrower_than_opening"] is False
    assert row["context_before_confirmation"]["strict_two_in_sequence"] is False
