from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from lms405_jm2601_m_window import LOCAL, added_lot_average, inspect_windows, read_sources


def at(hour, minute):
    return datetime(2025, 12, 1, hour, minute, tzinfo=LOCAL)


def bar(hour, minute, low, high, close):
    return SimpleNamespace(bar_end=at(hour, minute), low=Decimal(low), high=Decimal(high),
                           close=Decimal(close))


def test_added_lots_use_opening_average_and_weighted_tick_grid():
    sources = read_sources()
    assert "1061.50" in sources["N01"]["observed_summary"]
    assert "开仓均1063.61" in sources["O02"]["observed_summary"]
    assert "持仓均1065.89" in sources["O02"]["observed_summary"]
    result = added_lot_average()
    assert result["display_arithmetic_mean"] == Decimal("1084.71")
    assert result["conservative_rounding_interval"] == (Decimal("1084.605"), Decimal("1084.815"))
    assert result["conditional_total_ticks"] == [4339]
    assert result["conditional_mean_values"] == [Decimal("1084.75")]


def test_post_minutes_boundary_and_inclusive_touch_are_distinct():
    bars = [
        bar(9, 33, "1070", "1080", "1070"),
        bar(9, 34, "1067", "1085", "1067"),
        bar(9, 35, "1068", "1085", "1069"),
        bar(9, 36, "1077.5", "1081", "1077.5"),
        bar(9, 45, "1080", "1085", "1085"),
        bar(9, 46, "1084", "1086", "1085"),
        bar(9, 47, "1085", "1086", "1085"),
        bar(10, 3, "1082", "1084", "1084"),
        bar(10, 4, "1067", "1110", "1067"),
    ]
    result = inspect_windows(bars, locked_post=at(9, 34), confirmed=at(9, 45),
                             midpoint=Decimal("1084.5"), cutoff=at(10, 4))
    assert result["first_band_contact"] == at(9, 36)
    assert result["first_strict_low_below_upper"] is None
    assert result["first_strict_close_below_upper"] is None
    assert result["first_strict_low_below_lower"] is None
    assert result["first_strict_close_below_lower"] is None
    assert result["first_older_m_band_contact"] is None
    assert result["first_close_above_final_structure_midpoint"] == at(9, 45)
    assert result["first_trading_day_prefix_allowing_mean"]["bar_end"] == at(9, 34)
    assert result["first_preconfirmation_prefix_allowing_mean"] == {
        "bar_end": at(9, 45), "high_before_compatible_bar": Decimal("1081"), "same_minute_compatible": True,
    }
    windows = result["conditional_price_envelopes"]
    assert windows["trading_day_before_locked_post_minute"]["count"] == 1
    assert windows["confirmation_boundary_minute"]["count"] == 1
    assert windows["minutes_starting_strictly_after_confirmation"]["count"] == 2
    assert windows["minutes_starting_strictly_after_confirmation"]["envelope_allows_average"]
    assert windows["minutes_starting_strictly_after_confirmation"]["same_minute_envelope_count"] == 0
