from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.portfolio_tasks import REQUIRED, Book, Intent, assess
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from guiyi_quant.lms405.public_conditions import Condition
from lms405_portfolio_task_policy import gated_replay, published_protection_events

STEP = timedelta(seconds=1)
T0 = datetime(2026, 10, 22, 12, tzinfo=UTC)


def prepare(book, op, lots, *, plan="plan"):
    start = book.known_at
    request = Intent(book, op, Decimal(lots), plan, start + 8 * STEP)
    facts = tuple(Condition(name, request.scope, book.contract, True, start + STEP, start + 2 * STEP,
                            "TEST_FIXTURE", "EVENT_TIME") for name in REQUIRED[op])
    approval = HandoffConfirmation(request.confirmation_scope(facts), "approval", True, start + 3 * STEP,
                                   start + 4 * STEP, "TEST_FIXTURE")
    return request, facts, approval


def advance(book, op, lots):
    request, facts, approval = prepare(book, op, lots)
    assert assess(book, request, (), as_of=approval.known_at + STEP)["after"] is None
    assert assess(book, request, facts, approval=approval, as_of=approval.known_at)["after"] is None
    result = assess(book, request, facts, approval=approval, as_of=approval.known_at + STEP, allow_test_fixture=True)
    assert result["status"] == "CONDITIONAL_ACTION"
    return result["after"]


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_shared_position_lifecycle_preserves_original_and_counter_m_roles(direction):
    seed = Book("FG2701", "one-cycle", direction, T0)
    entry = advance(seed, "ENTER_TREND", 20)
    first = advance(entry, "PROTECT_EARLY", 7)
    locked = advance(first, "PROTECT_TOPUP", 13)
    with_m = advance(locked, "ENTER_COUNTER_M", 5)
    restored = advance(with_m, "RECOVER_ORIGINAL", 20)
    assert (restored.original, restored.protection, restored.counter_m) == (20, 0, 5)
    assert (restored.visible.long, restored.visible.short) == ((20, 5) if direction == "LONG" else (5, 20))
    left = advance(restored, "EXIT_COUNTER_M", 3)
    assert (left.original, left.protection, left.counter_m) == (20, 0, 2)
    trend_exited = advance(left, "CLEAR_TREND", 20)
    assert (trend_exited.original, trend_exited.protection, trend_exited.counter_m) == (0, 0, 2)
    flat = advance(trend_exited, "EXIT_COUNTER_M", 2)
    assert advance(flat, "REENTER_TREND", 20).attempt == 2


def test_prior_scope_and_prior_action_cannot_authorize_topup_and_overprotection_fails():
    current = Book("FG2701", "cycle", "SHORT", T0, Decimal(20), attempt=1)
    early, _, permission = prepare(current, "PROTECT_EARLY", 7)
    first = advance(current, "PROTECT_EARLY", 7)
    topup, facts, approval = prepare(first, "PROTECT_TOPUP", 13)
    with pytest.raises(ValueError, match="APPROVAL_SCOPE_MISMATCH"):
        assess(first, topup, facts, approval=permission, as_of=approval.known_at + STEP, allow_test_fixture=True)
    assert assess(first, early, (), as_of=approval.known_at)["status"] == "POSITION_UNAVAILABLE_OR_SUPERSEDED"
    bad, bad_facts, bad_approval = prepare(first, "PROTECT_TOPUP", 20)
    assert assess(first, bad, bad_facts, approval=bad_approval, as_of=bad_approval.known_at + STEP,
                  allow_test_fixture=True)["status"] == "ACTION_STATE_CONFLICT"


def test_late_evaluation_cannot_backdate_position_to_approval():
    current = Book("FG2701", "cycle", "SHORT", T0, Decimal(20), attempt=1)
    request, facts, approval = prepare(current, "PROTECT_EARLY", 7)
    evaluated_at = T0 + 6 * STEP
    first = assess(current, request, facts, approval=approval, as_of=evaluated_at, allow_test_fixture=True)["after"]
    assert first.known_at == evaluated_at
    topup = Intent(first, "PROTECT_TOPUP", Decimal(13), "new plan", evaluated_at + 8 * STEP)
    stale = tuple(Condition(name, topup.scope, first.contract, True, evaluated_at - STEP, evaluated_at,
                             "TEST_FIXTURE", "EVENT_TIME") for name in REQUIRED["PROTECT_TOPUP"])
    assert assess(first, topup, stale, as_of=evaluated_at + STEP)["unknown"] == [
        *REQUIRED["PROTECT_TOPUP"], "SCOPED_APPROVAL",
    ]


def test_whole_leg_early_is_not_a_topup():
    current = Book("SA2701", "cycle", "SHORT", T0, Decimal(20), attempt=1)
    assert advance(current, "PROTECT_EARLY", 20).protection == 20
    request, facts, approval = prepare(current, "PROTECT_TOPUP", 20)
    result = assess(current, request, facts, approval=approval, as_of=approval.known_at + STEP, allow_test_fixture=True)
    assert result["status"] == "ACTION_STATE_CONFLICT"


def test_empty_market_prefix_produces_no_directional_or_blocked_action():
    assert gated_replay([], T0) == ([], [])


def test_preband_signal_needs_prepublished_current_zone_and_strict_event_clock():
    minute = timedelta(minutes=1)
    us = timedelta(microseconds=1)
    contract = "SH2701"
    candles = []
    for i, prices in enumerate(((100, 107, 98, 104), (103, 105, 100, 103), (104, 107, 103, 106))):
        start = T0 + i * minute
        candles.append(Bar(contract, start + minute, *map(Decimal, prices), start=start))
    longer = Bar(contract, T0 + 5 * minute, *map(Decimal, (100, 107, 98, 106)), start=T0)
    series = {1: candles, 5: [longer]}
    published = T0 - minute
    area = ProtectionBandUpdate(contract, "A5357264793370945", "PROTECTION", published, published, "plan",
                                "SHORT", Decimal(109), Decimal(110))
    clock = candles[-1].end + 6 * us
    assert published_protection_events(series, (area,), clock) == []
    (event,) = published_protection_events(series, (area,), clock + us)
    assert published_protection_events({1: candles, 5: []}, (area,), clock + us) == [event]
    assert event["operation"] == "PROTECT_EARLY" and event["period"] == 1
    assert event["at"] == clock and event["shape_start"] == candles[1].start

    late = replace(area, known_at=candles[1].start, effective_after=candles[1].start)
    assert published_protection_events(series, (late,), clock + us) == []
    review_at = candles[-1].start
    review = ProtectionBandUpdate(contract, "review", "REVIEW_PENDING", review_at, review_at, "review", "SHORT")
    assert published_protection_events(series, (area, review), clock + us) == []
    review_after_signal = replace(review, known_at=clock - us, effective_after=clock - us)
    assert published_protection_events(series, (area, review_after_signal), clock + us) == []
