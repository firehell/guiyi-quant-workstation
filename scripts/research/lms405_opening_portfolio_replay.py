"""Compare nine-product LMS research replays with explicitly permitted opening scenarios."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Action, Bar, Position, apply_action
from guiyi_quant.lms405.public_conditions import Condition, check_route
from lms405_carry_in_study import SNAPSHOT_SHA256
from lms405_managed_portfolio import BASELINE, SNAPSHOTS
from lms405_opening_clock_comparison import ROUTE
from lms405_portfolio_replay import CONTRACTS, DAYS, FIVE, batch_fixture_transitions
from lms405_protection_lot_timing import verified_json
from lms405_replay import ohlc, read_session_series
from lms405_right_side_study import ONE, US
from lms_near405_replay import encoded, sha

VERSION = "lms405-opening-portfolio-study-v1"
BASE_SHA = "fba8faadaffb8fc5f54bc84588ad67e2256a4b113db270ed4285e4fe518ba856"
OPENING = Path("output/lms405-opening-clock-comparison-20261125/verified.json")
OPENING_SHA = "6307b90e77dcae0db5cb3533a23fdd329cc09dbc4bca6095261293c896e38c62"
CASES = {
    "pta_new_long": "previous_close_retest", "jm_new_short": "divider_near",
    "soda_new_long": "divider_far", "soda_new_short": "divider_near",
}
CLOCKS = ("1m_to_1m", "5m_to_1m", "5m_to_5m", "15m_to_15m")
MODES = ("FIRST_COMPLETED_MINUTE", "DIRECTIONAL_PRICE_REACH")


def state_before(transitions, initial, anchor):
    last = next((row for row in reversed(transitions) if datetime.fromisoformat(row["known_at"]) < anchor), None)
    return last["after"] if last else initial


def opening_selection(case, role, mode, clock):
    if mode not in MODES or clock not in CLOCKS:
        raise ValueError("OPENING_PORTFOLIO_UNKNOWN_POLICY")
    if mode == "DIRECTIONAL_PRICE_REACH":
        context = case["clocks"][role]["first_range_reaches_direction"]
        gate = f"{role}:fresh_{clock}_after_reach"
    else:
        context = (datetime.fromisoformat(case["start"]) + ONE).isoformat()
        gate = f"keybar:{clock}"
    confirm = case["gates"][gate]
    if context is None or confirm is None:
        return None
    context_end, confirm_end = datetime.fromisoformat(context), datetime.fromisoformat(confirm)
    matching = [row for row in case["geometric_candidates"][f"keybar:{clock}"]
                if datetime.fromisoformat(row["confirmed_at"]) == confirm_end]
    if len(matching) != 1:
        raise ValueError("OPENING_PORTFOLIO_SIGNAL_NOT_UNIQUE")
    event = matching[0]
    shape_start = datetime.fromisoformat(event["shape_end"]) - int(clock.split("m", 1)[0]) * ONE
    if context_end + US >= shape_start:
        raise ValueError("OPENING_PORTFOLIO_FROZEN_SIGNAL_PRECEDES_CONTEXT")
    if confirm_end + US != datetime.fromisoformat(event["available_at"]):
        raise ValueError("OPENING_PORTFOLIO_CONFIRMATION_CLOCK_DRIFT")
    return dict(context_end=context_end, confirmed_at=confirm_end, shape_start=shape_start,
                price_bound=gate, signal=event)


def scenario_permission(scope, contract, signal, as_of, *, explicit_fixture_permission):
    facts = [Condition("OPENING_CONTEXT", scope, contract, True,
                       signal["context_end"], signal["context_end"] + US, scope, "EVENT_TIME")]
    if explicit_fixture_permission:
        # Both facts are explicit simulation assumptions, never author evidence.
        signal_at = signal["confirmed_at"]
        facts.extend(Condition(name, scope, contract, True, signal_at, signal_at + US,
                               "TEST_FIXTURE", "EVENT_TIME") for name in ROUTE[1:])
    visible = {fact.name: fact for fact in facts if fact.known_at < as_of}
    return check_route(ROUTE, (("OPENING_CONTEXT", "AUTHOR_SIGNAL"),), visible)


def apply_scenario(bars, transitions, initial, case, mode, clock, role, *, as_of, explicit_fixture_permission):
    signal = opening_selection(case, role, mode, clock)
    if signal is None:
        return transitions, dict(status="NO_CANDIDATE_IN_WINDOW")
    # The extra microsecond represents explicit fixture acceptance after evidence is available.
    known = signal["confirmed_at"] + 2 * US
    if known > as_of:
        return transitions, dict(status="CANDIDATE_NOT_KNOWN")
    contract = case["contract"]
    scope = f"{VERSION}:{contract}:{case['start']}:{mode}:{clock}"
    real = scenario_permission(scope, contract, signal, known, explicit_fixture_permission=False)
    if not explicit_fixture_permission:
        return transitions, dict(status="AUTHOR_PERMISSION_AND_SIGNAL_UNKNOWN", candidate=signal, evidence_checks=real)
    at_boundary = scenario_permission(scope, contract, signal, known - US, explicit_fixture_permission=True)
    fixture = scenario_permission(scope, contract, signal, known, explicit_fixture_permission=True)
    if real["value"] is not None or at_boundary["value"] is not None or fixture["value"] is not True:
        raise ValueError("OPENING_PORTFOLIO_PERMISSION_SCOPE_CHANGED")
    before = state_before(transitions, initial, known)
    if Decimal(before["long"]) or Decimal(before["short"]):
        return transitions, dict(status="EXISTING_RESEARCH_POSITION_AT_CANDIDATE", candidate=signal,
                                 existing=[before["long"], before["short"]], evidence_checks=real)
    if any(datetime.fromisoformat(row["known_at"]) == known for row in transitions):
        return transitions, dict(status="SAME_TIME_BASELINE_EVENT", candidate=signal, evidence_checks=real)
    direction = case["direction"]
    seed = candidate.CarryInSeed(contract, known, direction, False, f"TEST_FIXTURE:{scope}")
    continuation = candidate.replay(bars, as_of=as_of, carry_in=seed, timely_fixture=True)
    checkpoint = candidate.replay(bars, as_of=known, carry_in=seed, timely_fixture=True)["checkpoint"]
    if continuation != candidate.replay(bars, as_of=as_of, carry_in=seed, timely_fixture=True, checkpoint=checkpoint):
        raise ValueError("OPENING_PORTFOLIO_RESTART_DIVERGED")
    after = continuation["checkpoint"]["initial_state"]
    action = Action(f"ENTER_{direction}", Decimal(1))
    expected = apply_action(Position(contract), action)
    if (Decimal(after["long"]), Decimal(after["short"])) != (expected.long, expected.short):
        raise ValueError("OPENING_PORTFOLIO_SEED_POSITION_DIVERGED")
    event = dict(known_at=known.isoformat(), action=action.kind, reason="EXPLICIT_OPENING_SCENARIO",
                 proposal_id=candidate.fingerprint(dict(scope=scope, signal=signal)), before=before,
                 after=after, record_kind="TEST_FIXTURE")
    prior = [row for row in transitions if datetime.fromisoformat(row["known_at"]) < known]
    result = prior + [event] + continuation["transitions"]
    return result, dict(status="TEST_FIXTURE_ONLY", at=known.isoformat(), candidate=signal,
                        evidence_checks=real, fixture_checks=fixture, continuation_rule=continuation["version"],
                        continuation_prices="PRESEED_CONTEXT_PROXY")


def snapshot_projection(cases, records, baseline, initial):
    rows = {}
    for name, case in cases.items():
        contract = case["contract"]
        side = case["direction"].lower()
        before = initial[contract]
        outcome = records.get(name)
        rows[name] = {}
        for raw in case["capture_boundaries"]:
            at = datetime.fromisoformat(raw)
            baseline_visible = Decimal(state_before(baseline[contract], before, at)[side]) > 0
            scenario_visible = (Decimal(state_before(outcome[0], before, at)[side]) > 0
                                if outcome is not None else baseline_visible)
            entry = outcome[1] if outcome is not None else {}
            bound = None
            if entry.get("status") == "TEST_FIXTURE_ONLY" and datetime.fromisoformat(entry["at"]) < at:
                bounds = case["lot_formation_bounds"][entry["candidate"]["price_bound"]]["ONLY_COMPLETE_MINUTES_AFTER"]
                bound = next((row for label, row in bounds.items() if datetime.fromisoformat(label) == at), None)
                if bound is None:
                    raise ValueError("OPENING_PORTFOLIO_QUOTE_BOUND_MISSING")
            rows[name][raw] = dict(baseline_direction_visible=baseline_visible, scenario_direction_visible=scenario_visible,
                                   whole_observed_leg_compatible_after_scenario=bound["whole_leg_can_form_after"] if bound else None,
                                   minimum_lots_earlier_or_overlapping=bound["min_outside_later_bucket"] if bound else None)
    return rows


def replay_variant(bars, baseline, initial, cases, mode, clock, *, as_of, explicit_fixture_permission):
    projected = {contract: [row for row in rows if datetime.fromisoformat(row["known_at"]) <= as_of]
                 for contract, rows in baseline.items()}
    records = {}
    for name, case in sorted(cases.items(), key=lambda row: (datetime.fromisoformat(row[1]["start"]), row[0])):
        contract = case["contract"]
        projected[contract], audit = apply_scenario(bars[contract], projected[contract], initial[contract], case,
                                                    mode, clock, CASES[name], as_of=as_of,
                                                    explicit_fixture_permission=explicit_fixture_permission)
        records[name] = audit
    return projected, records


def study(session, market):
    reference = verified_json(BASELINE, BASE_SHA)
    openings = verified_json(OPENING, OPENING_SHA)
    snapshots = verified_json(SNAPSHOTS, SNAPSHOT_SHA256)
    cases = {key: openings["cases"][key] for key in CASES}
    as_of = datetime.fromisoformat(reference["as_of"])
    bars, baseline, initial = {}, {}, {}
    for contract in CONTRACTS:
        raw = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        series = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw if b.bar_end + US <= as_of]
        digest = sha(encoded([[b.end.isoformat(), *map(str, ohlc(b))] for b in series]).encode())
        if digest != reference["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("OPENING_PORTFOLIO_BASELINE_BAR_DRIFT")
        baseline_run = candidate.replay(series, as_of=as_of, timely_fixture=True)
        bars[contract] = series
        baseline[contract] = baseline_run["transitions"]
        initial[contract] = baseline_run["checkpoint"]["initial_state"]
    base_batches, _ = batch_fixture_transitions([row for rows in baseline.values() for row in rows])
    if base_batches != [row for row in reference["timeline"] if row["layer"] == "FIXTURE_STATE_BATCH"]:
        raise ValueError("OPENING_PORTFOLIO_BASELINE_TRANSITIONS_DRIFT")
    variants = {}
    research_prefix = datetime.fromisoformat(cases["soda_new_short"]["start"])
    for mode in MODES:
        for clock in CLOCKS:
            projected, audits = replay_variant(bars, baseline, initial, cases, mode, clock, as_of=as_of,
                                                 explicit_fixture_permission=True)
            without_fixture, actual_checks = replay_variant(bars, baseline, initial, cases, mode, clock, as_of=as_of,
                                                              explicit_fixture_permission=False)
            if without_fixture != baseline:
                raise ValueError("OPENING_PORTFOLIO_AUTHORIZATION_NOT_FAIL_CLOSED")
            prefix, _ = replay_variant(bars, baseline, initial, cases, mode, clock, as_of=research_prefix,
                                       explicit_fixture_permission=True)
            if any(prefix[c] != [row for row in projected[c] if datetime.fromisoformat(row["known_at"]) <= research_prefix]
                   for c in CONTRACTS):
                raise ValueError("OPENING_PORTFOLIO_PREFIX_DIVERGED")
            batches, terminal = batch_fixture_transitions([row for rows in projected.values() for row in rows])
            by_case = {name: (projected[case["contract"]], audits[name]) for name, case in cases.items()}
            for name, (actions, audit) in by_case.items():
                if audit["status"] == "TEST_FIXTURE_ONLY":
                    start, cut = datetime.fromisoformat(audit["at"]), datetime.fromisoformat(cases[name]["cutoff_exclusive"])
                    audit["management_until_post"] = [
                        {key: row[key] for key in ("known_at", "action", "reason")}
                        for row in actions if start < datetime.fromisoformat(row["known_at"]) < cut
                    ]
            anchored = {}
            for row in snapshots["snapshots"]:
                anchor = datetime.fromisoformat(row["quote_anchor"])
                anchored[row["source"]] = {
                    contract: {side: dict(baseline=Decimal(state_before(baseline[contract], initial[contract], anchor)[side]) > 0,
                                          scenario=Decimal(state_before(projected[contract], initial[contract], anchor)[side]) > 0)
                               for side in values["author_visible_legs"]}
                    for contract, values in row["contracts"].items() if values["quote_aligned"] is True
                }
            variants[f"{mode}/{clock}"] = dict(
                audits=audits, author_evidence_checks=actual_checks,
                opening_quote_comparisons=snapshot_projection(cases, by_case, baseline, initial),
                joint_quote_directions=anchored, fixture_state_batches=batches, terminal_units=terminal,
                changed_contracts=[c for c in CONTRACTS if baseline[c] != projected[c]],
            )
    return dict(version=VERSION, as_of=as_of, contracts=CONTRACTS, baseline_sha256=BASE_SHA,
                opening_sha256=OPENING_SHA, joint_quotes_sha256=SNAPSHOT_SHA256, baseline_batches=base_batches,
                checked_portfolio_prefix=research_prefix,
                case_sides="RESEARCH_HYPOTHESES_WITH_SIDES_SELECTED_FROM_SEEN_CASES", variants=variants,
                positive_cases_author_permissions=None, explicit_skip_control=openings["cases"]["jm_declined_m"],
                observed_opening_transitions=[], executable=False, author_match_rate=None,
                admitted_author_actions=0, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('OPENING_PORTFOLIO_') and code.isidentifier() else 'OPENING_PORTFOLIO_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
