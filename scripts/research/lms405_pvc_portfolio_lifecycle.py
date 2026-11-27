"""Compare PVC directional replacement and unlocked-position evidence on the portfolio tape."""

import argparse
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from lms405_iron_portfolio_lifecycle import LIFETIME_SHA as IRON_MARKET_SHA
from lms405_portfolio_lifecycle import candidate, next_cursor, published, run_mode, seed
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_pvc_recovery_carry import SOURCES as APRIL_SOURCES
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_v_exit_study import CONTRACT
from lms_near405_replay import encoded, sha

VERSION = "lms405-pvc-portfolio-lifecycle-v1"
FRONT = "WRot6yvHyS"
NIGHT = "WRov1j6e10"
PLAN = "A5358325549629506"
APRIL = "S5292358960155373"
REFS = {
    "portfolio": ("lms405-iron-portfolio-lifecycle-20261126/final-a.json",
                  "b2d4f388c019240a9ef0f8bbd6b37d12f9bec3cc87531803ede6cedc7e40504a"),
    "exit": ("lms405-v-exit-20261125/verified.json",
             "b6082e514c80036c0907d39bb2690f6c9416ba1e852beab2a7ad087f64939e58"),
    "daytime": ("lms405-v-daytime-exit-20261125/final.json",
                "18e1c1ebbc8ef71a4d9ab9f74a9ed7a76d3730d9882cb2f4eca4ce556c22aab3"),
    "recovery_negative": ("lms405-explicit-near-recovery-20261126/final.json",
                          "53689f072b7a230daa6bb455c5f7d6fedaa938f79bf3a044093a67ea4678f1a3"),
    "price": ("lms-v-ta-oct-20261125/comparison.json",
              "fcb5f1f9252afa59346910ef843e4d4ddfae682f4580b6acc13935fab22998af"),
}


def available(source):
    return datetime.fromisoformat(source["published_at"]) + ONE


def recorded_order(source_report):
    row = source_report["software_row"]
    if row["version"] is not None or row["quantity"] is not None or row["date"] is not None:
        raise ValueError("PVC_LIFECYCLE_ORDER_SCOPE_CHANGED")
    photos = source_report["report_images"]
    if set(photos) != set(row["repeated_in"]) or row["direction_closed"] != "LONG":
        raise ValueError("PVC_LIFECYCLE_ORDER_REFERENCE_INCOMPLETE")
    first = min(photos, key=lambda sid: available(source_report["sources"][sid]))
    event = dict(
        at=available(source_report["sources"][first]), mode="PVC_SOFTWARE_OBSERVATION", contract=CONTRACT,
        source=first, order={field: row.get(field) for field in (
            "displayed_time", "direction_closed", "status", "version", "date", "quantity", "price", "account",
        )}, author_trade_at=None, has_case_bound_executable_permission=False,
    )
    retrospective = dict(unique_report_count=1, other_copies=len(photos) - 1, complete_archive_context=row)
    return event, retrospective


def verify_sources(exit_report, day_report):
    index = input_sources()
    # Current archives may contain separate, later annotations. Require the
    # exact snapshots and exact strategy text used to build this experiment.
    for images in ("position_images", "report_images"):
        for row in exit_report[images].values():
            if sha(Path(row["path"]).read_bytes()) != row["sha256"]:
                raise ValueError("PVC_LIFECYCLE_IMAGE_CHANGED")
    for key in (FRONT, PLAN):
        source = load_source(index, key)
        if source != exit_report["sources"][key] or source != day_report["sources"][key]:
            raise ValueError("PVC_LIFECYCLE_ARCHIVE_CHANGED")
    april = load_source(index, APRIL)
    if april["archive_sha256"] != APRIL_SOURCES[APRIL][1]:
        raise ValueError("PVC_LIFECYCLE_APRIL_ARCHIVE_CHANGED")
    return april


def replacement_steps(before, plan, *, quantity, reduce_clock, add_clock):
    """Keep the directional tranche distinct from a protective-leg action."""
    flat_after_exit = quantity == before.position.long
    removal = candidate(f"{before.episode}:REMOVE", before, "CLEAR" if flat_after_exit else "DIRECTIONAL_LONG_REDUCE",
                        quantity, reduce_clock)
    preserved = next_cursor(removal)
    addition = candidate(f"{before.episode}:ADD", preserved, "REENTER_LONG" if flat_after_exit else "DIRECTIONAL_LONG_ADD",
                         quantity, add_clock, plan=plan)
    return removal, addition


def october_recipe(refs):
    old = refs["exit"]
    sources, obs = old["sources"], old["observations"]
    old_night, lunch = (obs[label] for label in ("first_night", "lunch"))
    if (old_night["total"], lunch["total"], old_night["today"], lunch["today"],
            old_night["opening_average"], lunch["opening_average"]) != (40, 40, 40, 40, "5117.0", "5078.4"):
        raise ValueError("PVC_LIFECYCLE_POSITION_CHANGED")
    nighttime = available(sources[NIGHT])
    morning = available(sources[obs["before_daytime_report"]["source"]])
    stop_proxy = refs["daytime"]["opposing_geometry"]["5m_to_1m"][0]
    daytime_clock = datetime.fromisoformat(stop_proxy["available_at"]) + US
    daytime = seed("V2701:26D_BEFORE_REPORT", CONTRACT, morning, long=obs["before_daytime_report"]["total"])
    day_clear = candidate("V:DAYTIME_STOP_FIXTURE", daytime, "CLEAR", 40, daytime_clock)
    if (stop_proxy["quote_pairs"]["strictly_between"] != refs["daytime"]["quote_pair_count"]
            or not daytime.at < day_clear.at < available(sources[FRONT]) < nighttime):
        raise ValueError("PVC_LIFECYCLE_DAYTIME_ORDER_CHANGED")
    zone = published(CONTRACT, PLAN, sources[PLAN], ("5045", "5074"))
    # Price breakdown supplies a repeatable *fixture clock* for reducing the
    # older directional tranche; its use as author permission is unproven.
    break_at = refs["price"]["pvc_paths"]["oct27_day"]["first_close_below_5055"]
    reduce_clock = datetime.fromisoformat(break_at) + 2 * US
    seeds, attempts, price_cases = [daytime], [day_clear], {}
    for variant, row in old["conditional_lot_analysis"]["only_add_after_first_completed_long_geometry"].items():
        add_clock = datetime.fromisoformat(row["first_signal"]["available_at"]) + US
        if not nighttime < reduce_clock < add_clock < at("2026-10-27T11:30"):
            raise ValueError("PVC_LIFECYCLE_REPLACEMENT_CLOCK_CHANGED")
        admitted = row["after_confirmation"]["possible_replaced_lots_within_envelopes"]
        for lots in (0, 14, 18, 22, 40):
            root = seed(f"V2701:{variant}:{lots}", CONTRACT, nighttime, long=40)
            seeds.append(root)
            if lots:
                attempts.extend(replacement_steps(root, zone, quantity=lots, reduce_clock=reduce_clock, add_clock=add_clock))
            price_cases[root.episode] = dict(
                replacement_lots=lots, retained_original_lots=40 - lots,
                price_necessary_condition=lots in admitted, source_clock=variant, confirmed_at=row["first_signal"]["confirmed_at"],
                opening_average_target=lunch["opening_average"],
            )
    return tuple(seeds), tuple(attempts), (zone,), price_cases


def release_contrast(iron, pvc_negative):
    """Compare price-only and scoped release evidence without promoting test permissions."""
    branches = iron["branches"]
    price_checks = ("strict_near_close", "break_known_before_shape", "confirmation_still_beyond_near")
    timing_checks = ("plan_known_before_shape", "break_started_under_plan_and_lock")
    pvc = []
    for row in pvc_negative:
        checks = row["result"]["checks"]
        price = all(checks[key] is True for key in price_checks)
        timing = all(checks[key] is True for key in timing_checks)
        role = checks["explicit_near_role"] is True
        pvc.append(dict(
            confirmed_at=row["confirmed_at"], price_only=price,
            price_with_role=price and role, price_with_plan_timing=price and timing,
            scoped_status=row["result"]["status"], failed=row["result"]["failed"],
        ))
    iron_paths = {}
    for label, row in branches.items():
        matches = row["compatible_if_same_complete_table_scope_and_quote_sync_before_quote"]
        rebuild = row["same_average_rebuild_price_sensitivity"]
        iron_paths[label] = dict(
            trigger_known_at=row["clock"], protection_ending_quantity=row["ending"]["protected_long"],
            original_short_ending_quantity=row["ending"]["position"]["short"],
            quote_count=len(row["quotes"]), compatible_by_visible_short_only=row["compatible_visible_short_before_quote"],
            compatible_if_same_complete_table_and_sync=matches,
            same_open_average_full_rebuild_compatible_quotes=None if rebuild is None else sum(rebuild.values()),
            test_permission_supplied=row["test_permission_supplied"],
        )
    return dict(
        iron=dict(contract="I2701", paths=iron_paths, actual_release_at=iron["actual_release_at"],
                  same_account_and_scope_verified=iron["close_to_night_same_scope_verified"]),
        pvc=dict(contract="V2609", author_reported_no_unlock=True, candidate_rows=pvc,
                 checks_describe_research_input_scope=True, original_plan_revision_verified=False),
        author_actions_scored=0, author_match_rate=None,
    )


def study(*, compare_releases=False):
    refs = {key: verified_json(Path("output") / path, digest) for key, (path, digest) in REFS.items()}
    base, exit_report = refs["portfolio"], refs["exit"]
    if base["bases"]["iron"] != IRON_MARKET_SHA or CONTRACT not in base["contracts"]:
        raise ValueError("PVC_LIFECYCLE_BASE_CHANGED")
    april_source = verify_sources(exit_report, refs["daytime"])
    seeds, steps, publications, by_case = october_recipe(refs)
    still_public = tuple(replace(row, trigger=None, approval=None) for row in steps)
    cutoff = at("2026-10-27T11:30")
    public, _, public_prefixes = run_mode(seeds, still_public, publications, cutoff, allow=False)
    fixture, terminal, fixture_prefixes = run_mode(seeds, steps, publications, cutoff, allow=True)
    if any(row.get("changed") for row in public) or any(
        terminal[episode]["position"]["long"] != 40 for episode in by_case
    ):
        raise ValueError("PVC_LIFECYCLE_TAPE_STATE_CHANGED")
    by_episode = defaultdict(list)
    for row in fixture:
        if row.get("changed"):
            by_episode[row["episode"]].append(row["operation"])
    by_case = {key: case | dict(operations=by_episode[key], closing_position=terminal[key]["position"])
               for key, case in by_case.items()}
    negatives = refs["recovery_negative"]["pvc_known_unreleased"]
    if not negatives or any(row["result"]["after"] is not None or row["result"]["checks"]["explicit_near_role"] is not False
                            for row in negatives):
        raise ValueError("PVC_LIFECYCLE_NEGATIVE_CHANGED")
    right = refs["price"]["pvc_paths"]["oct27_night_through_posts"]
    cross = datetime.fromisoformat(right["first_close_above_5195"])
    recorded_candidates = [datetime.fromisoformat(row[key]) for row in right["long_shapes"]
                           for key, enabled in (("first_1m_close", row["first_1m_close"] is not None),
                                                ("next_5m_at", row["next_5m_close"])) if enabled]
    right_after_break = [t for t in recorded_candidates if cross < t]
    posted_negative = dict(at=available(april_source), mode="PVC_LATER_AUTHOR_RECAP", contract="V2609",
                            source=april_source, decision_reported="NO_LONG_UNLOCK", author_event_at=None)
    software, order_context = recorded_order(exit_report)
    if not available(exit_report["sources"][FRONT]) < software["at"]:
        raise ValueError("PVC_LIFECYCLE_REPORT_ORDER_CHANGED")
    timeline = sorted([
        *base["timeline"],
        posted_negative,
        software,
        *(row | dict(mode="PVC_PUBLIC_PROJECTION") for row in public),
        *(row | dict(mode="PVC_TEST_FIXTURE") for row in fixture),
    ], key=lambda row: (datetime.fromisoformat(str(row["at"])), row["mode"], row.get("episode", "")))
    extra = {"release_contrast": release_contrast(base["iron"], negatives)} if compare_releases else {}
    return dict(
        version=VERSION, timeline=timeline,
        contracts=base["contracts"] | {CONTRACT: base["contracts"][CONTRACT] | dict(
            conditional_episodes=[row.episode for row in seeds],
            remaining_input="ACCOUNT_BINDING_QUANTITY_AND_TIMING_OF_ACTUAL_ACTIONS;ORIGINAL_VPLUS",
        )},
        pvc=dict(
            software_evidence=software, software_archive_comparison=order_context,
            daytime_author_exit=exit_report["daytime_report"],
            same_account_older_lots_remaining_by_first_night=exit_report["conditional_older_lots_remaining_at_first_night_if_same_account"],
            directional_replacement=by_case, retrospective_directional_test_case_selection=True,
            right_branch=dict(first_strict_close=cross, candidates_after=right_after_break),
            april_negative=dict(contract="V2609", published=posted_negative, earlier_case_checks=negatives,
                                used_recap_as_prior_permission=False),
            restart_checks=dict(public=public_prefixes, fixture=fixture_prefixes),
        ),
        references={key: ref[1] for key, ref in REFS.items()},
        author_actions_scored=0, author_match_rate=None, executable=False, fills=None, pnl=None, **extra,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compare-releases", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PVC_LIFECYCLE_OUTPUT_EXISTS")
    try:
        report = study(compare_releases=args.compare_releases)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(encoded(report))
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('PVC_LIFECYCLE_') and code.isidentifier() else 'PVC_LIFECYCLE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
