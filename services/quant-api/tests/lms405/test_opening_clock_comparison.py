from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_opening_clock_comparison import boundary_clocks, permission_replay
from lms405_right_side_study import ONE, US, at


START = at("2026-10-23T21:00")


def minute(index, *prices):
    end = START + index * ONE
    return Bar("SA2701", end, *map(Decimal, prices), start=end - ONE)


def test_outside_open_is_a_reach_but_not_a_touch_or_same_segment_cross():
    first = minute(1, 963, 965, 959, 961)
    result = boundary_clocks([first], Decimal(957), "LONG")
    assert result["open_already_beyond"] is True
    assert result["first_range_reaches_direction"] == result["first_close_strict_beyond"] == first.end
    assert result["first_range_contains_level"] is None
    assert result["first_same_segment_new_close_cross"] is None


def test_literal_touch_and_same_segment_cross_are_separate():
    bars = [minute(1, 960, 962, 957, 957), minute(2, 958, 960, 955, 956)]
    result = boundary_clocks(bars, Decimal(957), "SHORT")
    assert result["first_range_contains_level"] == bars[0].end
    assert result["first_same_segment_new_close_cross"] == bars[1].end


def test_late_negative_and_retrospective_context_stay_unavailable_at_equal_time():
    gate = START + ONE
    revealed = START + 2 * ONE
    kwargs = dict(context_end=gate, permission=("after-session-report", revealed), context_known_after=revealed)
    same = permission_replay("sa", "SA2701", revealed, **kwargs)
    after = permission_replay("sa", "SA2701", revealed + US, **kwargs)
    assert same["checks"] == {"OPENING_CONTEXT": None, "AUTHOR_SIGNAL": None, "PARTICIPATION_PERMISSION": None}
    assert same["value"] is None and after["value"] is False
    assert after["checks"]["OPENING_CONTEXT"] is True
