from decimal import Decimal
from types import SimpleNamespace

from lms405_oi_range_roles import range_activity
from lms405_right_side_study import ONE, at
from lms405_v_zone_progress import observations, publication_windows


def minute(end, low, high, close):
    time = at(f"2026-06-22T10:{end:02d}")
    return SimpleNamespace(start=time - ONE, end=time, low=Decimal(low), high=Decimal(high),
                           close=Decimal(close))


def test_gap_beyond_band_retains_range_overlap_as_unknown():
    downward = [minute(1, 110, 111, 110), minute(2, 97, 99, 99)]
    lower, upper = Decimal(100), Decimal(105)
    result = observations(downward, (lower, upper), "SHORT")
    assert result["first_near_reach"] == result["first_far_reach"] == "2026-06-22T10:02+08:00"
    assert result["first_range_overlap"] is None


def test_equal_far_touch_does_not_imply_strict_close():
    upward = [minute(1, 99, 101, 101), minute(2, 101, 105, 105)]
    result = observations(upward, (Decimal(100), Decimal(105)), "LONG")
    assert result["first_range_overlap"] == "2026-06-22T10:01+08:00"
    assert result["first_far_reach"] == "2026-06-22T10:02+08:00"
    assert result["first_strict_close_beyond_far"] is None


def test_visible_plan_excludes_publication_minute_and_ambiguous_boundary():
    bars = [minute(i, 99, 104, 102) for i in range(4, 9)]
    before, after = publication_windows(bars, at("2026-06-22T10:05"))
    assert before == bars[:1]
    assert after == bars[3:]


def test_range_return_distinguishes_opening_inside_from_contiguous_reentry():
    bars = [minute(*row) for row in (
        (1, 100, 104, 104), (2, 105, 107, 106), (4, 100, 102, 101), (5, 98, 101, 99), (6, 99, 102, 100),
    )]
    stats = range_activity(bars, (Decimal(100), Decimal(105)))
    assert stats["initial_close_inside"] is True
    assert stats["closes_inside"] == 3 and stats["overlap_bars"] == 5
    assert stats["same_segment_return_count"] == 1
    assert stats["first_same_segment_close_return"] == "2026-06-22T10:06+08:00"
