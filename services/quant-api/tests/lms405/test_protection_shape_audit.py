from datetime import timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_protection_shape_audit import outside_events
from lms405_right_side_study import US, at


def bar(index, ohlc, contract="I2701"):
    start = at("2026-10-26T21:00") + timedelta(minutes=5 * index)
    return Bar(contract, start + timedelta(minutes=5), *map(Decimal, ohlc), start=start)


def test_outside_shape_immediate_and_delayed_confirmation_are_distinct():
    parent = bar(0, ("100", "105", "95", "100"))
    shape = bar(1, ("98", "107", "94", "106"))
    following = bar(2, ("106", "109", "102", "108"))
    args = dict(shape_period=5, confirm_period=5, start=parent.start, side="LONG")
    series = {5: [parent, shape, following]}
    first = outside_events(series, as_of=following.end + US, **args)
    expanded = outside_events(series, as_of=following.end + 2 * US, **args)
    assert [event["kind"] for event in first] == ["OUTSIDE_OWN_CLOSE"]
    assert [event["kind"] for event in expanded] == ["OUTSIDE_OWN_CLOSE", "OUTSIDE_NEXT_CLOSE"]
    assert expanded[-1]["boundary"] == Decimal("107")


def test_outside_shape_disallows_equal_edges_session_gaps_and_other_contract():
    parent = bar(0, ("100", "105", "95", "100"))
    valid_pair = [
        bar(1, ("100", "105", "93", "94")),
        bar(2, ("100", "107", "93", "94")),
        bar(1, ("100", "107", "93", "94"), contract="SH2701"),
    ]
    for next_bar in valid_pair:
        assert outside_events(
            {5: [parent, next_bar]}, shape_period=5, confirm_period=5,
            start=parent.start, as_of=next_bar.end + 2 * US, side="SHORT",
        ) == []
