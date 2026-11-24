"""Compare source-linked right-side price prerequisites in fixed local windows."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from guiyi_quant.lms405 import Bar
from lms405_counter_m_study import beyond, subsequent_confirmation
from lms405_locked_exit_audit import confirmed_shapes, verify_aggregation
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

LOCAL = ZoneInfo("Asia/Shanghai")
ONE, FIVE, US = timedelta(minutes=1), timedelta(minutes=5), timedelta(microseconds=1)
SOURCE_WINDOWS = (
    ("v-long", "V2701", "2026-10-28", "2026-10-27T21:00", "2026-10-27T22:14", "LONG",
     "5195", None, "5232", ("A5358686423089344", "WRoEvFgWlh")),
    ("v-short-night", "V2701", "2026-10-27", "2026-10-26T21:00", "2026-10-26T23:01", "SHORT",
     "5055", "5074", "5045", ("A5358325549629506", "WRoCxx1ooa")),
    ("v-short-day", "V2701", "2026-10-27", "2026-10-27T09:00", "2026-10-27T15:01", "SHORT",
     "5055", "5074", "5045", ("A5358325549629506", "WRoCxx1ooa")),
    ("ru-short", "RU2701", "2026-10-27", "2026-10-26T21:00", "2026-10-27T15:01", "SHORT",
     "19505", None, "19370", ("A5358325972992140", "U05")),
    ("sh-short", "SH2701", "2026-10-22", "2026-10-22T09:31", "2026-10-22T15:01", "SHORT",
     "1653", None, "1623", ("WRnOnrllRX",)),
)


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=LOCAL)


def observed_at(bar):
    return bar.bar_end.astimezone(LOCAL).isoformat() if bar is not None else None


def ordered_closes(bars, levels, side):
    """One completed bar per step; several nested levels cannot be ordered inside one bar."""
    rows, remaining = [], iter(bars)
    for raw in levels:
        level = Decimal(raw)
        bar = next((b for b in remaining if beyond(b.close, level, side)), None)
        rows.append(dict(level=level, at=observed_at(bar), close=bar.close if bar else None))
        if bar is None:
            break
    return rows


def retest_path(bars, edge, opposite, side):
    """A labeled local hypothesis for break, later contact, later rejection."""
    brk = tested = previous = None
    for bar in bars:
        if previous and previous + ONE != bar.bar_end:
            brk = tested = None
        previous = bar.bar_end
        if brk is None:
            if beyond(bar.close, edge, side):
                brk = bar
            continue
        # A close through the opposite endpoint invalidates the current attempt.
        if beyond(opposite, bar.close, side):
            brk = tested = None
        elif tested and beyond(bar.close, edge, side):
            return brk, tested, bar
        elif tested is None and bar.low <= edge <= bar.high:
            tested = bar
    return brk, tested, None


def price_window(raw, contract, start, cut, side, edge, opposite, reference):
    minutes = [b for b in raw["1m"] if start <= b.bar_end - ONE and b.bar_end + US < cut]
    fives = [b for b in raw["5m"] if start <= b.bar_end - FIVE and b.bar_end + US < cut]
    if not minutes or not fives:
        raise ValueError("COMPLETED_PRICE_WINDOW_REQUIRED")
    breakout = {period: next((b for b in series if beyond(b.close, edge, side)), None)
                for period, series in (("1m", minutes), ("5m", fives))}
    setup = breakout["1m"]
    retest = None
    if opposite is not None:
        brk, tested, setup = retest_path(minutes, edge, opposite, side)
        retest = dict(restart_break_at=observed_at(brk), contact_at=observed_at(tested), rejection_at=observed_at(setup))
    research_fives = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw["5m"]]
    shapes = [s for s in confirmed_shapes(research_fives, raw["1m"], start=start, through=cut - 2 * US, side=side)
              if datetime.fromisoformat(s["shape_at"]) - FIVE >= start]
    quotes, segment = {}, None
    for bar in minutes:
        if bar.bar_end - ONE not in quotes:
            segment = bar.bar_end
        quotes[bar.bar_end] = (bar.close, segment)
    after = {variant: subsequent_confirmation(shapes, setup.bar_end if setup else None, field,
                                              shape_close_after_breach=False, quotes=quotes,
                                              level=edge, side=side)
             for variant, field in (("next-slot-1m", "fast_at"), ("next-5m", "slow_at"))}
    for event in after.values():
        if event:
            close = Decimal(event["confirmation_close"])
            event["signed_distance_to_reference"] = reference - close if side == "LONG" else close - reference
    first_ref = next((b for b in minutes if (b.high >= reference if side == "LONG" else b.low <= reference)), None)
    return dict(first_beyond={p: observed_at(b) for p, b in breakout.items()}, proposed_retest=retest,
                reference_price=reference, first_reference_reached=observed_at(first_ref),
                first_shape_confirmation_after_price_setup=after, shapes=shapes,
                high=max(b.high for b in minutes), low=min(b.low for b in minutes))


def study(session, market):
    from app.market_data.market_data_service import MarketDataError

    cases = {}
    for name, contract, trading_day, start, cut, side, edge, opposite, ref, sources in SOURCE_WINDOWS + (
        ("jm-transition", "JM2509", "2025-07-28", None, None, None, None, None, None, ("S5193109300577840",)),
    ):
        row = cases[name] = dict(contract=contract, trading_day=trading_day, sources=sources, state_or_author_action=None)
        try:
            raw = {period: read_session_series(session, market, contract[:-4].lower(), contract, period, step,
                                               (date.fromisoformat(trading_day),))
                   for period, step in (("1m", ONE), ("5m", FIVE))}
            verify_aggregation([Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw["5m"]], raw["1m"])
        except MarketDataError as exc:
            row.update(status="LOCAL_WINDOW_UNVERIFIED", reason=exc.code)
            continue
        except (ValueError, KeyError):
            row.update(status="LOCAL_WINDOW_UNVERIFIED", reason="AGGREGATION_OR_SESSION_COVERAGE_UNVERIFIED")
            continue
        row.update(status="WINDOW_READABLE", input={p: dict(count=len(bars), hash=sha(encoded([
                       (b.bar_end.isoformat(), *map(str, ohlc(b))) for b in bars]).encode())) for p, bars in raw.items()})
        if name == "jm-transition":
            night_end, day_start = at("2025-07-25T23:01"), at("2025-07-28T09:00")
            night = {p: [b for b in bars if b.bar_end < night_end] for p, bars in raw.items()}
            day = {p: [b for b in bars if b.bar_end > day_start] for p, bars in raw.items()}
            peak = max(night["1m"], key=lambda b: b.high)
            post_peak = {p: [b for b in night[p] if b.bar_end - step >= peak.bar_end]
                         for p, step in (("1m", ONE), ("5m", FIVE))}
            row.update(night_high=peak.high, first_night_high_at=observed_at(peak),
                       night_frames={p: ordered_closes(bars, ("1233", "1229.5", "1207"), "SHORT")
                                     for p, bars in night.items()},
                       post_peak_frames={p: ordered_closes(bars, ("1233", "1229.5", "1207"), "SHORT")
                                         for p, bars in post_peak.items()},
                       post_peak_scope="RETROSPECTIVE_FULL_NIGHT_HIGH_NOT_A_SIGNAL_INPUT",
                       monday_frames={p: ordered_closes(bars, ("1155.5", "1185", "1204", "1233.5"), "LONG")
                                      for p, bars in day.items()},
                       monday_high=max((b.high for b in day["1m"]), default=None))
        else:
            row.update(window=[start, cut], side=side, break_outer_edge=edge,
                       **price_window(raw, contract, at(start), at(cut), side, Decimal(edge),
                                      Decimal(opposite) if opposite else None, Decimal(ref)))
    return dict(version="lms405-right-side-research-v1", cases=cases, executable=False,
                admitted_author_samples=0, author_matches=None, fills=None, pnl=None)


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
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded(report))


if __name__ == "__main__":
    main()
