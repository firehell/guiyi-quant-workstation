from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.participation import RIGHT, Participation, assess_participation
from guiyi_quant.lms405.public_conditions import Condition
import lms405_participation_casebook as runner
from lms_near405_replay import sha


T = datetime.fromisoformat("2026-10-27T09:00:00+08:00")


def at(minute):
    return T + timedelta(minutes=minute)


def plan(long="1", short="0"):
    return Participation(Position("V2701", Decimal(long), Decimal(short)), "LONG", "plan-1", "position-1",
                         at(0), at(0), "source-1", True)


def fact(request, name, value=True, minute=2, *, review=False, known=None):
    return Condition(name, request.scope, request.position.contract, value, at(minute),
                     at(known if known is not None else minute), "test",
                     "RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME" if review else "EVENT_TIME")


def right_facts(request):
    return tuple(fact(request, name, minute=3 if name in {"RIGHT_SIGNAL", "SPACE_AVAILABLE", "PRICE_SETUP_STILL_VALID"}
                      else 2) for name in RIGHT)


def assess(request, facts, minute=6):
    result = assess_participation(request, facts, as_of=at(minute))
    assert result["action"] is None and not result["executable"]
    return result["decisions"]


def test_no_chase_does_not_block_holding_and_protection_uses_its_own_signal():
    request = plan()
    common = (fact(request, "POSITION_CONFIRMED"), fact(request, "PLAN_ACTIVE"),
              fact(request, "RIGHT_POLICY_PERMITS", False, review=True))
    quiet = assess(request, common + (fact(request, "PROTECTION_DUE", False),))
    assert [x["status"] for x in quiet.values()] == ["NOT_PERMITTED", "CONDITIONS_MET", "NOT_PERMITTED"]
    risk = assess(request, common + (fact(request, "PROTECTION_DUE"), fact(request, "PROTECTION_SIGNAL")))
    assert [x["status"] for x in risk.values()] == ["NOT_PERMITTED", "NOT_PERMITTED", "CONDITIONS_MET"]


def test_new_right_side_requires_fresh_signal_and_current_space():
    request = plan("0", "0")
    facts = right_facts(request)
    assert assess(request, facts)["RIGHT_PARTICIPATION"]["status"] == "CONDITIONS_MET"
    for name in ("RIGHT_SIGNAL", "SPACE_AVAILABLE", "PRICE_SETUP_STILL_VALID"):
        modified = tuple(replace(f, observed_at=at(1)) if f.name == name else f for f in facts)
        assert assess(request, modified)["RIGHT_PARTICIPATION"]["status"] == "NOT_PERMITTED"
    tied = tuple(replace(f, observed_at=at(2)) if f.name == "RIGHT_SIGNAL" else f for f in facts)
    assert assess(request, tied)["RIGHT_PARTICIPATION"]["status"] == "INDETERMINATE"


def test_true_protection_gate_blocks_adding_under_same_position():
    request = plan()
    facts = right_facts(request)
    assert assess(request, facts)["RIGHT_PARTICIPATION"]["status"] == "INDETERMINATE"
    ready = assess(request, facts + (fact(request, "PROTECTION_DUE", False, minute=3),))
    assert ready["RIGHT_PARTICIPATION"]["status"] == "CONDITIONS_MET"
    risk = assess(request, facts + (fact(request, "PROTECTION_DUE"), fact(request, "PROTECTION_SIGNAL")))
    assert risk["RIGHT_PARTICIPATION"]["status"] == "NOT_PERMITTED"
    assert risk["LOCK_PROTECTION"]["status"] == "CONDITIONS_MET"


def test_review_time_and_future_duplicate_do_not_become_facts():
    request = plan("0", "0")
    facts = (fact(request, "DIRECTION_ESTABLISHED", review=True),)
    result = assess(request, facts)["RIGHT_PARTICIPATION"]
    assert result["checks"]["DIRECTION_ESTABLISHED"] is None
    duplicate = fact(request, "DIRECTION_ESTABLISHED", known=6)
    assert assess(request, facts + (duplicate,)) == assess(request, facts)
    with pytest.raises(ValueError, match="UNEXPECTED_OR_DUPLICATE_PARTICIPATION_CONDITION"):
        assess(request, facts + (duplicate,), 7)
    with pytest.raises(ValueError, match="CONDITION_SCOPE_MISMATCH"):
        assess(replace(request, position_id="position-2"), facts)


@pytest.mark.parametrize("long,short", [("1", "1"), ("0", "1")])
def test_locked_or_opposite_position_does_not_use_right_route(long, short):
    request = plan(long, short)
    assert assess(request, right_facts(request))["RIGHT_PARTICIPATION"]["status"] == "NOT_PERMITTED"


def test_late_setup_does_not_release_old_signal_or_reuse_old_risk():
    request = plan("0", "0")
    facts = right_facts(request)
    late = tuple(replace(f, known_at=at(5)) if f.name == "PRICE_SETUP" else f for f in facts)
    result = assess(request, late)["RIGHT_PARTICIPATION"]
    assert result["status"] == "NOT_PERMITTED" and result["failed"] == ["PRICE_SETUP_KNOWN_BEFORE_SIGNAL"]

    request = plan()
    stale = (fact(request, "PROTECTION_DUE", False, minute=-1),)
    hold = assess(request, stale)["KEEP_HOLDING"]
    assert hold["status"] == "NOT_PERMITTED" and "PROTECTION_ASSESSED_FOR_POSITION" in hold["failed"]
    older_risk = fact(request, "PROTECTION_DUE", False, minute=2)
    right = assess(request, right_facts(request) + (older_risk,))["RIGHT_PARTICIPATION"]
    assert right["failed"] == ["EXISTING_POSITION_PROTECTION_ASSESSED_AT_SIGNAL_OR_LATER"]

    old_plan = (fact(request, "POSITION_CONFIRMED", minute=-1), fact(request, "PLAN_ACTIVE", minute=-1),
                fact(request, "PROTECTION_DUE", False, minute=2))
    hold = assess(request, old_plan)["KEEP_HOLDING"]
    assert hold["failed"] == ["PLAN_ACTIVE_CHECKED_FOR_POSITION", "POSITION_CONFIRMED_FOR_SNAPSHOT"]


def test_market_geometry_cannot_supply_historical_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "input_sources", lambda: {"ref": {"source_url": "review-source"}})
    raw = json.dumps({"cases": {"v": {"contract": "V2701", "sources": ["ref"],
        "status": "WINDOW_READABLE", "first_beyond": {"1m": at(2).isoformat()},
        "first_shape_confirmation_after_price_setup": {"next-5m": {"confirmation_at": at(3).isoformat()}},
    }}}).encode()
    geometry, casebook = tmp_path / "geometry.json", tmp_path / "casebook.json"
    geometry.write_bytes(raw)
    casebook.write_text(json.dumps({"review_at": at(5).isoformat(), "geometry_sha256": sha(raw), "cases": [{
        "id": "v-case", "contract": "V2701", "sources": ["ref"], "position": "FLAT", "side": "LONG",
        "version_405": True, "right_policy_at_review": True, "geometry": "v", "note": "unit scenario",
    }]}))
    case = runner.report(casebook, geometry)["cases"]["v-case"]
    decision = case["assessment"]["decisions"]["RIGHT_PARTICIPATION"]
    assert decision["status"] == "INDETERMINATE"
    assert all(decision["checks"][k] is None for k in ("PRICE_SETUP", "RIGHT_SIGNAL", "POSITION_CONFIRMED"))
    assert case["price_path_observation"]["first_beyond"]["1m"] == at(2).isoformat()
    geometry.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="GEOMETRY_SHA256_MISMATCH"):
        runner.report(casebook, geometry)
