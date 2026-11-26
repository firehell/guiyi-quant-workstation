"""Compare the portfolio's immediate and deferred protection clocks on fixed original shorts."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405.protection_band import active_band, visible_bands
from lms405_portfolio_protection_gate import plan_rows
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_portfolio_task_policy import published_protection_events
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_route_comparison import FROZEN_ROUTES
from lms405_protection_timeframes import read_window
from lms405_right_side_study import US
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

MODES = {"IMMEDIATE": False, "WAIT_FOR_VALID_FIRST_TOUCH": True}


def price_gate(bars, gate, *, tick, lots, totals):
    """Lower bound on lots outside the eligible price window, conditional on that quote prefix."""
    earlier = [bar for bar in bars if bar.start <= gate]
    later = [bar for bar in bars if gate < bar.start]
    counts = earlier_lot_counts(tick_bounds(earlier, tick), tick_bounds(later, tick), lots, totals)
    return dict(minimum_lots_outside_window=min(counts, default=None), whole_leg_compatible=0 in counts)


def compare_quote(minutes, anchor, contact, candidates, *, tick, lots, totals):
    results = {}
    for boundary, rows in (
        ("BEFORE_QUOTE_MINUTE", [bar for bar in minutes if bar.end < anchor]),
        ("INCLUDE_ENTIRE_QUOTE_MINUTE", [bar for bar in minutes if bar.end <= anchor]),
    ):
        whole_prefix_possible = bool(earlier_lot_counts(None, tick_bounds(rows, tick), lots, totals))
        kwargs = dict(tick=tick, lots=lots, totals=totals)
        result = dict(price_possible_without_clock=whole_prefix_possible)
        if contact is not None and contact.end <= anchor and whole_prefix_possible:
            result.update(from_touch_minute_start=price_gate(rows, contact.start - US, **kwargs),
                          strictly_after_touch_is_known=price_gate(rows, contact.end + US, **kwargs))
        for mode, events in candidates.items():
            event = next((row for row in events if row["at"] < anchor), None)
            result[mode] = price_gate(rows, event["at"], **kwargs) if whole_prefix_possible and event else None
        results[boundary] = result
    return results | dict(touch_known_strictly_before_quote=bool(contact and contact.end + US < anchor),
                          touch_shares_quote_minute=bool(contact and contact.end == anchor))


def inspect(series, row, plans):
    start, cutoff = (datetime.fromisoformat(row[key]) for key in ("start", "cutoff"))
    minutes = completed(series[1], start, cutoff)
    anchors = [bar.end for bar in minutes if bar.low <= Decimal(row["mark"]) <= bar.high]
    if not minutes or not anchors or minutes[0].start != start:
        raise ValueError("PROTECTION_CLOCK_CASE_WINDOW_CHANGED")
    if row["anchors"] and anchors != [datetime.fromisoformat(value) for value in row["anchors"]]:
        raise ValueError("PROTECTION_CLOCK_CASE_QUOTE_CHANGED")
    low, high = map(Decimal, row["band"])
    contract = minutes[0].contract
    band, _ = active_band(visible_bands(plans, contract, start), start, "SHORT")
    if band is None or band.source != row["plan"]["source_url"] or (band.lower, band.upper) != (low, high):
        raise ValueError("PROTECTION_CLOCK_CASE_PLAN_SCOPE_CHANGED")
    contact = next((bar for bar in minutes if bar.low <= high and low <= bar.high), None)
    # The hypothetical original short predates the plan. Do not infer when the
    # public screenshot was captured or create new signals from its prices.
    initial = {period: [bar for bar in group if start <= bar.start] for period, group in series.items() if period in (1, 5)}
    by_mode = {key: published_protection_events(initial, plans, cutoff, advance_at_touch=wait)
               for key, wait in MODES.items()}
    if any(event["band"] != band for events in by_mode.values() for event in events):
        raise ValueError("PROTECTION_CLOCK_CASE_REVISED_CANDIDATE_SCOPE")
    for anchor in anchors:
        prefix = {period: [bar for bar in group if bar.end + US < anchor] for period, group in initial.items()}
        for key, wait in MODES.items():
            if published_protection_events(prefix, plans, anchor, advance_at_touch=wait) != [
                event for event in by_mode[key] if event["at"] < anchor
            ]:
                raise ValueError("PROTECTION_CLOCK_CASE_PREFIX_DIVERGED")
    tick, lots = Decimal(row["tick"]), row["long"]["quantity"]
    totals = displayed_tick_totals(Decimal(row["average"]), lots, tick)
    if (row["long"]["today_quantity"] != lots or row["short"]["quantity"] != lots
            or row["short"]["today_quantity"] != 0 or row["long"]["opening_average"] is None
            or Decimal(row["average"]) != Decimal(row["long"]["opening_average"])):
        raise ValueError("PROTECTION_CLOCK_CASE_POSITION_SCOPE_CHANGED")
    comparisons = {stamp.isoformat(): compare_quote(minutes, stamp, contact, by_mode, tick=tick, lots=lots,
                                                    totals=totals) for stamp in anchors}
    return dict(
        status="HYPOTHETICAL_ORIGINAL_SHORT_BEFORE_PLAN", plan=row["plan"], image=row["photo"],
        original_short=row["short"], displayed_long=row["long"],
        active_band_scope=band.scope, range=[low, high], quote_mark=row["mark"], tick_size=tick,
        market=row["market"], observed_mean_allowed_tick_totals=[totals.start, totals.stop - 1],
        first_range_touch_minute_end=contact.end if contact else None,
        candidates={key: [dict(available=row["at"], operation=row["operation"], confirmation=row["signal"]["confirmed_at"],
                               touch_known_at=row.get("touch_known_at"), period=row["period"], revision=row["band"].revision)
                          for row in rows] for key, rows in by_mode.items()},
        quote_checks=comparisons, candle_prefix_checks=len(anchors) * len(MODES),
        account_scope_verified=False, actual_capture_at=None, author_action_at=None,
    )


def study(session, market):
    by_day = verified_json(*FROZEN_ROUTES)["case_days"]
    cases, index = {}, input_sources()
    for day, group in by_day.items():
        for contract, case in group.items():
            if "inputs" not in case:
                continue
            row = case["inputs"]
            for proof in (row["photo"], dict(path=row["plan"]["archive_path"], sha256=row["plan"]["archive_sha256"])):
                if sha((ARCHIVE.parent / proof["path"]).read_bytes()) != proof["sha256"]:
                    raise ValueError("PROTECTION_CLOCK_CASE_EVIDENCE_CHANGED")
            series = read_window(session, market, contract, date.fromisoformat(row["trading_day"]))
            if {f"{period}m": digest(bars) for period, bars in series.items()} != row["market"]:
                raise ValueError("PROTECTION_CLOCK_CASE_MARKET_CHANGED")
            identity = f"{day}/{contract}"
            if row["band"] is None:
                cases[identity] = dict(status="NO_TYPED_PROTECTION_REFERENCE", plan=row["plan"], image=row["photo"])
                continue
            plans, _, _ = plan_rows(index, contract)
            cases[identity] = inspect(series, row, plans)
    return dict(version="lms405-protection-clock-cases-v1", cases=cases, source_report_sha256=FROZEN_ROUTES[1],
                author_action_samples=0, author_match_rate=None, real_permission_supplied=False,
                executable=False, fills=None, pnl=None)


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
        parser.exit(2, f"{code if code.startswith('PROTECTION_CLOCK_CASE_') and code.isidentifier() else 'PROTECTION_CLOCK_CASE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
