"""Test whole-leg formation after completed-bar confirmation across a 4.0.5 snapshot."""

import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from lms405_common_protection_window import DAY, FIRST, POST, START
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import EXPOSURE, displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_public_plan_roles import load_source
from lms405_replay import display
from lms405_reversal_stage_bounds import PHOTO, PHOTO_SHA
from lms405_right_side_study import US
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_sizing_audit import EXPOSURE_SHA256, SPECS, load_specs
from lms_near405_replay import encoded, sha

MARKET_REFERENCE = Path("output/lms405-sized-portfolio-20261125/common-protection-window.json")
MARKET_SHA = "ef337f6c8610671d4664cee1160da052c845cf8eba23707059f9a067cb4f466c"
REGULAR = "A5356884629782554"
ALTERNATIVE = "A5356884885635211"
CASES = dict(
    FG2701=("828.0", REGULAR, "829 836"),
    I2701=("668.75", REGULAR, None),
    JM2701=("1400.10", REGULAR, "1382.5 1397.5"),
    RU2701=("19505.0", ALTERNATIVE, "19530 19680"),
    SA2701=("935.0", REGULAR, "931 936"),
    SH2701=("1618.5", ALTERNATIVE, "1610 1632"),
)


def price_envelope(minutes, event, tick, lots, totals, end):
    prefix = [bar for bar in minutes if bar.end <= end]
    full_possible = 0 in earlier_lot_counts(None, tick_bounds(prefix, tick), lots, totals)
    known_before = event is not None and event["available_at"] < end
    result = dict(whole_leg_price_possible_in_prefix=full_possible, complete_minutes=len(prefix),
                  first_candidate_known_before_quote_end=known_before, minimum_lots_outside_later_minutes=None)
    if not full_possible or not known_before:
        return result
    known = event["available_at"]
    minima = {}
    for mode, later in (("overlap_allowed", [b for b in prefix if b.end > known]),
                        ("fully_after", [b for b in prefix if b.start > known])):
        limit = later[0].start if later else end
        earlier = [b for b in prefix if b.end <= limit]
        counts = earlier_lot_counts(tick_bounds(earlier, tick), tick_bounds(later, tick), lots, totals)
        if not counts:
            raise ValueError("FIRST_CLOCK_PARTITION_INFEASIBLE")
        minima[mode] = min(counts)
    result["minimum_lots_outside_later_minutes"] = minima
    return result


def study(session, market):
    sources = input_sources()
    exposure = verified_json(EXPOSURE, EXPOSURE_SHA256)
    reference = verified_json(MARKET_REFERENCE, MARKET_SHA)
    photo = verified_json(PHOTO, PHOTO_SHA)["photos"][FIRST]
    specs = load_specs(json.loads(SPECS.read_bytes()))
    (table,) = [row for row in exposure["tables"] if row["source"] == FIRST]
    image = table["image"]
    if (table["system"] != "4.0.5" or table["binding"] != "SYSTEM_COVER"
            or sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]
            or datetime.fromisoformat(table["published_at"]) != POST
            or set(CASES) != set(table["contracts"])):
        raise ValueError("FIRST_CLOCK_SNAPSHOT_CHANGED")
    results = {}
    for contract, (raw_average, source_id, raw_band) in CASES.items():
        series = read_window(session, market, contract, DAY)
        fingerprints = {f"{period}m": digest(rows) for period, rows in series.items()}
        expected = reference["input_1m"][contract]
        minutes = completed(series[1], START, POST)
        if len(series[1]) != expected["full_day_count"] or fingerprints["1m"] != expected["full_day_sha256"] or (
            len(minutes) != expected["window_minutes"]
        ):
            raise ValueError("FIRST_CLOCK_MARKET_CHANGED")
        long, short = (table["contracts"][contract]["legs"][side] for side in ("long", "short"))
        average, lots, tick = Decimal(raw_average), long["quantity"], specs[contract]["tick"]
        if (average != Decimal(long["opening_average"]) or lots != long["today_quantity"]
                or short["today_quantity"] != 0 or short["quantity"] != lots):
            raise ValueError("FIRST_CLOCK_POSITION_CHANGED")
        totals = displayed_tick_totals(average, lots, tick)
        observed = photo["per_symbol"][contract[:-4].lower()]
        price = Decimal(observed["mark"])
        anchors = [bar.end for bar in minutes if bar.low <= price <= bar.high]
        if not anchors or [display(end) for end in anchors] != observed["contains"]:
            raise ValueError("FIRST_CLOCK_QUOTE_CHANGED")
        plan = load_source(sources, source_id)
        if datetime.fromisoformat(plan["published_at"]) >= START:
            raise ValueError("FIRST_CLOCK_SOURCE_AFTER_SESSION")
        band = tuple(map(Decimal, raw_band.split())) if raw_band else None
        clocks = {}
        for shape, confirm in VARIANTS:
            args = dict(start=START, side="LONG")
            events = signals(series, shape, confirm, cut=POST, **args)
            for stop in anchors:
                prefix = {period: [bar for bar in rows if bar.end + US < stop] for period, rows in series.items()}
                if signals(prefix, shape, confirm, cut=stop, **args) != [e for e in events if e["available_at"] < stop]:
                    raise ValueError("FIRST_CLOCK_PREFIX_DIVERGED")
            event = next(iter(events), None)
            clocks[f"{shape}m_to_{confirm}m"] = dict(
                events=events, first_candidate=event,
                first_confirmation_inside_published_band=band[0] <= event["close"] <= band[1] if band and event else None,
                before_publication=price_envelope(minutes, event, tick, lots, totals, POST),
                by_conditional_quote_minute={display(end): price_envelope(minutes, event, tick, lots, totals, end)
                                             for end in anchors},
            )
        results[contract] = dict(
            original_short=short, displayed_long=long, average=average, tick=tick, market=fingerprints,
            quote=price, individual_quote_ends=anchors, plan=plan, protection_band=band, clocks=clocks,
            whole_leg_price_possible_before_publication=bool(earlier_lot_counts(None, tick_bounds(minutes, tick),
                                                                                lots, totals)),
        )
    return dict(
        version="lms405-first-night-confirmation-clocks-v1", cases=results,
        study="CONDITIONAL_ENTIRE_TODAY_LEG_FORMED_IN_NIGHT_WINDOW", quote_identity="INDIVIDUAL_PRICE_ENVELOPE_ONLY",
        shared_photo_timestamp=None, photo=image, photo_source=load_source(sources, FIRST),
        references=dict(market=MARKET_SHA, quote=PHOTO_SHA, exposure=EXPOSURE_SHA256),
        trading_day=DAY, start=START, cutoff_exclusive=POST, author_action_samples=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
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
        parser.exit(2, (code if code.startswith("FIRST_CLOCK_") and code.isidentifier()
                        else "FIRST_CLOCK_SOURCE_OR_MARKET_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
