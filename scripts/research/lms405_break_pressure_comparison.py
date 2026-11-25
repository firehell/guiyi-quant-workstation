"""Compare two observable break-and-retest sequences across FG and V cases."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_jm_oct_recovery_clock import window_signals
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded

JULY = "S5325691679933993"
AUGUST = "S5328222180872595"
PVC = "A5358325549629506"
WAIT = Path("output/lms405-glass-soda-august-wait-20261126/verified-a.json")
WAIT_SHA = "52e733e21a235201bb82f750ffa3436b08537f9f195cf7598dcc51abe8332e2c"
CASES = (
    ("glass_preceding_path", JULY, "FG2609", "2026-07-27", ("900", "902"), None, "RETROSPECTIVE_PRIOR_PATH"),
    ("glass_trend_continuation", JULY, "FG2609", "2026-07-28", ("900", "902"), ("882", "887"),
     "RETROSPECTIVE_RECAP"),
    ("glass_next_plan", JULY, "FG2609", "2026-07-29", ("904", "907"), None, "CURRENT_TEXT_POST_PUBLICATION"),
    ("glass_second_session_control", JULY, "FG2609", "2026-07-30", ("904", "907"), None, "EXPIRY_UNVERIFIED_CONTROL"),
    ("glass_false_break", AUGUST, "FG2609", "2026-08-04", ("870", "870"), None, "RETROSPECTIVE_RECAP"),
    ("pvc_short_branch", PVC, "V2701", "2026-10-27", ("5055", "5074"), ("5012", "5045"),
     "CURRENT_TEXT_POST_PUBLICATION"),
)


def continuous_groups(minutes):
    groups = []
    for bar in minutes:
        if not groups or groups[-1][-1].end != bar.start:
            groups.append([])
        groups[-1].append(bar)
    return groups


def first_shape_after(signals, completed_at, invalid_at):
    return {clock: next((event for event in events if completed_at + US < event["shape_start"]
                        and event["available_at"] < invalid_at), None)
            for clock, events in signals.items()}


def compare_break(group, index, band, signals):
    lower, upper = band
    initial = group[index]
    following = group[index + 1:]
    first_touch = next((bar for bar in following if bar.high >= lower), None)
    reset = next((bar for bar in following if bar.close >= lower), None)
    strict_run = [bar for bar in following if reset is None or bar.end < reset.end]
    fast_retest = next((bar for bar in strict_run if bar.high >= lower), None)
    complete_retest = next((bar for bar in strict_run if bar.high >= lower and bar.start > initial.end + US), None)

    outside = next((bar for bar in following if bar.close > upper), None)
    inside = next((bar for bar in following if lower <= bar.close <= upper
                   and (outside is None or bar.end < outside.end)), None)
    renewed = next((bar for bar in following if inside and inside.end + US < bar.end and bar.close < lower
                    and (outside is None or bar.end < outside.end)), None)
    after_renewed_reset = next((bar for bar in following if renewed and renewed.end < bar.end and bar.close >= lower),
                               None)

    def candidate(bar, cap):
        if bar is None:
            return None
        invalid_at = cap.end + US if cap else group[-1].end + 2 * US
        return dict(bar_end=bar.end, close=bar.close, observed_until=invalid_at,
                    fresh_short_geometry=first_shape_after(signals, bar.end, invalid_at))

    return dict(
        break_end=initial.end, break_close=initial.close, first_later_touch=first_touch.end if first_touch else None,
        first_close_to_or_above_lower=reset.end if reset else None, strict_below_run_minutes=1 + len(strict_run),
        uninterrupted_observed_retest=candidate(fast_retest, reset),
        uninterrupted_full_bar_retest=candidate(complete_retest, reset),
        first_equal_or_inside_close=inside.end if inside else None,
        renewed_break_after_inside_close=candidate(renewed, after_renewed_reset),
    )


def inspect(series, start, cutoff, band, target):
    minutes = completed(series[1], start, cutoff)
    if not minutes:
        raise ValueError("LMS_PRESSURE_EMPTY_WINDOW")
    signals, prefix_checks = window_signals(series, start, cutoff, "SHORT")
    rows = [compare_break(group, index, band, signals)
            for group in continuous_groups(minutes)
            for index, (prior, bar) in enumerate(zip(group, group[1:]), start=1)
            if prior.close >= band[0] > bar.close]
    target_touch = next((bar.end for bar in minutes if target and bar.low <= target[1] and bar.high >= target[0]), None)
    return dict(
        minutes=len(minutes), open=minutes[0].open, high=max(b.high for b in minutes),
        low=min(b.low for b in minutes), close=minutes[-1].close,
        opens_below_band=minutes[0].open < band[0],
        all_closes_below_band=all(bar.close < band[0] for bar in minutes),
        first_band_touch=next((bar.end for bar in minutes if bar.low <= band[1] and bar.high >= band[0]), None),
        first_target_overlap=target_touch, new_breaks=rows,
        short_candidates_total={clock: len(events) for clock, events in signals.items()},
        prefix_checks=prefix_checks,
    )


def study(session, market):
    index = input_sources()
    prior_august = verified_json(WAIT, WAIT_SHA)["cases"][AUGUST]["market"]
    results = {}
    for key, source_id, contract, day, raw_band, raw_target, scope in CASES:
        source = load_source(index, source_id)
        published = datetime.fromisoformat(source["published_at"])
        series = read_window(session, market, contract, date.fromisoformat(day))
        first, last = series[1][0].start, series[1][-1].end
        morning = at(f"{day}T09:00")
        if scope == "CURRENT_TEXT_POST_PUBLICATION" and not published < first:
            raise ValueError("LMS_PRESSURE_SOURCE_NOT_BEFORE_WINDOW")
        if scope.startswith("RETROSPECTIVE") and not last < published:
            raise ValueError("LMS_PRESSURE_RECAP_TIME_CHANGED")
        band = tuple(map(Decimal, raw_band))
        target = tuple(map(Decimal, raw_target)) if raw_target else None
        fingerprints = {str(p): dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()}
        if source_id == AUGUST and fingerprints != prior_august:
            raise ValueError("LMS_PRESSURE_AUGUST_MARKET_CHANGED")
        results[key] = dict(
            contract=contract, trading_day=day, source=source, band=band, target=target, scope=scope,
            night=inspect(series, first, morning, band, target),
            day=inspect(series, morning, last + 2 * US, band, target),
            market=fingerprints, author_signal_at=None, actual_author_action_at=None,
            article_history_verified=False, strategy_version=None,
        )
    return dict(
        version="lms405-break-pressure-comparison-v1", cases=results, august_reference_sha256=WAIT_SHA,
        definitions={
            "uninterrupted": "NEW_CONTIGUOUS_CLOSE_BELOW_NEAR_THEN_RETEST_CLOSING_BELOW_WITHOUT_CLOSE_RESET",
            "renewed": "NEW_BREAK_THEN_CLOSE_WITHIN_BAND_THEN_NEW_STRICT_CLOSE_BELOW_BEFORE_EXCEEDING_FAR",
        },
        behavior_match_rate=None, author_action_samples=0, fills=None, pnl=None, executable=False,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("LMS_PRESSURE_") and code.isidentifier()
                        else "LMS_PRESSURE_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
