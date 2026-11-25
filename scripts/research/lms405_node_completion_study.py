"""Compare author descriptions of target completion with distinct market observations."""

import argparse
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, LOCAL, input_sources
from lms405_protection_shape_audit import price_digest
from lms405_protection_timeframes import read_window
from lms405_recovery_confirmation_audit import strict_runs
from lms405_replay import display
from lms405_v_zone_progress import observations, publication_windows
from lms_near405_replay import encoded, sha

# Current author reviews supply the node identities. The bands have no verified historical release times.
CASES = (
    ("S5344544578342362", "OI2701", "SHORT", "10052 10063", "10062", None, "M_ONLY", None),
    ("S5343801842598111", "OI2701", "LONG", "10185 10203", "10243", True, "EXTREME_M", None),
    ("S5311208706277938", "RU2609", "SHORT", "17555 17670", "17640", False, "CYCLE_FAILED_RANGE", None),
    ("S5313021782003245", "RU2609", "SHORT", "17555 17670", "17580", False, "RANGE_WITH_INTRADAY_M", "4.0.5"),
    ("S5308311465361601", "RU2609", "SHORT", "17275 17370", "17245", True, "BEARISH_TREND_REPORTED", None),
    ("S5313008607692211", "I2609", "SHORT", "736.5 738", "734", True, "WEAK_SIDE_AFTER_ONE_TARGET", None),
    ("U05", "RU2701", "SHORT", "19220 19290", "19200", True, "SECOND_TARGET_COMPLETE", None),
)


def measure(bars, band, side):
    path = observations(bars, band, side)
    runs = strict_runs(bars, path["far"], side)
    first_two = next((end for end, run in runs.items() if run["close_count"] >= 2), None)
    active_run = runs.get(bars[-1].end)
    return dict(path, low=min(bar.low for bar in bars), high=max(bar.high for bar in bars), close=bars[-1].close,
                first_two_strict_closes_beyond_far=display(first_two) if first_two else None,
                strict_close_run_at_window_end=active_run["close_count"] if active_run else 0)


def compare_rules(cases, window, period):
    results = {}
    for key in ("first_near_reach", "first_far_reach", "first_strict_close_beyond_far",
                "first_two_strict_closes_beyond_far", "strict_close_run_at_window_end"):
        agreeing, differing, unlabelled = [], [], []
        for source, case in cases.items():
            if case["completion_reported"] is None:
                unlabelled.append(source)
                continue
            mark = case["periods"][period][window][key]
            fulfilled = mark >= 2 if key == "strict_close_run_at_window_end" else mark is not None
            (agreeing if fulfilled == case["completion_reported"] else differing).append(source)
        results[key] = dict(agreeing=agreeing, differing=differing, unlabelled=unlabelled)
    return results


def study(session, market):
    index = input_sources()
    result = {}
    for source_id, contract, side, raw_band, expected_extreme, complete, wording, version in CASES:
        source = index[source_id]
        published = datetime.fromisoformat(source["published_at"]).astimezone(LOCAL)
        day = published.date()
        band = tuple(map(Decimal, raw_band.split()))
        day_open = datetime.combine(day, time(9), LOCAL)
        series = read_window(session, market, contract, day)
        periods = {}
        for period, bars in series.items():
            before, _ = publication_windows(bars, published.replace(second=0, microsecond=0))
            daytime = [bar for bar in before if bar.start >= day_open]
            if len(before) != len(bars) or not daytime:
                raise ValueError("NODE_COMPLETION_SOURCE_WINDOW_UNVERIFIED")
            periods[f"{period}m"] = dict(
                market_sha256=sha(encoded(price_digest(bars)).encode()),
                trading_day=measure(before, band, side), day_session=measure(daytime, band, side),
            )
        daytime = periods["1m"]["day_session"]
        day_extreme = daytime["low" if side == "SHORT" else "high"]
        result[source_id] = dict(
            source=source | dict(archive_sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes())),
            contract=contract, side=side, band=band, completion_reported=complete, author_state=wording,
            version_mentioned_for_behavior=version, reported_daytime_extreme=Decimal(expected_extreme),
            extreme_matches_local_day_session=day_extreme == Decimal(expected_extreme), periods=periods,
            historical_plan_availability=None, author_state_changed_at=None, author_action_at=None,
        )
    comparisons = {period: {scope: compare_rules(result, scope, period) for scope in ("day_session", "trading_day")}
                   for period in ("1m", "5m", "15m")}
    return dict(version="lms405-node-completion-study-v1", cases=result, completion_comparison=comparisons,
                comparisons_are_development_only=True, author_action_match_rate=None, admitted_author_actions=0,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('NODE_COMPLETION_') and code.isidentifier()
                         else 'NODE_COMPLETION_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
