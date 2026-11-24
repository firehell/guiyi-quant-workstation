from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from guiyi_quant.lms405 import Bar
from lms405_locked_exit_audit import (
    confirmed_shapes, first_confirmation, first_exit, hard_stop, hypothetical_first_action,
    verify_aggregation,
)


T = datetime(2026, 10, 23, 9, tzinfo=UTC)
FIVE = timedelta(minutes=5)
ONE = timedelta(minutes=1)
US = timedelta(microseconds=1)


def bar(index, values):
    start = T + index * FIVE
    return Bar("JM2701", start + FIVE, *map(Decimal, values), start=start)


def test_completed_fast_confirmation_survives_a_shorter_cutoff_without_slow_data():
    parent = bar(0, (104, 110, 100, 106))
    shape = bar(1, (104, 108, 102, 104))
    following = bar(2, (104, 110, 103, 104))
    minutes = [
        SimpleNamespace(bar_end=shape.end + ONE, close=Decimal(108)),
        SimpleNamespace(bar_end=shape.end + 2 * ONE, close=Decimal(109)),
    ]
    fast_end = shape.end + 2 * ONE
    shorter = confirmed_shapes(
        [parent, shape], minutes, start=parent.end, through=fast_end, side="LONG",
    )
    full = confirmed_shapes(
        [parent, shape, following], minutes, start=parent.end, through=following.end, side="LONG",
    )
    assert shorter == full
    assert first_confirmation(full, "fast_at") == fast_end + US
    assert first_confirmation(full, "slow_at") is None


def test_signal_at_lock_or_past_session_break_is_unavailable():
    parent = bar(0, (104, 110, 100, 106))
    shape = bar(1, (104, 108, 102, 104))
    minutes = [SimpleNamespace(bar_end=shape.end + 2 * ONE, close=Decimal(110))]
    through = shape.end + FIVE
    assert confirmed_shapes([parent, shape], minutes, start=parent.end, through=through, side="LONG") == []
    assert confirmed_shapes([parent, shape], minutes, start=shape.end, through=through, side="LONG") == []


def test_hard_risk_wins_ties_but_does_not_block_earlier_recovery():
    closed = bar(1, (106, 109, 100, 100))
    risk = hard_stop(
        [closed], T, closed.end + US,
        {"original_side": "LONG", "plan": {"lower": "100"}},
    )
    assert risk == closed.end + US
    assert hypothetical_first_action(risk, risk, "LONG", as_of=risk)["action"] == "CLEAR"
    assert hypothetical_first_action(risk, risk - ONE, "LONG", as_of=risk)["action"] == "UNLOCK_LONG"
    assert hypothetical_first_action(risk, risk, "LONG", as_of=risk - US)["action"] is None


def test_minute_aggregation_has_to_match_each_five_minute_bar():
    parent = bar(0, (104, 110, 100, 106))
    parts = [SimpleNamespace(bar_end=T + k * ONE, open=Decimal(104), high=Decimal(110),
                             low=Decimal(100), close=Decimal(106))
             for k in range(1, 6)]
    verify_aggregation([parent], parts)
    parts[-1].close = Decimal(105)
    with pytest.raises(ValueError, match="MINUTE_AGGREGATE_DIVERGED"):
        verify_aggregation([parent], parts)


def test_deferring_one_exit_preserves_other_exit_priority_and_time():
    times = {"PLAN_EXPIRED": T, "RANGE_TARGET": T, "RISK_INVALID": T + FIVE}
    assert first_exit(times) == (T, "PLAN_EXPIRED")
    assert first_exit(times, exclude="PLAN_EXPIRED") == (T, "RANGE_TARGET")
    assert first_exit({"PLAN_EXPIRED": T}, exclude="PLAN_EXPIRED") == (None, None)
