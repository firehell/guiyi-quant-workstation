from datetime import timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import US, at
from lms405_sh2609_recovery_context import area_path, contexts


def test_continuous_session_does_not_reuse_ranges_across_a_break():
    def candle(clock, spread):
        end = at(f"2026-07-28T{clock}")
        return Bar("SH2609", end, Decimal(100), Decimal(100 + spread), Decimal(100), Decimal(100),
                   start=end - timedelta(minutes=15))

    bars = [candle("10:00", 25), candle("10:15", 11), candle("10:45", 6), candle("11:00", 8)]
    sessions = [(at("2026-07-28T09:45"), at("2026-07-28T10:15")),
                (at("2026-07-28T10:30"), at("2026-07-28T11:00"))]
    after_break = contexts(bars, sessions, at("2026-07-28T10:44"))
    assert after_break["continuous_session"] is None
    cutoff = at("2026-07-28T10:45") + 2 * US
    after_new_bar = contexts(bars, sessions, cutoff)
    assert after_new_bar["trading_day"]["latest_narrower_than_opening"] is True
    assert after_new_bar["continuous_session"]["latest_narrower_than_opening"] is False
    assert after_new_bar["continuous_session"]["trailing_ranges"] == [6]
    assert contexts(bars[:3], sessions, cutoff) == after_new_bar


def test_price_area_equality_counts_for_overlap_only():
    end = at("2026-07-28T10:40")
    bar = Bar("SH2609", end, Decimal(1870), Decimal(1873), Decimal(1870), Decimal(1870),
              start=end - timedelta(minutes=1))
    path = area_path([bar], (Decimal(1859), Decimal(1870)))
    assert path["first_overlap"] == end
    assert path["first_strict_close_below_near"] is None
    assert path["first_strict_close_below_far"] is None
