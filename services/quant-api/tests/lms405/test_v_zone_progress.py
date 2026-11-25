from decimal import Decimal
from types import SimpleNamespace

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
