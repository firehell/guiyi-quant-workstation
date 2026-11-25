from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_break_pressure_comparison import compare_break, first_shape_after, inspect
from lms405_counter_m_exit_clocks import inspect_level
from lms405_jm_may_recovery_reset import overlapping_breaks
from lms405_ordered_original_short import ordered_followups
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


def test_separate_break_excludes_earlier_and_overlapping_crosses_and_stops_at_recapture():
    end = at("2025-12-18T09:05")
    bars = [minute(end + n * ONE, close) for n, close in enumerate(
        [8970, 8968, 8970, 8968, 8970, 8968, 8968, 8968, 8970, 8968, 8968]
    )]
    anchor = bars[2].end
    pressure = dict(
        uninterrupted_observed_retest=None, uninterrupted_full_bar_retest=None,
        renewed_break_after_inside_close=dict(bar_end=anchor, observed_until=bars[-1].end + US),
    )
    fresh_break = bars[5].end
    recaptured = bars[8].end
    valid = dict(shape_start=bars[6].end, available_at=bars[7].end + US)
    at_recapture = dict(shape_start=bars[6].end, available_at=recaptured + US)
    before_break = dict(shape_start=bars[4].start, available_at=bars[6].end + US)
    report = ordered_followups(bars, [pressure], Decimal(8969),
                               {"yes": [before_break, valid], "too_late": [at_recapture]})
    assert [entry["at"] for entry in report["fresh_crosses"]] == [
        bars[1].end, bars[3].end, fresh_break, bars[9].end,
    ]
    branch = report["branches"][0]
    first, second = branch["trigger_attempts"]
    assert first["trigger_at"] == fresh_break
    assert first["trigger_recaptured_at"] == recaptured
    assert first["fresh_shapes_before_pressure_reset"] == {"yes": valid, "too_late": at_recapture}
    assert first["fresh_shapes_before_trigger_recapture"] == {"yes": valid, "too_late": None}
    assert second["trigger_at"] == bars[9].end
    assert second["fresh_shapes_before_trigger_recapture"] == {"yes": None, "too_late": None}


def test_completed_closes_can_be_ordered_without_a_fully_later_trigger_bar():
    pressure = at("2026-05-21T13:59")
    report = {
        "branches": [{"variant": "example", "pressure_at": pressure, "expires_before": pressure + 3 * ONE}],
        "fresh_crosses": [
            {"at": pressure + n * ONE, "close": Decimal("1205")} for n in (-1, 0, 1, 2, 3)
        ],
    }
    rows = overlapping_breaks(report)
    assert [row["trigger_at"] for row in rows] == [pressure, pressure + ONE]
    report["branches"][0]["expires_before"] = pressure + ONE + US
    assert [row["trigger_at"] for row in overlapping_breaks(report)] == [pressure]


def test_risk_clock_distinguishes_opening_outside_from_fresh_cross_and_reset():
    end = at("2025-07-28T09:01")
    bars = [minute(end + n * ONE, close) for n, close in enumerate([1160, 1155, 1156, 1157, 1155])]
    cross_at = bars[2].end
    reset = bars[4].end
    geometry = {"1m": [{"shape_start": bars[3].end, "available_at": reset + US}]}
    result = inspect_level([bars], "LONG", Decimal(1155), geometry)
    assert result["first_strict_close"] == end
    assert result["first_fresh_cross"]["at"] == cross_at
    assert result["first_fresh_cross"]["reset_at"] == reset
    assert result["first_fresh_cross"]["geometry_starting_after_cross"] == {"1m": None}
