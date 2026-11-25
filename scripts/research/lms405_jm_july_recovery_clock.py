"""Compare published single-point recovery with a prior protection bar's boundary."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_recovery_confirmation_audit import edge_candidates, strict_runs
from lms405_right_side_study import ONE, US
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


def study(session, market):
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
    return dict(
        version="lms405-jm-july-recovery-clock-v1", contract=CONTRACT, trading_day=DAY,
        start=start, cutoff_exclusive=cutoff, sources=sources, source_index_sha256=sha(SOURCE_INDEX.read_bytes()),
        market={f"{p}m": dict(count=len(rows), sha256=sha(encoded([
            (bar.start, bar.end, bar.open, bar.high, bar.low, bar.close) for bar in rows
        ]).encode())) for p, rows in series.items()}, frozen_5m_sha256=FROZEN_SHA,
        case_scope="REPORTED_LMS_RECOVERY_VERSION_AND_TIME_UNVERIFIED",
        comparisons={key: compare(series, start, cutoff, edge) for key, edge in PRICE_LEVELS.items()},
        author_action_time=None, author_signal_time=None, author_match_rate=None, admitted_author_action_samples=0,
        executable=False, fills=None, pnl=None,
    )


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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "JULY_RECOVERY_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
