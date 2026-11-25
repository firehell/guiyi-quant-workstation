"""Check whether the visible TA2701 long can have been fully replaced during the pause."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, verified_json
from lms405_protection_timeframes import read_window
from lms405_pta_pause_entry import AVG, CONTRACT, DAY, HOLDINGS, OTHER_SYSTEM, PLAN, SUMMARY, retention_bounds
from lms405_public_plan_roles import load_source
from lms405_replay import photo_comparison, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms405_sizing_audit import SPECS, load_specs
from lms405_v_ta_case import identity
from lms_near405_replay import encoded, sha

VERSION = "lms405-pta-pause-carry-v1"
REFERENCE = Path("output/lms405-pta-pause-entry-20261125/final.json")
REFERENCE_SHA = "dd1b685239a92e01296bdb30277b77a6e406b159bec213c09e72863c38062e65"
SPECS_SHA = "fc430ad455e81d41cdd479f470e26a7a543cac0f427729de150185dfb3e40652"
MORNING, OTHER_MORNING = "WRoql30FdC", "WRoqlD0k9c"
MORNING_IMAGE = "02-持仓记录/2026-10-26/Roql30FdC-position-screen.png"
MORNING_IMAGE_SHA = "a04a15ffe26365621b062208cfc8cd808c56e624ee2bdaae5444c0641eada52c"
OTHER_IMAGE = "02-持仓记录/2026-10-26/WRoqlD0k9c-screen.png"
OTHER_IMAGE_SHA = "c5d8379b4ef41c18c6e5085716a72cf03f4596d7ceeeaf792bb624caf7920efd"
MORNING_MARKS = {"ta": "6602", "v": "5223", "sa": "952", "jm": "1400", "rb": "3040",
                 "sh": "1547", "i": "668.5", "ru": "19760"}


def lot_survival(minutes, before, after, *, tick, lots, totals):
    pairs = retention_bounds(minutes, before, after, tick=tick, lots=lots, totals=totals)
    if not pairs:
        raise ValueError("PTA_CARRY_NO_ORDERED_QUOTE_PAIRS")
    minimum = min(row["min_retained"] for row in pairs.values())
    return dict(quote_pairs=pairs, minimum_retained_across_pairs=minimum,
                maximum_replaced_across_pairs=max(row["max_replaced"] for row in pairs.values()),
                complete_close_then_rebuild_price_compatible=minimum == 0,
                unchanged_possible_for_every_pair=all(row["unchanged_possible"] for row in pairs.values()))


def verify_sources(reference):
    index = input_sources()
    sources = {key: load_source(index, key) for key in (PLAN, HOLDINGS, SUMMARY, MORNING, OTHER_SYSTEM, OTHER_MORNING)}
    for key in (PLAN, HOLDINGS, SUMMARY, OTHER_SYSTEM):
        if sources[key]["archive_sha256"] != reference["sources"][key]["archive_sha256"]:
            raise ValueError("PTA_CARRY_SOURCE_CHANGED")
    earlier = reference["snapshot"]["image"]
    hashes = {MORNING_IMAGE: MORNING_IMAGE_SHA, OTHER_IMAGE: OTHER_IMAGE_SHA, earlier["path"]: earlier["sha256"],
              **reference["repeated_holdings_summary"]["images"]}
    if any(sha((ARCHIVE.parent / path).read_bytes()) != fingerprint for path, fingerprint in hashes.items()):
        raise ValueError("PTA_CARRY_IMAGE_CHANGED")
    return sources, hashes


def compare_morning(series, one_day, reference, *, open_at, cutoff, tick, lots):
    quote = photo_comparison(one_day, open_at, cutoff, MORNING_MARKS)
    minutes = completed(series[1], series[1][0].start, cutoff)
    before_sets = {
        "night_cover_to_morning": reference["row_mark"]["quote_captures"],
        "night_summary_to_morning": reference["repeated_holdings_summary"]["quote_candidates"]["joint_contains"],
    }
    after = list(map(datetime.fromisoformat, quote["per_symbol"]["ta"]["contains"]))
    if not after or not all(before_sets.values()):
        raise ValueError("PTA_CARRY_QUOTE_UNVERIFIED")
    totals = displayed_tick_totals(AVG, lots, tick)
    bounds = {name: lot_survival(minutes, list(map(datetime.fromisoformat, earlier)), after, tick=tick,
                                 lots=lots, totals=totals) for name, earlier in before_sets.items()}
    return quote, bounds


def study(session, market, reference, spec):
    sources, image_hashes = verify_sources(reference)
    one_day = {symbol: read_session_series(session, market, symbol, f"{symbol.upper()}2701", "1m", ONE, (DAY,))
               for symbol in MORNING_MARKS}
    series = read_window(session, market, CONTRACT, DAY)
    fingerprints = {f"{p}m": dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()}
    if (fingerprints != reference["market"] or any(identity(one_day[symbol]) != expected
            for symbol, expected in reference["repeated_holdings_summary"]["market_1m"].items())):
        raise ValueError("PTA_CARRY_FROZEN_MARKET_CHANGED")

    earlier_long = reference["snapshot"]["legs"]["long"]
    lots, spread, screenshot_float = 34, Decimal(54), Decimal(9180)  # Morning screenshot fields.
    if (earlier_long["quantity"] != lots or earlier_long["today_quantity"] != lots
            or Decimal(earlier_long["opening_average"]) != AVG
            or AVG + spread != Decimal(MORNING_MARKS["ta"]) or lots * spread * spec["multiplier"] != screenshot_float):
        raise ValueError("PTA_CARRY_MORNING_ROW_CHANGED")
    open_at = at("2026-10-26T09:00")
    cutoff = datetime.fromisoformat(sources[MORNING]["published_at"])
    plan_at = datetime.fromisoformat(sources[PLAN]["published_at"]) + ONE
    if not plan_at < series[1][0].start < open_at < cutoff:
        raise ValueError("PTA_CARRY_PUBLICATION_ORDER_CHANGED")
    scope = dict(open_at=open_at, tick=spec["tick"], lots=lots)
    quote, bounds = compare_morning(series, one_day, reference, cutoff=cutoff, **scope)
    loose_cutoff = cutoff + ONE + 2 * US
    loose_quote, loose_bounds = compare_morning(series, one_day, reference, cutoff=loose_cutoff, **scope)
    loose_quote["comparison_cutoff_minute"] = loose_quote.pop("published_minute")
    return dict(version=VERSION, contract=CONTRACT, trading_day=DAY, sources=sources, image_sha256=image_hashes,
                ta_market=fingerprints, symbol_quote_inputs={s: identity(rows) for s, rows in one_day.items()},
                morning_quote=quote, morning_long=dict(quantity=lots, today_quantity=lots, opening_average=AVG,
                                                      floating_field=screenshot_float, profit_spread_field=spread),
                morning_5_0_other_table=dict(opening_average=Decimal(6538), holding_average=Decimal(6502),
                                              quantity=None, scope="DISTINCT_VERSION_DO_NOT_JOIN"),
                same_account_and_complete_row_assumed=True, actual_account_continuity=None,
                publication_minute_sensitivity=dict(quote=loose_quote, retention=loose_bounds, cutoff=loose_cutoff,
                                                   rule="ALLOW_ENTIRE_PUBLICATION_MINUTE_FOR_RETROSPECTIVE_BOUNDS"),
                retention=bounds, public_plan_status="NEW_PUBLIC_ZONE_UNAVAILABLE", actual_restart_at=None,
                actual_protection_change=None, unshown_short_quantity=None, exact_capture_at=None,
                frozen_input_sha256=REFERENCE_SHA, author_actions_scored=0, author_match_rate=None,
                executable=False, fills=None, pnl=None)


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
        reference = verified_json(REFERENCE, REFERENCE_SHA)
        spec = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session), reference, spec)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        reason = str(exc)
        parser.exit(2, (reason if reason.startswith("PTA_CARRY_") and reason.isidentifier()
                        else "PTA_CARRY_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
