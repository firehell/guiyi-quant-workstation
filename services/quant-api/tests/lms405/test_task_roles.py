from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.task_roles import ROUTES, TaskBook, assess_task_action
from lms405_counter_m_lot_roles import compare_roles
from lms405_task_role_replay import turnover_bounds

T = datetime(2026, 7, 27, 9, tzinfo=UTC)
ONE = Decimal(1)
US = timedelta(microseconds=1)
INPUT = dict(source="study", source_available_at=T, version_405=True)


def short_trend():
    return TaskBook(Position("SH2609", ONE, ONE), Position("SH2609", 2 * ONE),
                    "SHORT", "original", "temporary", T)


def test_conditional_turnover_distinguishes_carry_replacement_and_missing_directions():
    old = {"long": {"quantity": 20, "today_quantity": 20}, "short": {"quantity": 20, "today_quantity": 0}}
    midday = {"long": {"quantity": 20, "today_quantity": 20}}
    night = {"short": {"quantity": 20, "today_quantity": 20}}
    same_day = turnover_bounds(old, midday, "D1", "D1", {"long": list(range(16))})
    assert (same_day["long"]["minimum_close"], same_day["long"]["minimum_open"]) == (5, 5)
    assert same_day["short"]["minimum_close"] == 20

    new_day = turnover_bounds(midday, night, "D1", "D2", {})
    assert new_day["long"]["minimum_close"] == new_day["short"]["minimum_open"] == 20
    assert "short" not in midday and "long" not in night
    with pytest.raises(ValueError, match="LMS_TASK_TURNOVER_RETENTION_CONFLICT"):
        turnover_bounds(old, night, "D1", "D2", {"short": [1]})


def test_equal_locks_can_hide_full_turnover_of_the_protection_leg():
    before = {"long": {"quantity": 20, "today_quantity": 20}, "short": {"quantity": 20, "today_quantity": 0}}
    after = {side: dict(leg) for side, leg in before.items()}
    result = turnover_bounds(before, after, "D1", "D2", {"short": [20]})
    assert result["long"]["minimum_close"] == result["long"]["minimum_open"] == 20
    assert result["short"]["retained_min"] == result["short"]["retained_max"] == 20

    shifted = {"long": {"quantity": 20, "today_quantity": 16}}
    earlier = {"long": {"quantity": 20, "today_quantity": 12}}
    same_day = turnover_bounds(earlier, shifted, "D1", "D1", {})
    assert (same_day["long"]["retained_min"], same_day["long"]["retained_max"]) == (4, 16)
    earlier_unknown = {"long": {"quantity": 15, "today_quantity": None}}
    same_day = turnover_bounds(earlier_unknown, shifted, "D1", "D1", {})
    assert (same_day["long"]["retained_min"], same_day["long"]["retained_max"]) == (4, 15)
    with pytest.raises(ValueError, match="LMS_TASK_TURNOVER_PRIOR_LOTS_INCREASED_SAME_DAY"):
        turnover_bounds(before, shifted, "D1", "D1", {})


def facts_for(book, route):
    scope = book.scope(route, ONE, "study", T, True)
    return tuple(Condition(name, scope, book.trend.contract, True, T + US, T + 2 * US,
                           "TEST_FIXTURE", "EVENT_TIME") for name in ROUTES[route])


def test_short_term_partial_exit_preserves_both_legs_of_the_trend_task():
    book, route = short_trend(), "EXIT_COUNTER_M"
    result = assess_task_action(book, route, ONE, facts_for(book, route), as_of=T + 3 * US, **INPUT)
    assert result["status"] == "CONDITIONAL_ACTION"
    assert result["acting_task_id"] == "temporary"
    assert result["after"]["trend"] == result["before"]["trend"]
    assert result["after"]["counter_m"]["long"] == ONE
    assert result["after"]["aggregate"]["short"] == ONE
    assert result["executable"] is False and result["fill"] is None


def test_protection_adds_only_to_original_task_even_when_aggregate_has_both_sides():
    book = replace(short_trend(), trend=Position("SH2609", short=ONE))
    route = "LOCK_TREND"
    result = assess_task_action(book, route, ONE, facts_for(book, route), as_of=T + 3 * US, **INPUT)
    assert result["status"] == "CONDITIONAL_ACTION"
    assert result["after"]["counter_m"] == result["before"]["counter_m"]
    assert result["after"]["trend"]["long"] == result["after"]["trend"]["short"] == ONE


def test_exit_facts_cannot_unlock_trend_and_exact_availability_excludes_facts():
    book, route = short_trend(), "EXIT_COUNTER_M"
    facts = facts_for(book, route)
    early = assess_task_action(book, route, ONE, facts, as_of=T + 2 * US, **INPUT)
    assert early["status"] == "INDETERMINATE" and early["after"] is None
    with pytest.raises(ValueError, match="CONDITION_SCOPE_MISMATCH"):
        assess_task_action(book, "RESUME_TREND", ONE, facts, as_of=T + 3 * US, **INPUT)


def test_future_book_cannot_change_result_or_cause_an_action_conflict():
    book, route = short_trend(), "EXIT_COUNTER_M"
    not_yet_open = replace(book, counter_m=Position("SH2609"), counter_m_id="future")
    earlier_source = INPUT | {"source_available_at": T - US}
    facts = facts_for(book, route)
    baseline = assess_task_action(book, route, ONE, facts, as_of=T, **earlier_source)
    assert baseline == assess_task_action(not_yet_open, route, ONE, facts, as_of=T, **earlier_source)
    assert baseline["status"] == "INDETERMINATE"
    assert baseline["scope"] is baseline["requested_action"] is baseline["acting_task_id"] is None


def test_future_source_metadata_does_not_change_a_known_book_result():
    book, route = short_trend(), "EXIT_COUNTER_M"
    first = INPUT | {"source_available_at": T + 2 * US}
    second = first | {"source": "another future source", "version_405": False}
    output = assess_task_action(book, route, ONE, (), as_of=T + 2 * US, **first)
    assert output == assess_task_action(book, route, ONE, (), as_of=T + 2 * US, **second)
    assert output["scope"] is None and output["sources"] == [] and output["after"] is None


def test_trend_recovery_only_removes_original_tasks_protection_leg():
    book, route = short_trend(), "RESUME_TREND"
    result = assess_task_action(book, route, ONE, facts_for(book, route), as_of=T + 3 * US, **INPUT)
    assert result["status"] == "CONDITIONAL_ACTION"
    assert result["after"]["counter_m"] == result["before"]["counter_m"]
    assert result["after"]["trend"] == {"contract": "SH2609", "long": 0, "short": ONE}


def test_post_reading_time_and_wrong_contract_cannot_confirm_a_task_exit():
    book, route = short_trend(), "EXIT_COUNTER_M"
    first, *remaining = facts_for(book, route)
    retrospective = replace(first, time_kind="RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME")
    result = assess_task_action(book, route, ONE, (retrospective, *remaining), as_of=T + 3 * US, **INPUT)
    assert result["status"] == "INDETERMINATE"
    assert result["checks"][first.name] is None
    with pytest.raises(ValueError, match="CONTRACT_OR_SIDE_INVALID"):
        replace(book, counter_m=Position("SH2701", ONE))


def test_equal_visible_longs_have_different_residual_exposure_under_explicit_lot_roles():
    result = compare_roles("JM2601", 22, 20, [20])
    (separate,) = result["new_longs_only_are_m_original_short_still_held"]
    transfers = result["all_longs_are_m_original_short_still_held"]
    reverse_only = result["all_longs_are_m_original_short_already_closed"]
    assert separate["before"] == transfers["before"] == dict(long=22, short=20, net=2, gross=42)
    assert separate["designated_m_longs"] == 2
    assert separate["after"] == dict(long=20, short=20, net=0, gross=40)
    assert transfers["after"] == dict(long=0, short=20, net=-20, gross=20)
    assert reverse_only["after"] == dict(long=0, short=0, net=0, gross=0)
