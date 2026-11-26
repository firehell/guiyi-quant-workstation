"""Recompute nine contracts with the scoped rubber, caustic and iron research options."""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import json
from pathlib import Path

from lms405_iron_original_exit import CONTRACT as IRON
from lms405_iron_original_exit import evidence_gate, published_exit_plans
from lms405_m_permission_study import read_pair
from lms405_portfolio_leg_audit import SIZE, SIZE_SHA, SPECS, SPECS_SHA, load_specs, lot_profile, pta_example, summarize
from lms405_portfolio_origin_window import ALL_DAYS, FROZEN_SCOPE, compare_rows
from lms405_portfolio_protection_gate import plan_rows
from lms405_portfolio_replay import CONTRACTS, input_sources
from lms405_portfolio_task_policy import replay_scoped_policy
from lms405_protection_lot_timing import verified_json
from lms405_public_plan_roles import load_source
from lms405_rubber_protection_handoff import CONTRACT as RUBBER
from lms405_rubber_protection_handoff import CONTROL, OLD, RECOVER, REPLACE, handoff_plan
from lms405_sh_entry_and_handoff import RUBBER as RUBBER_REFERENCE
from lms405_sh_entry_and_handoff import case_options
from lms405_sh_lock_lifecycle import digest
from lms405_sh_middle_protection import CONTRACT as CAUSTIC
from lms405_sh_middle_protection import (
    ENTRY, INTERMEDIATE, MID_LOCK, MORNING_SOURCE, NEW_PROTECTION, OLD_LOCK, RECOVERY_REF, REREVIEW,
    replay_middle, reread_morning_field,
)
from lms405_v_ta_case import identity
from lms_near405_replay import encoded
from lms405_right_side_study import US, at

START = date(2026, 10, 19)
CAUSTIC_REFERENCE = (Path("output/lms405-sh-middle-protection-20261126/final-a.json"),
                     "665ac4c965ee0cd3316130254081802eeb0ed97f97a7281b0be6d166a0dd2a93")
IRON_REFERENCE = (Path("output/lms405-iron-original-exit-20261126/verified-a.json"),
                  "a0568f2c2f6b1000509ecb6dd60dcc6b4e107af93c1726b79d90bbc6205830c3")
MODES = ("PENDING", "TOUCH_FAR")
METRICS = ("VISIBLE_LEGS_CHECKED", "AT_LEAST_ONE_QUOTE_COMPATIBLE", "TWO_VISIBLE_LEGS_CHECKED",
           "BOTH_LEGS_COMPATIBLE_AT_SAME_QUOTE")
CAUSTIC_PREFIXES = ("2026-10-23T22:03", "2026-10-26T11:30", "2026-10-26T23:00",
                    "2026-10-27T10:13", "2026-10-27T15:00", "2026-10-27T21:40")


def source_alignment(comparisons):
    """Group measured rows at the same quote-minute label, without assigning a photo time."""
    sources = defaultdict(dict)
    for contract, rows in comparisons.items():
        for row in rows:
            if row["status"] == "CHECKED":
                leg = (contract, row["side"])
                match = sources[row["source"]]
                if leg in match:
                    raise ValueError("COMBINED_REPEAT_SOURCE_LEG")
                match[leg] = row["by_variant"]["strict_replay"]
    results = {}
    for source, legs in sources.items():
        snapshot = defaultdict(list)
        for leg, checks in legs.items():
            for label, check in checks.items():
                slot = snapshot[label]
                if check["status"] == "PRICE_COMPATIBLE":
                    slot.append(leg)
        count = max(map(len, snapshot.values()), default=0)
        results[source] = dict(
            checked_legs=len(legs),
            independently_compatible_legs=sum(
                any(check["status"] == "PRICE_COMPATIBLE" for check in checks.values()) for checks in legs.values()
            ),
            most_compatible_at_one_quote_label=count,
            best_quote_labels={time: sorted(legs) for time, legs in sorted(snapshot.items()) if len(legs) == count}
            if count else {},
        )
    return results


def verify_tape(actions, diagnostics, reference, *, diagnostics_key="blocked"):
    if json.loads(encoded((actions, diagnostics))) != [reference["actions"], reference[diagnostics_key]]:
        raise ValueError("COMBINED_FROZEN_TAPE_CHANGED")


def study(session, market):
    baseline = verified_json(*CONTROL)
    rubber = verified_json(*RUBBER_REFERENCE)
    caustic = verified_json(*CAUSTIC_REFERENCE)
    iron = verified_json(*IRON_REFERENCE)
    reread = verified_json(*INTERMEDIATE)["observations"][MORNING_SOURCE]
    if set(baseline["contracts"]) != set(CONTRACTS) or rubber["control_sha256"] != CONTROL[1] or (
        iron["reference_sha256"] != CONTROL[1] or iron["as_of"] != baseline["as_of"]
        or caustic["cited_intermediate_sha256"] != INTERMEDIATE[1]
    ):
        raise ValueError("COMBINED_CONTROL_SCOPE_CHANGED")
    start, cutoff = START.isoformat(), datetime.fromisoformat(baseline["as_of"])
    base_rows = {contract: baseline["contracts"][contract][start] for contract in CONTRACTS}
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    sizing = verified_json(SIZE, SIZE_SHA)
    profile, ta_lots = lot_profile(sizing), pta_example(sizing)
    index = input_sources()
    iron_plans = published_exit_plans(index)
    if json.loads(encoded(iron_plans)) != iron["plans"]:
        raise ValueError("COMBINED_IRON_PLAN_CHANGED")
    iron_check = evidence_gate(iron_plans, allow_price_proxy=False)
    rubber_sources = {key: load_source(index, key) for key in (OLD, RECOVER, REPLACE)}
    if rubber_sources != rubber["sources"]:
        raise ValueError("COMBINED_RUBBER_PLAN_CHANGED")
    replacement = handoff_plan(rubber_sources, "FAR_CLOSE")
    caustic_sources = {key: load_source(index, key)
                       for key in (ENTRY, OLD_LOCK, MID_LOCK, RECOVERY_REF, REREVIEW, NEW_PROTECTION)}
    if caustic_sources != caustic["sources"]:
        raise ValueError("COMBINED_CAUSTIC_PLAN_CHANGED")
    bands, _, _ = plan_rows(index, CAUSTIC)
    entry, _ = case_options(caustic_sources, "FIRST_FAR_CLOSE", False)

    scope = FROZEN_SCOPE | dict(range_exit_requires_confirmation=True)
    days = tuple(day for day in ALL_DAYS if day >= START)
    traces, comparisons = {}, {}
    for contract in CONTRACTS:
        raw, series = read_pair(session, market, contract, days)
        minutes = raw[1]
        fives = [bar for bar in series[5] if bar.end + US <= cutoff]
        frozen = base_rows[contract]
        fingerprints = dict(one_minute=identity(minutes), five_minute=digest(fives))
        if fingerprints != dict(one_minute=frozen["market"]["1m"], five_minute=frozen["market"]["5m_prefix_sha256"]):
            raise ValueError("COMBINED_MARKET_CHANGED")
        actions, blocked, *_ = replay_scoped_policy(fives, minutes, cutoff, index, **scope)
        verify_tape(actions, blocked, frozen)
        cases = {"control": (actions, blocked, frozen["comparisons"])}
        if contract == RUBBER:
            actions, blocked, *_ = replay_scoped_policy(fives, minutes, cutoff, index, handoff_plan=replacement, **scope)
            verify_tape(actions, blocked, rubber["windows"][start]["variants"]["FAR_CLOSE"],
                        diagnostics_key="diagnostics")
            cases["replacement"] = actions, blocked, frozen["comparisons"]
        if contract == IRON:
            actions, blocked, *_ = replay_scoped_policy(
                fives, minutes, cutoff, index, original_reversal_evidence=iron_check, **scope,
            )
            verify_tape(actions, blocked, iron["windows"][start]["comparisons"]["require_disclosed_exit"])
            cases["retention"] = actions, blocked, frozen["comparisons"]
        if contract == CAUSTIC:
            rows = reread_morning_field(frozen["comparisons"], reread)
            for mode in MODES:
                actions, blocked = replay_middle(series, entry, bands, caustic_sources, cutoff, mode, None)
                verify_tape(actions, blocked, caustic["windows"][start]["cases"][mode + ":SHAPE_ONLY"])
                for value in CAUSTIC_PREFIXES:
                    cut = at(value)
                    if replay_middle(series, entry, bands, caustic_sources, cut, mode, None) != (
                        [row for row in actions if datetime.fromisoformat(row["at"]) < cut],
                        [row for row in blocked if row["at"] < cut],
                    ):
                        raise ValueError("COMBINED_CAUSTIC_PREFIX_CHANGED")
                cases[mode] = actions, blocked, rows
        traces[contract] = dict(market=fingerprints, input_bars={"1m": len(minutes), "5m_before_cutoff": len(fives)},
                                tapes={label: dict(actions=actions, blocked=blocked)
                                       for label, (actions, blocked, _) in cases.items()})
        comparisons[contract] = {
            label: compare_rows(contract, rows, "replay", actions, minutes, profile.get(contract), ta_lots,
                                specs[contract]["tick"])
            for label, (actions, _, rows) in cases.items()
        }
        if json.loads(encoded(comparisons[contract]["control"])) != frozen["comparisons"]:
            raise ValueError("COMBINED_FROZEN_COMPARISONS_CHANGED")

    results = {}
    for mode in MODES:
        for retain in (False, True):
            selection = {contract: "control" for contract in CONTRACTS}
            selection.update({RUBBER: "replacement", CAUSTIC: mode, IRON: "retention" if retain else "control"})
            rows = {contract: comparisons[contract][label] for contract, label in selection.items()}
            per_contract = {k: v["strict_replay"] for k, v in summarize(rows).items()}
            totals = Counter()
            for counts in per_contract.values():
                totals.update({name: counts.get(name, 0) for name in METRICS})
            if not retain and totals != caustic["windows"][start]["cases"][mode + ":SHAPE_ONLY"]["portfolio"]:
                raise ValueError("COMBINED_PREVIOUS_TOTALS_CHANGED")
            results[f"{mode}:{'IRON_RETAIN' if retain else 'IRON_CONTROL'}"] = dict(
                modes=selection, strict_totals=dict(totals), by_contract=per_contract,
                quote_alignment=source_alignment(rows), comparisons=rows,
            )
    return dict(
        study="LMS405_NINE_CONTRACT_COMBINED_RESEARCH_REPLAY", as_of=cutoff, start_trading_day=START, runs=results,
        contracts=traces, reference_sha256=dict(control=CONTROL[1], rubber=RUBBER_REFERENCE[1],
                                               caustic=CAUSTIC_REFERENCE[1], iron=IRON_REFERENCE[1]),
        assumptions=dict(scoped_fixture_permissions=True, same_quote_label_not_photo_timestamp=True,
                         screenshots_only_for_validation=True, shared_account_risk_model=None,
                         iron_undisclosed_protection_permits=None, caustic_target_role_is_sensitivity=True),
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("COMBINED_")
                        else "COMBINED_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
