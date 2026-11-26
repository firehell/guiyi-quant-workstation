"""Recompute nine contracts with the scoped rubber, caustic and iron research options."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path

from lms405_iron_original_exit import CONTRACT as IRON
from lms405_iron_original_exit import evidence_gate, published_exit_plans
from lms405_jm_first_lock_chain import COMBINED as COAL_CONTROL
from lms405_jm_first_lock_chain import CONTRACT as COAL
from lms405_jm_first_lock_chain import FIRST_RUN, POST, PROTECT_TRADING_DAY, START, replay_first_lock
from lms405_jm_first_lock_handoff import close_cohort_continuity
from lms405_m_permission_study import read_pair
from lms405_portfolio_left_entry import scope_for
from lms405_portfolio_leg_audit import SIZE, SIZE_SHA, SPECS, SPECS_SHA, load_specs, lot_profile, pta_example, summarize
from lms405_portfolio_origin_window import ALL_DAYS, FROZEN_SCOPE, compare_rows, verify_tape
from lms405_portfolio_protection_gate import plan_rows
from lms405_portfolio_replay import CONTRACTS, input_sources
from lms405_portfolio_right_entry import branches
from lms405_portfolio_task_policy import replay_scoped_policy
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
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

CAUSTIC_REFERENCE = (Path("output/lms405-sh-middle-protection-20261126/final-a.json"),
                     "665ac4c965ee0cd3316130254081802eeb0ed97f97a7281b0be6d166a0dd2a93")
IRON_REFERENCE = (Path("output/lms405-iron-original-exit-20261126/verified-a.json"),
                  "a0568f2c2f6b1000509ecb6dd60dcc6b4e107af93c1726b79d90bbc6205830c3")
MODES = ("PENDING", "TOUCH_FAR")
METRICS = ("VISIBLE_LEGS_CHECKED", "AT_LEAST_ONE_QUOTE_COMPATIBLE", "TWO_VISIBLE_LEGS_CHECKED",
           "BOTH_LEGS_COMPATIBLE_AT_SAME_QUOTE")
CAUSTIC_PREFIXES = ("2026-10-23T22:03", "2026-10-26T11:30", "2026-10-26T23:00",
                    "2026-10-27T10:13", "2026-10-27T15:00", "2026-10-27T21:40")
CROSS_DATE = (Path("output/lms405-cross-date-protection-20261126/final-a.json"),
              "cf93cde04473f75bb42597c63bcd9e9bff1c386d6e2eae52d9299ef41db3009e")
THREE_LEG = (Path("output/lms405-three-night-deadlines-20261126/final-a.json"),
             "609ca99cf782fb570256638cfdd758e18df49095c7a7dcdf1cfc1a5fdb689af0")
LOCK_CLOCK_STARTS = (at("2026-10-22T21:00"), at("2026-10-27T21:00"))
CLOCK_REJECTIONS = "RESEARCH_WAIT_FOR_COMMON_PROTECTION_CLOCK"
COAL_CASE = "JM_FIRST_LOCK"


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


def clock_windows():
    first = verified_json(*CROSS_DATE)
    second = verified_json(*THREE_LEG)
    if first["reference"]["oct27"] != THREE_LEG[1]:
        raise ValueError("COMBINED_CLOCK_EVIDENCE_LINK_CHANGED")
    alternatives = {}
    for label, left, right in (
        ("EARLY_COMMON", "first_available_local_candidate", "common_after_all_early_clocks"),
        ("LATE_COMMON", "last_available_local_candidate", "common_after_oil_divider_contact"),
    ):
        (right_release,) = {datetime.fromisoformat(row["gate"]) for row in second["policies"][right]["by_contract"].values()}
        releases = (datetime.fromisoformat(first["common_price_hypotheses"][left]), right_release)
        windows = tuple(zip(LOCK_CLOCK_STARTS, releases, strict=True))
        if any(not start < release < start.replace(hour=23) for start, release in windows):
            raise ValueError("COMBINED_CLOCK_OUTSIDE_NIGHT_WINDOW")
        alternatives[label] = windows
    return alternatives


def variant_summary(rows, selection):
    per_contract = {k: v["strict_replay"] for k, v in summarize(rows).items()}
    totals = Counter()
    for counts in per_contract.values():
        totals.update({name: counts.get(name, 0) for name in METRICS})
    return dict(modes=selection, strict_totals=dict(totals), by_contract=per_contract,
                quote_alignment=source_alignment(rows), comparisons=rows)


def before(actions, blocked, cutoff):
    return ([row for row in actions if datetime.fromisoformat(row["at"]) < cutoff],
            [row for row in blocked if row["at"] < cutoff])


def coal_extension(session, market, index, series, cutoff, reference):
    if (reference["reference_sha256"] != COAL_CONTROL[1]
            or any(load_source(index, key) != source for key, source in reference["sources"].items())
            or scope_for(index, COAL) is not None or branches(index, COAL)):
        raise ValueError("COMBINED_COAL_SOURCE_CHANGED")
    first_day = read_window(session, market, COAL, PROTECT_TRADING_DAY)
    if {f"{p}m": digest(bars) for p, bars in first_day.items()} != reference["price_window"]["market"]:
        raise ValueError("COMBINED_COAL_MARKET_CHANGED")
    series = series | {15: first_day[15]}
    bands, _, _ = plan_rows(index, COAL)
    controls = dict(retain=True, extend=True)
    actions, blocked = replay_first_lock(series, bands, cutoff, **controls)
    expected = reference["modes"]["RETAIN_AND_ADD_15M"]
    verify_tape(*before(actions, blocked, POST), expected)
    for value in ("2026-10-22T21:45", "2026-10-22T22:08", "2026-10-23T10:38",
                  "2026-10-23T15:00", "2026-10-23T21:16", "2026-10-23T22:05", "2026-10-26T23:00"):
        cut = at(value)
        if replay_first_lock(series, bands, cut, **controls) != before(actions, blocked, cut):
            raise ValueError("COMBINED_COAL_PREFIX_CHANGED")
    return actions, blocked


def study(session, market, *, compare_protection_clocks=False, compare_coal_first_lock=False):
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
    waits = clock_windows() if compare_protection_clocks else {}
    coal_first = verified_json(*FIRST_RUN) if compare_coal_first_lock else None
    days = tuple(day for day in ALL_DAYS if day >= START)
    traces, comparisons = {}, {}
    coal_continuity = None
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
        if contract == COAL and coal_first is not None:
            actions, blocked = coal_extension(session, market, index, series, cutoff, coal_first)
            cases[COAL_CASE] = actions, blocked, frozen["comparisons"]
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
        for label, windows in waits.items():
            basis = {RUBBER: "replacement", CAUSTIC: "TOUCH_FAR", IRON: "retention"}.get(contract, "control")
            scoring_rows = cases[basis][2]
            if contract == CAUSTIC:
                altered, blocked = replay_middle(series, entry, bands, caustic_sources, cutoff, "TOUCH_FAR", None,
                                                protection_wait_windows=windows)
                for cut in (at("2026-10-22T22:07"), at("2026-10-27T22:09")):
                    prefix = replay_middle(series, entry, bands, caustic_sources, cut, "TOUCH_FAR", None,
                                           protection_wait_windows=windows)
                    if prefix != ([row for row in altered if datetime.fromisoformat(row["at"]) < cut],
                                  [row for row in blocked if row["at"] < cut]):
                        raise ValueError("COMBINED_CLOCK_CAUSTIC_PREFIX_CHANGED")
            else:
                altered, blocked, *_ = replay_scoped_policy(
                    fives, minutes, cutoff, index, handoff_plan=replacement if contract == RUBBER else None,
                    original_reversal_evidence=iron_check if contract == IRON else None,
                    protection_wait_windows=windows, **scope,
                )
            if not any(row.get("reason") == CLOCK_REJECTIONS for row in blocked):
                if (altered, blocked) != cases[basis][:2]:
                    raise ValueError("COMBINED_CLOCK_UNAFFECTED_TAPE_CHANGED")
            cases[label] = altered, blocked, scoring_rows
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
        if contract == COAL and coal_first is not None:
            coal_continuity = close_cohort_continuity(comparisons[COAL][COAL_CASE], series[1], specs[COAL]["tick"])

    results = {}
    for mode in MODES:
        for retain in (False, True):
            selection = {contract: "control" for contract in CONTRACTS}
            selection.update({RUBBER: "replacement", CAUSTIC: mode, IRON: "retention" if retain else "control"})
            rows = {contract: comparisons[contract][label] for contract, label in selection.items()}
            result = variant_summary(rows, selection)
            if not retain and result["strict_totals"] != caustic["windows"][start]["cases"][mode + ":SHAPE_ONLY"]["portfolio"]:
                raise ValueError("COMBINED_PREVIOUS_TOTALS_CHANGED")
            results[f"{mode}:{'IRON_RETAIN' if retain else 'IRON_CONTROL'}"] = result
    chosen_control = "TOUCH_FAR:IRON_RETAIN"
    extra = {}
    if coal_first is not None:
        control = results[chosen_control]
        selection = control["modes"] | {COAL: COAL_CASE}
        rows = {contract: comparisons[contract][label] for contract, label in selection.items()}
        result = variant_summary(rows, selection)
        if any(result["strict_totals"][m] != control["strict_totals"][m] for m in (
            "VISIBLE_LEGS_CHECKED", "TWO_VISIBLE_LEGS_CHECKED",
        )):
            raise ValueError("COMBINED_COAL_SCORING_SCOPE_CHANGED")
        results[COAL_CASE] = result
        extra["coal_first_lock_experiment"] = dict(
            reference_sha256=FIRST_RUN[1], conditional_control=chosen_control,
            retention_sensitivity_until=POST, continuation_uses_control_management=True,
            screenshots_only_for_validation=True, close_cohort_continuity=coal_continuity,
        )
    if waits:
        control = results[chosen_control]
        for label in waits:
            rows = {contract: comparisons[contract][label] for contract in CONTRACTS}
            result = variant_summary(rows, dict.fromkeys(CONTRACTS, label))
            if any(result["strict_totals"][m] != control["strict_totals"][m] for m in (
                "VISIBLE_LEGS_CHECKED", "TWO_VISIBLE_LEGS_CHECKED",
            )):
                raise ValueError("COMBINED_CLOCK_SCORING_SCOPE_CHANGED")
            result["rejections_by_contract"] = {c: [r for r in traces[c]["tapes"][label]["blocked"]
                                                            if r.get("reason") == CLOCK_REJECTIONS] for c in CONTRACTS}
            results[label] = result
        extra["clock_experiment"] = dict(
            reference_sha256=dict(six_leg=CROSS_DATE[1], three_leg=THREE_LEG[1]),
            conditional_control=chosen_control, windows=waits,
            waiting_only_rejects_early_local_protection=True, discarded_signals_not_reused=True,
            shared_wait_never_supplies_local_signal_or_permission=True,
        )
    return dict(
        study="LMS405_NINE_CONTRACT_COMBINED_RESEARCH_REPLAY", as_of=cutoff, start_trading_day=START, runs=results,
        contracts=traces, reference_sha256=dict(control=CONTROL[1], rubber=RUBBER_REFERENCE[1],
                                               caustic=CAUSTIC_REFERENCE[1], iron=IRON_REFERENCE[1]),
        assumptions=dict(scoped_fixture_permissions=True, same_quote_label_not_photo_timestamp=True,
                         screenshots_only_for_validation=True, shared_account_risk_model=None,
                         iron_undisclosed_protection_permits=None, caustic_target_role_is_sensitivity=True),
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
        **extra,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compare-protection-clocks", action="store_true")
    parser.add_argument("--compare-coal-first-lock", action="store_true")
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
            report = study(session, build_market_data_service(session),
                           compare_protection_clocks=args.compare_protection_clocks,
                           compare_coal_first_lock=args.compare_coal_first_lock)
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
