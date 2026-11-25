from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.task_roles import ROUTES, TaskBook, assess_task_action

T = datetime(2026, 7, 27, 9, tzinfo=UTC)
ONE = Decimal(1)
US = timedelta(microseconds=1)
INPUT = dict(source="study", source_available_at=T, version_405=True)


def short_trend():
    return TaskBook(Position("SH2609", ONE, ONE), Position("SH2609", 2 * ONE),
                    "SHORT", "original", "temporary", T)


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
