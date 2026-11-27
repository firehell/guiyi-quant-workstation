"""Replay early protection and competing leg roles on the nine-contract research timeline."""

import argparse
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.public_plan_handoff import PlanAction, assess_plan_action
from guiyi_quant.lms405.task_roles import ROUTES, TaskBook, assess_task_action
from lms405_portfolio_lifecycle import candidate, published, run_mode, seed
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_pta_public_plan_handoff import study as study_pta_handoff
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US
from lms_near405_replay import encoded, sha

VERSION = "lms405-portfolio-role-replay-v1"
SODA = "SA2701"
OIL = "OI2701"
SODA_PHOTO = "WRnTlEfj1t"
OIL_PHOTO = "WRoEvasxQR"
REFS = {
    "portfolio": ("lms405-pvc-portfolio-lifecycle-20261126/reviewed-a.json",
                  "32b4e94085b0323d44f4dd21c611b810371454771814d9dc3dd15027ebead8a3"),
    "soda": ("lms405-pa-signal-deadline-20261126/reviewed-a.json",
             "077ce7aabb1a3e196b6c1807ca467eb2c36edcc74bf2d46a5e45e0b1320f8886"),
    "oil": ("lms405-oi-ru-signal-deadlines-20261126/reviewed-a.json",
            "6ebb8708b1058b68861f5ce38ecc851767f048381eaf8edabca6803f7be1a4fe"),
    "soda_later": ("lms-fg-sa-oct-20261125/sa-paired-final.json",
                   "505a0c14baea7759c629be45d9fac1fd1ae216f3ba1286214a7e8da41f97f952"),
}


def photo_source(index, source_id, image):
    source = load_source(index, source_id)
    source_text = (ARCHIVE.parent / source["archive_path"]).read_text(encoding="utf-8")
    if (Path(image["path"]).name not in source_text
            or sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]):
        raise ValueError("PORTFOLIO_ROLE_PHOTO_IDENTITY_CHANGED")
    return source


def photo_clock(source):
    # The archive provides the displayed minute rather than exact publication seconds.
    return datetime.fromisoformat(source["published_at"]) + ONE


def soda_projection(plan, contact, cutoff, quantity):
    root = seed("SA2701:22N_EARLY_PROTECTION", SODA, contact - US, short=quantity)
    attempt = candidate("SA:EARLY_PROTECTION_FIXTURE", root, "PROTECT_ADD", quantity, contact, plan=plan)
    factual = replace(attempt, trigger=None, approval=None)
    public, public_state, public_checks = run_mode((root,), (factual,), (plan,), cutoff, allow=False)
    fixture, fixture_state, fixture_checks = run_mode((root,), (attempt,), (plan,), cutoff, allow=True)
    return dict(episode=root.episode, assumed_seed_is_historical=False, public=public, fixture=fixture,
                terminal=dict(public=public_state[root.episode], fixture=fixture_state[root.episode]),
                restart_checks=dict(public=public_checks, fixture=fixture_checks))


def soda_case(index, report, later):
    case = report["cases"][SODA]
    quantity = case["displayed"]["quantity"]
    window = case["windows"]["COMPLETE_MINUTES_BEFORE_QUOTE_MINUTE"]["PROTECTION_BAND_ONLY"]
    gates = window["by_gate"]
    first, late = (gates[key] for key in ("protection_contact_completed", "fresh_inside_minute_far_excursion"))
    contact = datetime.fromisoformat(first["known_at"])
    limit = datetime.fromisoformat(window["latest_strict_signal_knowledge_bound_exclusive"])
    late_known = datetime.fromisoformat(late["known_at"])
    cutoff = datetime.fromisoformat(window["quote_end"])
    disclosed = photo_clock(photo_source(index, SODA_PHOTO, report["photo"]))
    plan = published(SODA, "A5356884629782554", case["plan"], tuple(case["band"]))
    if not (plan.known_at < contact < limit < late_known < cutoff < disclosed
            and quantity == case["displayed"]["today_quantity"]
            and first["whole_leg_with_later_prices"] is True and late["whole_leg_with_later_prices"] is False
            and not any(case["geometry_candidates"]["COMPLETE_MINUTES_BEFORE_QUOTE_MINUTE"].values())):
        raise ValueError("PORTFOLIO_ROLE_SODA_BOUND_CHANGED")
    replay = soda_projection(plan, contact, cutoff, quantity)
    event = dict(at=disclosed + US, mode="SA_RETROSPECTIVE_CONDITIONAL_REPLAY", contract=SODA, episode=replay["episode"],
                 source=SODA_PHOTO, historical_clock=contact, scenario=replay, author_action_at=None,
                 historical_plan_revision_verified=report["historical_plan_revision_verified"])
    followups = {}
    for side, fields in (
        ("long", ("after_first_fast_keybar", "after_first_slow_keybar")),
        ("short", ("after_or_during_first_return_to_957",)),
    ):
        followups[side] = {
            key: {name: row[name] for name in ("start", "range", "average_range_compatible")}
            for key in fields if (row := later[side]["price_checks"][key]) is not None
        }
        if len(followups[side]) != len(fields) or any(row["average_range_compatible"] for row in followups[side].values()):
            raise ValueError("PORTFOLIO_ROLE_SODA_LATER_PRICE_CHANGED")
    return event, dict(
        displayed=case["displayed"], quote_minute_end=cutoff, last_complete_price_bar_end=cutoff - ONE,
        strict_signal_bound_exclusive=limit,
        early_contact=first, late_far_excursion=late, later_independent_price_checks=followups,
        later_checks_linked_as_account_transitions=False, original_trigger_identified=False,
    )


def oil_exit_projections(known_at, long_lots, short_lots, source):
    """Keep the two hypotheses separate even though their visible endpoints coincide."""
    options = (
        (TaskBook(Position(OIL, long_lots, short_lots), Position(OIL), "SHORT", "OI:TREND_LOCKED",
                  "OI:M_UNUSED", known_at), "RESUME_TREND"),
        (TaskBook(Position(OIL, short=short_lots), Position(OIL, long_lots), "SHORT", "OI:TREND_OPEN",
                  "OI:M_LONG", known_at), "EXIT_COUNTER_M"),
    )
    events = []
    for book, route in options:
        scope = dict(source=source, source_available_at=known_at, version_405=True)
        public_at = known_at + US
        public = assess_task_action(book, route, long_lots, (), as_of=public_at, **scope)
        fixture_scope = scope | dict(source=f"TEST_FIXTURE_OI:{route}")
        case_id = book.scope(route, long_lots, **fixture_scope)
        signal_at = known_at + 2 * US
        evidence_at = known_at + 3 * US
        approval_at = known_at + 5 * US
        position, plan_or_task_permission, signal = ROUTES[route]
        facts = (
            Condition(position, case_id, OIL, True, public_at, signal_at, "TEST_FIXTURE_POSITION", "EVENT_TIME"),
            Condition(signal, case_id, OIL, True, signal_at, evidence_at, "TEST_FIXTURE_SIGNAL", "EVENT_TIME"),
            Condition(plan_or_task_permission, case_id, OIL, True, public_at, evidence_at,
                      "TEST_FIXTURE_TASK_CONDITION", "EVENT_TIME"),
        )
        task = assess_task_action(book, route, long_lots, facts, as_of=approval_at, **fixture_scope)
        selected = book.trend if route == "RESUME_TREND" else book.counter_m
        request = PlanAction(selected, case_id, known_at, Action(task["requested_action"], long_lots))
        trigger = Condition("TRIGGER", request.scope, OIL, True, signal_at, evidence_at,
                            "TEST_FIXTURE_SIGNAL", "EVENT_TIME")
        approval = HandoffConfirmation(request.confirmation_scope(trigger), f"TEST_FIXTURE_OI_APPROVAL:{route}",
                                       True, known_at + 4 * US, approval_at, "TEST_FIXTURE")
        ready_at = approval_at + US
        before_gate = assess_plan_action(request, (), as_of=approval_at, trigger=trigger, approval=approval,
                                         allow_test_fixture=True)
        after_gate = assess_plan_action(request, (), as_of=ready_at, trigger=trigger, approval=approval,
                                        allow_test_fixture=True)
        task_key = "trend" if route == "RESUME_TREND" else "counter_m"
        if (public["after"] is not None or task["after"] is None or before_gate["after"] is not None
                or after_gate["after"] is None
                or any(Decimal(after_gate["after"][side]) != task["after"][task_key][side]
                       for side in ("long", "short"))):
            raise ValueError("PORTFOLIO_ROLE_OIL_SCOPE_CHANGED")
        same_time = task | dict(status=before_gate["status"], after=None, unknown=before_gate["unknown"],
                                confirmation_checks=before_gate["checks"], approval_kind=None)
        after = task | dict(confirmation_checks=after_gate["checks"], approval_kind=after_gate["approval_kind"])
        episode = f"{OIL}:27N_{route}"
        base = dict(contract=OIL, episode=episode, source=OIL_PHOTO, author_action_at=None)
        events.extend((
            base | dict(at=public_at, mode="OI_PUBLIC_ROLE_HYPOTHESIS", result=public),
            base | dict(at=approval_at, mode="OI_TEST_BEFORE_PERMISSION", result=same_time),
            base | dict(at=ready_at, mode="OI_TEST_ROLE_EXIT", result=after),
        ))
    return events


def oil_case(index, report):
    case = report["cases"][OIL]
    long = case["new_long_display"]["later_leg"]
    short = case["old_short_retention"]
    plan = published(OIL, "A5358686423089344", case["plan"])
    snapshot = photo_source(index, OIL_PHOTO, report["source"]["image"])
    disclosed = photo_clock(snapshot)
    if not (plan.known_at < disclosed and case["role"] == "RANGE_DIVIDER"
            and snapshot["published_at"] == report["source"]["published_at"]
            and snapshot["source_url"] == report["source"]["source_url"]
            and short["retained"] == [long["quantity"]]
            and case["new_long_display"]["after"] == short["after"] == OIL_PHOTO):
        raise ValueError("PORTFOLIO_ROLE_OIL_INPUT_CHANGED")
    events = oil_exit_projections(disclosed, Decimal(long["quantity"]), Decimal(short["later_leg"]["quantity"]),
                                 report["source"]["source_url"])
    return events, dict(divider=case["band"], divider_role=case["role"], plan_source=plan.source,
                        old_short_retention=short["retained"], new_long_display=long,
                        hypotheses_mutually_exclusive=True, role_identified=False,
                        protection_band=None, actual_time=None)


def plan_admission(oil_events, oil, soda_path, soda, pta):
    """Expose the evidence boundary for each route before a multi-session replay."""
    oil_routes = {}
    for event in oil_events:
        action = event["result"]["requested_action"]
        route = oil_routes.setdefault(action, {})
        route[event["mode"]] = event["result"]

    observed = soda_path["long"]["observed"]
    next_short, repeated_short = (soda_path["short"]["observed"][key] for key in ("WRov1j6e10", "WRozNbg3en"))
    windows = [
        observed["morning_short"] | {"side": "SHORT"},
        observed["night_long"] | {"side": "LONG"},
        next_short | {"source": "WRov1j6e10"},
    ]
    days = [row["assumed_trading_day"] for row in windows]
    if (days != sorted(set(days)) or repeated_short != next_short
            or any(row["today_quantity"] != row["quantity"] for row in windows)
            or observed["same_account_chain"] is not None or soda_path["short"]["same_account_chain"] is not None):
        raise ValueError("PORTFOLIO_ROLE_SODA_CROSS_DAY_SCOPE_CHANGED")
    return {
        OIL: dict(display=oil, routes=oil_routes, order_or_position_detail_for_role_required=True),
        SODA: dict(observed_legs=windows, repeated_short_source="WRozNbg3en",
                   post_confirmation_price_checks=soda["later_independent_price_checks"],
                   omitted_side=None, account_continuity=None, cross_day_close_or_reverse=None),
        pta["contract"]: dict(
            public=pta["historical_assessments"], test=pta["test_fixtures"], carry=pta["carry"],
            published_revisions={key: value["known_at"] for key, value in pta["publication_timeline"].items()},
            last_archived_publication_known_at=pta["last_archived_publication_known_at"],
            author_restart_at=pta["author_restart_at"], author_protection_or_exit_at=pta["author_protection_or_exit_at"],
        ),
    }


def study(*, compare_plan_admission=False):
    refs = {key: verified_json(Path("output") / path, digest) for key, (path, digest) in REFS.items()}
    base = refs["portfolio"]
    index = input_sources()
    soda, soda_report = soda_case(index, refs["soda"], refs["soda_later"])
    oil, oil_report = oil_case(index, refs["oil"])
    contracts = base["contracts"] | {
        SODA: base["contracts"][SODA] | dict(conditional_episodes=[soda["episode"]]),
        OIL: base["contracts"][OIL] | dict(conditional_episodes=sorted({row["episode"] for row in oil})),
    }
    timeline = sorted((*base["timeline"], soda, *oil), key=lambda row: (
        datetime.fromisoformat(str(row["at"])), row["mode"], row.get("episode", ""),
    ))
    report = base | dict(version=VERSION, contracts=contracts, timeline=timeline, soda=soda_report, oil=oil_report,
                         references={key: digest for key, (_, digest) in REFS.items()})
    if compare_plan_admission:
        report["plan_admission"] = plan_admission(oil, oil_report, refs["soda_later"], soda_report, study_pta_handoff())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare-plan-admission", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PORTFOLIO_ROLE_OUTPUT_EXISTS")
    try:
        report = encoded(study(compare_plan_admission=args.compare_plan_admission))
        with args.output.open("x", encoding="utf-8") as output:
            output.write(report)
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('PORTFOLIO_ROLE_') and code.isidentifier() else 'PORTFOLIO_ROLE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
