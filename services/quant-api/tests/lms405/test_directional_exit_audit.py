from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_directional_exit_audit import later_extension, oil_price_anchor
from lms405_right_side_study import ONE, US, at


def minute(clock, close, *, high=None):
    end, value = at(f"2025-11-12T{clock}"), Decimal(close)
    return Bar("SA2601", end, value, Decimal(high) if high else value, value, value, start=end - ONE)


def test_extension_cannot_consume_base_confirmation_or_overlapping_minute():
    rows = [minute(clk, "101", high="112") for clk in ("09:01", "09:02", "09:03", "09:04")]
    later = minute("09:05", "111")
    result = later_extension([*rows, later], Decimal(100), Decimal(110))
    assert result["first_base_known_at"] == rows[1].end + US
    assert result["first_extension_touch"]["bar_end"] == rows[3].end
    assert result["first_extension_strict_close"]["bar_end"] == later.end


def test_extension_requires_unbroken_base_and_adjacent_session_minutes():
    rows = [minute("09:01", "101"), minute("09:02", "101"), minute("09:03", "100", high="115"),
            minute("09:04", "112"), minute("10:31", "112"), minute("10:32", "112")]
    result = later_extension(rows, Decimal(100), Decimal(110))
    assert result["first_extension_touch"] is None
    assert result["first_extension_strict_close"] is None


def test_oil_anchor_distinguishes_touch_reset_and_strictly_later_shape():
    rows = [minute("09:01", "99", high="100"), minute("09:02", "101"), minute("09:03", "100")]
    overlapping = {"shape_start": rows[0].end}
    fresh = {"shape_start": rows[1].end}
    signals = {"1m_to_1m": [overlapping, fresh]}
    near = oil_price_anchor(rows, signals, "LONG", Decimal(100))
    assert near["first_reach_bar_end"] == rows[0].end
    assert near["first_strict_close_bar_end"] == rows[1].end
    assert near["first_reset_after_strict_close_bar_end"] == rows[2].end
    assert near["first_short_geometry_after_reach"] == {"1m_to_1m": fresh}

    far = oil_price_anchor(rows, signals, "LONG", Decimal(102))
    assert far["first_reach_bar_end"] is None
    assert far["first_short_geometry_after_reach"] == {"1m_to_1m": None}
