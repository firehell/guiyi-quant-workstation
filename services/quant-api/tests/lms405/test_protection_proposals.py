from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from dataclasses import replace

import pytest

from guiyi_quant.lms405 import Bar, Position
from guiyi_quant.lms_keybar_approx import classify
from guiyi_quant.lms_protection_proposals import ResearchState, recommend, VERSION

START = datetime(2025, 7, 22, 1, tzinfo=UTC)


def bar(i, o="10", h="14", low="8", c="12"):
    start = START + timedelta(minutes=5 * i)
    return Bar(
        "JM2509", start + timedelta(minutes=5), *map(D, (o, h, low, c)), start=start
    )


def state(side, locked=False, flat=False):
    long = not flat and (side == "LONG" or locked)
    short = not flat and (side == "SHORT" or locked)
    return ResearchState(
        Position("JM2509", D(int(long)), D(int(short))),
        side,
        START - timedelta(seconds=1),
        START - timedelta(seconds=1),
    )


def frame():
    return classify(bar(-1, h="20", low="5"), bar(0))


@pytest.mark.parametrize(
    "side,close,expected",
    [
        ("LONG", "7", "LOCK"),
        ("SHORT", "15", "LOCK"),
        ("LONG", "15", None),
        ("SHORT", "7", None),
    ],
)
def test_protection_preserves_original_leg_and_only_proposes(side, close, expected):
    before = state(side)
    nxt = bar(1, "11", "16", "6", close)
    result = recommend(before, frame(), nxt, as_of=nxt.end + timedelta(microseconds=1))
    assert result["suggested_action"] == expected
    assert (
        result["requires_human_confirmation"] is True and result["executable"] is False
    )
    assert result["policy_version"] == VERSION == "lms-protection-proposal-v1"
    assert before == state(
        side
    )  # no model-state progression hidden inside recommendation
    if expected:
        assert result["hypothetical_unit_position_after"] == {"long": "1", "short": "1"}
        assert result["status"] == "PROPOSAL"


@pytest.mark.parametrize(
    "side,close,action,after",
    [
        ("LONG", "15", "UNLOCK_LONG", {"long": "1", "short": "0"}),
        ("SHORT", "7", "UNLOCK_SHORT", {"long": "0", "short": "1"}),
        ("LONG", "7", None, None),
        ("SHORT", "15", None, None),
    ],
)
def test_restore_only_original_direction_no_reverse_or_m(side, close, action, after):
    before = state(side, locked=True)
    nxt = bar(1, "11", "16", "6", close)
    r = recommend(before, frame(), nxt, as_of=nxt.end + timedelta(seconds=1))
    assert r["suggested_action"] == action
    assert r["hypothetical_unit_position_after"] == after
    assert before.position == Position("JM2509", D(1), D(1))


@pytest.mark.parametrize("close", ["14", "8", "11"])
def test_equal_or_wick_only_cross_does_not_trigger(close):
    nxt = bar(1, "11", "16", "6", close)
    r = recommend(state("LONG"), frame(), nxt, as_of=nxt.end + timedelta(seconds=1))
    assert r["suggested_action"] is None and r["signal_direction"] is None


def test_pinbar_requires_break_in_its_own_direction():
    pin = classify(None, bar(0, "10", "11", "7", "11"))
    down = bar(1, "10", "12", "6", "6")
    up = bar(1, "10", "12", "9", "12")
    assert (
        recommend(state("LONG"), pin, down, as_of=down.end + timedelta(seconds=1))[
            "signal_direction"
        ]
        is None
    )
    assert (
        recommend(state("SHORT"), pin, up, as_of=up.end + timedelta(seconds=1))[
            "suggested_action"
        ]
        == "LOCK"
    )


def test_ibar_can_confirm_opposite_to_overlapping_unconfirmed_pinbar():
    pin = classify(bar(-1, h="20", low="5"), bar(0, "10", "11", "7", "11"))
    down = bar(1, "10", "12", "6", "6")
    r = recommend(state("LONG"), pin, down, as_of=down.end + timedelta(seconds=1))
    assert r["suggested_action"] == "LOCK" and r["basis"] == ["IBAR_DOWN_CLOSE_BREAK"]


def test_strict_time_visibility_and_signal_formed_after_input_state():
    nxt = bar(1, "11", "16", "6", "7")
    s = state("LONG")
    assert recommend(s, frame(), nxt, as_of=nxt.end)["status"] == "NOT_YET_AVAILABLE"
    later = replace(s, since=bar(0).end, known_at=bar(0).end)
    assert (
        recommend(later, frame(), nxt, as_of=nxt.end + timedelta(seconds=1))["status"]
        == "STALE_SIGNAL"
    )
    unknown = replace(s, known_at=nxt.end + timedelta(seconds=2))
    assert (
        recommend(unknown, frame(), nxt, as_of=nxt.end + timedelta(seconds=1))["status"]
        == "STATE_NOT_AVAILABLE"
    )


def test_flat_does_not_open_and_repeated_reads_do_not_apply_proposal():
    nxt = bar(1, "11", "16", "6", "7")
    t = nxt.end + timedelta(seconds=1)
    assert (
        recommend(state("LONG", flat=True), frame(), nxt, as_of=t)["status"]
        == "FLAT_NO_ENTRY"
    )
    a = recommend(state("LONG"), frame(), nxt, as_of=t)
    b = recommend(state("LONG"), frame(), nxt, as_of=t + timedelta(seconds=1))
    assert (
        a["proposal_id"] == b["proposal_id"]
        and a["suggested_action"] == b["suggested_action"] == "LOCK"
    )
    assert a["available_after"] == nxt.end.isoformat()


def test_fail_closed_on_contract_state_version_and_frame_forgery():
    nxt = bar(1, "11", "16", "6", "7")
    s = state("LONG")
    t = nxt.end + timedelta(seconds=1)
    with pytest.raises(ValueError):
        recommend(s, frame(), replace(nxt, contract="SH2701"), as_of=t)
    with pytest.raises(ValueError):
        recommend(s, replace(frame(), ibar=False), nxt, as_of=t)
    with pytest.raises(ValueError):
        ResearchState(Position("JM2509", D(2), D(0)), "LONG", START, START)
    with pytest.raises(ValueError):
        ResearchState(Position("JM2509", D(1), D(0)), "SHORT", START, START)
    with pytest.raises(ValueError):
        ResearchState(s.position, "LONG", START, START - timedelta(seconds=1))
