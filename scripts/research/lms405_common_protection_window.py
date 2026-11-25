"""Bound common formation windows for visible LMS405 protection legs."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from itertools import combinations
import json
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE
from lms405_replay import display, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sizing_audit import EXPOSURE_SHA256
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

FIRST = "WRnTlEfj1t"
LATER = ("WRnY5bznUE", "WRo00BFM1E", "WRo2KQ43iX")
SOURCE_SHA256 = "b2249deb5f5c558c31f7d82b1b9415d0541b392c7b3c2db0d6bf35b989249e5a"
ZONE_SHA256 = "f8aca6e77cf418c0ec2e2cf26d8d56a9a8d2d9db756084fe014297474d4bab60"
# These two rows are preserved in the full-table transcription, outside the six
# research-portfolio contracts indexed in the exposure audit.
OTHER_LONG_ROWS = {"J2701": (10, "1906.75"), "RB2701": (40, "3048")}
START = at("2026-10-22T21:00")
POST = at("2026-10-22T22:10")
DAY = date(2026, 10, 23)


def enclosed_averages(series, averages):
    """Return all compatible contiguous interval sizes and the earliest of each size."""
    if not series or series.keys() != averages.keys():
        raise ValueError("PRICE_AND_AVERAGE_SCOPE_MISMATCH")
    first = next(iter(series.values()))
    spine = [row.bar_end for row in first]
    if (not spine or any(right - left != ONE for left, right in zip(spine, spine[1:]))
            or any([row.bar_end for row in bars] != spine for bars in series.values())):
        raise ValueError("COMMON_WINDOW_MINUTE_IDENTITY_MISMATCH")
    sizes = {}
    # Holding means require only independent per-leg envelopes. Each time window
    # may contain prices before another leg; no shared execution is inferred.
    for start, left in enumerate(spine):
        extrema = {contract: (bars[start].low, bars[start].high) for contract, bars in series.items()}
        for end in range(start, len(spine)):
            for contract, bars in series.items():
                low, high = extrema[contract]
                bar = bars[end]
                extrema[contract] = min(low, bar.low), max(high, bar.high)
            if all(extrema[key][0] <= value <= extrema[key][1] for key, value in averages.items()):
                width = end - start + 1
                minimum = sizes.setdefault(width, dict(count=0, first_window={
                    "start": display(left - ONE), "last_bar_end": display(spine[end]),
                }))
                minimum["count"] += 1
    return sizes


def summary(sizes):
    minimum = min(sizes, default=None)
    return dict(
        minimum_minutes=minimum,
        first_minimum_window=sizes[minimum]["first_window"] if minimum is not None else None,
        number_of_minimum_windows=sizes[minimum]["count"] if minimum is not None else 0,
        counts_at_fixed_width={str(width): sizes.get(width, {}).get("count", 0)
                               for width in (1, 5, 15, 30, 45, 60)},
    )


def classify_leg(previous, later):
    if later is None:
        return "UNLISTED_UNKNOWN"
    fields = (previous["quantity"], later["quantity"], previous["opening_average"], later["opening_average"])
    if any(value is None for value in fields):
        return "VISIBLE_FIELDS_INCOMPLETE"
    if previous["quantity"] == later["quantity"] and Decimal(previous["opening_average"]) == Decimal(later["opening_average"]):
        return "SAME_VISIBLE_QUANTITY_AND_OPENING_AVERAGE"
    return "VISIBLE_FIELDS_CHANGED"


def later_screens(tables, first):
    output = {}
    for source in LATER:
        row = tables[source]
        legs = {}
        for contract, observed in first.items():
            current = row["contracts"].get(contract, {}).get("legs", {})
            legs[contract] = {side: dict(status=classify_leg(before, current.get(side)), shown=current.get(side))
                              for side, before in observed["legs"].items()}
        output[source] = dict(published_at=row["published_at"], binding=row["binding"], legs=legs)
    return output


def study(session, market, exposure, zone):
    tables = {row["source"]: row for row in exposure["tables"] if row["source"] in (FIRST, *LATER)}
    if tables.keys() != {FIRST, *LATER}:
        raise ValueError("NEIGHBORING_PUBLISHED_RECORDS_MISSING")
    for row in tables.values():
        if sha((ARCHIVE.parent / row["image"]["path"]).read_bytes()) != row["image"]["sha256"]:
            raise ValueError("NEIGHBORING_PUBLISHED_IMAGE_CHANGED")
    first = tables[FIRST]
    if (sha((ARCHIVE.parent / first["archive_path"]).read_bytes()) != SOURCE_SHA256
            or first["system"] != "4.0.5" or datetime.fromisoformat(first["published_at"]) != POST):
        raise ValueError("FIRST_NIGHT_POST_CHANGED")

    observed = {}
    for contract, row in first["contracts"].items():
        long, short = (row["legs"][side] for side in ("long", "short"))
        if long["quantity"] != long["today_quantity"] or short["today_quantity"] != 0 or long["quantity"] != short["quantity"]:
            raise ValueError("EXPECTED_MATCHED_PROTECTION_PAIR")
        observed[contract] = long["quantity"], long["opening_average"]
    displayed = observed | OTHER_LONG_ROWS
    if len(displayed) != 8 or 2 * sum(quantity for quantity, _ in displayed.values()) != 332:
        raise ValueError("FULL_DISPLAY_TOTAL_MISMATCH")
    averages = {key: Decimal(average) for key, (_, average) in displayed.items()}
    lenses = {row["contract"]: row["market"]["1m"] for row in zone["cases"].values()
              if row["trading_day"] == DAY.isoformat()}
    timelines, coverage = {}, {}
    for contract in sorted(displayed):
        raw = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, (DAY,))
        key = bars_sha(raw)
        if contract in lenses and lenses[contract] != key:
            raise ValueError("FIRST_NIGHT_MINUTE_FINGERPRINT_CHANGED")
        timelines[contract] = [bar for bar in raw if START <= bar.bar_end - ONE and bar.bar_end + US < POST]
        coverage[contract] = dict(full_day_count=len(raw), full_day_sha256=key, window_minutes=len(timelines[contract]))
    single = {}
    for key, bars in timelines.items():
        candidate = enclosed_averages({key: bars}, {key: averages[key]})
        end_times = [display(bar.bar_end) for bar in bars if bar.low <= averages[key] <= bar.high]
        single[key] = dict(**summary(candidate), quantity=displayed[key][0], shown_average=averages[key],
                           first_single_minute_end=end_times[0] if end_times else None,
                           last_single_minute_end=end_times[-1] if end_times else None)
    pairs = {
        f"{a}/{b}": summary(enclosed_averages({a: timelines[a], b: timelines[b]}, {a: averages[a], b: averages[b]}))
        for a, b in combinations(timelines, 2)
    }
    portfolio = {key: timelines[key] for key in observed}
    return dict(
        version="lms405-common-protection-window-v1", source_ids=[FIRST, "WRnTl1Ej2P", *LATER],
        start=display(START), source_published_at=display(POST), exact_quote_anchor=None,
        author_mentions_crude_disruption=True, event_onset=None, actual_lock_timing=None,
        assumption="ENTIRE_VISIBLE_LONG_LEG_FORMED_WITHIN_RETAINED_COMPLETED_MINUTES",
        price_scope="DISPLAYED_AVERAGE_IN_WINDOW_OHLC_ENVELOPE_ONLY",
        all_eight=summary(enclosed_averages(timelines, averages)),
        six_research_contracts=summary(enclosed_averages(portfolio, {key: averages[key] for key in portfolio})),
        by_contract=single, pairwise=pairs, later_observations=later_screens(tables, first["contracts"]),
        input_1m=coverage, author_action_samples=0, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--exposure", type=Path, required=True)
    parser.add_argument("--zone-order", type=Path, required=True)
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
        exposure, zone = args.exposure.read_bytes(), args.zone_order.read_bytes()
        if sha(exposure) != EXPOSURE_SHA256 or sha(zone) != ZONE_SHA256:
            raise ValueError("FROZEN_ASSET_CHANGED")
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            result = study(session, build_market_data_service(session), json.loads(exposure), json.loads(zone))
        result["input_sha256"] = dict(exposure=EXPOSURE_SHA256, zone=ZONE_SHA256, article=SOURCE_SHA256)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
