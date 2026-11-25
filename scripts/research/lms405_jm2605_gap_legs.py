"""Bound the displayed February JM2605 position legs around the reported night gap."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_fresh_reprotection import leg_envelope
from lms405_jm1072_stability import session_bounds
from lms405_jm_gap_protection import opening_gap
from lms405_jm_oct_recovery_clock import window_signals
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, latest_whole_leg_start, tick_bounds
from lms405_protection_timeframes import read_window
from lms405_replay import ohlc
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

CONTRACT, TICK = "JM2605", Decimal("0.5")
FIRST, SECOND = date(2026, 2, 4), date(2026, 2, 5)
ROOT = Path("docs/research/lms405/evidence")
FROZEN = Path("output/lms405-jm2605-feb-20261021/market-read-authorized/JM2605_2026-02-04_2026-02-05_1m.csv")
FROZEN_SHA = "13ee78bd70d6502efa6b2a7d3384da3b06b856df5d10b94bb4b06a4f93aee35e"
MORNING_PLAN, FIRST_TARGET_REPORT, DAY_SCREEN, NIGHT_SCREEN = (
    at("2026-02-04T10:36"), at("2026-02-04T11:33"), at("2026-02-04T15:08"), at("2026-02-04T23:04"),
)
EARLY_SCREEN, LUNCH_SCREEN, LATE_SCREEN = (
    at("2026-02-05T10:44"), at("2026-02-05T11:35"), at("2026-02-05T16:02"),
)
EARLY_BAND = Decimal("1190.5"), Decimal("1201.5")
NIGHT_BAND = Decimal("1200"), Decimal("1212")
SHORT = {"quantity": 44, "opening_average": "1221.95"}
LONG = {"quantity": 44, "opening_average": "1170.50"}
SHORT_TODAY_AT_NIGHT_SCREEN = 0


def source_bindings():
    expected = {"L01": DAY_SCREEN, "L02": NIGHT_SCREEN, "L03": EARLY_SCREEN, "L06": MORNING_PLAN,
                "L07": FIRST_TARGET_REPORT, "K06": LATE_SCREEN, "K07": LUNCH_SCREEN,
                "K02": at("2026-02-05T15:36"), "K03": at("2026-02-04T17:30")}
    records = {}
    for filename, key in (("jm2605-period-recovery-20261017.csv", "id"), ("jm2605-feb-timeline-20261021.csv", "source_id")):
        file = ROOT / filename
        with file.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                source = row[key]
                if source in expected:
                    published = at(row["published_shanghai"][:16].replace(" ", "T"))
                    if source in records or expected[source] != published:
                        raise ValueError("JM_FEB_SOURCE_TIME_CHANGED")
                    records[source] = dict(url=row["url"], display_minute=published, source_index=file.as_posix(),
                                           row_sha256=sha(encoded(row).encode()))
    if records.keys() != expected.keys():
        raise ValueError("JM_FEB_SOURCE_MISSING")
    return records


def verify_frozen(minutes):
    raw = FROZEN.read_bytes()
    if sha(raw) != FROZEN_SHA:
        raise ValueError("JM_FEB_FROZEN_HASH_CHANGED")
    expected = [(row["contract"], row["frequency"], datetime.fromisoformat(row["bar_end_utc"]),
                 *(Decimal(row[k]) for k in ("open", "high", "low", "close")))
                for row in csv.DictReader(raw.decode().splitlines())]
    if expected != [(b.contract, "1m", b.end, *ohlc(b)) for b in minutes]:
        raise ValueError("JM_FEB_FROZEN_MDS_BARS_DIVERGED")


def overlap(rows, band):
    return next((bar for bar in rows if bar.low <= band[1] and bar.high >= band[0]), None)


def lots_split(earlier, later, leg):
    lots = leg["quantity"]
    totals = displayed_tick_totals(Decimal(leg["opening_average"]), lots, TICK)
    compatible = earlier_lot_counts(tick_bounds(earlier, TICK), tick_bounds(later, TICK), lots, totals)
    return dict(earlier_range_ticks=tick_bounds(earlier, TICK), later_range_ticks=tick_bounds(later, TICK),
                total_tick_sum_min=totals.start, total_tick_sum_max=totals.stop - 1,
                min_earlier=min(compatible, default=None),
                min_later=lots - max(compatible) if compatible else None, whole_in_later=0 in compatible,
                whole_in_earlier=lots in compatible)


def inspect_short(first, night):
    minutes = first[1]
    same_day = completed(minutes, minutes[0].start, DAY_SCREEN)
    after_morning_source = [b for b in same_day if b.start >= MORNING_PLAN + ONE]
    levels = {"target_a_far": Decimal("1224.5"), "target_b_near": Decimal("1226")}
    checkpoints = {name: next((b for b in after_morning_source if b.low <= level <= b.high), None)
                   for name, level in levels.items()}
    checkpoints["first_new_protection_touch"] = overlap(after_morning_source, EARLY_BAND)
    geometry, checks = window_signals(first, MORNING_PLAN + ONE, DAY_SCREEN, "SHORT")
    return dict(
        leg=SHORT, first_source_band=EARLY_BAND,
        latest_whole_leg_window_start=latest_whole_leg_start(same_day, TICK, SHORT["quantity"],
            displayed_tick_totals(Decimal(SHORT["opening_average"]), SHORT["quantity"], TICK),
            start_of=lambda bar: bar.start),
        gates={name: dict(end=bar.end, high=bar.high,
                         timing=leg_envelope(same_day, bar.end, DAY_SCREEN, SHORT, TICK)) if bar else None
               for name, bar in checkpoints.items()},
        short_geometry_after_full_publication_minute={clock: [event | dict(
            close_within_update_band=EARLY_BAND[0] <= event["close"] <= EARLY_BAND[1],
            timing=leg_envelope(same_day, event["confirmed_at"], DAY_SCREEN, SHORT, TICK))
            for event in candidates] for clock, candidates in geometry.items()},
        nightly_rebuild_if_same_display=lots_split(same_day, night, SHORT),
        night_screen_displayed_short_today=SHORT_TODAY_AT_NIGHT_SCREEN,
        prefix_checks=checks, observed_lock_actual=None,
    )


def study(session, market):
    sources = source_bindings()
    first = read_window(session, market, CONTRACT, FIRST)
    second = read_window(session, market, CONTRACT, SECOND)
    verify_frozen(first[1] + second[1])
    start, night_end = session_bounds(session, market, "jm", SECOND)[0]
    night = completed(second[1], start, night_end + 2 * US)
    morning = at(f"{SECOND}T09:00")
    day = completed(second[1], morning, LATE_SCREEN)
    if not first[1][-1].end < DAY_SCREEN < sources["K03"]["display_minute"] < start < night_end < NIGHT_SCREEN < morning:
        raise ValueError("JM_FEB_SESSION_SOURCE_ORDER_CHANGED")
    if day[0].start != morning or night[-1].end != night_end:
        raise ValueError("JM_FEB_SESSION_PRICE_MISSING")
    night_touch = overlap(night, NIGHT_BAND)
    long_splits = {source: lots_split(
        [bar for bar in second[1] if bar.start < cut + ONE], [bar for bar in day if bar.start >= cut + ONE], LONG,
    ) for source, cut in (("L03", EARLY_SCREEN), ("K07", LUNCH_SCREEN))}
    return dict(
        version="lms405-jm2605-gap-legs-v1", contract=CONTRACT, sources=sources,
        coverage={day: {p: dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()}
                  for day, series in ((str(FIRST), first), (str(SECOND), second))},
        frozen_1m_sha256=FROZEN_SHA, current_visible_sources_history_verified=False,
        lot_bound_scope="CONDITIONAL_ON_ALL_DISPLAYED_LOTS_PRICED_WITHIN_THE_TWO_COMPARED_WINDOWS",
        night_open=opening_gap(night, start, first[1][-1], band=NIGHT_BAND),
        next_day_open=opening_gap(day, morning, night[-1], band=NIGHT_BAND),
        first_night_overlap=night_touch.end if night_touch else None,
        short=inspect_short(first, night),
        long=dict(leg=LONG, night_to_day=lots_split(night, day, LONG), first_price_compatible_single_minute=next(
            (bar.end for bar in day if bar.low <= Decimal(LONG["opening_average"]) <= bar.high), None),
            windows_after_missing_long_rows=long_splits,
            earlier_long_absent=None, actual_new_long_at=None),
        actual_strategy_identity=None, same_account_verified=False, actual_fills=None,
        author_actions_scored=0, author_match_rate=None, executable=False, pnl=None,
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
    except (OSError, KeyError, StopIteration, ValueError) as exc:
        name = str(exc)
        parser.exit(2, (name if name.startswith("JM_FEB_") and name.isidentifier()
                        else "JM_FEB_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
