from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from lms405_protection_band_return_study import compare_band
from lms405_right_side_study import US, at


def bar(i, close, low=None, high=None):
    end = at("2026-01-02T09:00") + timedelta(minutes=i)
    return SimpleNamespace(bar_end=end, close=Decimal(close), low=Decimal(low or close), high=Decimal(high or close))


def test_fresh_cross_does_not_infer_a_path_through_a_session_gap():
    rows = [bar(1, 99), bar(16, 103), bar(17, 100), bar(18, 101), bar(19, 103)]
    result = compare_band(rows, band=(Decimal(100), Decimal(102)), side="LONG")
    assert result["first_range_overlap"]["bar_end"] == rows[2].bar_end
    assert result["first_fresh_near_close"]["bar_end"] == rows[3].bar_end
    assert result["first_fresh_far_close"]["bar_end"] == rows[4].bar_end
    assert result["first_later_far_after_near"]["available_at"] == rows[4].bar_end + US
    assert result["first_later_far_after_near"]["preceding_near"]["bar_end"] == rows[3].bar_end


def test_one_bar_crossing_both_edges_does_not_supply_two_ordered_observations():
    rows = [bar(1, 103), bar(2, 99, 99, 103)]
    result = compare_band(rows, band=(Decimal(100), Decimal(102)), side="SHORT")
    assert result["first_fresh_near_close"] == result["first_fresh_far_close"]
    assert result["first_later_far_after_near"] is None
