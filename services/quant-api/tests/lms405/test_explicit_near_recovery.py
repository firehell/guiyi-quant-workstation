from dataclasses import replace
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.near_recovery import EXPLICIT_NEAR, US, NearRecoveryCase, assess_near_recovery
from lms405_explicit_near_recovery import fixture, make_case
from lms405_right_side_study import at


def bar(start, end, prices):
    return Bar("JM2601", at(f"2025-11-27T{end}"), *map(Decimal, prices), start=at(f"2025-11-27T{start}"))


def sample():
    broke = bar("09:00", "09:01", (1071, 1073, 1069, 1070))
    shape = bar("09:10", "09:15", (1072, 1074, 1071, 1071))
    confirm = bar("09:15", "09:16", (1071, 1071, 1068, 1069))
    return make_case("JM2601", "SHORT", (Decimal(1061), Decimal(1072)), EXPLICIT_NEAR, source="TEST_FIXTURE",
                     plan_at=at("2025-11-27T08:57"), seed_at=at("2025-11-27T08:58"),
                     bars=(broke, shape, confirm), version=True)


def test_explicit_near_price_route_only_removes_protection_after_bound_approval():
    case = sample()
    run = fixture(case)
    assert run["with_approval"]["after"] == {"long": "0", "short": "1"}
    assert run["with_approval"]["requested_action"] == "UNLOCK_SHORT"
    assert run["with_approval"]["hypothetical_active_id"] == case.request.cycle_id
    assert run["at_approval_clock"]["after"] is None
    assert run["without_approval"]["after"] is None
    assert run["without_external_facts"]["after"] is None
    assert fixture(replace(case, version_405=None))["with_approval"]["after"] is None


def test_target_role_late_plan_and_near_equality_cannot_enable_recovery():
    case = sample()
    as_of = case.confirmation.end + 5 * US
    wrong_role = assess_near_recovery(replace(case, role="STRONG_TARGET"), (), as_of=as_of)
    assert wrong_role["failed"] == ["explicit_near_role"]
    late = replace(case, zone=replace(case.zone, known_at=case.shape.start))
    assert "plan_known_before_shape" in assess_near_recovery(late, (), as_of=as_of)["failed"]
    returned = replace(case, confirmation=bar("09:15", "09:16", (1071, 1072, 1068, 1072)))
    assert "confirmation_still_beyond_near" in assess_near_recovery(returned, (), as_of=as_of)["failed"]
    expired = replace(case, zone=replace(case.zone, expires_at=as_of))
    assert "plan_current_at_assessment" in assess_near_recovery(expired, (), as_of=as_of)["failed"]


def test_no_prior_break_is_unknown_and_other_plan_or_contract_cannot_be_used():
    case = sample()
    unknown = assess_near_recovery(replace(case, break_bar=None), (), as_of=case.confirmation.end + 2 * US)
    assert unknown["status"] == "INDETERMINATE"
    assert unknown["after"] is None
    with pytest.raises(ValueError, match="NEAR_RECOVERY_PLAN_ID_MISMATCH"):
        replace(case, zone=replace(case.zone, id="different-plan"))
    with pytest.raises(ValueError, match="NEAR_RECOVERY_BAR_OR_CONTRACT_MISMATCH"):
        replace(case, confirmation=replace(case.confirmation, contract="JM2701"))
    with pytest.raises(ValueError, match="NEAR_RECOVERY_CONFIRMATION_WINDOW_MISMATCH"):
        NearRecoveryCase(case.request, case.zone, case.role, case.break_bar, case.shape,
                         bar("09:20", "09:21", (1071, 1071, 1068, 1069)), case.version_405)


def test_late_plan_reveals_no_selected_price_checks_before_publication():
    case = sample()
    known_at = at("2025-11-27T17:07")
    late = replace(case, zone=replace(case.zone, known_at=known_at))
    prefix = assess_near_recovery(late, (), as_of=known_at)
    assert prefix["status"] == "INDETERMINATE"
    assert all(value is None for value in prefix["checks"].values())
    assert prefix["after"] is None
    seen = assess_near_recovery(late, (), as_of=known_at + US)
    assert seen["checks"]["break_known_before_shape"] is True
    assert seen["checks"]["plan_known_before_shape"] is False
    assert seen["status"] == "NOT_PERMITTED"
    assert seen["after"] is None
