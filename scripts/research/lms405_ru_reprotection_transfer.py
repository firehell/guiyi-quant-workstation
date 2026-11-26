"""Test the frozen caustic soda re-protection hypothesis on two RU2701 windows."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position
from lms405_carry_in_study import keybar_events
from lms405_counter_m_lot_roles import RETENTION, RETENTION_SHA
from lms405_m_permission_study import read_pair
from lms405_portfolio_leg_audit import scoped_input_quotes
from lms405_portfolio_protection_gate import plan_rows
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_right_side_study import ONE
from lms405_rubber_leg_transition import LATER, source_images
from lms405_rubber_quote_windows import TIMING, TIMING_SHA
from lms405_sh_reprotection_replay import CLOCKS, NEW_PLAN, opening_average_support, tape
from lms405_sizing_audit import EXPOSURE_SHA256, SPECS, load_specs
from lms405_task_role_replay import EXPOSURE_PATH
from lms405_turnover_replay import capture_cuts, state_at
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

CONTRACT = "RU2701"
FIRST, CLOSE, NIGHT = "WRnTlEfj1t", "U03", "WRoEvasxQR"
OLD_PLAN_STUDY = Path("output/lms405-rubber-leg-transition-20261125/final.json")
OLD_PLAN_STUDY_SHA = "b73fbed1e6052c56e98fe232906b561408159895d069d63edfcbf06b26943541"
SH_STUDY = Path("output/lms405-sh-reprotection-20261126/final-a.json")
SH_STUDY_SHA = "14d00152d232eff5bac1b73a138b6991e09976f304caa243bfab6a03c4c60a30"
SPECS_SHA = "fc430ad455e81d41cdd479f470e26a7a543cac0f427729de150185dfb3e40652"


def compatible_visible_rebuild(actions, seed, cutoffs, observed, bars, tick):
    """Check only a complete newly built long leg. The opposite side stays unknown when unlisted."""
    matching_states, rebuilt_states = [], []
    for cutoff in cutoffs:
        position = state_at(seed, actions, cutoff)
        if any(position[side] != leg["quantity"] for side, leg in observed.items()):
            continue
        matching_states.append(cutoff)
        if any(event["at"] < cutoff and event["action"] == "LOCK" for event in actions):
            rebuilt_states.append(cutoff)
    checks = opening_average_support(
        actions, {"rows": [{"feasible_checkpoints": rebuilt_states}]}, {"displayed_legs": observed}, bars, tick,
    )
    return dict(
        visible_quantity_cutoffs=matching_states, modeled_new_leg_cutoffs=rebuilt_states,
        opening_average_checks=checks,
        strict_price_compatible=sum(row["whole_minutes_compatible"] for row in checks),
        overlap_price_compatible=sum(row["overlap_minutes_compatible"] for row in checks),
    )


def run_case(raw, bars, start, cutoffs, observed, seed, revisions, tick):
    through = cutoffs[-1]
    recoveries = sorted(keybar_events(bars[5], raw[1], start, through)["KEYBAR_1M_CLOSE"].items())
    policies = (
        ("FROZEN_NEW_PLAN", NEW_PLAN, False),
        ("EARLY_WITHOUT_NEW_PLAN_CONTROL", "EARLIER_SIGNAL", False),
        ("SHAPE_RANGE_CONTACT_CHALLENGER", NEW_PLAN, True),
    )
    seed_quantities = {"long": seed.long, "short": seed.short}
    results = {}
    for name, policy, shape_contact in policies:
        args = (tuple(CLOCKS), policy)
        actions = tape(bars, recoveries, revisions, seed, start, through, *args, allow_shape_touch=shape_contact)
        for cutoff in cutoffs:
            prefix = {period: [bar for bar in rows if bar.end < cutoff] for period, rows in bars.items()}
            if tape(prefix, recoveries, revisions, seed, start, cutoff, *args, allow_shape_touch=shape_contact) != [
                item for item in actions if item["at"] < cutoff
            ]:
                raise ValueError("RU_REPROTECTION_PREFIX_DIVERGED")
        results[name] = dict(
            actions=actions,
            **compatible_visible_rebuild(actions, seed_quantities, cutoffs, observed, bars[1], tick),
        )
    return results


def study(session, market):
    legacy = verified_json(OLD_PLAN_STUDY, OLD_PLAN_STUDY_SHA)
    night_leg = verified_json(TIMING, TIMING_SHA)["cases"]["ru_before_m"]["visible_leg"]
    sh = verified_json(SH_STUDY, SH_STUDY_SHA)
    if not all(row["comparisons"][f"EITHER:{NEW_PLAN}"]["full_chain_match"] for row in sh["scenarios"].values()):
        raise ValueError("RU_REPROTECTION_FROZEN_SH_POLICY_MISSING")
    prior = verified_json(RETENTION, RETENTION_SHA)["contracts"][CONTRACT]
    source_rows = input_sources()
    source_pictures = source_images(source_rows)
    plans, _, plan_sources = plan_rows(source_rows, CONTRACT)
    plans = sorted(plans, key=lambda row: row.effective_after)
    revisions = [(plan, later.effective_after) for plan, later in zip(plans, plans[1:])] + [(plans[-1], None)]
    tables = verified_json(EXPOSURE_PATH, EXPOSURE_SHA256)["tables"]
    selected = {row["source"]: row for row in tables if row["source"] in (FIRST, CLOSE, NIGHT)}
    if selected[NIGHT]["image"] != night_leg["image"] or night_leg["source"] != NIGHT:
        raise ValueError("RU_REPROTECTION_NIGHT_AVERAGE_SOURCE_MISMATCH")
    for row in selected.values():
        image = row["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("RU_REPROTECTION_IMAGE_CHANGED")
    tick = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]["tick"]
    quotes = scoped_input_quotes()
    cases = {}
    for key, date_text, seed_source, endpoint in (
        ("old_plan_23_day", "2026-10-23", FIRST, LATER),
        ("new_plan_27_night", "2026-10-28", CLOSE, NIGHT),
    ):
        raw, bars = read_pair(session, market, CONTRACT, (date.fromisoformat(date_text),))
        if prior["market"][date_text] != dict(count=len(raw[1]), sha256=bars_sha(raw[1])):
            raise ValueError("RU_REPROTECTION_MARKET_CHANGED")
        seed_legs = selected[seed_source]["contracts"][CONTRACT]["legs"]
        start = datetime.fromisoformat(selected[seed_source]["published_at"]) + ONE
        seed = Position(CONTRACT, Decimal(seed_legs.get("long", {}).get("quantity", 0)),
                        Decimal(seed_legs["short"]["quantity"]))
        if endpoint == LATER:
            observed = {"long": {key: legacy["later"][name] for key, name in (
                ("quantity", "lots"), ("today_quantity", "today"), ("opening_average", "opening_average"),
            )}}
            mark = Decimal(legacy["later"]["quote_candidate"])
            minutes = [datetime.fromisoformat(row["end"]) for row in legacy["later_mark_compatible"]]
            by_end = {bar.end: bar for bar in bars[1]}
            if any(not by_end[end].low <= mark <= by_end[end].high for end in minutes):
                raise ValueError("RU_REPROTECTION_QUOTE_CHANGED")
            cutoffs = sorted(set(minutes) | {end - ONE for end in minutes})
            source_pictures[endpoint]["role"] = "MIXED_SYSTEM_DISPLAY"
        else:
            observed = selected[endpoint]["contracts"][CONTRACT]["legs"].copy()
            long = observed["long"]
            if (long["quantity"] != night_leg["quantity"]
                    or Decimal(long["opening_average"]) != Decimal(night_leg["display_average"])):
                raise ValueError("RU_REPROTECTION_NIGHT_AVERAGE_CHANGED")
            observed["long"] = long | {"opening_average": night_leg["display_average"]}
            capture = prior["capture_scopes"][endpoint]
            cutoffs = capture_cuts(raw[1], capture, quotes[endpoint, CONTRACT])
        if cutoffs[0] <= start:
            raise ValueError("RU_REPROTECTION_QUOTE_PRECEDES_SEED")
        upper = datetime.fromisoformat(source_rows[endpoint]["published_at"])
        later_revision = [r.revision for r in plans if start < r.effective_after < upper]
        cases[key] = dict(
            seed_source=seed_source, seed_available_at=start, seed_observed_legs=seed_legs,
            assumed_seed={"long": seed.long, "short": seed.short}, endpoint=endpoint,
            endpoint_observed_legs=observed, new_plan_sources_before_post=later_revision,
            quote_cutoffs=cutoffs, market={f"{period}m": dict(count=len(rows), sha256=bars_sha(rows))
                                          for period, rows in raw.items()},
            candidates=run_case(raw, bars, start, cutoffs, observed, seed, revisions, tick),
        )
    return dict(
        version="lms405-ru-reprotection-transfer-v1", contract=CONTRACT, cases=cases,
        plan_sources=plan_sources, prior_study=SH_STUDY_SHA, price_retention_reference=RETENTION_SHA,
        old_plan_replacement_reference=OLD_PLAN_STUDY_SHA, night_display_precision_reference=TIMING_SHA,
        source_images={**source_pictures, **{key: row["image"] for key, row in selected.items()}},
        assumes_same_account_for_comparison=True, source_history_at_original_time_verified=False,
        absent_seed_long_is_only_a_hypothesis=True, absent_endpoint_leg_is_unknown=True,
        opening_average_scope="POST_SIGNAL_FULL_LEG_PRICE_ENVELOPE", fixture_only=True,
        actual_recovery_at=None, actual_reprotection_at=None, admitted_author_actions=0,
        author_match_rate=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("RU_REPROTECTION_OUTPUT_EXISTS_OR_ENV_MISSING")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "RU_REPROTECTION_LOCAL_MDS_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('RU_REPROTECTION_') and code.isidentifier() else 'RU_REPROTECTION_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
