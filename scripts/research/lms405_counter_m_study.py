"""Read-only ordering study for the interruption and countertrend M signals."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from guiyi_quant.lms405 import Bar
from lms405_locked_exit_audit import confirmed_shapes, verify_aggregation
from lms405_portfolio_replay import FIVE
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

SHANGHAI = ZoneInfo("Asia/Shanghai")
ONE = timedelta(minutes=1)
US = timedelta(microseconds=1)

# Each label identifies the interpretation of one endpoint, independent of the others.
# A publication bound limits price observations only. It never supplies author inputs.
CASES = (
    ("oi2605", "OI2605", ("2025-12-22",), "LONG",
     "2025-12-22T09:00", "2025-12-22T15:01", ("S5246699477926773",),
     (("m_near", "8738"), ("m_far", "8814"))),
    ("oi2609_prior_day", "OI2609", ("2026-06-04", "2026-06-05"), "SHORT",
     "2026-06-04T09:00", "2026-06-04T15:01", ("S5306128623993006", "S5306393997347489"),
     (("prior_protection_far", "10273"), ("same_day_low", "10230"))),
    ("oi2609_before_update", "OI2609", ("2026-06-04", "2026-06-05"), "SHORT",
     "2026-06-04T21:00", "2026-06-05T10:26", ("F09", "S5306393997347489"),
     (("prior_protection_far", "10273"), ("prior_day_low", "10230"))),
    ("jm2601_before_observation", "JM2601", ("2025-12-01",), "LONG",
     "2025-12-01T09:00", "2025-12-01T10:04", ("N02", "O02", "M01", "N04"),
     (("interruption_near", "1069"), ("interruption_far", "1077.5"))),
    ("jm2601_between_posts", "JM2601", ("2025-12-01",), "LONG",
     "2025-12-01T09:35", "2025-12-01T10:04", ("N02", "O02", "M01", "N04"),
     (("interruption_near", "1069"), ("interruption_far", "1077.5"))),
    ("jm2609_failed_long", "JM2609", ("2026-05-21",), "LONG",
     "2026-05-21T09:00", "2026-05-21T15:01", ("G02", "G07"),
     (("divider_near", "1223"), ("divider_far", "1228.5"), ("long_target_near", "1229"))),
    ("jm2701_extreme_m", "JM2701", ("2026-10-23",), "LONG",
     "2026-10-22T21:00", "2026-10-23T15:01", ("A5356884629782554", "WRo0OCbeQG"),
     (("interruption_far", "1397.5"), ("m_near", "1410.5"),
      ("m_far", "1420"), ("extreme_m_near", "1420.5"), ("extreme_m_far", "1427.5"))),
)


def local_time(value):
    return value.astimezone(SHANGHAI).isoformat(timespec="minutes")


def beyond(price, level, side):
    return price > level if side == "LONG" else price < level


def first_breach(bars, *, field, level, side):
    for bar in bars:
        if beyond(getattr(bar, field), level, side):
            return bar.end
    return None


def subsequent_confirmation(shapes, breach, field, *, shape_close_after_breach, quotes, level, side):
    if breach is None:
        return None
    after = (row for row in shapes if row[field]
             and datetime.fromisoformat(row[field]) > breach
             and (not shape_close_after_breach or datetime.fromisoformat(row["shape_at"]) > breach))
    first = min(after, key=lambda row: datetime.fromisoformat(row[field]), default=None)
    if first is None:
        return None
    at = datetime.fromisoformat(first[field])
    close, session = quotes[at]
    return dict(shape_at=local_time(datetime.fromisoformat(first["shape_at"])),
                confirmation_at=local_time(at), keybar_boundary=first["level"],
                confirmation_close=str(close), close_beyond_price_endpoint=beyond(close, level, side),
                uninterrupted_minute_coverage=(session == quotes[breach][1]))


def examine(minutes, fives, *, start, cut, side, levels):
    one = [bar for bar in minutes if start <= bar.bar_end - ONE and bar.bar_end < cut]
    five = [bar for bar in fives if start <= bar.start and bar.end < cut]
    if not one or not five:
        raise ValueError("CASE_HAS_NO_COMPLETED_BARS")
    # The shared detector needs authoritative minute objects for each shape's next slot.
    # A shape must follow the start and its confirmation must precede the cut.
    shapes = [shape for shape in confirmed_shapes(fives, minutes, start=start, through=cut - US, side=side)
              if datetime.fromisoformat(shape["shape_at"]) - FIVE >= start]
    minute_bars = [Bar(fives[0].contract, b.bar_end, *ohlc(b), start=b.bar_end - ONE) for b in one]
    # The authoritative 1m close at each 5m end equals the 5m close.
    quotes = {}
    session = None
    for bar in minute_bars:
        if bar.start not in quotes:
            session = bar.start
        quotes[bar.end] = (bar.close, session)
    events = {}
    for label, value in levels:
        level = Decimal(value)
        paths = {}
        for name, series, field in (
            ("strict_1m_excursion", minute_bars, "high" if side == "LONG" else "low"),
            ("strict_1m_close", minute_bars, "close"),
            ("strict_5m_close", five, "close"),
        ):
            breach = first_breach(series, field=field, level=level, side=side)
            paths[name] = dict(
                first_bar_end=local_time(breach) if breach else None,
                confirmation={
                    key: {window: subsequent_confirmation(shapes, breach, field, shape_close_after_breach=fresh,
                                                           quotes=quotes, level=level, side=side)
                          for window, field in (("next_slot_1m", "fast_at"), ("next_5m", "slow_at"))}
                    for key, fresh in (("allow_prior_shape", False), ("require_shape_close_after_breach", True))
                },
            )
        events[label] = dict(level=value, paths=paths)
    return dict(bars_1m=len(one), bars_5m=len(five),
                high=str(max(bar.high for bar in one)), low=str(min(bar.low for bar in one)),
                confirmed_shape_windows=len(shapes), events=events)


def study(session, market):
    from app.market_data.market_data_service import MarketDataError

    coverage, cases = {}, {}
    for name, contract, dates, side, start, cut, source_ids, levels in CASES:
        cases[name] = dict(contract=contract, trading_days=dates, side=side, source_ids=source_ids,
                           window=[start, cut], author_action_at=None)
        key = (contract, dates)
        if key not in coverage:
            days = tuple(date.fromisoformat(value) for value in dates)
            try:
                raw = {period: read_session_series(session, market, contract[:-4].lower(), contract,
                                                   period, step, days)
                       for period, step in (("1m", ONE), ("5m", FIVE))}
                fives = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw["5m"]]
                verify_aggregation(fives, raw["1m"])
            except (MarketDataError, ValueError, KeyError) as exc:
                reason = (exc.code if isinstance(exc, MarketDataError) else
                          "MINUTE_COMPONENT_OR_SESSION_COVERAGE_UNVERIFIED")
                coverage[key] = (dict(status="LOCAL_DATA_UNVERIFIED", reason=reason), None, None)
            else:
                coverage[key] = (dict(status="WINDOW_READABLE", series={
                    period: dict(count=len(bars), ohlc_sha256=sha(encoded([
                        [b.bar_end.isoformat(), *(str(p) for p in ohlc(b))] for b in bars
                    ]).encode())) for period, bars in raw.items()
                }), raw["1m"], fives)
        info, minutes, fives = coverage[key]
        cases[name].update(info)
        if minutes is not None:
            cases[name].update(examine(minutes, fives, start=datetime.fromisoformat(start).replace(tzinfo=SHANGHAI),
                                       cut=datetime.fromisoformat(cut).replace(tzinfo=SHANGHAI),
                                       side=side, levels=levels))
    return dict(version="lms405-counter-m-order-study-v1", cases=cases, executable=False,
                author_matches=None, admitted_author_samples=0, fills=None, pnl=None)


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
