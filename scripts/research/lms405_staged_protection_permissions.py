"""Replay conditional staged protection with distinct early and top-up decisions."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position
from guiyi_quant.lms405.public_conditions import Condition, PublicCase, assess_case
from lms405_counter_m_lot_roles import exposure
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_quantity_stages import compatible_allocations
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US
from lms405_visible_lock_handoff import stamp
from lms_near405_replay import encoded, sha

STAGES = Path("output/lms405-protection-quantity-stages-20261126/verified-a.json")
STAGES_SHA = "ac96e3d3e36a53e2b1cc3f99419744dad2a9e5530c0c05554d24224353ea5b8b"
INTERPRETATIONS = {
    "S5287284540178482": "EARLY_LOCK_REPORTED_AFTER_STRONG_SIDE_PROGRESS",
    "S5305666088472874": "ADVANCE_BAND_AND_15M_REVERSE_SIGNAL_OPTION",
    "S5321717736278116": "AUTHOR_DIRECTS_REVERSE_VPLUS_SEARCH_BEFORE_OR_INSIDE_PROTECTION_BAND",
    "S5338740245135941": "RESISTANCE_PROMOTED_TO_INTERRUPTION_REFERENCE",
    "S5275686522850612": "HIGH_VOLATILITY_AND_GAPS_STILL_LOOK_FOR_REVERSE_VPLUS",
    "S5310365073410706": "PARTIAL_LOCK_DESCRIBED_AT_PORTFOLIO_LEVEL",
}
CONDITIONS = ("PRICE_OR_LATER_CONFIRMATION", "ACTION_SPECIFIC_TRIGGER", "ACTION_SPECIFIC_PERMISSION")


def project_stage(position, amount, *, stage, source, plan_at, price_at, as_of,
                  trigger_at=None, approved_at=None, approved=None):
    """Only add to a separate protection slice after scoped conditions pass."""
    if not 0 < amount <= position.short - position.long or not plan_at < price_at:
        raise ValueError("STAGED_PROTECTION_INVALID_CAPACITY_OR_PLAN")
    scope = sha(encoded([stage, exposure(position), position.contract, amount, source, plan_at, price_at]).encode())
    case = PublicCase(scope, position.contract, source, plan_at, True, ("ENTER_LONG",),
                      (CONDITIONS,), ((CONDITIONS[0], CONDITIONS[1]), (CONDITIONS[1], CONDITIONS[2])))
    facts = [Condition(CONDITIONS[0], scope, position.contract, True, price_at, price_at + US,
                       "FROZEN_MARKET_OBSERVATION", "EVENT_TIME")]
    if trigger_at is not None:
        trigger_known_after_price = True if price_at + US < trigger_at else None
        facts.append(Condition(CONDITIONS[1], scope, position.contract, trigger_known_after_price, trigger_at, trigger_at + US,
                               "TEST_FIXTURE_TRIGGER", "EVENT_TIME"))
    if approved_at is not None:
        trigger_available = trigger_at + US if trigger_at is not None else None
        value = approved if trigger_available is not None and trigger_available < approved_at else None
        facts.append(Condition(CONDITIONS[2], scope, position.contract, value, approved_at, approved_at + US,
                               "TEST_FIXTURE_PERMISSION", "EVENT_TIME"))
    # Per-stage additions use the existing action validator on a separate
    # initially empty slice. The original leg size cannot be reduced here.
    result = assess_case(case, Position(position.contract), Action("ENTER_LONG", amount), tuple(facts), as_of=as_of)
    after = position if result["after"] is None else Position(
        position.contract, position.long + Decimal(result["after"]["long"]), position.short,
    )
    return after, dict(status=result["status"], before=exposure(position), after=exposure(after),
                       fixture_effective_at=approved_at + 2 * US if result["after"] is not None else None,
                       scope=scope, priced_at=price_at, assessed_at=as_of, conditions=result["routes"][0]["checks"])


def hypothetical(position, early_lots, *, source, plan_at, touch, confirm, cutoff):
    if not touch + 6 * US < confirm or not confirm + 6 * US < cutoff:
        raise ValueError("STAGED_PROTECTION_INVALID_CLOCK")
    early_clock = dict(stage="EARLY_PROTECTION", source=source, plan_at=plan_at, price_at=touch,
                       as_of=touch + 6 * US)
    normal_clock = dict(stage="AFTER_CONFIRMATION", source=source, plan_at=plan_at, price_at=confirm, as_of=cutoff)
    late_approval = dict(trigger_at=confirm + 2 * US, approved_at=confirm + 4 * US, approved=True)
    if not early_lots:
        _, baseline = project_stage(position, position.short, **normal_clock, **late_approval)
        return dict(early_lots=0, normal_only_fixture=baseline)
    amount = Decimal(early_lots)
    _, public = project_stage(position, amount, **early_clock)
    early_facts = dict(trigger_at=touch + 2 * US, approved_at=touch + 4 * US, approved=True)
    partial, early = project_stage(position, amount, **early_clock, **early_facts)
    _, unconfirmed_top_up = project_stage(partial, position.short - partial.long, **normal_clock,
                                          trigger_at=late_approval["trigger_at"])
    _, approved_top_up = project_stage(partial, position.short - partial.long, **normal_clock, **late_approval)
    return dict(early_lots=early_lots, public_price_only=public, early_fixture=early,
                later_without_separate_approval=unconfirmed_top_up, later_fixture=approved_top_up)


def allowed_first_stage(row, lots, totals):
    bounds = row["tick_bounds_before_touch_middle_after_confirmation"]
    # Allow any first-slice size that can all use prices after contact but
    # before confirmation, with the remainder compatible after confirmation.
    return sorted({middle for before, middle, _ in compatible_allocations(lots, totals, bounds) if before == 0})


def study():
    frozen = verified_json(STAGES, STAGES_SHA)
    index = input_sources()
    public_sources = {key: load_source(index, key) | dict(
        admitted_meaning=value, numeric_per_position_early_size=None,
        permits_ignoring_all_reversal_signals=None,
    ) for key, value in INTERPRETATIONS.items()}
    common = set(frozen["shared_quote_minute_ends"])
    cases = {}
    for contract, row in frozen["cases"].items():
        reference = row["policies"]["ADD_15M:SHAPE_CONTACT"]
        windows = [item for item in reference["quantities"]["WHOLE_MINUTES_ONLY"] if item["quote_end"] in common]
        if len(windows) != len(common) or not windows:
            raise ValueError("STAGED_PROTECTION_SHARED_QUOTE_MISSING")
        touch = datetime.fromisoformat(row["first_touch_minute"]["end"])
        confirm = datetime.fromisoformat(reference["earliest"]["confirmed_at"])
        lots = row["snapshot"]["quantity"]
        low, high = row["snapshot"]["displayed_tick_total_interval"]
        supported = [allowed_first_stage(window, lots, range(low, high + 1)) for window in windows]
        consensus = sorted(set.intersection(*(set(quantities) for quantities in supported)))
        prior = Position(contract, short=Decimal(lots))
        source = row["source"]["id"]
        plan_at = stamp(index[source]) + ONE
        cutoff = min(datetime.fromisoformat(window["quote_end"]) for window in windows)
        schedule = dict(source=source, plan_at=plan_at, touch=touch, confirm=confirm, cutoff=cutoff)
        scenarios = [hypothetical(prior, qty, **schedule) for qty in consensus if 0 < qty < lots]
        cases[contract] = dict(
            touch_at=touch, later_confirmation_clock=reference["earliest"]["variant"],
            later_confirmation_at=confirm, quote_ends=[row["quote_end"] for row in windows],
            admissible_early_lots_by_quote=supported, admissible_early_lots_at_both=consensus,
            price_constrains_but_does_not_set_early_size=True, full_early_scenario_is_not_partial=lots in consensus,
            normal_only=hypothetical(prior, 0, **schedule) | {"price_compatible_at_both_quotes": 0 in consensus},
            prior=exposure(prior), scenarios=scenarios,
            historical_early_trigger=None, historical_approval=None, historical_size=None,
        )
    return dict(
        version="lms405-staged-protection-permissions-v1", cases=cases, public_sources=public_sources,
        market_stage_ref_sha256=STAGES_SHA, author_partial_lot_formula=None,
        positive_permissions_are_test_fixtures=True, fixture_405_version_assumed=True,
        historical_plan_revision_verified=False, size_set_is_retrospective_from_quote_averages=True,
        quantity_scope="HYPOTHETICAL_FIXED_ORIGINAL_SHORT", evidence_price_minutes_are_not_fills=True,
        admitted_author_actions=0, executable=False, fills=None, pnl=None, author_match_rate=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("STAGED_PROTECTION_OUTPUT_EXISTS")
    try:
        result = study()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('STAGED_PROTECTION_') and code.isidentifier() else 'STAGED_PROTECTION_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
