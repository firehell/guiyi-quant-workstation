"""Compare target completion and protection location without combining their rules."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_replay import display, ohlc
from lms405_right_side_study import US
from lms405_v_zone_progress import observations, publication_windows
from lms_near405_replay import encoded, sha

# Author descriptions are attached after replay, with separate outcome scope.
TARGETS = (
    ("S5287284540178482", "SA2605", "2026-04-10", ("1123", "1133"), None, "EARLIER_TARGET_LINKED_TO_PROTECTION"),
    ("S5315919708685519", "SH2609", "2026-07-01", ("1870", "1878"), "1871", "INCOMPLETE"),
    ("S5353961087567230", "FG2701", "2026-10-13", ("850", "864"), "852", "PRIOR_DAY_PRICE_COMPARISON"),
    ("S5353961087567230", "FG2701", "2026-10-14", ("850", "864"), "851", "INCOMPLETE"),
    ("S5353961748169131", "SA2701", "2026-10-14", ("958", "967"), "940", "COMPLETED"),
)
PROTECTION = (
    ("S5293454072479751", "SH2607", "2026-04-30", ("2017", "2039"), "2032", "SYSTEM_PROTECTION_DESCRIBED"),
    ("S5354685196405809", "FG2701", "2026-10-16", ("855", "861"), "866", "BEFORE_OR_WITHIN_INTENDED"),
)
PROTECTION_VERSION_SOURCES = {"S5287284540178482", "S5293454072479751"}


def first_location(events, band, first_overlap):
    low, high = band
    locations = {
        "price_below_near": [event for event in events if event["close"] < low],
        "price_within_inclusive": [event for event in events if low <= event["close"] <= high],
        "price_above_far": [event for event in events if event["close"] > high],
    }
    if first_overlap is not None:
        locations["known_before_first_range_overlap"] = [event for event in events
                                                         if event["available_at"] < first_overlap]
    result = {key: dict(count=len(rows), first=next(iter(rows), None)) for key, rows in locations.items()}
    result.setdefault("known_before_first_range_overlap", None)
    return result


def price_role(series, band, kind, cutoff, reported_extreme):
    prefix = {period: publication_windows(bars, cutoff)[0] for period, bars in series.items()}
    minutes = prefix[1]
    side = "SHORT" if kind == "target" else "LONG"
    price = {f"{period}m": observations(bars, band, side) for period, bars in prefix.items()}
    extreme = min(bar.low for bar in minutes) if side == "SHORT" else max(bar.high for bar in minutes)
    reported = None if reported_extreme is None else Decimal(reported_extreme)
    result = dict(
        cutoff_exclusive=cutoff, observed_extreme=extreme, price=price, reported_extreme=reported,
        extreme_difference=None if reported is None else extreme - reported,
        market={f"{period}m": dict(
            bars=len(bars), sha256=sha(encoded([[bar.end.isoformat(), *map(str, ohlc(bar))] for bar in bars]).encode()),
        ) for period, bars in prefix.items()},
    )
    if kind == "protection":
        first_overlap = next((b.end + US for b in minutes if b.low <= band[1] and b.high >= band[0]), None)
        result["first_range_overlap_bar_end"] = display(first_overlap) if first_overlap else None
        result["shapes_by_confirmation_price"] = {
            f"{shape}m_to_{confirm}m": first_location(
                geometry_events(prefix, shape, confirm, start=minutes[0].start, as_of=cutoff, side=side),
                band, first_overlap,
            ) for shape, confirm in VARIANTS
        }
    return result


def study(session, market):
    index = input_sources()
    cases = {}
    for kind, inputs in (("target", TARGETS), ("protection", PROTECTION)):
        for source_id, contract, day, levels, reported, label in inputs:
            source = index[source_id]
            published = datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0)
            series = read_window(session, market, contract, date.fromisoformat(day))
            band = tuple(map(Decimal, levels))
            result = price_role(series, band, kind, published, reported)
            cases[f"{contract}/{day}"] = result | dict(
                kind=kind, author_description=label, source_id=source_id, source=source,
                protection_system_mentioned="4.0.5" if source_id in PROTECTION_VERSION_SOURCES else None,
                source_sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes()),
                historical_plan_and_applicability_verified=False,
                author_vplus=None, author_lock_at=None,
            )
    return dict(
        version="lms405-target-protection-roles-v1", cases=cases, evaluation="RETROSPECTIVE_PRICE_ONLY",
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=40):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "TARGET_PROTECTION_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
