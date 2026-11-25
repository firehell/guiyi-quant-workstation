from decimal import Decimal

from guiyi_quant.lms405 import Bar, Position
from guiyi_quant.lms405.handoff import Handoff
from lms405_right_side_study import ONE, US, at
from lms405_visible_lock_handoff import branch_position, compare_paths


START = at("2026-10-28T09:00")


def sample(end_minute, *prices):
    end = START + end_minute * ONE
    return Bar("RU2701", end, *map(Decimal, prices), start=end - ONE)


def cases():
    return {
        1: [sample(1, 100, 115, 99, 111), sample(2, 112, 113, 109, 110),
            sample(3, 109, 111, 108, 111), sample(4, 111, 111, 110, 111),
            sample(5, 111, 112, 109, 111), sample(6, 111, 111, 110, 111),
            sample(7, 111, 113, 110, 112)],
        5: [], 15: [],
    }


def test_same_run_requires_completed_close_strictly_before_shape():
    paths = compare_paths(cases(), "LONG", (Decimal(110), Decimal(115)), START, START + 8 * ONE)
    rows = paths["groups"]["1m_to_1m"]
    (signal,) = [row for row in rows if row["confirmed_at"] == START + 7 * ONE]
    assert signal["checks"]["near"] == {
        "prior_strict_close": START + ONE,
        "current_run_before_shape": START + 3 * ONE,
        "current_run_started_with_new_crossing": True,
        "still_beyond": True,
    }
    assert not signal["checks"]["far"]["still_beyond"]
    assert paths["checked_prefixes"] >= 2


def test_mother_bar_before_start_does_not_supply_ibar():
    paths = compare_paths(cases(), "LONG", (Decimal(110), Decimal(115)), START + 5 * ONE, START + 8 * ONE)
    assert paths["groups"]["1m_to_1m"] == []


def test_visible_lot_fixture_does_not_qualify_author_action_or_carry_past_cutoff():
    request = Handoff("COUNTER_M_FROM_LOCK", Position("RU2701", Decimal(20), Decimal(20)),
                      "SHORT", "plan", "old", "counter", START, START)
    paths = compare_paths(cases(), "LONG", (Decimal(110), Decimal(115)), START, START + 8 * ONE)
    verdict = branch_position(request, "source-id", START, START + 8 * ONE, paths)
    assert verdict["unresolved_assessment_with_assumed_position"]["status"] == "INDETERMINATE"
    assert verdict["unresolved_assessment_with_assumed_position"]["after"] is None
    fixture = verdict["test_fixture"]
    assert fixture["after"] == {"long": "20", "short": "0"}
    assert fixture["confirmation_kind"] == "TEST_FIXTURE"
    assert fixture["parent_cycle_id"] == "old" and fixture["hypothetical_active_id"] == "counter"
    as_of = verdict["weak_market_candidate"]["available_at"] + 2 * US
    earlier = branch_position(request, "source-id", START, as_of, paths)
    assert earlier["test_fixture"] is None
    at_signal = branch_position(request, "source-id", START, as_of - 2 * US, paths)
    assert at_signal["weak_market_candidate"] is None
