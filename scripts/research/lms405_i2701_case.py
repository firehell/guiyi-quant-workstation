"""Read-only comparison of the I2701 source snapshots and price paths."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from lms405_replay import display, keybar_windows, ohlc, photo_comparison, read_session_series

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


def compute(session, market):
    symbols = sorted({symbol for _, _, marks in PHOTOS.values() for symbol in marks})
    series = {
        symbol: read_session_series(session, market, symbol, f"{symbol.upper()}2701", "1m", ONE, DAYS)
        for symbol in symbols
    }
    minutes = series["i"]
    fives = read_session_series(session, market, "i", "I2701", "5m", FIVE, DAYS)
    source_photos = {
        source: photo_comparison(series, at(start), at(published), marks)
        for source, (start, published, marks) in PHOTOS.items()
    }
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
        long_protection_candidates=keybar_windows(
            fives, minutes, at("09:00"), at("11:31"), contract="I2701", long=True,
        ),
        short_recovery_candidates=keybar_windows(
            fives, minutes, at("21:00"), at("22:12"), contract="I2701", long=False,
        ),
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
