"""Read-only comparison of the I2701 source snapshots and price paths."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_keybar_approx import classify
from lms405_replay import check_session_coverage, read_local

LOCAL = ZoneInfo("Asia/Shanghai")
DAYS = (date(2026, 10, 27), date(2026, 10, 28))
ONE = timedelta(minutes=1)
FIVE = timedelta(minutes=5)
PHOTOS = {
    "WRozNbg3en": ("09:00", "10:13", {
        "i": "662.5", "sh": "1500", "fg": "828", "oi": "10285",
        "sa": "962", "rb": "3017", "ru": "19410",
    }),
    "WRoAkcEppg": ("09:00", "11:34", {
        "i": "666.5", "sh": "1514", "jm": "1392.5", "j": "1889.5", "v": "5100",
    }),
    "U03": ("13:30", "15:16", {
        "i": "664", "sh": "1486", "jm": "1414.5", "j": "1921", "v": "5132",
    }),
    "WRoEvasxQR": ("21:00", "22:12", {
        "i": "661.5", "sh": "1491", "jm": "1424", "j": "1934",
        "v": "5203", "oi": "10237", "ru": "19480",
    }),
}
LEVELS = ("654", "662.5", "664.5", "667", "668.5", "671", "671.5", "675", "677.5", "681", "685.5")


def at(value):
    return datetime.fromisoformat(f"2026-10-27T{value}").replace(tzinfo=LOCAL)


def display(end):
    return end.astimezone(LOCAL).isoformat(timespec="minutes")


def ohlc(bar):
    return bar.open, bar.high, bar.low, bar.close


def read_series(session, market, symbol, frequency, step, days):
    from app.market_data.session_clock import resolved_session_windows_for_trading_day

    contract = f"{symbol.upper()}2701"
    exchange = market.catalog.exchange_for_symbol(symbol)
    sessions = {
        day: resolved_session_windows_for_trading_day(
            session, exchange=exchange, symbol=symbol, trading_day=day,
        )
        for day in days
    }
    bars = read_local(market, symbol, contract, frequency, days[0], days[-1]).bars
    check_session_coverage(bars, sessions, step)
    return bars


def readback(bars):
    by_day = {}
    for day in DAYS:
        selected = [b for b in bars if b.trading_day == day]
        rows = [[b.bar_end.isoformat(), *(str(value) for value in ohlc(b))] for b in selected]
        by_day[day.isoformat()] = {
            "bars": len(rows),
            "ohlc_sha256": sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest(),
        }
    return by_day


def photo_comparison(series, start, published, marks):
    per_symbol, contains, closes = {}, {}, {}
    for symbol, value in marks.items():
        mark = Decimal(value)
        eligible = [b for b in series[symbol] if at(start) < b.bar_end < at(published)]
        if not eligible:
            raise ValueError("PHOTO_WINDOW_NOT_COVERED")
        contains[symbol] = {b.bar_end for b in eligible if b.low <= mark <= b.high}
        closes[symbol] = {b.bar_end for b in eligible if b.close == mark}
        per_symbol[symbol] = dict(mark=value, contains=sorted(map(display, contains[symbol])),
                                  equal_close=sorted(map(display, closes[symbol])))
    return dict(
        published_minute=display(at(published)),
        per_symbol=per_symbol,
        joint_contains=sorted(map(display, set.intersection(*contains.values()))),
        joint_equal_close=sorted(map(display, set.intersection(*closes.values()))),
    )


def price_path(bars):
    low = min(b.low for b in bars)
    high = max(b.high for b in bars)
    return dict(
        count=len(bars), low=str(low), high=str(high),
        first_low_at=display(next(b.bar_end for b in bars if b.low == low)),
        first_high_at=display(next(b.bar_end for b in bars if b.high == high)),
        levels={
            raw: {
                name: next((display(b.bar_end) for b in bars if test(b, level)), None)
                for name, test in (
                    ("first_low_below", lambda b, p: b.low < p),
                    ("first_close_below", lambda b, p: b.close < p),
                    ("first_high_above", lambda b, p: b.high > p),
                    ("first_close_above", lambda b, p: b.close > p),
                )
            }
            for raw, level in zip(LEVELS, map(Decimal, LEVELS), strict=True)
        },
    )


def keybar_windows(fives, minutes, start, cutoff, *, long):
    """Evaluate an already completed 5m shape only through its next contiguous window."""
    calendar = {b.bar_end: b for b in minutes}
    bars = [Bar("I2701", b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in fives
            if b.bar_end < cutoff]
    rows = []
    previous = None
    for shape, following in zip(bars, bars[1:]):
        frame = classify(previous, shape)
        previous = shape
        if shape.end < start or shape.end != following.start:
            continue
        if not frame.ibar and frame.pinbar != ("LONG" if long else "SHORT"):
            continue
        child = [calendar[shape.end + n * ONE] for n in range(1, 6)]
        if (child[0].open, max(b.high for b in child), min(b.low for b in child), child[-1].close) != ohlc(following):
            raise ValueError("MINUTE_AGGREGATE_DIVERGED")
        boundary = shape.high if long else shape.low
        hit = (lambda p: p > boundary) if long else (lambda p: p < boundary)
        rows.append(dict(
            shape_at=display(shape.end), next_5m_at=display(following.end),
            shape_ibar=frame.ibar, shape_pinbar=frame.pinbar, keybar_boundary=str(boundary),
            first_1m_touch=next((display(b.bar_end) for b in child if hit(b.high if long else b.low)), None),
            first_1m_close=next((display(b.bar_end) for b in child if hit(b.close)), None),
            next_5m_close=hit(following.close),
        ))
    return rows


def compute(session, market):
    symbols = sorted({symbol for _, _, marks in PHOTOS.values() for symbol in marks})
    series = {symbol: read_series(session, market, symbol, "1m", ONE, DAYS) for symbol in symbols}
    minutes = series["i"]
    fives = read_series(session, market, "i", "5m", FIVE, DAYS)
    source_photos = {source: photo_comparison(series, *spec) for source, spec in PHOTOS.items()}
    paths = {
        "oct27_full_trading_day": [b for b in minutes if b.trading_day == DAYS[0]],
        "oct27_previous_night": [b for b in minutes if b.trading_day == DAYS[0] and b.bar_end < at("09:00")],
        "oct27_day": [b for b in minutes if at("09:00") < b.bar_end < at("15:16")],
        "oct27_morning_after_publication_minute": [b for b in minutes if at("10:13") < b.bar_end <= at("11:30")],
        "oct27_night_before_publication": [b for b in minutes if at("21:00") < b.bar_end < at("22:12")],
    }
    return dict(
        purpose="PRICE_AND_HYPOTHESES_ONLY",
        author_prediction_samples=0,
        market_1m={symbol: readback(bars) for symbol, bars in series.items()},
        i2701_5m=readback(fives),
        photos=source_photos,
        iron_price_path={scope: price_path(bars) for scope, bars in paths.items()},
        long_protection_candidates=keybar_windows(fives, minutes, at("09:00"), at("11:31"), long=True),
        short_recovery_candidates=keybar_windows(fives, minutes, at("21:00"), at("22:12"), long=False),
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
            report = compute(session, build_market_data_service(session))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (ValueError, KeyError):
        parser.exit(2, "MDS_SESSION_OR_BAR_COVERAGE_UNVERIFIED\n")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
