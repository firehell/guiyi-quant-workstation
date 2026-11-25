from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_break_pressure_comparison import compare_break, first_shape_after, inspect
from lms405_right_side_study import ONE, US, at


def minute(end, close, high=None):
    close = Decimal(close)
    return Bar("FG2609", end, close, Decimal(high) if high is not None else close, close, close, start=end - ONE)


def test_near_touch_and_renewed_break_use_distinct_completed_windows():
    start = at("2026-07-27T13:31")
    rows = [minute(start + n * ONE, close, high) for n, (close, high) in enumerate(
        [(900, 900), (899, 899), (898, 900), (898, 900), (901, 901), (899, 899), (903, 903)],
    )]
    threshold = Decimal(900), Decimal(902)
    prefix = compare_break(rows[:2], 1, threshold, {})
    assert prefix["uninterrupted_observed_retest"] is None
    assert prefix["renewed_break_after_inside_close"] is None
    result = compare_break(rows, 1, threshold, {})
    assert result["uninterrupted_observed_retest"]["bar_end"] == start + 2 * ONE
    assert result["uninterrupted_full_bar_retest"]["bar_end"] == start + 3 * ONE
    assert result["renewed_break_after_inside_close"]["bar_end"] == start + 5 * ONE


def test_a_gap_does_not_turn_the_next_below_band_close_into_a_new_break():
    start = at("2026-07-27T09:00")
    reopen = at("2026-07-27T10:30")
    rows = [minute(start + ONE, 903), minute(reopen + ONE, 899), minute(reopen + 2 * ONE, 898)]
    result = inspect({1: rows, 5: [], 15: []}, start, rows[-1].end + 2 * US,
                     (Decimal(900), Decimal(902)), None)
    assert result["new_breaks"] == []


def test_only_new_shapes_known_before_invalidation_can_follow_a_retest():
    end = at("2026-07-27T13:32")
    invalid = end + 3 * ONE + US
    too_early = {"shape_start": end + US, "available_at": end + 2 * ONE}
    present = {"shape_start": end + ONE, "available_at": end + 2 * ONE}
    at_invalidation = {"shape_start": end + ONE, "available_at": invalid}
    events = {"valid": [too_early, present], "invalid": [at_invalidation]}
    assert first_shape_after(events, end, invalid) == {"valid": present, "invalid": None}
