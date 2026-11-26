"""Replay scoped SH2701 re-protection with one recovery clock across both cases."""

import argparse
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, apply_action
from lms405_carry_in_study import keybar_events
from lms405_counter_m_lot_roles import RETENTION, RETENTION_SHA, exposure
from lms405_oi_leg_intent import SPECS_SHA
from lms405_portfolio_protection_gate import plan_rows
from lms405_portfolio_replay import input_sources
from lms405_pre_touch_protection import analyze
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_public_plan_roles import load_source
from lms405_right_side_study import US
from lms405_sizing_audit import SPECS, load_specs
from lms405_turnover_replay import TURNOVER, TURNOVER_SHA, compare_tape, study
from lms_near405_replay import encoded

CONTRACT = "SH2701"
CLOCKS = {"1m_to_1m": (1, 1), "5m_to_1m": (5, 1)}
POLICIES = ("INSIDE_ONLY", "EARLIER_SIGNAL", "FIRST_TOUCH", "SURVIVING_FIRST_TOUCH")
NEW_PLAN = "ADVANCE_REQUIRES_NEW_PLAN"


def admitted_event(event, policy, *, refreshed):
    # The recorded close is a research condition, not the market's knowledge time.
    if event["in_band"]:
        return event["available_at"], "IN_BAND"
    if (policy == "EARLIER_SIGNAL" or (policy == NEW_PLAN and refreshed)) and event["pre_touch_arm"]:
        return event["available_at"], "ADVANCE"
    touch = event["touch_known_at"]
    if touch is not None and (
        policy == "FIRST_TOUCH" or (policy == "SURVIVING_FIRST_TOUCH" and event["survives_both_diagnostics"])
    ):
        return touch, "AFTER_FIRST_TOUCH"
    return None


def next_protection(bars, revisions, since, through, clocks, policy):
    for revision, next_at in revisions:
        if revision.role != "PROTECTION":
            continue
        start = max(since, revision.effective_after)
        cut = min(through, next_at) if next_at is not None else through
        if start >= cut:
            continue
        band = revision.lower, revision.upper
        options = tuple(CLOCKS[clock] for clock in clocks)
        variants = analyze(bars, start=start, cut=cut, band=band, side="LONG", leg=None, variants=options)["variants"]
        candidates = []
        for clock, rows in variants.items():
            step = timedelta(minutes=CLOCKS[clock][0])
            for event in rows:
                if event["shape_end"] - step <= start:
                    continue
                admission = admitted_event(event, policy, refreshed=since < revision.effective_after)
                if admission is None:
                    continue
                known, route = admission
                accepted = known + US
                if accepted < cut:
                    candidates.append(dict(
                        at=accepted, revision=revision.revision, band=band, route=route, clock=clock,
                        signal_at=event["confirmed_at"], signal_known_at=event["available_at"],
                        signal_close=event["close"], first_touch=(event["segment_first_touch"]
                                                                 if route == "AFTER_FIRST_TOUCH" else None),
                    ))
        if candidates:
            return min(candidates, key=lambda row: (row["at"], row["signal_at"]))
    return None


def next_recovery(recoveries, since, through):
    for when, candidates in recoveries:
        if since < when < through:
            fresh = [row for row in candidates if since < row["shape_start"]]
            if {row["direction"] for row in fresh} == {"SHORT"}:
                return dict(at=when, signals=fresh)
    return None


def tape(bars, recoveries, revisions, seed, seed_at, through, clocks, policy):
    rows, position, since = [], seed, seed_at
    while since < through:
        if position.long:
            result = next_recovery(recoveries, since, through)
            action = "UNLOCK_SHORT"
        else:
            result = next_protection(bars, revisions, since, through, clocks, policy)
            action = "LOCK"
        if result is None:
            break
        after = apply_action(position, Action(action, seed.short))
        rows.append(result | dict(action=action, before=exposure(position), after=exposure(after),
                                  decision_kind="TEST_FIXTURE"))
        position, since = after, result["at"]
    return rows


def opening_average_support(tape, matched, final_point, minutes, tick):
    leg = final_point["displayed_legs"]["long"]
    lots = leg["quantity"]
    totals = displayed_tick_totals(Decimal(leg["opening_average"]), lots, tick)
    rows = []
    for cutoff in matched["rows"][-1]["feasible_checkpoints"]:
        lock = next((event for event in reversed(tape) if event["at"] < cutoff and event["action"] == "LOCK"), None)
        if not lock:
            raise ValueError("SH_REPROTECTION_MATCHED_NEW_LEG_WITHOUT_LOCK")
        through = [bar for bar in minutes if lock["at"] < bar.end <= cutoff]
        strict = [bar for bar in through if lock["at"] < bar.start]
        rows.append(dict(cutoff=cutoff, protection_at=lock["at"],
                         whole_minutes_compatible=bool(earlier_lot_counts(None, tick_bounds(strict, tick), lots, totals)),
                         overlap_minutes_compatible=bool(earlier_lot_counts(None, tick_bounds(through, tick), lots, totals))))
    return rows


def compare(session, market):
    source_index = input_sources()
    plans, _, sources = plan_rows(source_index, CONTRACT)
    plans = sorted(plans, key=lambda row: row.effective_after)
    revisions = [(plan, plans[index + 1].effective_after if index + 1 < len(plans) else None)
                 for index, plan in enumerate(plans)]
    source_note = "WRo1A1rN9b"
    tick = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]["tick"]
    price_checks = {}

    def policies_for_case(raw, bars, seed_at, through, seed_quantities, points):
        recovery = keybar_events(bars[5], raw[1], seed_at, through)["KEYBAR_1M_CLOSE"]
        recovery = sorted(recovery.items())
        position = Position(CONTRACT, seed_quantities["long"], seed_quantities["short"])
        results = {}
        scenarios = {(clock, policy): (clock,) for clock in CLOCKS for policy in POLICIES}
        scenarios.update({("EITHER", policy): tuple(CLOCKS) for policy in ("EARLIER_SIGNAL", NEW_PLAN)})
        prices = {}
        for (clock, policy), clock_choices in scenarios.items():
            full = tape(bars, recovery, revisions, position, seed_at, through, clock_choices, policy)
            for cut in (point["cuts"][0] for point in points):
                if tape(bars, recovery, revisions, position, seed_at, cut, clock_choices, policy) != [
                    event for event in full if event["at"] < cut
                ]:
                    raise ValueError("SH_REPROTECTION_PREFIX_DIVERGED")
            identity = f"{clock}:{policy}"
            results[identity] = full
            matched = compare_tape(seed_quantities, full, seed_at, points)
            prices[identity] = opening_average_support(full, matched, points[-1], bars[1], tick)
        price_checks[points[-1]["source"]] = prices
        return results

    turnover = verified_json(TURNOVER, TURNOVER_SHA)
    retention = verified_json(RETENTION, RETENTION_SHA)
    result = study(session, market, turnover, retention, reprotection=policies_for_case)
    return result | dict(
        version="lms405-sh-scoped-reprotection-replay-v1", plan_sources=sources,
        retrospective_context={source_note: load_source(source_index, source_note)},
        historical_plan_revision_verified=False,
        plan_active_from_publication_as_research_hypothesis=True, real_permission_available=False,
        recovery_clock="5m_SHAPE_TO_1m_CLOSE", opening_average_checks=price_checks,
        opening_average_is_retrospective_price_envelope=True, contract_specs_sha256=SPECS_SHA,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not args.env_file.is_file():
        parser.error("SH_REPROTECTION_OUTPUT_EXISTS_OR_ENV_MISSING")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = compare(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "SH_REPROTECTION_LOCAL_MDS_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('SH_REPROTECTION_') and code.isidentifier() else 'SH_REPROTECTION_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
