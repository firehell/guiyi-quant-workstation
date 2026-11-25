"""Compare published SH weak-side classifications on completed physical-contract bars."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import input_sources
from lms405_protection_timeframes import geometry_events, summarize
from lms405_public_plan_roles import load_source
from lms405_right_side_study import US, at
from lms405_v_zone_progress import observations
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded

CASES = (
    ("SH2607", "2026-04-30", "2026-04-30", "S5293454072479751", (("interruption", "LONG", 2017, 2039),)),
    ("SH2607", "2026-06-04", "2026-06-05", "S5306498940930568",
     (("next_day_weak_side_reference", "LONG", 1950, 1964),)),
    ("SH2607", "2026-06-05", "2026-06-05", "S5306498940930568", (("weak_side_m", "LONG", 1950, 1964),)),
    ("SH2609", "2026-07-27", "2026-07-27", "S5325329692361179",
     (("extreme_m", "LONG", 1896, 1911), ("original_short_recovery_reference", "SHORT", 1859, 1870))),
)
VARIANTS = ((1, 1), (5, 1), (5, 5))


def study(session, market):
    index = input_sources()
    cases = {}
    for contract, day, published_day, source_id, zones in CASES:
        source = load_source(index, source_id)
        raw, series = read_pair(session, market, contract, (date.fromisoformat(day),))
        minutes = series[1]
        start = minutes[0].start
        close = at(f"{day}T15:00")
        cutoff = close + 2 * US
        if minutes[-1].end != close:
            raise ValueError("SH_WEAK_SIDE_WINDOW_UNVERIFIED")
        published = datetime.fromisoformat(source["published_at"]).astimezone(close.tzinfo)
        if published.date().isoformat() != published_day or published <= cutoff:
            raise ValueError("SH_WEAK_SIDE_SOURCE_TIME_UNVERIFIED")
        levels = {}
        for role, side, lower, upper in zones:
            band = Decimal(lower), Decimal(upper)
            levels[role] = dict(side=side, band=band, price=observations(minutes, band, side), geometry={
                f"{shape}m_to_{confirmation}m": summarize(
                    geometry_events(series, shape, confirmation, start=start, as_of=cutoff, side=side),
                    band=band, milestones=(),
                ) for shape, confirmation in VARIANTS
            })
        cases[day] = dict(
            contract=contract, zone_source_id=source_id, zone_source=source,
            lookback_from_later_trading_day=published_day != day, start=start, cutoff_exclusive=cutoff,
            open=minutes[0].open, low=min(bar.low for bar in minutes), high=max(bar.high for bar in minutes),
            close=minutes[-1].close, bars={f"{period}m": len(rows) for period, rows in raw.items()},
            hashes={f"{period}m": bars_sha(rows) for period, rows in raw.items()}, levels=levels,
        )
    return dict(version="lms405-sh-weak-side-comparison-v1", cases=cases, lookback_only=True,
                historical_preplan_verified=False, author_action_samples=0, author_match_rate=None,
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
    except (KeyError, ValueError, OSError):
        parser.exit(2, "SH_WEAK_SIDE_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
