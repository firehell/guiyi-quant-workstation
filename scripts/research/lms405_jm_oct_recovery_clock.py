"""Constrain the JM2701 October 9 lock-to-long hypothesis using both holding photos."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from lms405_fg_sa_case import identity
from lms405_fg_sa_cycle_order import fresh_geometry
from lms405_fresh_reprotection import leg_envelope
from lms405_portfolio_retention_prices import feasible_retention
from lms405_position_continuity import continuity
from lms405_protection_lot_timing import displayed_tick_totals, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_replay import ohlc, photo_comparison, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms405_sizing_audit import SPECS, load_specs
from lms_near405_replay import encoded, sha

ROOT = Path("docs/research/lms405")
VERSION = "lms405-jm-oct-recovery-clock-v1"
CONTRACT = "JM2701"
DAYS = (date(2026, 10, 9), date(2026, 10, 12))
PHOTO = {
    "E11": dict(path="evidence/day-holdings.png", sha256="dc1c2012349c64ebce0dcfe5b36bd5fb901d93913b4783cda273ef873a910338",
                marks=dict(jm="1539.50", oi="10306.0", j="2020.00", i="682.50", ru="20645.0"),
                pvc_rounded_tick="4948", jm_long=dict(quantity=20, today=20, opening_average="1490.12"),
                jm_short=dict(quantity=20, today=20, opening_average="1543.30")),
    "E49": dict(path="evidence/night-holdings.png", sha256="b9cc52821a40b6209b7ee92cc54c620bfeeb908cc7c9db54dc53ae19c2269386",
                marks=dict(jm="1550.50", oi="10431.0", j="2033.00", i="683.50", ru="20845.0"),
                pvc_rounded_tick="4993", jm_long=dict(quantity=20, today=0, opening_average="1490.12"),
                jm_short=None),
}
JM_TICK = Decimal("0.5")
PLAN_START = at("2026-10-09T10:15")
DAY_CLOSE = at("2026-10-09T15:00")
NIGHT_START = at("2026-10-09T21:00")
UPDATE = at("2026-10-09T23:10")
SHORT_TERM_TARGET_UPPER = Decimal("1542.5")
EXTENSION_FAR = Decimal("1571")
WEAK_REFERENCE = Decimal("1517.5")
M_BAND = (Decimal("1507.5"), Decimal("1512.5"))
BASELINE = Path("output/lms405-jm-oct-recovery-clock-20261126/final-a.json")
BASELINE_SHA = "00de58c37951973e50c262ba2b6981ec8878b4b2baaa34a557e5a00bf03d0167"
PORTFOLIO_LEGS = (
    ("V2701", "long", 40, 40, "4930.3"),
    ("OI2701", "long", 40, 0, "10046.2"),
    ("JM2701", "long", 20, 20, "1490.12"),
    ("I2701", "short", 16, 16, "684.50"),
    ("RU2701", "long", 20, 0, "18925.0"),
)


def source_bindings():
    with (ROOT / "sources.csv").open(newline="", encoding="utf-8") as stream:
        evidence = {row[0]: dict(url=row[1], published_at=at(row[3].replace(" ", "T")))
                    for row in csv.reader(stream) if row[0] in {"E11", "E48", "E49"}}
    if evidence["E48"]["published_at"] + ONE != PLAN_START:
        raise ValueError("JM_OCT_PLAN_TIME_CHANGED")
    for source, row in PHOTO.items():
        if sha((ROOT / row["path"]).read_bytes()) != row["sha256"]:
            raise ValueError("JM_OCT_PHOTO_CHANGED")
        evidence[source].update(row)
    return evidence


def window_signals(series, start, cutoff, side):
    signals = fresh_geometry(series, start, cutoff, side)
    checks = {row["available_at"] for rows in signals.values() for row in rows}
    checks |= {cut + US for cut in checks if cut + US < cutoff}
    for cut in sorted(checks):
        prefix = {p: [b for b in bars if b.end + US < cut] for p, bars in series.items()}
        expected = {clock: [row for row in rows if row["available_at"] < cut] for clock, rows in signals.items()}
        if fresh_geometry(prefix, start, cut, side) != expected:
            raise ValueError("JM_OCT_PREFIX_DIVERGED")
    return signals, len(checks)


def price_checks(bars):
    return dict(minimum=min(b.low for b in bars), maximum=max(b.high for b in bars),
                first_strict_close_above_1542_5=next((b.end for b in bars if b.close > SHORT_TERM_TARGET_UPPER), None),
                first_directional_reach_1517_5=next((b.end for b in bars if b.low <= WEAK_REFERENCE), None),
                first_m_overlap=next((b.end for b in bars if b.low <= M_BAND[1] and b.high >= M_BAND[0]), None),
                first_directional_reach_1571=next((b.end for b in bars if b.high >= EXTENSION_FAR), None))


def observed_before_quote(signals, quote_minutes):
    return {clock: [dict(confirmed_at=row["confirmed_at"], close=row["close"],
                         strict_before_candidates=sum(row["available_at"] < end - ONE for end in quote_minutes),
                         closes_above_1542_5=row["close"] > SHORT_TERM_TARGET_UPPER)
                    for row in rows] for clock, rows in signals.items()}


def portfolio_leg_study(report, quotes):
    if encoded(report) != encoded(verified_json(BASELINE, BASELINE_SHA)):
        raise ValueError("JM_OCT_BASELINE_CHANGED")
    with SPECS.open(encoding="utf-8") as stream:
        specs = load_specs(json.load(stream))
    before_close = datetime.fromisoformat(report["photos"]["E11"]["primary"]["joint_equal_close"][0])
    common_night = datetime.fromisoformat(report["photos"]["E49"]["primary"]["joint_contains"][0])
    night_post = report["sources"]["E49"]["published_at"]
    if not before_close == DAY_CLOSE or not NIGHT_START < common_night < night_post:
        raise ValueError("JM_OCT_PORTFOLIO_CLOCK_CHANGED")
    pairs = {}
    for contract, side, lots, before_today, shown_average in PORTFOLIO_LEGS:
        symbol = contract[:-4].lower()
        specs_row = specs[contract]
        tick = specs_row["tick"]
        day, night = quotes["E11"][symbol], quotes["E49"][symbol]
        if (day[-1].bar_end, night[0].bar_end - ONE) != (before_close, NIGHT_START):
            raise ValueError("JM_OCT_PORTFOLIO_SESSION_CLOCK_CHANGED")
        before = dict(quantity=lots, today_quantity=before_today, opening_average=shown_average)
        after = before | dict(today_quantity=0)
        totals = displayed_tick_totals(Decimal(shown_average), lots, tick, include_upper_tie=True)
        if not totals:
            raise ValueError("JM_OCT_PORTFOLIO_AVERAGE_OUTSIDE_TICK_GRID")
        unconstrained_old = (1, totals.stop - 1)
        old = tick_bounds(day, tick) if before_today == lots else unconstrained_old
        choices = {}
        for name, end in (("five_quote_candidate_minute", common_night), ("before_published_minute", night_post - US)):
            window = [bar for bar in night if bar.bar_end <= end]
            bounds = tick_bounds(window, tick)
            new_without_today = after | dict(today_quantity=None)
            compatible = feasible_retention(lots, new_without_today, (0, lots), totals, totals,
                                            unconstrained_old, None, bounds, same_day=False)
            with_day_quantity = feasible_retention(lots, new_without_today, (0, lots), totals, totals,
                                                   old, None, bounds, same_day=False)
            if not compatible or not with_day_quantity:
                raise ValueError("JM_OCT_PORTFOLIO_PRICE_SCOPE_CONFLICT")
            choices[name] = dict(minute_count=len(window), last_bar_end=window[-1].bar_end,
                                 replacement_price_bounds=[tick * value for value in bounds],
                                 retained_if_only_using_prices=[min(compatible), max(compatible)],
                                 retained_using_day_today_quantity=[min(with_day_quantity), max(with_day_quantity)],
                                 full_replacement_possible=0 in compatible)
        pairs[contract] = dict(side=side, day=before, night=after, tick=tick,
                               spec_source_sha256=specs_row["source_sha256"], price_windows=choices,
                               displayed_opening_total_ticks=[totals.start, totals.stop - 1],
                               conditional_session_retention=continuity(before, after, same_day=False,
                                                                        at_prior_session_close=True)["bounds"])
    return dict(
        version="lms405-oct9-portfolio-leg-carry-v1", base_report_sha256=BASELINE_SHA,
        rounding_assumption="CLOSED_HALF_DISPLAY_UNIT_ENVELOPE",
        sources=report["sources"], photos=report["photos"], market_1m=report["market_1m"], common_legs=pairs,
        day_display_total=206, night_display_total=146,
        unlisted_at_night={"OI2701": dict(side="short", previously_visible=40, later_quantity=None),
                          "JM2701": dict(side="short", previously_visible=20, later_quantity=None)},
        quote_capture_is_confirmed=False, actual_account_continuity=None, day_rows_version_verified=False,
        author_action_at=None, author_actions_scored=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def study(session, market, *, portfolio_legs=False):
    sources = source_bindings()
    series = {day: read_window(session, market, CONTRACT, day) for day in DAYS}
    photos = {}
    minute_info = {}
    quotes = {}
    for source, day, start in (("E11", DAYS[0], at("2026-10-09T09:00")), ("E49", DAYS[1], NIGHT_START)):
        row = sources[source]
        cutoff = row["published_at"]
        minutes = {symbol: read_session_series(session, market, symbol, f"{symbol.upper()}2701", "1m", ONE, (day,))
                   for symbol in (*row["marks"], "v")}
        if ([(b.bar_end, ohlc(b)) for b in minutes["jm"]] != [(b.end, ohlc(b)) for b in series[day][1]]):
            raise ValueError("JM_OCT_QUOTE_INPUT_MISMATCH")
        quotes[source] = minutes
        minute_info[source] = {symbol: identity(bars) for symbol, bars in minutes.items()}
        photos[source] = dict(primary=photo_comparison(minutes, start, cutoff, row["marks"]),
                              pvc_rounded_sensitivity=photo_comparison(
                                  minutes, start, cutoff, row["marks"] | {"v": row["pvc_rounded_tick"]},
                              ))
    close_quotes = photos["E11"]["primary"]["joint_equal_close"]
    if [datetime.fromisoformat(t) for t in close_quotes] != [DAY_CLOSE]:
        raise ValueError("JM_OCT_DAY_CLOSE_ANCHOR_CHANGED")
    night_quotes = [datetime.fromisoformat(t) for t in photos["E49"]["primary"]["per_symbol"]["jm"]["contains"]]
    if not night_quotes:
        raise ValueError("JM_OCT_NO_NIGHT_JM_QUOTE_CANDIDATE")

    day, night = (series[d] for d in DAYS)
    close_cut = DAY_CLOSE + 2 * US
    day_short, day_checks = window_signals(day, PLAN_START, close_cut, "SHORT")
    # Every minute of the trading day may contribute to the displayed today quantity.
    leg = sources["E11"]["jm_short"]
    short_bounds = {key: [row | dict(price_bound=leg_envelope(day[1], row["confirmed_at"], close_cut, leg, JM_TICK))
                          for row in events] for key, events in day_short.items()}
    night_long, night_checks = window_signals(night, NIGHT_START, UPDATE, "LONG")
    report = dict(version=VERSION, contract=CONTRACT, sources=sources, photos=photos,
                quote_capture_is_confirmed=False, actual_account_continuity=None,
                market_1m=minute_info, market_jm={str(d): {f"{p}m": digest(b) for p, b in s.items()} for d, s in series.items()},
                day_protection=dict(path=price_checks(completed(day[1], PLAN_START, close_cut)),
                                    same_trading_day_short_lot_bounds=short_bounds),
                night_before_post=price_checks(completed(night[1], NIGHT_START, sources["E49"]["published_at"])),
                night_before_update=dict(path=price_checks(completed(night[1], NIGHT_START, UPDATE)),
                                         long_candidates_for_release_hypothesis=observed_before_quote(night_long, night_quotes)),
                prefix_checks=day_checks + night_checks, author_bd_at=None, author_action_at=None,
                author_actions_scored=0, author_match_rate=None, executable=False, fills=None, pnl=None)
    return portfolio_leg_study(report, quotes) if portfolio_legs else report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--portfolio-legs", action="store_true")
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
            report = study(session, build_market_data_service(session), portfolio_legs=args.portfolio_legs)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("JM_OCT_")
                        else "JM_OCT_CLOCK_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
