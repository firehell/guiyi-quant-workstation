from decimal import Decimal

from lms405_portfolio_role_replay import OIL, SODA, oil_exit_projections, soda_projection
from lms405_right_side_study import ONE, US, at

from guiyi_quant.lms405 import Zone
from guiyi_quant.lms405.public_plan_handoff import Publication


def test_oil_identical_visible_legs_require_different_scoped_actions():
    known = at("2026-10-27T22:13")
    quantity = Decimal(40)
    rows = oil_exit_projections(known, quantity, quantity, "archived night snapshot")
    public = [row["result"] for row in rows if row["mode"] == "OI_PUBLIC_ROLE_HYPOTHESIS"]
    at_permission = [row["result"] for row in rows if row["mode"] == "OI_TEST_BEFORE_PERMISSION"]
    fixture = [row["result"] for row in rows if row["mode"] == "OI_TEST_ROLE_EXIT"]
    assert len(public) == len(at_permission) == len(fixture) == 2
    assert all(row["after"] is None for row in public + at_permission)
    assert all(row["unknown"] == ["permission_after_trigger_known", "specific_permission"] for row in at_permission)
    assert all(row["approval_kind"] is None for row in at_permission)
    assert at_permission[0]["checks"]["ORIGINAL_PLAN_VALID"] is True
    assert at_permission[1]["checks"]["COUNTER_M_EXIT_PERMISSION"] is True
    unlock, exit_m = fixture
    assert unlock["approval_kind"] == exit_m["approval_kind"] == "TEST_FIXTURE"
    assert unlock["before"]["aggregate"] == exit_m["before"]["aggregate"] == dict(
        contract=OIL, long=quantity, short=quantity,
    )
    assert unlock["after"]["aggregate"] == exit_m["after"]["aggregate"] == dict(
        contract=OIL, long=0, short=quantity,
    )
    assert unlock["scope"] != exit_m["scope"]
    assert (unlock["requested_action"], exit_m["requested_action"]) == ("UNLOCK_SHORT", "EXIT_LONG")
    assert unlock["after"]["counter_m"] == unlock["before"]["counter_m"]
    assert exit_m["after"]["trend"] == exit_m["before"]["trend"]


def test_soda_contact_alone_keeps_old_short_and_fixture_adds_only_protection():
    contact = at("2026-10-22T21:01") + US
    source_at = at("2026-10-22T18:18")
    zone = Zone("A1", SODA, Decimal(931), Decimal(936), source_at + ONE, "archived plan")
    publication = Publication("A1", SODA, source_at, zone.known_at, zone.source, zone)
    result = soda_projection(publication, contact, contact + ONE, 20)
    public = result["terminal"]["public"]
    fixture = result["terminal"]["fixture"]
    assert result["public"][-1]["changed"] is False
    assert result["fixture"][-1]["changed"] is True
    assert public["position"] == dict(contract=SODA, long=0, short=20)
    assert fixture["position"] == dict(contract=SODA, long=20, short=20)
    assert public["protected_long"] == 0
    assert fixture["protected_long"] == 20
    assert result["restart_checks"] == dict(public=6, fixture=6)
