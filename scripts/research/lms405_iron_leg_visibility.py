"""Bound I2701 protection continuity and release clocks without treating a missing row as flat."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_i2701_case import DAYS, FROZEN_COMPARISON_SHA256, readback
from lms405_m_permission_study import read_pair
from lms405_oi_leg_intent import CONTINUITY, CONTINUITY_SHA
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, latest_whole_leg_start, tick_bounds, verified_json
from lms405_reversal_stage_bounds import SPECS_SHA
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import CLOSE, LUNCH, NIGHT, signals
from lms405_sh_protection_replacement import compatible_counts
from lms405_sizing_audit import SPECS, load_specs
from lms_near405_replay import encoded, sha

CONTRACT = "I2701"
QUOTE_REPORT = Path("output/lms-i2701-oct-20261125/comparison.json")
NEAR, FAR = Decimal("662.5"), Decimal("654")
PERIODS = ((1, 1), (5, 1), (5, 5))


def quote_clock_counts(quote_ends, available_at):
    before = [end for end in quote_ends if available_at is not None and available_at < end - ONE]
    within = [end for end in quote_ends if available_at is not None and end - ONE <= available_at < end]
    return dict(known_before_entire_quote_minute=len(before), known_during_quote_minute=len(within),
                not_known_before_quote_minute_end=len(quote_ends) - len(before) - len(within))


def bounds_for_later_opens(all_minutes, noon, close, tick, lots, totals):
    old = tick_bounds([bar for bar in all_minutes if bar.end <= noon], tick)
    afternoon = [bar for bar in all_minutes if bar.start > noon + US and bar.end <= close]
    last = latest_whole_leg_start(afternoon, tick, lots, totals, start_of=lambda bar: bar.start)
    if last is None:
        raise ValueError("IRON_VISIBILITY_NO_COMPLETE_REBUILD_WINDOW")
    last = datetime.fromisoformat(last)

    def case(start):
        pool = [bar for bar in afternoon if bar.start >= start]
        prices = tick_bounds(pool, tick)
        possible = compatible_counts(lots, totals, totals, old, prices, None)
        if not possible:
            raise ValueError("IRON_VISIBILITY_OLD_POSITION_OUTSIDE_ENVELOPE")
        return dict(first_start=start, minute_count=len(pool), ticks=prices,
                    feasible_retained=sorted({row[0] for row in possible}),
                    minimum_retained=min(row[0] for row in possible))

    return dict(earlier_tick_bounds=old, noon_to_close=case(afternoon[0].start),
                last_possible_whole_rebuild=case(last), next_minute_start=case(last + ONE))


def study(session, market):
    quoted = verified_json(QUOTE_REPORT, FROZEN_COMPARISON_SHA256)
    continuity = verified_json(CONTINUITY, CONTINUITY_SHA)
    rows = {row["later"]: row["later_legs"] for row in continuity["contracts"][CONTRACT]["transitions"]}
    sources = {post: continuity["sources"][post] for post in (LUNCH, CLOSE, NIGHT)}
    for row in sources.values():
        image = row["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("IRON_VISIBILITY_POSITION_IMAGE_CHANGED")
    midday, closing, overnight = (rows[post] for post in (LUNCH, CLOSE, NIGHT))
    if (not midday["short"] == closing["short"] == overnight["short"]
            or midday["short"]["quantity"] != 16 or midday["short"]["today_quantity"] != 0
            or overnight.get("long", {}).get("quantity") is not None
            or midday["long"]["quantity"] != 16 or closing["long"]["quantity"] != 16
            or midday["long"]["today_quantity"] != 16 or closing["long"]["today_quantity"] is not None
            or not Decimal(midday["long"]["opening_average"]) == Decimal(closing["long"]["opening_average"]) == Decimal("663.34")):
        raise ValueError("IRON_VISIBILITY_POSITION_FIELDS_CHANGED")
    noon, close = (datetime.fromisoformat(sources[post]["quote_anchor"]) for post in (LUNCH, CLOSE))
    raw, bars = read_pair(session, market, CONTRACT, DAYS)
    fingerprints = {p: readback(series) for p, series in raw.items()}
    if fingerprints[1] != quoted["market_1m"]["i"] or fingerprints[5] != quoted["i2701_5m"]:
        raise ValueError("IRON_VISIBILITY_MARKET_CHANGED")
    tick = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]["tick"]
    totals = displayed_tick_totals(Decimal("663.34"), 16, tick)
    day_minutes = [bar for bar, item in zip(bars[1], raw[1], strict=True) if item.trading_day == DAYS[0]]
    same_average = bounds_for_later_opens(day_minutes, noon, close, tick, 16, totals)
    same_average["requires"] = ("SAME_ACCOUNT", "SAME_OPENING_AVERAGE_CONVENTION",
                                "QUOTE_AND_POSITION_CAPTURE_SYNCHRONIZED")
    same_average["afternoon_contiguous_long_candidates"] = {
        f"{shape}m_to_{confirm}m": signals(bars, shape, confirm, side="LONG", start=noon + US, cut=close + 2 * US)
        for shape, confirm in PERIODS
    }
    night_start = at("2026-10-27T21:00")
    night_cut = datetime.fromisoformat(sources[NIGHT]["published_at"])
    overnight_minutes = [bar for bar in bars[1] if night_start <= bar.start and bar.end + US < night_cut]
    prices = {part: row for part, row in quoted["photos"][NIGHT]["per_symbol"].items()}
    displayed = Decimal(prices["i"]["mark"])
    individual = [bar.end for bar in overnight_minutes if bar.low <= displayed <= bar.high]
    if individual != [datetime.fromisoformat(value) for value in prices["i"]["contains"]]:
        raise ValueError("IRON_VISIBILITY_QUOTE_CLOCKS_CHANGED")
    joint_six = sorted(set.intersection(*[set(map(datetime.fromisoformat, row["contains"]))
                                          for symbol, row in prices.items() if symbol != "sh"]))
    if quoted["photos"][NIGHT]["joint_contains"] or not joint_six:
        raise ValueError("IRON_VISIBILITY_PARTIAL_QUOTE_CHANGED")
    clocks = {}
    for periods in PERIODS:
        rows_for_variant = signals(bars, *periods, side="SHORT", start=night_start, cut=night_cut)
        clocks[f"geometry_{periods[0]}m_to_{periods[1]}m"] = next((row["available_at"] for row in rows_for_variant), None)
    for label, level in (("first_strict_close_below_near", NEAR), ("first_strict_close_below_far", FAR)):
        clocks[label] = next((bar.end + US for bar in overnight_minutes if bar.close < level), None)
    gate_cases = {label: dict(known_at=clock, iron_quote_candidates=quote_clock_counts(individual, clock),
                              six_symbol_partial_candidates=quote_clock_counts(joint_six, clock))
                  for label, clock in clocks.items()}
    return dict(version="lms405-iron-leg-visibility-v1", contract=CONTRACT, market=fingerprints,
                snapshots={post: dict(image=sources[post]["image"], quote_anchor=sources[post]["quote_anchor"],
                                     displayed_legs=legs) for post, legs in zip((LUNCH, CLOSE, NIGHT), (midday, closing, overnight), strict=True)},
                inputs=dict(quote_sha256=FROZEN_COMPARISON_SHA256, continuity_sha256=CONTINUITY_SHA, specs_sha256=SPECS_SHA),
                minimum_tick=tick, long_opening_average_as_displayed="663.34", compatible_integer_tick_totals=list(totals),
                daytime_same_average=same_average,
                overnight_if_missing_long_is_confirmed_zero=dict(
                    assumption_only=True, requires=("SAME_ACCOUNT", "COMPLETE_POSITION_SCOPE", "NIGHT_LONG_IS_ZERO",
                                                    "QUOTE_AND_POSITION_CAPTURE_SYNCHRONIZED"),
                    iron_quote_minutes=individual, six_symbol_partial_quote_minutes=joint_six,
                    all_symbols_joint_quote_minutes=[], timing_sensitivity=gate_cases,
                ), actual_overnight_long_lots=None, actual_release_time=None, author_action_samples=0,
                executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    load_dotenv(args.env_file, override=False)
    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "IRON_VISIBILITY_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
