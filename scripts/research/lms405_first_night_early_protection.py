"""Compare earlier resistance, protection-area contact and known confirmation for the first-night long legs."""

from argparse import ArgumentParser
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from operator import attrgetter
from pathlib import Path

from lms405_first_night_confirmation_clocks import DAY, POST, START, price_envelope
from lms405_first_night_pa import REFERENCE, REFERENCE_HASH
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import (
    displayed_tick_totals,
    earlier_lot_counts,
    latest_whole_leg_start,
    tick_bounds,
    verified_json,
)
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import US
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

PREVIOUS_DAY = date(2026, 10, 22)
PRIOR_PLAN, CURRENT_PLAN = "A5356507058536457", "A5356884629782554"
CASES = {
    "FG2701": ("827 829", "829 836", "841 852"),
    "SA2701": ("926 931", "931 936", None),
    "JM2701": ("1375 1382.5", "1382.5 1397.5", "1424.5 1436.5"),
}


def touched(bars, band):
    if band is None:
        return None
    lo, hi = band
    return next((bar for bar in bars if bar.low <= hi and lo <= bar.high), None)


def after_price_paths(minutes, gate_bar, *, tick, lots, totals):
    if gate_bar is None or gate_bar.end > minutes[-1].end:
        return None
    # Treat the entire touch minute as potentially after the intraminute event.
    before = [bar for bar in minutes if bar.end < gate_bar.end]
    overlap_or_later = [bar for bar in minutes if bar.end >= gate_bar.end]
    counts = earlier_lot_counts(tick_bounds(before, tick), tick_bounds(overlap_or_later, tick), lots, totals)
    return dict(
        minimum_before_touch_minute=min(counts, default=None),
        quote_and_touch_share_minute=minutes[-1].end == gate_bar.end,
        after_completed_touch_minute=price_envelope(
            minutes, {"available_at": gate_bar.end + US}, tick, lots, totals, minutes[-1].end,
        )["minimum_lots_outside_later_minutes"],
    )


def minimum_outside_directional_near(minutes, level, *, tick, lots, totals):
    lo, hi = tick_bounds(minutes, tick)
    threshold = level / tick
    if threshold != int(threshold):
        raise ValueError("EARLY_PROTECTION_OFF_TICK_NEAR")
    below = (lo, min(hi, int(threshold) - 1)) if lo < threshold else None
    at_or_above = (max(lo, int(threshold)), hi) if hi >= threshold else None
    counts = earlier_lot_counts(below, at_or_above, lots, totals)
    return min(counts, default=None)


def study(session, market):
    reference = verified_json(REFERENCE, REFERENCE_HASH)
    photo = reference["photo"]
    if sha((ARCHIVE.parent / photo["path"]).read_bytes()) != photo["sha256"]:
        raise ValueError("EARLY_PROTECTION_PHOTO_CHANGED")
    index = input_sources()
    sources = {key: load_source(index, key) for key in (PRIOR_PLAN, CURRENT_PLAN, "WRo0YIbejU", "WRo11edvNX")}
    cases = {}
    for contract, raw_bands in CASES.items():
        case = reference["cases"][contract]
        if case["plan"] != sources[CURRENT_PLAN]:
            raise ValueError("EARLY_PROTECTION_PLAN_CHANGED")
        series = read_window(session, market, contract, DAY)
        if {f"{p}m": digest(bars) for p, bars in series.items()} != case["market"]:
            raise ValueError("EARLY_PROTECTION_MARKET_CHANGED")
        minutes = completed(series[1], START, POST)
        prior_day = read_window(session, market, contract, PREVIOUS_DAY)[1]
        if prior_day[-1].end >= START or minutes[0].start != START:
            raise ValueError("EARLY_PROTECTION_SESSION_CHANGED")
        resist, protect, old = tuple(tuple(map(Decimal, raw.split())) if raw else None for raw in raw_bands)
        if protect != tuple(map(Decimal, case["protection_band"])):
            raise ValueError("EARLY_PROTECTION_BAND_CHANGED")
        long, short = case["displayed_long"], case["original_short"]
        lots, tick, avg = long["quantity"], Decimal(case["tick"]), Decimal(case["average"])
        if lots != long["today_quantity"] or short["today_quantity"] != 0:
            raise ValueError("EARLY_PROTECTION_TODAY_FIELDS_CHANGED")
        totals = displayed_tick_totals(avg, lots, tick)
        quote = Decimal(case["quote"])
        anchors = [b.end for b in minutes if b.low <= quote <= b.high]
        if anchors != [datetime.fromisoformat(value) for value in case["individual_quote_ends"]]:
            raise ValueError("EARLY_PROTECTION_QUOTE_CHANGED")
        gates = {"current_resistance": resist, "current_protection": protect, "prior_protection": old}
        firsts = {key: touched(minutes, band) for key, band in gates.items()}
        events = [datetime.fromisoformat(v["first_candidate"]["available_at"]) for v in case["clocks"].values()
                  if v["first_candidate"]]
        confirmation = min(events, default=None)
        results = {}
        for end in anchors:
            prefix = [b for b in minutes if b.end <= end]
            if any(touched(prefix, band) != (firsts[key] if firsts[key] and firsts[key].end <= end else None)
                   for key, band in gates.items()):
                raise ValueError("EARLY_PROTECTION_PREFIX_DIVERGED")
            clock = {"available_at": confirmation} if confirmation else None
            results[end.isoformat()] = dict(
                touches={key: after_price_paths(prefix, bar, tick=tick, lots=lots, totals=totals)
                         for key, bar in firsts.items()},
                after_first_confirmation=price_envelope(prefix, clock, tick, lots, totals, end),
                min_lots_below_protection_near=minimum_outside_directional_near(
                    prefix, protect[0], tick=tick, lots=lots, totals=totals),
                latest_full_leg_start=latest_whole_leg_start(prefix, tick, lots, totals, start_of=attrgetter("start")),
                latest_full_leg_start_excluding_quote_minute=latest_whole_leg_start(
                    prefix[:-1], tick, lots, totals, start_of=attrgetter("start")),
            )
        cases[contract] = dict(
            previous_day_close=prior_day[-1].close, prior_day_market_sha=digest(prior_day),
            first_minute=asdict(minutes[0]), bands=gates,
            first_touches={key: asdict(bar) if bar else None for key, bar in firsts.items()},
            first_confirmation_available_at=confirmation,
            visible_long=long, visible_short=short, quote_mark=quote, displayed_tick_totals=list(totals),
            market=case["market"], quote_results=results,
        )
    return dict(
        study="CONDITIONAL_TODAY_LONG_LEG_PRICE_ENVELOPE", trading_day=DAY, cases=cases, sources=sources,
        source_snapshot=reference["photo_source"], photo=photo, reference_sha256=REFERENCE_HASH,
        intraminute_sequence_unknown=True, actual_account_continuity=None, actual_quote_time=None,
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = ArgumentParser(description=__doc__)
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
        parser.exit(2, (code if code.isidentifier() and code.startswith("EARLY_PROTECTION_")
                        else "EARLY_PROTECTION_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
