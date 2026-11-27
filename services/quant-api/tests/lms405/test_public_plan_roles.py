from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_public_plan_roles import cotton_protection_clocks
from lms405_right_side_study import ONE, US, at


def test_cotton_same_bar_touch_cannot_precede_shape():
    end = at("2026-05-06T10:15")
    touch = Bar("CF2609", end, Decimal(16865), Decimal(16870), Decimal(16845), Decimal(16845), start=end - ONE)
    before_touch = {"shape_start": end - 10 * ONE, "confirmed_at": end, "close": Decimal(16845)}
    fresh = {"shape_start": end + 30 * ONE, "confirmed_at": end + 36 * ONE, "close": Decimal(16805)}
    signals = {"5m_to_1m": [before_touch, fresh]}

    result = cotton_protection_clocks([touch], signals, (Decimal(16755), Decimal(16855)))

    assert result["overlap_known_at"] == end + US
    assert result["clocks"]["5m_to_1m"]["in_band"] == before_touch
    assert result["clocks"]["5m_to_1m"]["fresh_after_completed_overlap"] == fresh
