"""Compare JM2701's published protection area with same-contract opening gaps."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Bar
from lms405_jm1072_stability import session_bounds
from lms405_jm_oct_recovery_clock import window_signals
from lms405_portfolio_replay import input_sources
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import ohlc, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

VERSION = "lms405-jm-gap-protection-v1"
CONTRACT = "JM2701"
PRIOR, FOCAL, NEXT = (date(2026, 8, 28), date(2026, 8, 31), date(2026, 9, 1))
LOWER, UPPER = Decimal("1674.5"), Decimal("1684.5")
POST = at("2026-08-31T09:47")
SOURCE_CSV = Path("docs/research/lms405/evidence/public-conditions-20261017.csv")


def source_binding():
    with SOURCE_CSV.open(newline="", encoding="utf-8") as stream:
        row, = (row for row in csv.DictReader(stream) if row["id"] == "I05")
    if (row["url"] != "https://weibo.com/1885745060/RfUgudQ5d"
            or row["market"] != CONTRACT or row["version"] != "4.0.5明确"
            or at(row["published_shanghai"].replace(" ", "T")) != POST
            or f"{LOWER}至{UPPER}" not in row["summary"]):
        raise ValueError("JM_GAP_SOURCE_IDENTITY_CHANGED")
    return dict(id=row["id"], url=row["url"], published_display_minute=POST, edited=row["edited"],
                scope=row["read_scope"], sha256=sha(encoded(row).encode()), historical_text_verified=False)


def opening_gap(minutes, opening, prior, *, band=(LOWER, UPPER)):
    first = next(bar for bar in minutes if bar.start == opening)
    if (prior.contract != first.contract or prior.end + US >= opening
            or first.end != opening + ONE):
        raise ValueError("JM_GAP_OPENING_IDENTITY_UNVERIFIED")
    previous, current = prior.close, first.open
    lower, upper = band
    return dict(open_at=opening, prior_bar_end=prior.end, prior_close=previous, opening_price=current,
                gap_points=current - previous, first_completed_bar_end=first.end, first_ohlc=ohlc(first),
                first_bar_contains_previous_close=first.low <= previous <= first.high,
                skipped_band_on_open_down=previous > upper and current < lower,
                skipped_band_on_open_up=previous < lower and current > upper)


def minute_bars(session, market, contract, day):
    raw = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, (day,))
    return [Bar(contract, bar.bar_end, *ohlc(bar), start=bar.bar_end - ONE) for bar in raw]


def first_containing(rows, price):
    return next((bar.end for bar in rows if bar.low <= price <= bar.high), None)


def adjacent_prices(rows):
    pairs = [(previous, bar) for previous, bar in zip(rows, rows[1:]) if previous.end == bar.start]
    if not pairs:
        raise ValueError("JM_GAP_NO_ADJACENT_MINUTES")
    previous, bar = max(pairs, key=lambda pair: abs(pair[1].open - pair[0].close))
    return dict(
        contiguous_pairs=len(pairs),
        largest_open_minus_prior_close=dict(at=bar.start, gap_points=bar.open - previous.close),
        whole_band_down_jumps=[bar.start for previous, bar in pairs if previous.close > UPPER and bar.open < LOWER],
        whole_band_up_jumps=[bar.start for previous, bar in pairs if previous.close < LOWER and bar.open > UPPER],
    )


def path(series, start, cutoff):
    rows = completed(series[1], start, cutoff)
    jumps = adjacent_prices(rows)
    signals, checks = window_signals(series, start, cutoff, "SHORT")
    overlap = [bar for bar in rows if bar.low <= UPPER and bar.high >= LOWER]
    first_touch = {str(edge): first_containing(rows, edge) for edge in (LOWER, UPPER)}
    return dict(start=start, strict_cutoff=cutoff, minutes=len(rows),
                low=min(bar.low for bar in rows), high=max(bar.high for bar in rows),
                first_band_overlap=overlap[0].end if overlap else None, band_overlap_bars=len(overlap),
                first_endpoint_touch=first_touch, adjacent_minute_open_jumps=jumps, prefix_checks=checks,
                short_geometry={clock: dict(total=len(events), first=events[0] if events else None,
                                            close_in_band=[event for event in events
                                                           if LOWER <= event["close"] <= UPPER])
                                for clock, events in signals.items()})


def study(session, market):
    source = source_binding()
    prior = minute_bars(session, market, CONTRACT, PRIOR)
    data = {day: read_window(session, market, CONTRACT, day) for day in (FOCAL, NEXT)}
    boundaries = {day: session_bounds(session, market, "jm", day) for day in data}
    previous, days = prior[-1], {}
    for day, series in data.items():
        sessions = boundaries[day]
        night_start, night_end = sessions[0]
        morning_open = at(f"{day}T09:00")
        if not (night_end < morning_open and any(start == morning_open for start, _ in sessions)):
            raise ValueError("JM_GAP_SESSION_BOUNDARIES_UNVERIFIED")
        minutes = series[1]
        night_close = next(bar for bar in minutes if bar.end == night_end)
        morning = opening_gap(minutes, morning_open, night_close)
        days[day.isoformat()] = dict(
            night=opening_gap(minutes, night_start, previous),
            morning=morning,
            apparent_morning_gap_if_night_omitted=morning["opening_price"] - previous.close,
            coverage={f"{p}m": dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()},
        )
        previous = minutes[-1]
    focal, following = data[FOCAL], data[NEXT]
    display_minute_cut = POST + ONE
    focal_night_start, focal_night_end = boundaries[FOCAL][0]
    next_night_start, next_night_end = boundaries[NEXT][0]
    return dict(
        version=VERSION, contract=CONTRACT, source=source, quoted_band=[LOWER, UPPER], openings=days,
        prior_day=dict(trading_day=PRIOR, minute_count=len(prior), sha256=digest(prior)),
        paths=dict(
            focal_preceding_night=path(focal, focal_night_start, focal_night_end + 2 * US),
            focal_morning_strictly_before_post_minute=path(focal, at(f"{FOCAL}T09:00"), POST),
            focal_starting_after_post_minute=path(focal, display_minute_cut, focal[1][-1].end + 2 * US),
            following_night=path(following, next_night_start, next_night_end + 2 * US),
            following_day=path(following, at(f"{NEXT}T09:00"), following[1][-1].end + 2 * US),
        ),
        band_application="RETROSPECTIVE_PRICE_COMPARISON_ONLY",
        author_band_effective_at=None, author_band_expires_at=None, author_signal_period=None,
        author_special_gap_qualified=None, author_time_for_signal=None, author_position_change=None,
        author_actions_scored=0, author_match_rate=None, fills=None, pnl=None, executable=False,
    )


def rubber_control(session, market):
    """Test the price context of a reported lock after a gap, without guessing its L boundary."""
    contract, day = "RU2601", date(2025, 10, 13)
    source = load_source(input_sources(), "G27130-171")
    post = datetime.fromisoformat(source["published_at"])
    morning = at(f"{day}T09:00")
    night_start, night_end = session_bounds(session, market, "ru", day)[0]
    prior = minute_bars(session, market, contract, date(2025, 10, 10))
    minutes = minute_bars(session, market, contract, day)
    if post != at(f"{day}T17:54") or not night_start < night_end < morning < minutes[-1].end < post:
        raise ValueError("JM_GAP_RU_SOURCE_OR_SESSION_UNVERIFIED")
    night_close = next(bar for bar in minutes if bar.end == night_end)
    day_rows = [bar for bar in minutes if bar.start >= morning]
    lower, reported_low, upper = map(Decimal, ("14795", "14835", "14855"))
    band = (lower, upper)
    return dict(
        version="lms405-rubber-gap-control-v1", source=source, contract=contract, trading_day=day,
        band=band, band_role="REPORTED_STRONG_SIDE_TARGET",
        night_open=opening_gap(minutes, night_start, prior[-1], band=band),
        day_open=opening_gap(minutes, morning, night_close, band=band),
        reported_low=reported_low, observed_day_low=min(bar.low for bar in day_rows),
        first_day_endpoint_or_low={str(price): first_containing(day_rows, price)
                                   for price in (lower, reported_low, upper)},
        coverage=dict(prior_minutes=len(prior), prior_sha256=digest(prior),
                      case_minutes=len(minutes), case_sha256=digest(minutes)),
        author_reported_system_lock=True, author_strategy_version=None, author_lock_at=None,
        author_l_boundary=None, author_opening_gap_caused_lock=None, historical_plan_verified=False,
        author_actions_scored=0, author_match_rate=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rubber-control", action="store_true")
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
            evaluate = rubber_control if args.rubber_control else study
            result = evaluate(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, StopIteration, ValueError) as exc:
        name = str(exc)
        parser.exit(2, (name if name.startswith("JM_GAP_") and name.isidentifier()
                        else "JM_GAP_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
