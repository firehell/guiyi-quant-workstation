"""Compare protection prices, failed breaks, and the next-day wait in FG2609 and SA2609."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_jm_oct_recovery_clock import window_signals
from lms405_portfolio_replay import input_sources
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded

CASES = (
    ("S5328222180872595", "FG2609", "2026-08-04", "16:03", {
        "short_reentry_break_required": ("870", "870"),
        "old_short_protection": ("870", "879"),
        "weak_side_m_reference": ("886", "893"),
    }),
    ("S5328592286253773", "FG2609", "2026-08-05", "16:34", {"range_divider": ("883", "891")}),
    ("S5328593089468376", "SA2609", "2026-08-05", "16:37", {"old_short_protection": ("924", "927")}),
    ("S5328957219012753", "SA2609", "2026-08-06", "16:44", {"range_divider": ("926", "932")}),
    ("S5330404632694755", "FG2609", "2026-08-10", "16:36", {
        "range_divider": ("883", "891"),
        "reported_failed_benchmark": ("904", "907"),
    }),
)


def lowest_return(rows, threshold):
    first_low = next((bar for bar in rows if bar.low < threshold), None)
    first_close = next((bar for bar in rows if bar.close < threshold), None)
    first_above = next((bar for bar in rows if first_close and bar.end > first_close.end and bar.close > threshold), None)
    new_cross = next((bar for prior, bar in zip(rows, rows[1:])
                      if prior.end == bar.start and prior.close >= threshold > bar.close), None)
    return_after_new = next(
        (bar for bar in rows if new_cross and bar.end > new_cross.end and bar.close > threshold), None,
    )
    run, longest, previous = 0, 0, None
    for bar in rows:
        if bar.close < threshold:
            run = run + 1 if previous == bar.start else 1
        else:
            run = 0
        longest = max(longest, run)
        previous = bar.end
    return dict(first_low_below_end=first_low.end if first_low else None,
                first_strict_close_below_end=first_close.end if first_close else None,
                first_strict_return_above_end=first_above.end if first_above else None,
                longest_consecutive_minutes_closed_below=longest,
                strict_close_below_count=sum(bar.close < threshold for bar in rows),
                first_new_contiguous_cross_below_end=new_cross.end if new_cross else None,
                first_return_above_after_new_cross_end=return_after_new.end if return_after_new else None)


def observe_prices(rows, bands):
    ranges = {}
    for role, (lower, upper) in bands.items():
        inside = [bar for bar in rows if bar.low <= upper and bar.high >= lower]
        ranges[role] = dict(
            band=(lower, upper), overlap_count=len(inside), first_overlap_end=inside[0].end if inside else None,
            first_lower_touch_end=next((b.end for b in rows if b.low <= lower <= b.high), None),
            first_upper_touch_end=next((b.end for b in rows if b.low <= upper <= b.high), None),
            first_close_above_end=next((b.end for b in rows if b.close > upper), None),
            closes_inside=sum(lower <= bar.close <= upper for bar in rows),
            below_and_return=lowest_return(rows, lower),
        )
    low, high = min(b.low for b in rows), max(b.high for b in rows)
    return dict(
        minutes=len(rows), open=rows[0].open, low=low, high=high, close=rows[-1].close,
        first_low_end=next(b.end for b in rows if b.low == low),
        first_high_end=next(b.end for b in rows if b.high == high), bands=ranges,
    )


def geometry_comparison(series, morning, cut, bands):
    by_direction, count = {}, 0
    for direction in ("LONG", "SHORT"):
        signals, checks = window_signals(series, morning, cut, direction)
        count += checks
        by_direction[direction] = {clock: dict(
            total=len(events), first=events[0] if events else None,
            closes_inside={role: [event for event in events if lower <= event["close"] <= upper]
                           for role, (lower, upper) in bands.items()},
            closes_below={role: [event for event in events if event["close"] < lower]
                          for role, (lower, _) in bands.items()},
        ) for clock, events in signals.items()}
    return by_direction, count


def study(session, market):
    index, results = input_sources(), {}
    for source_id, contract, day, minute, raw_bands in CASES:
        source = load_source(index, source_id)
        publication = at(f"{day}T{minute}")
        if datetime.fromisoformat(source["published_at"]) != publication:
            raise ValueError("LMS_AUGUST_SOURCE_MINUTE_CHANGED")
        series = read_window(session, market, contract, date.fromisoformat(day))
        morning, end = at(f"{day}T09:00"), series[1][-1].end
        if not series[1][0].start < morning < end < publication:
            raise ValueError("LMS_AUGUST_SESSION_SOURCE_ORDER_CHANGED")
        bands = {role: tuple(map(Decimal, pair)) for role, pair in raw_bands.items()}
        night_start = series[1][0].start
        night_rows = completed(series[1], night_start, morning)
        day_rows = completed(series[1], morning, end + 2 * US)
        if not night_rows or not day_rows or day_rows[0].start != morning:
            raise ValueError("LMS_AUGUST_MORNING_COVERAGE_CHANGED")
        geometry, checks = geometry_comparison(series, morning, end + 2 * US, bands)
        night_geometry, night_checks = geometry_comparison(series, night_start, night_rows[-1].end + 2 * US, bands)
        results[source_id] = dict(
            source=source, contract=contract, trading_day=day,
            night=observe_prices(night_rows, bands), day=observe_prices(day_rows, bands),
            whole_trading_day=observe_prices(series[1], bands),
            completed_day_geometry=geometry, completed_night_geometry=night_geometry, prefix_checks=checks + night_checks,
            market={str(p): dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()},
            author_signal_at=None, policy_405=None, actual_position_change=None, historical_vplus_verified=False,
        )
    return dict(
        version="lms405-glass-soda-august-wait-v1", cases=results,
        use="RETROSPECTIVE_PRICE_COMPARISON_OF_POST_CLOSE_AUTHOR_STATEMENTS",
        price_conditions_are_permissions=False, author_action_samples=0, author_match_rate=None,
        fills=None, pnl=None, executable=False,
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
        parser.exit(2, (code if code.startswith("LMS_AUGUST_") and code.isidentifier()
                        else "LMS_AUGUST_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
