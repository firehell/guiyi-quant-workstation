from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from guiyi_quant.lms405 import Bar, Position
from guiyi_quant.lms405.handoff import Handoff, HandoffConfirmation
from guiyi_quant.lms405.minute_recovery import MINUTE, US, assess_minute_recovery
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.recovery_permission import MinuteRecoveryPermission, RecoveryPermission, visible_permissions

START = datetime(2026, 10, 27, 13, 30, tzinfo=UTC)


def scenario(side):
    contract = "SH2701"
    request = Handoff("RESUME_ORIGINAL", Position(contract, D(20), D(20)), side, "plan", "cycle", None,
                      START - timedelta(minutes=3), START - timedelta(minutes=2))
    edge = D(110 if side == "LONG" else 100)
    permit = MinuteRecoveryPermission(contract, request.plan_id, request.cycle_id, side, request.position_since,
                                      START - MINUTE, "PERMIT", "NEAR", edge, "case", "TEST_FIXTURE", shape_minutes=1)
    prices = ((108, 111, 105, 108), (108, 110, 107, 109), (109, 114, 108, 112),
              (112, 113, 111, 112), (112, 115, 111, 114))
    if side == "SHORT":
        prices = [(210 - o, 210 - lo, 210 - hi, 210 - c) for o, hi, lo, c in prices]
    rows = [Bar(contract, START + (i + 1) * MINUTE, *map(D, ohlc), start=START + i * MINUTE)
            for i, ohlc in enumerate(prices)]
    return request, permit, rows


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_fast_release_needs_scoped_permission_and_independent_approval(side):
    request, permit, rows = scenario(side)
    t = rows[-1].end + US
    opts = dict(version_405=True, allow_test_fixture=True)
    assert assess_minute_recovery(request, rows, as_of=t, permissions=(permit,), **opts)["proposal"] is None
    assert assess_minute_recovery(request, rows, as_of=t + US, **opts)["status"] == "RECOVERY_PERMISSION_UNKNOWN"
    deny = replace(permit, decision="DENY", edge=None, endpoint=None, shape_minutes=None, known_at=permit.known_at + US)
    assert assess_minute_recovery(request, rows, as_of=t + US, permissions=(permit, deny), **opts)["status"] == (
        "RECOVERY_PERMISSION_DENIED"
    )
    with pytest.raises(ValueError, match="HUMAN_RECOVERY_PERMISSION_REQUIRED"):
        assess_minute_recovery(request, rows, as_of=t + US, permissions=(permit,))
    facts = tuple(Condition(name, request.scope, request.before.contract, True,
                            request.position_since, request.position_known_at, "fixture", "EVENT_TIME")
                  for name in ("ORIGINAL_PLAN_VALID", "POSITION_PATH_CONFIRMED"))
    result = assess_minute_recovery(request, rows, as_of=t + US, permissions=(permit,), facts=facts, **opts)
    p = result["proposal"]
    assert p["crossing_end"] == rows[2].end and result["after"] is None
    approval = HandoffConfirmation(p["approval_scope"], "accept", True, t + US, t + US, "TEST_FIXTURE")
    accepted = assess_minute_recovery(request, rows, as_of=t + 2 * US, permissions=(permit,),
                                     facts=iter(facts), approval=approval, **opts)
    assert accepted["hypothetical_active_id"] == request.cycle_id
    assert accepted["after"] == ({"long": "20", "short": "0"} if side == "LONG" else {"long": "0", "short": "20"})
    veto = replace(deny, known_at=t + US)
    blocked = assess_minute_recovery(request, rows, as_of=t + 2 * US, permissions=(permit, veto),
                                    facts=facts, approval=approval, **opts)
    assert blocked["proposal"] is blocked["after"] is None
    stale = assess_minute_recovery(request, rows, as_of=t + MINUTE + US, permissions=(permit,), **opts)
    assert stale["status"] == "MINUTE_CONFIRMATION_STALE"


def test_fast_release_resets_at_gaps_and_rejects_mismatched_cycle_and_width():
    request, permit, rows = scenario("LONG")
    opts = dict(as_of=rows[-1].end + 2 * US, allow_test_fixture=True)
    for records in ((replace(permit, cycle_id="previous"),), (replace(permit, locked_at=START - 4 * MINUTE),)):
        assert assess_minute_recovery(request, rows, permissions=records, **opts)["status"] == (
            "RECOVERY_PERMISSION_UNKNOWN"
        )
    gap = assess_minute_recovery(request, rows[:2] + rows[3:], permissions=(permit,), **opts)
    assert gap["status"] == "MINUTE_FRESH_PRICE_RETURN_UNCONFIRMED"
    five = assess_minute_recovery(request, rows, permissions=(replace(permit, shape_minutes=5),), **opts)
    assert five["status"] == "MINUTE_KEYBAR_UNCONFIRMED"
    with pytest.raises(ValueError, match="MINUTE_RECOVERY_SHAPE_PERIOD_REQUIRED"):
        replace(permit, shape_minutes=15)
    old = RecoveryPermission(**{k: getattr(permit, k) for k in RecoveryPermission.__dataclass_fields__})
    with pytest.raises(ValueError, match="RECOVERY_PERMISSION_REQUIRED"):
        assess_minute_recovery(request, rows, permissions=(old,), **opts)
    with pytest.raises(ValueError, match="RECOVERY_PERMISSION_REQUIRED"):
        visible_permissions((permit,), request.before.contract, timely_fixture=True, as_of=opts["as_of"])
    with pytest.raises(ValueError, match="MINUTE_RECOVERY_BAR_IDENTITY_MISMATCH"):
        assess_minute_recovery(request, [*rows[:-1], replace(rows[-1], contract="V2609")], permissions=(permit,), **opts)


def test_five_minute_shape_requires_matching_complete_minute_aggregation():
    request, permit, _ = scenario("LONG")
    permit = replace(permit, shape_minutes=5)
    quotes = ([(109, 118, 104, 109)] * 5 + [(109, 113, 107, 109)] * 4
              + [(109, 113, 107, 111), (111, 113, 110, 112), (112, 115, 111, 114)])
    rows = [Bar(request.before.contract, START + (i + 1) * MINUTE, *map(D, ohlc), start=START + i * MINUTE)
            for i, ohlc in enumerate(quotes)]
    mother = Bar(request.before.contract, rows[4].end, *map(D, (109, 118, 104, 109)), start=START)
    shape = Bar(request.before.contract, rows[9].end, *map(D, (109, 113, 107, 111)), start=rows[5].start)
    opts = dict(as_of=rows[-1].end + 2 * US, permissions=(permit,), allow_test_fixture=True)
    result = assess_minute_recovery(request, rows, (mother, shape), **opts)
    assert result["proposal"]["shape_minutes"] == 5 and result["proposal"]["shape_start"] == rows[5].start
    for minutes, five in ((rows, (mother, replace(shape, high=D("113.5")))),
                          (rows, (replace(mother, high=D(119)), shape)),
                          (rows[:6] + rows[7:], (mother, shape))):
        denied = assess_minute_recovery(request, minutes, five, **opts)
        assert denied["proposal"] is denied["after"] is None
