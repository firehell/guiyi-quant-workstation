"""Compare dated FG2701/SA2701 positions and price paths using local historical MDS."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from lms405_replay import display, keybar_windows, photo_comparison, read_session_series

LOCAL = ZoneInfo("Asia/Shanghai")
DAYS = (date(2026, 10, 23), date(2026, 10, 26))
ONE = timedelta(minutes=1)
FIVE = timedelta(minutes=5)
LEVELS = {
    "fg": ("821", "825", "827", "829", "836", "842", "844", "854", "857"),
    "sa": ("915", "927", "926", "931", "936", "942", "945", "953", "957"),
}
PHOTOS = {
    "WRnTlEfj1t": ("22T21:00", "22T22:10", {
        "fg": "833", "sa": "943", "jm": "1410", "j": "1918.5",
        "rb": "3048", "sh": "1626", "i": "670", "ru": "19615",
    }),
    "WRnY5bznUE": ("23T09:00", "23T10:13", {
        "fg": "827", "sa": "941", "rb": "3041", "sh": "1587", "i": "673",
    }),
    "WRnZKEysLc": ("23T09:00", "23T14:28", {
        "fg": "837", "v": "5092", "oi": "10367", "jm": "1423",
        "j": "1937.5", "rb": "3047", "sh": "1584", "i": "673.5",
    }),
    "WRo00BFM1E": ("23T13:30", "23T15:07", {
        "fg": "836", "v": "5115", "oi": "10343", "jm": "1427.5",
        "j": "1937", "rb": "3047", "sh": "1579", "i": "675",
    }),
    "WRo2KQ43iX": ("23T21:00", "23T22:07", {
        "sa": "968", "ta": "6734", "v": "5215", "oi": "10358",
        "jm": "1397", "rb": "3040", "sh": "1577", "i": "669",
    }),
}
WINDOWS = {
    "first_night": ("22T21:00", "22T22:10"),
    "next_day_before_morning_post": ("23T09:00", "23T10:13"),
    "next_day_after_morning_post_to_lunch": ("23T10:13", "23T11:31"),
    "next_day_after_morning_post_through_close": ("23T10:13", "23T15:01"),
    "next_day": ("23T09:00", "23T15:01"),
    "second_night": ("23T21:00", "23T22:07"),
}


def at(value):
    return datetime.fromisoformat(f"2026-10-{value}").replace(tzinfo=LOCAL)


def price_path(bars, raw_levels, start, cutoff):
    window = [b for b in bars if start < b.bar_end < cutoff]
    low, high = min(b.low for b in window), max(b.high for b in window)
    levels = tuple(map(Decimal, raw_levels))
    return dict(
        count=len(window), low=str(low), high=str(high),
        first_low_at=display(next(b.bar_end for b in window if b.low == low)),
        first_high_at=display(next(b.bar_end for b in window if b.high == high)),
        levels={
            raw: {
                name: next((display(b.bar_end) for b in window if test(b, level)), None)
                for name, test in (
                    ("first_low_at_or_below", lambda b, p: b.low <= p),
                    ("first_high_at_or_above", lambda b, p: b.high >= p),
                    ("first_high_above", lambda b, p: b.high > p),
                    ("first_close_above", lambda b, p: b.close > p),
                    ("first_close_below", lambda b, p: b.close < p),
                )
            }
            for raw, level in zip(raw_levels, levels, strict=True)
        },
    )


def identity(bars):
    payload = [
        (b.bar_end.isoformat(), str(b.open), str(b.high), str(b.low), str(b.close))
        for b in bars
    ]
    return dict(bars=len(bars), ohlc_sha256=sha256(json.dumps(
        payload, separators=(",", ":"),
    ).encode()).hexdigest())


def compute(session, market):
    symbols = sorted({symbol for _, _, marks in PHOTOS.values() for symbol in marks})
    minutes = {
        symbol: read_session_series(session, market, symbol, f"{symbol.upper()}2701", "1m", ONE, DAYS)
        for symbol in symbols
    }
    fives = {
        symbol: read_session_series(session, market, symbol, f"{symbol.upper()}2701", "5m", FIVE, DAYS)
        for symbol in LEVELS
    }
    windows = {label: (at(start), at(cutoff)) for label, (start, cutoff) in WINDOWS.items()}
    return dict(
        purpose="PRICE_AND_HYPOTHESES_ONLY",
        author_prediction_samples=0,
        market_1m={symbol: identity(bars) for symbol, bars in minutes.items()},
        pair_5m={symbol: identity(bars) for symbol, bars in fives.items()},
        photos={source: photo_comparison(minutes, at(start), at(published), marks)
                for source, (start, published, marks) in PHOTOS.items()},
        price_paths={
            symbol: {label: price_path(minutes[symbol], levels, *bounds)
                     for label, bounds in windows.items()}
            for symbol, levels in LEVELS.items()
        },
        long_protection_candidates={
            symbol: {
                label: keybar_windows(
                    bars, minutes[symbol], *bounds, contract=f"{symbol.upper()}2701", long=True,
                )
                for label, bounds in windows.items() if label != "next_day"
            }
            for symbol, bars in fives.items()
        },
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
