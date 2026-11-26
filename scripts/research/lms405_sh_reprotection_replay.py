"""Replay scoped SH2701 re-protection with one recovery clock across both cases."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, apply_action
from lms405_carry_in_study import keybar_events
from lms405_counter_m_lot_roles import RETENTION, RETENTION_SHA, exposure
from lms405_exit_position_scope import MIDDAY, NEXT_EARLY, NIGHT, NIGHT_CLOSE, NIGHT_SHA
from lms405_m_permission_study import read_pair
from lms405_oi_leg_intent import SPECS_SHA
from lms405_portfolio_protection_gate import plan_rows
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_pre_touch_protection import analyze
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_snapshot_window import price_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sizing_audit import SPECS, load_specs
from lms405_turnover_replay import TURNOVER, TURNOVER_SHA, compare_tape, state_at, study
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

CONTRACT = "SH2701"
CLOCKS = {"1m_to_1m": (1, 1), "5m_to_1m": (5, 1)}
POLICIES = ("INSIDE_ONLY", "EARLIER_SIGNAL", "FIRST_TOUCH", "SURVIVING_FIRST_TOUCH")
NEW_PLAN = "ADVANCE_REQUIRES_NEW_PLAN"
INTERMEDIATE_SEED = "WRo2KQ43iX"
INTERMEDIATE_SEED_IMAGE = "Ro2KQ43iX-position-screen.png"
INTERMEDIATE_SEED_SHA = "c98d0864d8120f9c4b7276e72d570da113e846952d504f67c877892a6a2a18a6"
MORNING_IMAGE_SHA = "d8503ed169ba33faa3affbcd815549f9a334c227b4ef34ef5fb54bbb3266dd47"
EXIT_SCOPE = Path("output/lms405-exit-position-scope-20261125/final.json")
EXIT_SCOPE_SHA = "9ba998d56d83f28cc6b2f0b7a4a4365b315a1dcbe076ee01b9cdc035f12a6801"


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


def shape_range_admits(shape, confirmed_close, band):
    lower, upper = band
    return confirmed_close > upper and shape.low <= upper and lower <= shape.high


def next_protection(bars, revisions, since, through, clocks, policy, *, allow_shape_touch=False):
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
            shape_period = CLOCKS[clock][0]
            step = timedelta(minutes=shape_period)
            shapes = {bar.end: bar for bar in bars[shape_period]} if allow_shape_touch else {}
            for event in rows:
                if event["shape_end"] - step <= start:
                    continue
                admission = admitted_event(event, policy, refreshed=since < revision.effective_after)
                footprint = {}
                if (admission is None and allow_shape_touch
                        and shape_range_admits(shapes[event["shape_end"]], event["close"], band)):
                    shape = shapes[event["shape_end"]]
                    admission = event["available_at"], "SHAPE_RANGE_CONTACT"
                    footprint = dict(shape_start=shape.start, shape_end=shape.end,
                                     shape_low=shape.low, shape_high=shape.high)
                if admission is None:
                    continue
                known, route = admission
                accepted = known + US
                if accepted < cut:
                    candidates.append(footprint | dict(
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


def tape(bars, recoveries, revisions, seed, seed_at, through, clocks, policy, *, allow_shape_touch=False):
    rows, position, since = [], seed, seed_at
    while since < through:
        if position.long:
            result = next_recovery(recoveries, since, through)
            action = "UNLOCK_SHORT"
        else:
            result = next_protection(bars, revisions, since, through, clocks, policy,
                                     allow_shape_touch=allow_shape_touch)
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


def source_revisions(source_index):
    plans, _, sources = plan_rows(source_index, CONTRACT)
    plans = sorted(plans, key=lambda row: row.effective_after)
    revisions = [(plan, plans[index + 1].effective_after if index + 1 < len(plans) else None)
                 for index, plan in enumerate(plans)]
    return revisions, sources


def compare(session, market, *, shape_range_control=False):
    source_index = input_sources()
    revisions, sources = source_revisions(source_index)
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
        if shape_range_control:
            scenarios["EITHER_SHAPE_CONTACT", NEW_PLAN] = tuple(CLOCKS)
        prices = {}
        for (clock, policy), clock_choices in scenarios.items():
            kwargs = {"allow_shape_touch": clock == "EITHER_SHAPE_CONTACT"}
            full = tape(bars, recovery, revisions, position, seed_at, through, clock_choices, policy, **kwargs)
            for cut in (point["cuts"][0] for point in points):
                if tape(bars, recovery, revisions, position, seed_at, cut, clock_choices, policy, **kwargs) != [
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


def chain_observation(index, frozen, source):
    observed = load_source(index, source)
    field_reread = None
    if source == INTERMEDIATE_SEED:
        path = (ARCHIVE.parent / observed["archive_path"]).with_name(INTERMEDIATE_SEED_IMAGE)
        digest = INTERMEDIATE_SEED_SHA
        legs = {"long": dict(quantity=20, today_quantity=20, opening_average="1568.6"),
                "short": dict(quantity=20, today_quantity=0, opening_average="1720")}
        quotes = []
    else:
        frozen_source = frozen["sources"][source]
        if frozen_source["published_at"] != observed["published_at"]:
            raise ValueError("SH_REPROTECTION_CHAIN_PUBLICATION_CHANGED")
        path = ARCHIVE.parent / frozen_source["image"]["path"]
        digest = frozen_source["image"]["sha256"]
        legs = {side: frozen["observed_rows"][source].get(f"{CONTRACT}/{side}") for side in ("long", "short")}
        quotes = [datetime.fromisoformat(value) for value in frozen["quote_anchors"][source]]
        if source == NEXT_EARLY:
            if digest != MORNING_IMAGE_SHA or legs["long"]["today_quantity"] is not None:
                raise ValueError("SH_REPROTECTION_CHAIN_MORNING_FIELD_CHANGED")
            # The frozen scope report predates the reread of the watermark-covered cells.
            field_reread = dict(field="long.today_quantity", frozen=None, value=20, image_sha256=digest)
            legs["long"] = legs["long"] | {"today_quantity": 20}
    if sha(path.read_bytes()) != digest:
        raise ValueError("SH_REPROTECTION_CHAIN_IMAGE_CHANGED")
    return dict(source=observed, image=dict(path=str(path.relative_to(ARCHIVE.parent)), sha256=digest),
                legs=legs, quote_anchors=quotes, actual_capture_at=None, field_reread=field_reread)


def intermediate_chain(session, market):
    days = date(2026, 10, 26), date(2026, 10, 27)
    raw, bars = read_pair(session, market, CONTRACT, days)
    index = input_sources()
    frozen = verified_json(EXIT_SCOPE, EXIT_SCOPE_SHA)
    night_reference = verified_json(NIGHT, NIGHT_SHA)
    market_identity = {period: bars_sha(series) for period, series in raw.items()}
    if night_reference["market"]["sh"] != {"bars": len(raw[1]), "sha256": market_identity[1]}:
        raise ValueError("SH_REPROTECTION_CHAIN_MARKET_CHANGED")
    observations = {source: chain_observation(index, frozen, source)
                    for source in (INTERMEDIATE_SEED, MIDDAY, NIGHT_CLOSE, NEXT_EARLY)}
    midday, night, morning = (observations[source] for source in (MIDDAY, NIGHT_CLOSE, NEXT_EARLY))
    if (midday["legs"]["long"] is not None or night["legs"]["long"] is not None or morning["quote_anchors"]
            or morning["legs"]["long"]["quantity"] != 20
            or any(leg["quantity"] != 20 or leg["today_quantity"] != 0 or Decimal(leg["opening_average"]) != 1720
                   for leg in (item["legs"]["short"] for item in observations.values()))):
        raise ValueError("SH_REPROTECTION_CHAIN_SCOPE_CHANGED")
    seed_at = datetime.fromisoformat(observations[INTERMEDIATE_SEED]["source"]["published_at"]) + ONE
    through = datetime.fromisoformat(morning["source"]["published_at"])
    seed_quantity = {"long": Decimal(20), "short": Decimal(20)}
    seed = Position(CONTRACT, **seed_quantity)
    revisions, sources = source_revisions(index)
    full_range = sorted(keybar_events(bars[5], raw[1], seed_at, through)["KEYBAR_1M_CLOSE"].items())
    checkpoint_times = (*midday["quote_anchors"], *night["quote_anchors"], through)
    checked = {point for cut in checkpoint_times for point in (cut, cut + 3 * US) if point <= through}
    morning_bars = [bar for bar in bars[1] if at("2026-10-27T09:00") <= bar.start and bar.end + US < through]
    morning_candidates = [bar.end for bar in morning_bars]
    row_quote = Decimal(1500)
    morning_single_row = [bar.end for bar in morning_bars if bar.low <= row_quote <= bar.high]
    day2 = [bar for row, bar in zip(raw[1], bars[1], strict=True) if row.trading_day == days[1]]
    lots = morning["legs"]["long"]["quantity"]
    tick = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]["tick"]
    totals = displayed_tick_totals(Decimal(morning["legs"]["long"]["opening_average"]), lots, tick)
    (night_anchor,) = night["quote_anchors"]
    if [night_anchor] != [datetime.fromisoformat(value) for value in night_reference["quote_alignment"]["joint_contains"]]:
        raise ValueError("SH_REPROTECTION_CHAIN_NIGHT_ANCHOR_CHANGED")
    price_only = price_window([bar for bar in raw[1] if night_anchor < bar.bar_end - ONE
                               and bar.bar_end + US < through], tick, lots, totals)

    policies = {"HOLD_BOTH": []}
    for policy in (*POLICIES, NEW_PLAN):
        rows = tape(bars, full_range, revisions, seed, seed_at, through, tuple(CLOCKS), policy)
        for point in checked:
            raw_prefix = [row for row in raw[1] if row.bar_end + US < point]
            prefix = {period: [bar for bar in group if bar.end + US < point] for period, group in bars.items()}
            recovery = sorted(keybar_events(prefix[5], raw_prefix, seed_at, point)["KEYBAR_1M_CLOSE"].items())
            if tape(prefix, recovery, revisions, seed, seed_at, point, tuple(CLOCKS), policy) != [
                row for row in rows if row["at"] < point
            ]:
                raise ValueError("SH_REPROTECTION_CHAIN_PREFIX_DIVERGED")
        policies[policy] = rows

    results = {}
    for policy, rows in policies.items():
        def has_new_long(cut):
            if state_at(seed_quantity, rows, cut)["long"] != lots:
                return False
            last_lock = next((row for row in reversed(rows) if row["at"] < cut and row["action"] == "LOCK"), None)
            if last_lock is None or last_lock["at"] < day2[0].start:
                return False
            leg = [bar for bar in day2 if last_lock["at"] < bar.start and bar.end + US < cut]
            return bool(earlier_lot_counts(None, tick_bounds(leg, tick), lots, totals))

        possible = [cut for cut in morning_candidates if has_new_long(cut)]
        all_visible_quantities = (
            all(state_at(seed_quantity, rows, cut)["short"] == 20 for cut in checkpoint_times)
            and any(state_at(seed_quantity, rows, cut)["long"] == 20 for cut in morning_candidates)
        )
        midday_missing_as_zero = [cut for cut in midday["quote_anchors"]
                                  if state_at(seed_quantity, rows, cut)["long"] == 0]
        after_night_missing_as_zero = [cut for cut in possible if any(
            state_at(seed_quantity, rows, end)["long"] == 0 for end in night["quote_anchors"]
        )]
        results[policy] = dict(
            simulated_events=rows, visible_quantities_compatible=all_visible_quantities,
            midday_conditional_zero_long_quote_candidates=midday_missing_as_zero,
            night_conditional_zero_long=all(state_at(seed_quantity, rows, end)["long"] == 0
                                            for end in night["quote_anchors"]),
            new_long_price_compatible_at_publication_bound=has_new_long(through),
            new_long_price_compatible_assumed_morning_minutes=possible,
            new_long_price_compatible_single_row_quote_minutes=[cut for cut in possible if cut in morning_single_row],
            complete_table_and_fresh_leg_compatible_morning_minutes=(after_night_missing_as_zero
                                                                    if midday_missing_as_zero else []),
        )

    return dict(version="lms405-sh-intermediate-chain-v1", contract=CONTRACT, observations=observations,
                results=results, plans=sources, assumed_seed_available_at=seed_at, morning_cutoff_exclusive=through,
                plan_windows=[dict(revision=row.revision, role=row.role, available=row.effective_after,
                                   expires=cut) for row, cut in revisions],
                assumed_morning_checkpoints=morning_candidates, actual_snapshot_synchrony_verified=False,
                morning_single_row_quote=dict(value=row_quote, compatible_bar_ends=morning_single_row,
                                              account_scope_verified=False),
                complete_table_case_requirements=("SAME_ACCOUNT", "FULL_DIRECTIONAL_ROWS",
                                                  "QUOTES_AND_HOLDINGS_SYNCHRONOUS", "MISSING_LONG_TREATED_AS_ZERO"),
                price_only_after_night_quote_anchor=price_only,
                complete_scope_verified=False, market=market_identity,
                market_minutes=len(bars[1]), market_fives=len(bars[5]), prefix_checks=len(checked) * len((*POLICIES, NEW_PLAN)),
                cited_scope_sha256=EXIT_SCOPE_SHA, night_anchor_reference_sha256=NIGHT_SHA,
                author_action_samples=0, author_match_rate=None,
                real_permission_available=False, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--shape-range-control", action="store_true")
    modes.add_argument("--intermediate-chain", action="store_true")
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
            market = build_market_data_service(session)
            result = (intermediate_chain(session, market) if args.intermediate_chain else
                      compare(session, market, shape_range_control=args.shape_range_control))
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
