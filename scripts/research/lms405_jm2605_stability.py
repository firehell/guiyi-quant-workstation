"""Compare completed volatility context and signal order in two JM2605 plan windows."""

import argparse
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from lms405_jm_oct_recovery_clock import window_signals
from lms405_protection_timeframes import read_window
from lms405_right_side_study import LOCAL, ONE, US
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

CONTRACT = "JM2605"
VERSION = "lms405-jm2605-stability-context-v1"
SOURCE = Path("docs/research/lms405/evidence/jm2605-period-recovery-20261017.csv")
CASES = {
    "K01": (date(2026, 1, 7), date(2026, 1, 8)),
    "K04": (date(2026, 1, 29), date(2026, 1, 30)),
}
K01_BANDS = {name: tuple(map(Decimal, prices)) for name, prices in {
    "regular_protection": ("1177.5", "1183"),
    "early_protection": ("1186.5", "1190.5"),
    "strong_target": ("1215.5", "1220.5"),
}.items()}


def stability_context(fifteens, as_of):
    """Retain raw ranges and two descriptive contraction comparisons only."""
    seen = [bar for bar in fifteens if bar.end + US < as_of]
    if not seen:
        return None
    latest = seen[-1]
    baseline = seen[0].high - seen[0].low
    trailing = [bar.high - bar.low for bar in seen[-3:]]
    return dict(last_completed_15m_end=latest.end, opening_range=baseline, trailing_ranges=trailing,
                latest_narrower_than_opening=trailing[-1] < baseline,
                strict_two_in_sequence=(trailing[0] > trailing[1] > trailing[2]) if len(trailing) == 3 else None)


def compare_after_lock(night, long_events, scenario):
    return {clock: [event | dict(
        fresh_shape_after_hypothetical_lock=scenario["available_at"] < event["shape_start"],
        context_before_shape=stability_context(night[15], event["shape_start"]),
        context_before_confirmation=stability_context(night[15], event["confirmed_at"]),
    ) for event in rows if scenario["available_at"] < event["available_at"]] for clock, rows in long_events.items()}


def inspect(session, market, source, prior_day, day, bands):
    prior = read_window(session, market, CONTRACT, prior_day)
    series = read_window(session, market, CONTRACT, day)
    publication = datetime.fromisoformat(source["published_shanghai"]).replace(tzinfo=LOCAL)
    start = series[1][0].start.astimezone(LOCAL)
    if (start.date() != publication.date() or (start.hour, start.minute) != (21, 0)
            or prior[1][-1].end.astimezone(LOCAL).date() != start.date() or not prior[1][-1].end < start < publication):
        raise ValueError("JM2605_SOURCE_NIGHT_CHANGED")
    night_end = start + timedelta(hours=2)
    cut = night_end + 2 * US
    night = {period: completed(bars, start, cut) for period, bars in series.items()}
    if len(night[15]) != 8 or any(left.end != right.start for left, right in zip(night[15], night[15][1:])):
        raise ValueError("JM2605_NIGHT_15M_GAP")
    short, short_checks = window_signals(night, start, cut, "SHORT")
    long, long_checks = window_signals(night, start, cut, "LONG")
    usable_after = publication + ONE
    price_areas = {name: dict(
        band=band,
        first_night_touch=next((b.end for b in night[1] if b.low <= band[1] and b.high >= band[0]), None),
        first_touch_in_completed_bar_starting_after_post_minute=next((b.end for b in night[1]
            if b.start >= usable_after and b.low <= band[1] and b.high >= band[0]), None),
    ) for name, band in bands.items()}
    short_events = {clock: [event | dict(
        shape_entirely_after_post_minute=event["shape_start"] >= usable_after,
        available_after_post_minute=event["available_at"] > usable_after,
        closing_price_in_areas=[name for name, band in bands.items() if band[0] <= event["close"] <= band[1]],
    ) for event in rows] for clock, rows in short.items()}
    if "early_protection" in bands:
        lock_options = [event for event in short_events["5m_to_1m"] if event["available_after_post_minute"]
                        and "early_protection" in event["closing_price_in_areas"]]
    else:
        lock_options = [event for event in short_events["1m_to_1m"] if event["shape_entirely_after_post_minute"]][:1]
    return dict(source=source, prior_trading_day=prior_day, trading_day=day, night_start=start, night_end=night_end,
                prior_close=prior[1][-1].close, open_gap=night[1][0].open - prior[1][-1].close,
                series_sha256={name: {p: digest(rows) for p, rows in bars.items()}
                               for name, bars in (("prior", prior), ("study", series))},
                price_areas=price_areas, short_candidates=short_events, long_candidates=long,
                night_15m_ranges=[(b.end, b.high - b.low) for b in night[15]],
                conditional_paths=[dict(hypothetical_lock=lock,
                                        subsequent_candidates=compare_after_lock(night, long, lock))
                                   for lock in lock_options],
                prefix_checks=short_checks + long_checks, actual_lock_at=None, actual_unlock_at=None,
                author_volatility_stable=None, author_bd_at=None)


def study(session, market):
    with SOURCE.open(newline="", encoding="utf-8") as stream:
        index = {row["id"]: row for row in csv.DictReader(stream)}
    cases = {key: inspect(session, market, index[key], prior, day, K01_BANDS if key == "K01" else {})
             for key, (prior, day) in CASES.items()}
    return dict(version=VERSION, contract=CONTRACT, source_index_sha256=sha(SOURCE.read_bytes()), cases=cases,
                source_revision_verified=False, observed_volatility_rule=None,
                author_actions_scored=0, author_match_rate=None, executable=False, fills=None, pnl=None)


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
        parser.exit(2, "JM2605_STABILITY_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
