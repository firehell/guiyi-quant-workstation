"""Replay TA2701 public-region suspensions and an explicitly hypothetical restart."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, Zone
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.public_plan_handoff import PlanAction, Publication, assess_plan_action
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_pta_pause_carry import MORNING
from lms405_pta_pause_entry import CONTRACT, HOLDINGS, PLAN
from lms405_pta_pause_scopes import FROZEN_OCT, source_clock
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US
from lms_near405_replay import encoded, sha

VERSION = "lms405-pta-public-plan-handoff-v1"
PAUSED = {
    "A5355789916438626": "7add28732086dc5411abdd81e96355ba67bd1d21e5b9f7fda283a8873326b0f2",
    "A5356507360788540": "e5be3a3a7feec88c567488d29fadee87bb75e5d9cb60913e73b822cf4ee2b53b",
    "A5356884885635211": "a6f1c62e08795e6e20852aecb3e8b2899dc6b7bacb1893471531d7f97d58f95c",
    PLAN: "9185db35e8e033c825e0dac5ff5ac7f1c7d22438cc6223326fc6adc0f459f3b7",
    "A5358325972992140": "e175b94b08a52845062bed5dfbf6eedf26afd1c619e3b1e854e7a6aa9bf17140",
    "A5358686695981271": "d91159c7ff383371bf49968b1e8fc93a90df8deace577cc58e88a1469a34f3e7",
}


def action(seed, position_revision, known_at, kind, lots=1, public_plan=None):
    return PlanAction(seed, position_revision, known_at, Action(kind, Decimal(lots)), public_plan)


def fixture_facts(request, trigger_at, *, approved=True):
    trigger = Condition("TRIGGER", request.scope, CONTRACT, True, trigger_at, trigger_at + US, "TEST_FIXTURE_TRIGGER",
                        "EVENT_TIME")
    return (
        trigger,
        HandoffConfirmation(request.confirmation_scope(trigger), "TEST_FIXTURE_PERMISSION", approved, trigger_at + 2 * US,
                            trigger_at + 3 * US, "TEST_FIXTURE"),
    )


def checked(request, publications, as_of, *, fixture=(None, None)):
    trigger, approval = fixture
    result = assess_plan_action(request, publications, as_of=as_of, trigger=trigger, approval=approval,
                                allow_test_fixture=approval is not None)
    visible = tuple(row for row in publications if row.known_at < as_of)
    scoped = dict(
        trigger=trigger if trigger is not None and trigger.known_at < as_of else None,
        approval=approval if approval is not None and approval.known_at < as_of else None,
    )
    if result != assess_plan_action(request, visible, as_of=as_of, **scoped, allow_test_fixture=approval is not None):
        raise ValueError("PTA_HANDOFF_PREFIX_DIVERGED")
    return result


def study():
    carry = verified_json(*FROZEN_OCT)
    index = input_sources()
    sources = {key: load_source(index, key) for key in (*PAUSED, HOLDINGS, MORNING)}
    if any(sources[key]["archive_sha256"] != fingerprint for key, fingerprint in PAUSED.items()):
        raise ValueError("PTA_HANDOFF_PAUSED_SOURCE_CHANGED")
    if any(carry["sources"][key] != sources[key] for key in (PLAN, HOLDINGS, MORNING)):
        raise ValueError("PTA_HANDOFF_CARRY_SOURCE_CHANGED")
    if any(sha((ARCHIVE.parent / path).read_bytes()) != fingerprint
           for path, fingerprint in carry["image_sha256"].items()):
        raise ValueError("PTA_HANDOFF_CARRY_IMAGE_CHANGED")
    publications = tuple(sorted((Publication(key, CONTRACT, datetime.fromisoformat(sources[key]["published_at"]),
                                             source_clock(sources[key]), sources[key]["source_url"], None)
                                 for key in PAUSED), key=lambda row: row.known_at))
    night, morning = (source_clock(sources[key]) for key in (HOLDINGS, MORNING))
    if not publications[3].known_at < night < morning < publications[-2].known_at < publications[-1].known_at:
        raise ValueError("PTA_HANDOFF_SOURCE_ORDER_CHANGED")
    quantity = carry["morning_long"]["quantity"]
    retained = min(bounds["minimum_retained_across_pairs"] for scope in (
        carry["retention"], carry["publication_minute_sensitivity"]["retention"],
    ) for bounds in scope.values())
    seed = Position(CONTRACT, long=Decimal(quantity))
    flat = Position(CONTRACT)
    candidate_open = action(flat, "TEST_FIXTURE_FLAT", night, "ENTER_LONG", public_plan=publications[3])
    independent_open = PlanAction(flat, "TEST_FIXTURE_FLAT", night, Action("ENTER_LONG", Decimal(1)),
                                  independent_entry=True)
    candidate_exit = action(seed, HOLDINGS, night, "CLEAR", quantity)
    candidate_lock = action(seed, HOLDINGS, night, "LOCK", quantity)
    pending = night + ONE
    historical = {name: checked(request, publications, instant)
                  for name, request, instant in (
                      ("public_entry_during_pause", candidate_open, pending),
                      ("independent_entry_during_pause", independent_open, pending),
                      ("protect_prior_long_during_pause", candidate_lock, pending),
                      ("clear_prior_long_during_pause", candidate_exit, pending),
                      ("prior_long_clear_by_morning_under_public_facts", candidate_exit, morning + US),
                  )}
    timeline_request = action(flat, "TEST_FIXTURE_FLAT", publications[0].known_at - ONE, "ENTER_LONG",
                              public_plan=publications[3])
    timeline = {item.revision: dict(
        known_at=item.known_at,
        at_publication_boundary=checked(timeline_request, publications, item.known_at),
        after_publication_boundary=checked(timeline_request, publications, item.known_at + US),
    ) for item in publications}
    future_at = publications[-1].known_at + ONE
    revision = "TEST_FIXTURE_RESTORED_PUBLIC_ZONE"
    placeholder_source = "TEST_FIXTURE_NOT_AN_AUTHOR_ZONE"
    zone = Zone(revision, CONTRACT, Decimal(100), Decimal(110), future_at, placeholder_source)
    restored = Publication(revision, CONTRACT, future_at, future_at, placeholder_source, zone)
    extended = publications + (restored,)
    reentry = action(flat, "TEST_FIXTURE_FLAT", morning, "REENTER_LONG", public_plan=restored)
    fresh = fixture_facts(reentry, future_at + ONE)
    stale = fixture_facts(reentry, future_at - ONE)
    after_permission = fresh[-1].known_at + US
    fixtures = dict(
        public_entry_during_pause_with_separate_test_facts=checked(
            candidate_open, publications, pending + ONE, fixture=fixture_facts(candidate_open, pending),
        ),
        independent_entry_during_pause_with_separate_test_facts=checked(
            independent_open, publications, pending + ONE, fixture=fixture_facts(independent_open, pending),
        ),
        protect_old_long_during_pause=checked(candidate_lock, publications, pending + ONE,
                                             fixture=fixture_facts(candidate_lock, pending)),
        clear_old_long_during_pause=checked(candidate_exit, publications, pending + ONE,
                                           fixture=fixture_facts(candidate_exit, pending)),
        restart_at_publication_clock=checked(reentry, extended, future_at),
        restart_plan_only=checked(reentry, extended, future_at + US),
        restart_with_stale_trigger=checked(reentry, extended, after_permission, fixture=stale),
        restart_at_permission_clock=checked(reentry, extended, fresh[-1].known_at, fixture=fresh),
        restart_with_new_trigger_and_permission=checked(reentry, extended, after_permission, fixture=fresh),
    )
    return dict(
        version=VERSION, contract=CONTRACT, sources=sources, publication_timeline=timeline,
        historical_assessments=historical, test_fixtures=fixtures,
        carry=dict(night_source=HOLDINGS, morning_source=MORNING, shown_long=quantity,
                   retained_lower_bound=retained, full_exit_and_rebuild_compatible=retained == 0,
                   retained_bound_assumes_same_account_and_quote_aligned=True, short_unknown=True,
                   no_action_preserves_research_seed_only=not any(row["after"] for row in historical.values())),
        last_archived_publication_known_at=publications[-1].known_at,
        author_restart_at=None, author_protection_or_exit_at=None,
        snapshot_continuity_verified=False, historical_plan_revision_verified=False, author_action_samples=0,
        author_match_rate=None, executable=False, fills=None, pnl=None, carry_reference_sha256=FROZEN_OCT[1],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PTA_HANDOFF_OUTPUT_EXISTS")
    try:
        result = study()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('PTA_HANDOFF_') and code.isidentifier() else 'PTA_HANDOFF_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
