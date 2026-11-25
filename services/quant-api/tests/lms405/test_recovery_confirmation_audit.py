from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_recovery_confirmation_audit import edge_candidates, strict_runs
from lms405_recovery_sequence import compare_boundary
from lms405_right_side_study import ONE, US, at


def minute(clock, price):
    end, value = at(f"2026-10-27T{clock}"), Decimal(price)
    return Bar("SH2701", end, value, value, value, value, start=end - ONE)


def test_fresh_return_requires_cross_after_observation_and_stays_in_session():
    already_beyond, equal, cross, still_beyond, next_session = [
        minute(clock, price) for clock, price in (
            ("09:01", "99"), ("09:02", "100"), ("09:03", "99"), ("09:04", "98"), ("10:31", "98"),
        )
    ]
    runs = strict_runs([already_beyond, equal, cross, still_beyond, next_session], Decimal(100), "SHORT")
    assert runs[already_beyond.end] == runs[next_session.end] == {
        "close_count": 1, "fresh_crossing_known_at": None,
    }
    assert equal.end not in runs
    assert runs[still_beyond.end] == {"close_count": 2, "fresh_crossing_known_at": cross.end + US}


def test_geometry_on_crossing_bar_only_qualifies_price_location():
    bars = [minute(clock, price) for clock, price in (("09:01", "100"), ("09:02", "101"), ("09:03", "102"))]
    on_cross, later = [dict(confirmed_at=bar.end, available_at=bar.end + US) for bar in bars[1:]]
    result = edge_candidates(bars, [on_cross, later], Decimal(100), "LONG")
    assert result["first_shape_with_current_close_beyond"] == on_cross
    assert result["run_at_first_shape_beyond"]["close_count"] == 1
    assert result["first_shape_after_fresh_cross_and_still_beyond"] == later
    assert result["fresh_run_at_shape"]["close_count"] == 2


def test_prior_crossing_gate_survives_a_return_but_resets_at_a_session_gap():
    edge = Decimal(100)
    clocks = ("09:01", "09:02", "09:03", "09:04", "09:05", "10:31")
    for side, offsets in (("LONG", (1, 0, 1, -1, 1, 1)), ("SHORT", (-1, 0, -1, 1, -1, -1))):
        bars = [minute(clock, edge + offset) for clock, offset in zip(clocks, offsets, strict=True)]
        events = [dict(confirmed_at=bar.end, available_at=bar.end + US, close=bar.close) for bar in bars]
        analysis = compare_boundary(bars, events, edge, side)
        result = analysis["decisions"]
        first_break_at = bars[2].end + US
        assert analysis["first_new_crossing_at"] == first_break_at
        assert [r["prior_break_at"] for r in result] == [None, None, None, first_break_at, first_break_at, None]
        assert [r["prior_break_in_window_at"] for r in result] == [
            None, None, None, first_break_at, first_break_at, bars[4].end + US,
        ]
        assert [r["close_beyond"] for r in result] == [True, False, True, False, True, True]
        assert [r["new_crossing_on_confirmation"] for r in result] == [False, False, True, False, True, False]
