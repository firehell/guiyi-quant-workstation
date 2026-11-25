"""Compare early and rebound-interruption protection using archived 4.0.5 cases."""

import argparse
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_replay import display, ohlc
from lms405_right_side_study import US, at
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

ARCHIVE = Path("docs/research/lms-source-archive/03-单品种分析")
CASES = {
    "SA2605": dict(
        source=ARCHIVE / "2026-04-13/纯碱/S5287284540178482.md",
        post="2026-04-13T16:52", days=("2026-04-09", "2026-04-10", "2026-04-13"),
        bands={"short_target": ("1123", "1133", "SHORT"), "counter_m": ("1160", "1164", "LONG")},
        reported_low=None, reported_high=Decimal("1163"),
    ),
    "SH2607": dict(
        source=ARCHIVE / "2026-04-30/烧碱/S5293454072479751.md",
        post="2026-04-30T17:27", days=("2026-04-29", "2026-04-30"),
        bands={"rebound_interruption": ("2017", "2039", "LONG")},
        reported_low=Decimal("1999"), reported_high=Decimal("2032"),
    ),
}


def study_day(series, config, previous_close):
    bars = series[1]
    start, end = bars[0].start, bars[-1].end
    cutoff = end + 2 * US
    if cutoff >= at(config["post"]):
        raise ValueError("PROTECTION_PATH_BARS_AFTER_SOURCE_CUTOFF")
    bands = {
        role: {
            f"{period}m": observations(rows, (Decimal(lower), Decimal(upper)), side)
            for period, rows in series.items()
        }
        for role, (lower, upper, side) in config["bands"].items()
    }
    low, high = min(bar.low for bar in bars), max(bar.high for bar in bars)
    geometries = {}
    for shape, confirm in VARIANTS:
        inputs = dict(start=start, side="LONG")
        full = geometry_events(series, shape, confirm, as_of=cutoff, **inputs)
        splits = {start + timedelta(minutes=15), *(row["available_at"] for row in full)}
        for split in sorted(splits):
            prefix = {period: [bar for bar in rows if bar.end + US < split] for period, rows in series.items()}
            if geometry_events(prefix, shape, confirm, as_of=split, **inputs) != [
                    row for row in full if row["available_at"] < split]:
                raise ValueError("PROTECTION_PATH_PREFIX_DIVERGED")
        geometries[f"{shape}m_to_{confirm}m"] = full
    return dict(
        minute_count=len(bars), first_start=display(start), opening_price=bars[0].open,
        open_minus_previous_close=None if previous_close is None else bars[0].open - previous_close,
        first_low_at=display(next(bar.end for bar in bars if bar.low == low)),
        first_high_at=display(next(bar.end for bar in bars if bar.high == high)),
        low=low, high=high, close=bars[-1].close, bands=bands, long_geometries=geometries,
        market={
            f"{p}m": dict(
                count=len(rows),
                sha256=sha(encoded([[bar.end.isoformat(), *map(str, ohlc(bar))] for bar in rows]).encode()),
            )
            for p, rows in series.items()
        },
    )


def study(session, market):
    cases = {}
    for contract, config in CASES.items():
        days, previous_close = {}, None
        for day in config["days"]:
            series = read_window(session, market, contract, date.fromisoformat(day))
            days[day] = study_day(series, config, previous_close)
            previous_close = days[day]["close"]
        publication_day = days[config["days"][-1]]
        cases[contract] = dict(
            source_id=config["source"].stem, source_path=str(config["source"]),
            source_sha256=sha(config["source"].read_bytes()), source_post_minute=config["post"],
            publication_day_price_deltas={
                key: publication_day[key] - config[f"reported_{key}"]
                if config[f"reported_{key}"] is not None else None for key in ("low", "high")
            },
            days=days, exact_vplus_signal=None, author_action_at=None, original_plan_verified=False,
        )
    return dict(
        version="lms405-protection-path-cases-v1", cases=cases, author_action_samples=0,
        author_match_rate=None, fills=None, pnl=None, executable=False,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "PROTECTION_PATH_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
