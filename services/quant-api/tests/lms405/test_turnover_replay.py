from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from lms405_turnover_replay import compare_tape, interval_check, state_at

START = datetime(2026, 10, 23, 9, tzinfo=UTC)
ONE = timedelta(minutes=1)
LOCKED = {"long": Decimal(20), "short": Decimal(20)}
SHORT = {"long": Decimal(0), "short": Decimal(20)}


def rule(retained, close=0, opened=0):
    return {"retained_min": retained, "retained_max": retained, "minimum_close": close, "minimum_open": opened}


def point(source, cutoff, position, long_rule):
    return dict(source=source, cuts=[cutoff], scope="JOINT_QUOTE_ANCHOR",
                visible={"short": Decimal(20)}, conditional=position,
                bounds={"long": long_rule, "short": rule(20)})


def test_replay_requires_an_ordered_chain_not_just_matching_endpoints():
    steps = [
        dict(at=START + ONE, before=LOCKED, after=SHORT),
        dict(at=START + 3 * ONE, before=SHORT, after=LOCKED),
    ]
    anchors = [
        point("only_short", START + 2 * ONE, SHORT, rule(0, close=20)),
        point("new_lock", START + 4 * ONE, LOCKED, rule(0, opened=20)),
    ]
    assert compare_tape(LOCKED, steps, START, anchors)["full_chain_match"]
    unchanged = compare_tape(LOCKED, [], START, anchors)
    assert unchanged["first_conflict"] == "only_short"
    assert unchanged["rows"][1]["any_conditional_quantity_match"]
    assert not unchanged["rows"][1]["cumulative_quantity_and_turnover_match"]


def test_exact_cutoff_and_same_quantity_replacement_are_distinguished():
    step = dict(at=START + ONE, before=LOCKED, after=SHORT)
    assert state_at(LOCKED, [step], START + ONE) == LOCKED
    replaced = [point("new_lock", START + 2 * ONE, LOCKED, rule(0, close=20, opened=20))]
    result = compare_tape(LOCKED, [], START, replaced)
    assert result["first_conflict_kind"] == "TURNOVER_OR_SEQUENCE"
    assert result["rows"][0]["rejected_interval_fields"] == ["LONG_CLOSE", "LONG_OPEN", "LONG_RETAINED"]
    with pytest.raises(ValueError, match="TURNOVER_REPLAY_PARTIAL_LEG_UNSUPPORTED"):
        interval_check(LOCKED, [step | {"after": {"long": 5, "short": 20}}], replaced[0]["bounds"])
    second = dict(at=step["at"] + timedelta(microseconds=1), before=SHORT, after=LOCKED)
    with pytest.raises(ValueError, match="TURNOVER_REPLAY_INTRAMINUTE_SEQUENCE_UNSUPPORTED"):
        compare_tape(LOCKED, [step, second], START, replaced)
    with pytest.raises(ValueError, match="TURNOVER_REPLAY_OVERLAPPING_CAPTURE_WINDOWS"):
        compare_tape(LOCKED, [], START, replaced + replaced)
