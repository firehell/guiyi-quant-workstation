"""Check volatility and price context around author-reported SH2609 recovery limits."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_jm2605_stability import stability_context
from lms405_jm_oct_recovery_clock import window_signals
from lms405_portfolio_replay import input_sources
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import US, at
from lms405_sh2609_handoff import MINUTE_HASHES
from lms405_sh_lock_lifecycle import digest
from lms_near405_replay import encoded

CONTRACT = "SH2609"
VERSION = "lms405-sh2609-recovery-context-v1"
PRIOR_BAND = (Decimal(1859), Decimal(1870))
CASES = (
    ("2026-07-24", "S5324249205048926", "TARGET_TESTS_REPORTED_COMPLETE_405_WAITED",
     {"first_short_target": (Decimal(1877), Decimal(1888)),
      "second_short_target": (Decimal(1854), Decimal(1863))}),
    ("2026-07-27", "S5325329692361179", "ORIGINAL_SHORT_NOT_ELIGIBLE_AT_RECAP",
     {"published_after_session_reference": PRIOR_BAND}),
    ("2026-07-28", "S5325700674619111", "PRIOR_BAND_SENSITIVITY_NO_AUTHOR_ACTION",
     {"prior_day_reference_validity_unknown": PRIOR_BAND}),
)


def contexts(fifteens, sessions, timestamp):
    bounds = next(((start, end) for start, end in sessions if start < timestamp <= end), None)
    run = [bar for bar in fifteens if bounds and bounds[0] <= bar.start and bar.end <= bounds[1]]
    return dict(trading_day=stability_context(fifteens, timestamp),
                continuous_session=stability_context(run, timestamp))


def area_path(minutes, band):
    far, near = band
    return dict(band=band,
                first_overlap=next((b.end for b in minutes if b.low <= near and b.high >= far), None),
                first_strict_close_below_near=next((b.end for b in minutes if b.close < near), None),
                first_strict_close_below_far=next((b.end for b in minutes if b.close < far), None))


def candidate_context(event, series, sessions, bands):
    confirmation = event["confirmed_at"]
    before = [bar for bar in series[1] if bar.end + US < event["available_at"]]
    bars_through_confirmation = [bar for bar in series[1] if bar.end <= confirmation]
    return event | dict(
        before_shape=contexts(series[15], sessions, event["shape_start"]),
        before_confirmation=contexts(series[15], sessions, confirmation),
        price={key: dict(
            strictly_below_near=event["close"] < band[1],
            strictly_below_far=event["close"] < band[0],
            strict_close_below_near_precedes_confirmation=area_path(before, band)["first_strict_close_below_near"],
            first_overlap_by_confirmation=area_path(bars_through_confirmation, band)["first_overlap"],
        ) for key, band in bands.items()},
    )


def study(session, market):
    from app.market_data.session_clock import resolved_session_windows_for_trading_day

    index = input_sources()
    exchange = market.catalog.exchange_for_symbol("sh")
    cases = {}
    for day, source_id, scope, bands in CASES:
        source = load_source(index, source_id)
        publication = datetime.fromisoformat(source["published_at"])
        trading_day = date.fromisoformat(day)
        series = read_window(session, market, CONTRACT, trading_day)
        hashes = {f"{period}m": digest(rows) for period, rows in series.items()}
        if hashes["1m"] != MINUTE_HASHES[day]:
            raise ValueError("SH2609_RECOVERY_FROZEN_MINUTES_CHANGED")
        start, close = series[1][0].start, at(f"{day}T15:00")
        cut = close + 2 * US
        if series[1][-1].end != close or publication <= cut:
            raise ValueError("SH2609_RECOVERY_SOURCE_SCOPE_CHANGED")
        events, prefix_checks = window_signals(series, start, cut, "SHORT")
        windows = resolved_session_windows_for_trading_day(session, exchange=exchange, symbol="sh",
                                                           trading_day=trading_day)
        sessions = [(row.window.start, row.window.end) for row in windows]
        candidates = {clock: [candidate_context(event, series, sessions, bands) for event in rows]
                      for clock, rows in events.items()}
        context_checks = 0
        for rows in candidates.values():
            for row in rows:
                cut_at = row["available_at"] + US
                prefix = {p: [bar for bar in bars if bar.end + US < cut_at] for p, bars in series.items()}
                if candidate_context(row, prefix, sessions, bands) != row:
                    raise ValueError("SH2609_RECOVERY_CONTEXT_PREFIX_DIVERGED")
                context_checks += 1
        cases[day] = dict(
            scope=scope, source=source, start=start, cutoff_exclusive=cut, market=hashes,
            minute_count=len(series[1]), low=min(b.low for b in series[1]), close=series[1][-1].close,
            references={key: area_path(series[1], band) for key, band in bands.items()},
            session_openings=[opening for opening, _ in sessions],
            candidates=candidates, signal_prefix_checks=prefix_checks,
            context_prefix_checks=context_checks, author_action_at=None,
        )
    return dict(version=VERSION, contract=CONTRACT, cases=cases, retrospective_comparison=True,
                author_volatility_formula=None, author_actions_scored=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=75):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "SH2609_RECOVERY_CONTEXT_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
