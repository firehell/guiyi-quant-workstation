"""Compare published single-point recovery with a prior protection bar's boundary."""

import argparse
import csv
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.handoff import Handoff
from guiyi_quant.lms405.minute_recovery import assess_minute_recovery
from guiyi_quant.lms405.recovery_permission import MinuteRecoveryPermission
from lms405_portfolio_recovery_shape_lifetime import compare as compare_shape_lifetime
from lms405_protection_lot_timing import (
    compatible_allocations,
    displayed_tick_totals,
    earlier_lot_counts,
    tick_bounds,
    verified_json,
)
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_recovery_confirmation_audit import edge_candidates, strict_runs
from lms405_right_side_study import ONE, US, at
from lms405_unlock_boundary_comparison import evaluate
from lms_near405_replay import encoded, sha

CONTRACT = "JM2509"
DAY = date(2025, 7, 22)
SOURCE_INDEX = Path("docs/research/lms405/evidence/signal-chain-20261017.csv")
FROZEN = Path(
    "output/lms405-jm2509-july22-20261017/market-read-authorized/JM2509_2025-07-21_2025-07-22_5m.csv",
)
FROZEN_SHA = "71c668cc3874cfdcb1c52b47c26615a89ed455977bfb5c80883a9e18b3cb91b3"
PRICE_LEVELS = {"published_recovery_point": Decimal("1025.5"), "early_ibar_low_proxy": Decimal("1026.5")}
RECOVERY_REFERENCE = Path("output/lms405-jm-july-recovery-20261125/final.json")
RECOVERY_REFERENCE_SHA = "bf5ee9333bbef15285d3cd45210023c347642feca3241c02ac90f0f4bf3cb0d0"
PROTECTION_REFERENCE = RECOVERY_REFERENCE.with_name("protection-origin.json")
PROTECTION_REFERENCE_SHA = "4d45113813a483fa790ad9cc03f79d902ba0c518645912da77d845270c94825f"


def source_records():
    with SOURCE_INDEX.open(newline="", encoding="utf-8") as stream:
        rows = {row["id"]: row for row in csv.DictReader(stream)}
    return {key: rows[key] for key in ("H06", "H08", "H11")}


def compare(series, start, cut, edge):
    minutes = [bar for bar in series[1] if bar.start >= start and bar.end + US < cut]
    runs = strict_runs(minutes, edge, "LONG")
    args = dict(start=start, cut=cut, side="LONG", band=(edge, edge))
    qualified = evaluate(series, **args)
    clocks = {}
    for period, confirm in VARIANTS:
        events = geometry_events(series, period, confirm, start=start, as_of=cut, side="LONG")
        qualified_pair = [event for event in qualified["candidates"]
                          if (event["shape_minutes"], event["confirm_minutes"]) == (period, confirm)]
        same_period = [bar for bar in series[confirm] if bar.start >= start and bar.end + US < cut]
        period_match = edge_candidates(same_period, events, edge, "LONG")
        clocks[f"{period}m_to_{confirm}m"] = dict(
            geometry_count=len(events),
            first_confirmed_outside=next((event for event in events if event["close"] > edge), None),
            first_fresh_two_minute_closes=next(iter(qualified_pair), None),
            first_fresh_two_confirmation_period_closes=period_match["first_shape_after_fresh_cross_and_still_beyond"],
        )
    stop_points = {row["available_at"] for row in qualified["candidates"]}
    if qualified["first_far_reach_known_at"] is not None:
        stop_points.add(qualified["first_far_reach_known_at"])
    stops = stop_points | {point + US for point in stop_points}
    for stop in sorted(stops):
        prefix = {p: [bar for bar in bars if bar.end + US < stop] for p, bars in series.items()}
        earlier = evaluate(prefix, **(args | {"cut": stop}))
        reach = qualified["first_far_reach_known_at"]
        if earlier["candidates"] != [row for row in qualified["candidates"] if row["available_at"] < stop] or (
            earlier["first_far_reach_known_at"] != (reach if reach is not None and reach < stop else None)
        ):
            raise ValueError("JULY_RECOVERY_CLOCK_PREFIX_DIVERGED")
    return dict(
        level=edge, minute_count=len(minutes), first_reach_known_at=qualified["first_far_reach_known_at"],
        first_geometric_candidates=clocks, checked_prefixes=len(stops),
        first_close_outside=next(iter(runs), None),
        first_fresh_two_closes=next((end for end, run in runs.items() if run["close_count"] >= 2
                                     and run["fresh_crossing_known_at"] is not None), None),
        candidates=qualified["candidates"], extrema=[min(bar.low for bar in minutes), max(bar.high for bar in minutes)],
    )


def protection_origin(series, published):
    quantity, average, tick = 16, Decimal("1026.69"), Decimal("0.5")
    totals = displayed_tick_totals(average, quantity, tick)
    high_precision_average = tuple(Decimal(total) * tick / quantity for total in totals)
    day_open = at(f"{DAY}T09:00")
    point = PRICE_LEVELS["early_ibar_low_proxy"]
    windows = {}
    for source_id in ("H06", "H11"):
        minutes = [bar for bar in series[1] if bar.end + US < published[source_id]]
        day_minutes = [bar for bar in minutes if bar.start >= day_open]
        bar_5m = [bar for bar in series[5] if bar.start >= day_open and bar.end + US < published[source_id]]
        shape = next(bar for bar in bar_5m if bar.end == at(f"{DAY}T09:10"))
        if shape.low != point:
            raise ValueError("JULY_PROTECTION_POINT_CHANGED")
        later_than_shape = [bar for bar in day_minutes if bar.start >= shape.end]
        gates = {
            "protection_shape_completed": shape,
            "first_intraminute_strict_break_bar": next(b for b in later_than_shape if b.low < point),
            "first_minute_strict_close_below": next(b for b in later_than_shape if b.close < point),
            "first_five_minute_strict_close_below": next(b for b in bar_5m if b.start >= shape.end and b.close < point),
        }
        bounds = {}
        for key, gate in gates.items():
            strict_after = [bar for bar in minutes if bar.start > gate.end + US]
            inclusive_after = [bar for bar in minutes if bar.end > gate.end]
            if key == "first_intraminute_strict_break_bar":
                # The minute contains the first breach. Its OHLC cannot place prices before or after the breach.
                inclusive_after.insert(0, gate)
            later = {}
            for rule, eligible in (("with_overlapping_minute", inclusive_after), ("complete_minutes_only", strict_after)):
                boundary = eligible[0].start if eligible else gate.end
                windows_before = {name: tick_bounds([bar for bar in window if bar.end <= boundary], tick)
                                  for name, window in (("same_trading_day", minutes), ("day_session", day_minutes))}
                after = tick_bounds(eligible, tick)
                minima = {name: min(earlier_lot_counts(before, after, quantity, totals), default=None)
                          for name, before in windows_before.items()}
                later[rule] = dict(after_high=Decimal(after[1]) * tick if after else None,
                                   eligible_minutes=len(eligible), earlier_window_tick_bounds=windows_before,
                                   minimum_quantity_outside_after_window=minima)
            bounds[key] = dict(bar_end=gate.end, high=gate.high, low=gate.low, close=gate.close, variants=later)
        windows[source_id] = dict(cutoff_exclusive=published[source_id], gates=bounds,
                                  trading_day_minutes=len(minutes), day_session_minutes=len(day_minutes))
    return dict(
        version="lms405-jm-july-protection-origin-v1", quantity=quantity, average_shown=average, price_tick=tick,
        quantity_source="H11", source_use="H06_ASSUME_SAME_SHOWN_LEG_H11_CONFIRMATION",
        rounding="ASSUMED_HALF_UP", possible_tick_sums=list(totals), possible_exact_average=high_precision_average,
        windows=windows, action_interval_unknown=True,
    )


def protection_stages(series, published, shared):
    reference = verified_json(PROTECTION_REFERENCE, PROTECTION_REFERENCE_SHA)
    if any(shared[key] != reference[key] for key in ("sources", "source_index_sha256", "market")):
        raise ValueError("JULY_PROTECTION_STAGE_REFERENCE_CHANGED")

    lots, tick = reference["quantity"], Decimal(reference["price_tick"])
    totals = displayed_tick_totals(Decimal(reference["average_shown"]), lots, tick)
    point = PRICE_LEVELS["early_ibar_low_proxy"]
    edge_tick = int(point / tick)
    day_open = at(f"{DAY}T09:00")
    windows = {}
    for source_id, window in reference["windows"].items():
        breach_end, confirm_end = (datetime.fromisoformat(window["gates"][gate]["bar_end"]) for gate in (
            "first_intraminute_strict_break_bar", "first_minute_strict_close_below",
        ))
        minutes = [bar for bar in series[1] if bar.end + US < published[source_id]]
        breach = next(bar for bar in minutes if bar.end == breach_end)
        confirm = next(bar for bar in minutes if bar.end == confirm_end)
        if breach.end != confirm.start or not breach.low < point == breach.close or not confirm.close < point:
            raise ValueError("JULY_PROTECTION_STAGE_CLOCK_CHANGED")
        scenarios = {}
        for end in (breach.end, confirm.end):
            middle = tick_bounds([bar for bar in minutes if breach.start < bar.end <= end], tick)
            # Apply the cap only if every opening in this minute is assumed to follow the breach.
            capped = (middle[0], min(middle[1], edge_tick))
            later = tick_bounds([bar for bar in minutes if bar.start >= end], tick)
            if later is None or later[1] > edge_tick:
                raise ValueError("JULY_PROTECTION_STAGE_LATER_RETRACE_CHANGED")
            for start in (minutes[0].start, day_open):
                earlier = tick_bounds([bar for bar in minutes if start <= bar.start < breach.start], tick)
                for key, eligible in (("whole_break_range", middle), ("break_triggered_without_retrace", capped)):
                    bounds = (earlier, eligible, later)
                    matches = compatible_allocations(lots, totals, bounds)
                    label = f"{end.isoformat()}/{start.isoformat()}/{key}"
                    scenarios[label] = dict(
                        start=start, before=breach.start, middle_ends_at=end, observed_through=minutes[-1].end,
                        constraint=key, bounds_in_ticks=bounds, allocations=matches,
                    )
        windows[source_id] = dict(break_minute=asdict(breach), close_confirmation_minute=asdict(confirm),
                                  scenarios=scenarios)
    return shared | dict(
        version="lms405-jm-july-protection-stages-v1", input_reference_sha256=PROTECTION_REFERENCE_SHA,
        lot_order=("before_break_minute", "break_to_cut", "from_cut_to_observation"),
        lots=lots, tick_size=tick, ibar_low_candidate=point, possible_tick_sums=list(totals), windows=windows,
    )


def recovery_lifetime(series, start, cutoff, shared, *, batch):
    reference = verified_json(RECOVERY_REFERENCE, RECOVERY_REFERENCE_SHA)
    if any(shared[name] != reference[name] for name in ("sources", "market", "source_index_sha256")):
        raise ValueError("JULY_RECOVERY_LIFETIME_REFERENCE_CHANGED")
    if (start, cutoff) != tuple(datetime.fromisoformat(reference[k]) for k in ("start", "cutoff_exclusive")):
        raise ValueError("JULY_RECOVERY_LIFETIME_SCOPE_CHANGED")
    request = Handoff("RESUME_ORIGINAL", Position(CONTRACT, Decimal(16), Decimal(16)), "LONG",
                      "july-H06-research-plan", "july-H11-assumed-lock", None, start, start)
    cuts = [bar.end + 2 * US for bar in series[1] if bar.start >= start and bar.end + 2 * US < cutoff]
    scopes = {}
    for label, edge in PRICE_LEVELS.items():
        lifetime = compare_shape_lifetime(series, start, cutoff, side="LONG", edge=edge,
                                          include_bounded=batch == "recovery-bounded",
                                          include_recross=batch == "recovery-recross")
        current = {}
        for period in (1, 5):
            # Shared source clocks, but both period permission and snapshot continuity are hypothetical.
            permit = MinuteRecoveryPermission(CONTRACT, request.plan_id, request.cycle_id, "LONG", start, start + US,
                                              "PERMIT", "NEAR", edge, "JULY_LIFETIME_TEST_FIXTURE", "TEST_FIXTURE",
                                              shape_minutes=period)
            proposals = []
            for as_of in cuts:
                opts = dict(as_of=as_of, permissions=(permit,), allow_test_fixture=True, version_405=True)
                full = assess_minute_recovery(request, series[1], series[5], **opts)
                prior = {p: [b for b in series[p] if b.end + US < as_of] for p in (1, 5)}
                if full != assess_minute_recovery(request, prior[1], prior[5], **opts) or full["after"] is not None:
                    raise ValueError("JULY_RECOVERY_LIFETIME_PREFIX_DIVERGED")
                if full["proposal"] is not None:
                    proposals.append(full["proposal"])
            current[str(period)] = proposals
        scopes[label] = dict(edge=edge, shape_lifetime_comparison=lifetime, current_minute_proposals=current,
                             minute_evaluator_prefix_checks=2 * len(cuts))
    return shared | dict(
        version={"recovery-bounded": "lms405-jm-july-recovery-lifetime-bounded-v1",
                 "recovery-recross": "lms405-jm-july-recovery-recross-v1",
                 "recovery-lifetime": "lms405-jm-july-recovery-lifetime-v1"}[batch],
        comparisons=scopes, start=start, cutoff_exclusive=cutoff,
        input_reference_sha256=RECOVERY_REFERENCE_SHA, author_permission=None, author_version_405=None,
        counterfactual_minute_permission=True, account_continuity=None,
    )


def study(session, market, *, batch="recovery-clock"):
    sources = source_records()
    published = {key: datetime.fromisoformat(row["published_at"]) for key, row in sources.items()}
    start, cutoff = max(published["H06"], published["H11"]) + ONE, published["H08"]
    series = read_window(session, market, CONTRACT, DAY)
    if sha(FROZEN.read_bytes()) != FROZEN_SHA:
        raise ValueError("JULY_RECOVERY_FROZEN_CSV_CHANGED")
    with FROZEN.open(newline="", encoding="utf-8") as stream:
        original = [(datetime.fromisoformat(row["bar_end_utc"]),
                     *(Decimal(row[key]) for key in ("open", "high", "low", "close")))
                    for row in csv.DictReader(stream) if row["bar_end_shanghai"].startswith(DAY.isoformat())]
    matching = [(bar.end, bar.open, bar.high, bar.low, bar.close) for bar in series[5]]
    if not original or original != [row for row in matching if row[0] >= original[0][0]]:
        raise ValueError("JULY_RECOVERY_DAY_5M_MISMATCH")
    shared = dict(
        contract=CONTRACT, trading_day=DAY, sources=sources, source_index_sha256=sha(SOURCE_INDEX.read_bytes()),
        market={f"{p}m": dict(count=len(rows), sha256=sha(encoded([
            (bar.start, bar.end, bar.open, bar.high, bar.low, bar.close) for bar in rows
        ]).encode())) for p, rows in series.items()}, frozen_5m_sha256=FROZEN_SHA,
        author_action_time=None, author_signal_time=None, author_match_rate=None, admitted_author_action_samples=0,
        executable=False, fills=None, pnl=None,
    )
    if batch == "protection-origin":
        return shared | protection_origin(series, published)
    if batch == "protection-stages":
        return protection_stages(series, published, shared)
    if batch in ("recovery-lifetime", "recovery-bounded", "recovery-recross"):
        return recovery_lifetime(series, start, cutoff, shared, batch=batch)
    return shared | dict(
        version="lms405-jm-july-recovery-clock-v1",
        start=start, cutoff_exclusive=cutoff,
        case_scope="REPORTED_LMS_RECOVERY_VERSION_AND_TIME_UNVERIFIED",
        comparisons={key: compare(series, start, cutoff, edge) for key, edge in PRICE_LEVELS.items()},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", choices=("recovery-clock", "protection-origin", "protection-stages", "recovery-lifetime",
                                            "recovery-bounded", "recovery-recross"),
                        default="recovery-clock")
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session), batch=args.batch)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, StopIteration, ValueError):
        parser.exit(2, "JULY_RECOVERY_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
