"""Cross-check PVC branches and PTA plan availability using read-only physical-contract data."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from lms405_replay import display, keybar_windows, ohlc, photo_comparison, read_session_series

LOCAL = ZoneInfo("Asia/Shanghai")
DAYS = tuple(date(2026, 10, day) for day in (19, 20, 21, 22, 23, 26, 27, 28))
PHOTO_DAYS = DAYS[-3:]
ONE = timedelta(minutes=1)
FIVE = timedelta(minutes=5)
PROTECTION_LOW = Decimal("5055")
PROTECTION_HIGH = Decimal("5074")
RIGHT_LONG = Decimal("5195")
PHOTOS = {
    "WRo2KQ43iX": ("23T21:00", "23T22:07", {
        "ta": "6734", "v": "5215", "oi": "10358", "sa": "968",
        "jm": "1397", "rb": "3040", "sh": "1577", "i": "669",
    }),
    "WRo2LIbP3s": ("23T21:00", "23T22:09", {
        "ta": "6732", "v": "5215", "oi": "10359", "i": "669",
    }),
    "WRov1j6e10": ("26T21:00", "26T22:04", {
        "v": "5111", "fg": "832", "oi": "10270", "sa": "957", "jm": "1369",
        "rb": "3020", "sh": "1486", "i": "663.5", "ru": "19445",
    }),
    "WRoEvasxQR": ("27T21:00", "27T22:12", {
        "v": "5203", "oi": "10237", "i": "661.5", "sh": "1491",
    }),
    "WRoEvFgWlh": ("27T21:00", "27T22:14", {
        "ta": "6558", "v": "5200", "oi": "10242", "i": "662",
    }),
}


def at(value):
    return datetime.fromisoformat(f"2026-10-{value}").replace(tzinfo=LOCAL)


def first(bars, matches):
    return next((display(bar.bar_end) for bar in bars if matches(bar)), None)


def path(bars, fives, start, cutoff):
    window = [b for b in bars if start < b.bar_end < cutoff]
    high, low = max(b.high for b in window), min(b.low for b in window)
    strict_down = next((b for b in window if b.close < PROTECTION_LOW), None)
    reentry = [b for b in window if strict_down and b.bar_end > strict_down.bar_end
               and b.high >= PROTECTION_LOW]
    return dict(
        bars=len(window), low=str(low), high=str(high),
        low_at=first(window, lambda b: b.low == low),
        high_at=first(window, lambda b: b.high == high),
        first_left_zone_overlap=first(window, lambda b: b.high >= 5045 and b.low <= PROTECTION_HIGH),
        first_close_below_5074=first(window, lambda b: b.close < PROTECTION_HIGH),
        first_close_below_5055=display(strict_down.bar_end) if strict_down else None,
        first_later_recontact_5055=display(reentry[0].bar_end) if reentry else None,
        first_high_above_5195=first(window, lambda b: b.high > RIGHT_LONG),
        first_close_above_5195=first(window, lambda b: b.close > RIGHT_LONG),
        first_low_at_or_below_5045=first(window, lambda b: b.low <= 5045),
        first_low_at_or_below_5012=first(window, lambda b: b.low <= 5012),
        long_shapes=keybar_windows(fives, bars, start, cutoff, contract="V2701", long=True),
        short_shapes=keybar_windows(fives, bars, start, cutoff, contract="V2701", long=False),
    )


def opening_gaps(bars):
    """Compare opening prints at night and morning; do not label breaks as opens."""
    rows = []
    for previous, current in zip(bars, bars[1:]):
        local_end = current.bar_end.astimezone(LOCAL)
        if (local_end.hour, local_end.minute) not in ((9, 1), (21, 1)):
            continue
        if current.bar_end - previous.bar_end <= ONE:
            raise ValueError("EXPECTED_SESSION_BOUNDARY")
        old = previous.close
        through_previous_close = current.low <= old <= current.high
        rows.append(dict(
            first_bar_end=display(current.bar_end), trading_day=current.trading_day.isoformat(),
            previous_at=display(previous.bar_end), previous_close=str(old),
            open=str(current.open), first_low=str(current.low), first_high=str(current.high),
            open_difference=str(current.open - old),
            first_minute_stays_clear=not through_previous_close,
        ))
    return rows


def identity(bars):
    raw = [(b.bar_end.isoformat(), *(str(x) for x in ohlc(b))) for b in bars]
    return dict(bars=len(raw), ohlc_sha256=sha256(json.dumps(raw, separators=(",", ":")).encode()).hexdigest())


def minutes_in(bars, start, end):
    return {
        display(b.bar_end): [str(value) for value in ohlc(b)]
        for b in bars if start < b.bar_end <= end
    }


def compute(session, market):
    symbols = sorted({symbol for _, _, marks in PHOTOS.values() for symbol in marks})
    one_minute = {
        symbol: read_session_series(
            session, market, symbol, f"{symbol.upper()}2701", "1m", ONE,
            DAYS if symbol in ("v", "ta") else PHOTO_DAYS,
        )
        for symbol in symbols
    }
    fives = read_session_series(session, market, "v", "V2701", "5m", FIVE, PHOTO_DAYS)
    scopes = {
        "oct26_day": ("26T09:00", "26T15:01"),
        "oct26_night": ("26T21:00", "26T23:01"),
        "oct27_day": ("27T09:00", "27T15:01"),
        "oct27_night_through_posts": ("27T21:00", "27T22:14"),
    }
    return dict(
        purpose="PRICE_AND_HYPOTHESES_ONLY",
        author_prediction_samples=0,
        market_1m={s: identity(bars) for s, bars in one_minute.items()},
        pvc_5m=identity(fives),
        photos={source: photo_comparison(one_minute, at(start), at(published), marks)
                for source, (start, published, marks) in PHOTOS.items()},
        pvc_paths={k: path(one_minute["v"], fives, at(a), at(b)) for k, (a, b) in scopes.items()},
        opening_gaps={s: opening_gaps(one_minute[s]) for s in ("ta", "v")},
        pvc_oct27_morning_break=minutes_in(one_minute["v"], at("27T09:11"), at("27T09:16")),
        software_report_context={
            "v": minutes_in(one_minute["v"], at("27T21:03"), at("27T21:04")),
            "ta": {
                **minutes_in(one_minute["ta"], at("27T21:39"), at("27T21:40")),
                **minutes_in(one_minute["ta"], at("27T21:51"), at("27T21:52")),
            },
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
