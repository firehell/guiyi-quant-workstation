"""Compare staged protection against a shared six-contract quote boundary and recovery controls."""

import argparse
from datetime import datetime
from decimal import Decimal
from itertools import product
from pathlib import Path

from guiyi_quant.lms405 import Position
from lms405_counter_m_lot_roles import exposure
from lms405_first_night_pa import REFERENCE, REFERENCE_HASH
from lms405_portfolio_replay import ARCHIVE, CONTRACTS, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_quantity_stages import LOCATION, LOCATION_SHA
from lms405_public_plan_roles import load_source
from lms405_pvc_recovery_carry import SOURCES as PVC_SOURCES
from lms405_right_side_study import ONE, US
from lms405_sh_cycle_permissions import study as sh_cycle
from lms405_sh_cycle_permissions import LIFECYCLE, LIFECYCLE_SHA, NEXT_NIGHT, NEXT_NIGHT_SHA, SH, SH_SHA
from lms405_staged_protection_permissions import STAGES, STAGES_SHA, allowed_first_stage, project_stage
from lms_near405_replay import encoded, sha

VERSION = "lms405-portfolio-staged-protection-v1"
PVC = Path("output/lms405-explicit-near-recovery-20261126/final.json")
PVC_SHA = "53689f072b7a230daa6bb455c5f7d6fedaa938f79bf3a044093a67ea4678f1a3"
PVC_SOURCE = "S5292358960155373"
SH_CYCLE_SHA = "f69045985afb4b72644c450627ba269eb35c3153361d6138964ffe8c022920a6"
FIRST_NIGHT_LOCATION = {
    "RU2701": "ru_first_night",
    "SA2701": "sa_first_night",
    "SH2701": "sh",
}


def common_quote_ends(rows):
    """Intersect actual single-row quote candidates for this one image."""
    return sorted(set.intersection(*(set(row["individual_quote_ends"]) for row in rows.values()))) if rows else []


def tape(seed, early_lots, *, plan, touch, confirm, cutoff, early, normal):
    """Model specified fixture quantities and separate approvals under a fixed original leg."""
    if not plan["available_at"] < touch or not touch + 6 * US < confirm or not confirm + 6 * US < cutoff:
        raise ValueError("PORTFOLIO_STAGE_CLOCK_INVALID")
    if seed.long or not isinstance(early_lots, int) or not 0 <= early_lots <= seed.short:
        raise ValueError("PORTFOLIO_STAGE_SIZE_INVALID")
    position, events, checks = seed, [], {}
    for stage, price, requested, approved in (
        ("EARLY_PROTECTION", touch, Decimal(early_lots), early),
        ("AFTER_CONFIRMATION", confirm, None, normal),
    ):
        amount = requested if requested is not None else seed.short - position.long
        if not amount:
            continue
        fixture = dict(trigger_at=price + 2 * US, approved_at=price + 4 * US, approved=True) if approved else {}
        scope = dict(stage=stage, source=plan["source_url"], plan_at=plan["available_at"], price_at=price)
        after, check = project_stage(position, amount, **scope, **fixture, as_of=price + 6 * US)
        if approved:
            at = check["fixture_effective_at"]
            unseen, _ = project_stage(position, amount, **scope, **fixture, as_of=at - US)
            if unseen != position or not at < cutoff or after != Position(
                seed.contract, position.long + amount, seed.short,
            ):
                raise ValueError("PORTFOLIO_STAGE_PERMISSION_OUT_OF_SEQUENCE")
            events.append(dict(stage=stage, effective_at=at, amount=amount, after=after))
        checks[stage] = check["status"]
        position = after
    return dict(events=events, checks=checks, terminal=exposure(position))


def compare_stages(contract, row, image, quote_ends, old, sources):
    snap, ref = row["snapshot"], row["policies"]["ADD_15M:SHAPE_CONTACT"]
    plan = load_source(sources, row["source"]["id"])
    if (plan["archive_sha256"] != row["source"]["archive_sha256"] or snap["image"] != image
            or plan["published_at"] != row["source"]["published_at"]):
        raise ValueError("PORTFOLIO_STAGE_SOURCE_OR_POSITION_CHANGED")
    if (snap["quantity"] != old["original_short"]["quantity"]
            or snap["quantity"] != old["displayed_long"]["quantity"]
            or snap["shown_as_today_quantity"] != old["displayed_long"]["today_quantity"]
            or Decimal(snap["display_average"]) != Decimal(old["displayed_long"]["opening_average"])):
        raise ValueError("PORTFOLIO_STAGE_LEG_CHANGED")
    lots = snap["quantity"]
    lo, hi = snap["displayed_tick_total_interval"]
    windows = {item["quote_end"]: item for item in ref["quantities"]["WHOLE_MINUTES_ONLY"]}
    possible = {end: allowed_first_stage(windows[end], lots, range(lo, hi + 1)) for end in quote_ends}
    compatible = sorted(set.intersection(*(set(counts) for counts in possible.values())))
    cut, touch, confirm = map(datetime.fromisoformat, (
        min(quote_ends), row["first_touch_minute"]["end"], ref["earliest"]["confirmed_at"],
    ))
    seed = Position(contract, short=Decimal(lots))
    frame = dict(plan=plan | {"available_at": datetime.fromisoformat(plan["published_at"]) + ONE},
                 touch=touch, confirm=confirm, cutoff=cut)
    branches = {
        "public_without_permission": tape(seed, lots, **frame, early=False, normal=False),
        "after_confirmation_only": tape(seed, 0, **frame, early=False, normal=True),
        "staged_no_topup": {size: tape(seed, size, **frame, early=True, normal=False) for size in compatible},
        "staged_independent_topup": {size: tape(seed, size, **frame, early=True, normal=True) for size in compatible},
    }
    return dict(status="STAGE_COMPARISON", plan=row["source"], seed=exposure(seed), whole_long=lots, touch_at=touch,
                confirmation_at=confirm, confirmation_variant=ref["earliest"]["variant"],
                early_lots_by_quote=possible, compatible_early_lots=compatible,
                confirmation_only_price_compatible=0 in compatible, branches=branches)


def exposure_bounds(covered, *, quote_ends):
    """Summarize only the price-compatible joint hypotheses for the admitted subset."""
    paths = [tuple(row["branches"]["staged_independent_topup"].values()) for row in covered.values()]
    joint_paths = list(product(*paths))
    cuts = {datetime.fromisoformat(end) for end in quote_ends}
    for variants in paths:
        cuts.update(event["effective_at"] + US for tape in variants for event in tape["events"])
    total_short = sum(row["seed"]["short"] for row in covered.values())
    rows = []
    for cutoff in sorted(cuts):
        def long_lots(trace):
            return sum((step["amount"] for step in trace["events"] if step["effective_at"] < cutoff), Decimal(0))

        longs = [sum(map(long_lots, tapes)) for tapes in joint_paths]
        if not longs:
            continue
        normal_long = sum(long_lots(row["branches"]["after_confirmation_only"]) for row in covered.values())
        low, high = min(longs), max(longs)
        rows.append(dict(as_of=cutoff, protective_lots_range=[low, high],
                         abs_net_lots_range=[total_short - high, total_short - low],
                         gross_lots_range=[total_short + low, total_short + high],
                         confirmation_only_protective_lots=normal_long))
    return dict(scope=list(covered), number_of_compatible_joint_sizes=len(joint_paths), initial_short_lots=total_short,
                joint_sizes_with_two_nonzero_stages_in_every_contract=sum(
                    all(len(tape["events"]) == 2 for tape in paths) for paths in joint_paths
                ),
                comparable_as_money_or_portfolio_risk=False, rows=rows)


def recovery_controls(sources):
    cycle = sh_cycle(verified_json(LIFECYCLE, LIFECYCLE_SHA), verified_json(SH, SH_SHA),
                     verified_json(NEXT_NIGHT, NEXT_NIGHT_SHA))
    if sha(encoded(cycle).encode()) != SH_CYCLE_SHA:
        raise ValueError("PORTFOLIO_STAGE_SH_CONTROL_DIVERGED")
    replacement = {
        name: dict(
            recovery_fixture=row["recovery_fixture"], protection_fixture=row["protection_fixture"],
            recovery_candidate_at=row["recovery_candidate"]["confirmed_at"],
            protection_candidate_at=row["protection_candidate"]["confirmed_at"],
            protection_touch_known_at=row["protection_candidate"]["touch_known_at"],
            end=row["trace"][-1], matches_new_long_quantity_constraint=row["matches_new_long_quantity_constraint"],
        ) for name, row in cycle["scenarios"].items()
    }
    pvc = verified_json(PVC, PVC_SHA)["pvc_known_unreleased"]
    pvc_source = load_source(sources, PVC_SOURCE)
    if (pvc_source["archive_sha256"] != PVC_SOURCES[PVC_SOURCE][1] or not pvc
            or any(row["result"]["after"] is not None or row["result"]["checks"]["explicit_near_role"] is not False
                   for row in pvc)):
        raise ValueError("PORTFOLIO_STAGE_PVC_NEGATIVE_DIVERGED")
    return dict(
        SH2701=dict(day_trading_date=cycle["day_trading_date"], night_trading_date=cycle["night_trading_date"],
                    initial=cycle["seed"], account_continuity=cycle["account_continuity"],
                    unshown_close_long=cycle["unshown_close_long"], assumption=cycle["assumption"], cases=replacement),
        V2609=dict(window="2026-04-27", tested=len(pvc), released=0,
                   research_rejection_includes="TARGET_ROLE_WITHOUT_RECOVERY_PERMISSION",
                   author_reason=None, source=pvc_source, cases=pvc),
    )


def study():
    clock = verified_json(REFERENCE, REFERENCE_HASH)
    stage = verified_json(STAGES, STAGES_SHA)
    location = verified_json(LOCATION, LOCATION_SHA)["cases"]
    next_night = verified_json(NEXT_NIGHT, NEXT_NIGHT_SHA)["cases"]
    image = clock["photo"]
    sources = input_sources()
    if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
        raise ValueError("PORTFOLIO_STAGE_FIRST_NIGHT_IMAGE_CHANGED")
    common = common_quote_ends(clock["cases"])
    if not common or not set(common) <= set(stage["shared_quote_minute_ends"]):
        raise ValueError("PORTFOLIO_STAGE_NO_SHARED_QUOTE_BOUNDARY")
    cases, covered = {}, {}
    for contract in CONTRACTS:
        later = next_night[contract]
        comparison = dict(status="NO_ROW_IN_THIS_405_SNAPSHOT", compatible_early_lots=None)
        if contract in stage["cases"]:
            comparison = compare_stages(contract, stage["cases"][contract], image, common,
                                        clock["cases"][contract], sources)
            covered[contract] = comparison
        elif contract in clock["cases"]:
            original = clock["cases"][contract]
            coverage = location.get(FIRST_NIGHT_LOCATION.get(contract), {}).get("by_rule")
            comparison = dict(status="NO_BOUND_PROTECTION_RANGE" if original["protection_band"] is None
                              else "NO_IN_BAND_OR_CONTACT_SHAPE_CANDIDATE",
                              visible_new_long=original["displayed_long"],
                              original_short_assumption=original["original_short"],
                              clock_diagnostics=coverage, compatible_early_lots=None)
            if original["protection_band"] and (
                coverage is None or any(coverage[rule]["candidates"] for rule in (
                    "confirmation_close_inside", "shape_range_contact",
                ))
            ):
                raise ValueError("PORTFOLIO_STAGE_OTHER_CANDIDATE_NOT_ASSESSED")
        cases[contract] = dict(first_night=comparison, october27_close_to_night=dict(
            status=later["status"], visible_close=later.get("close_display"), visible_night=later.get("displayed_night"),
        ))
    return dict(
        version=VERSION, source=clock["photo_source"], image=image, cases=cases, simultaneous_quote_ends=common,
        pair_comparison_extra_quote_ends=sorted(set(stage["shared_quote_minute_ends"]) - set(common)),
        simultaneous_capture_verified=False, final_fixture_comparison=exposure_bounds(covered, quote_ends=common),
        separately_timed_recovery_controls=recovery_controls(sources),
        references=dict(first_night=REFERENCE_HASH, stage=STAGES_SHA, location=LOCATION_SHA,
                        next_night=NEXT_NIGHT_SHA, sh_cycle=SH_CYCLE_SHA, pvc=PVC_SHA),
        first_stage_quantities_filtered_retrospectively=True, positive_permissions_are_test_fixtures=True,
        seed_is_hypothetical_fixed_original_short_from_later_snapshot=True,
        fixture_early_change_is_at_hypothetical_approval_not_observed_formation_time=True,
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PORTFOLIO_STAGE_OUTPUT_EXISTS")
    try:
        result = study()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('PORTFOLIO_STAGE_') and code.isidentifier() else 'PORTFOLIO_STAGE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
