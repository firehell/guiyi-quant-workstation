from decimal import Decimal

from lms405_right_side_study import US, at
from lms405_target_protection_roles import first_location


def test_price_location_and_time_before_first_overlap_are_independent():
    overlap_known_at = at("2026-10-16T09:02") + US
    band = Decimal(855), Decimal(861)
    events = [
        dict(close=Decimal(854), available_at=overlap_known_at - US),
        dict(close=Decimal(855), available_at=overlap_known_at),
        dict(close=Decimal(854), available_at=overlap_known_at + US),
        dict(close=Decimal(861), available_at=overlap_known_at + 2 * US),
        dict(close=Decimal(862), available_at=overlap_known_at + 3 * US),
    ]
    result = first_location(events, band, overlap_known_at)
    assert result["price_below_near"] == {"count": 2, "first": events[0]}
    assert result["price_within_inclusive"] == {"count": 2, "first": events[1]}
    assert result["price_above_far"] == {"count": 1, "first": events[4]}
    assert result["known_before_first_range_overlap"] == {"count": 1, "first": events[0]}
    assert first_location(events, band, None)["known_before_first_range_overlap"] is None
