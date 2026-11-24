"""Compare OI2609 protection and recovery hypotheses using read-only local MDS."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_keybar_approx import classify
from lms405_replay import read_local

SYMBOL, CONTRACT = "oi", "OI2609"
DAYS = tuple(date(2026, 6, day) for day in (3, 4, 5))
PERIODS = {"1m": 1, "5m": 5, "15m": 15}
SHANGHAI = ZoneInfo("Asia/Shanghai")
JUNE3_POST = datetime(2026, 6, 3, 10, 13, tzinfo=SHANGHAI)


def local_time(end):
    return end.astimezone(SHANGHAI).isoformat(timespec="minutes")


def check_coverage(bars, sessions, frequency):
    step = timedelta(minutes=PERIODS[frequency])
    expected = {}
    for day, items in sessions.items():
        for item in items:
            end = item.window.start + step
            while end <= item.window.end:
                if end in expected:
                    raise ValueError("OVERLAPPING_SESSION")
                expected[end] = (day, item.is_night)
                end += step
    actual = [bar.bar_end for bar in bars]
    if (not expected or actual != sorted(expected)
            or any(bar.trading_day != expected[bar.bar_end][0] for bar in bars)):
        raise ValueError("SESSION_OR_BAR_COVERAGE_MISMATCH")
    return expected


def price_summary(bars, levels):
    closes = {}
    for level in map(Decimal, levels):
        observations = (
            ("first_strict_low", (b for b in bars if b.low < level)),
            ("first_strict_close", (b for b in bars if b.close < level)),
        )
        closes[str(level)] = {
            name: local_time(first.bar_end) if (first := next(matches, None)) else None
            for name, matches in observations
        }
    return dict(
        bars=len(bars), first=local_time(bars[0].bar_end), last=local_time(bars[-1].bar_end),
        first_open=str(bars[0].open), first_close=str(bars[0].close),
        high=str(max(b.high for b in bars)), low=str(min(b.low for b in bars)),
        levels=closes,
    )


def short_candidates(fives, minutes):
    rows = []
    by_end = {bar.bar_end: bar for bar in minutes}
    previous = None
    for i, signal in enumerate(fives[:-1]):
        frame = classify(previous, signal)
        previous = signal
        following = fives[i + 1]
        if not (frame.ibar or frame.pinbar == "SHORT") or signal.end != following.start:
            continue
        minute_bars = [by_end[following.start + timedelta(minutes=n)] for n in range(1, 6)]
        if ((minute_bars[0].open, max(b.high for b in minute_bars),
             min(b.low for b in minute_bars), minute_bars[-1].close)
                != (following.open, following.high, following.low, following.close)):
            raise ValueError("MDS_ONE_MINUTE_VS_FIVE_MINUTE_OHLC_MISMATCH")
        later = fives[i + 2] if i + 2 < len(fives) else None
        rows.append(dict(
            shape_at=local_time(signal.end), next_5m_at=local_time(following.end),
            ibar=frame.ibar, pinbar=frame.pinbar, keybar_low=str(signal.low),
            first_minute_low_below=next(
                (local_time(b.bar_end) for b in minute_bars if b.low < signal.low), None),
            first_minute_close_below=next(
                (local_time(b.bar_end) for b in minute_bars if b.close < signal.low), None),
            next_5m_close_below=following.close < signal.low,
            second_5m_close_below=(
                later.close < signal.low if later and later.start == following.end else None),
        ))
    return rows


def compute(market, sessions):
    levels = {
        DAYS[0]: ("10197", "10175", "10151", "10019"),
        DAYS[1]: ("10315", "10273", "10230"),
        DAYS[2]: ("10315", "10273", "10230", "9970"),
    }
    series, coverage, prices, hashes = {}, {}, {}, {}
    for period, minutes in PERIODS.items():
        bars = read_local(market, SYMBOL, CONTRACT, period, DAYS[0], DAYS[-1]).bars
        coverage[period] = check_coverage(bars, sessions, period)
        series[period] = bars
        payload = [[local_time(b.bar_end), *(str(v) for v in (b.open, b.high, b.low, b.close))]
                   for b in bars]
        hashes[period] = sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
        prices[period] = {
            day.isoformat(): {
                name: price_summary([b for b in bars if b.trading_day == day
                                     and coverage[period][b.bar_end][1] is is_night], levels[day])
                for name, is_night in (("night", True), ("day", False))
            }
            for day in DAYS
        }
        # The displayed publication minute only bounds this retrospective calculation.
        prices[period][DAYS[0].isoformat()]["after_publication_minute"] = price_summary(
            [b for b in bars if b.trading_day == DAYS[0]
             and b.bar_end - timedelta(minutes=minutes) >= JUNE3_POST + timedelta(minutes=1)],
            levels[DAYS[0]],
        )
    fives = [Bar(CONTRACT, b.bar_end, b.open, b.high, b.low, b.close,
                 start=b.bar_end - timedelta(minutes=5)) for b in series["5m"]
             if b.trading_day == DAYS[-1]]
    rows = short_candidates(fives, [b for b in series["1m"] if b.trading_day == DAYS[-1]])
    return dict(
        status="WINDOW_READABLE", contract=CONTRACT, trading_days=[day.isoformat() for day in DAYS],
        purpose="PRICE_AND_HYPOTHESES_ONLY", author_action_at=None, author_signal_period=None,
        author_prediction_samples=0, input_ohlc_sha256=hashes, price_paths=prices,
        june5_short_keybar_hypotheses=rows,
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
    from app.market_data.session_clock import resolved_session_windows_for_trading_day
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=30):
            market = build_market_data_service(session)
            exchange = market.catalog.exchange_for_symbol(SYMBOL)
            sessions = {day: resolved_session_windows_for_trading_day(
                session, exchange=exchange, symbol=SYMBOL, trading_day=day) for day in DAYS}
            report = compute(market, sessions)
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (ValueError, IndexError, KeyError):
        parser.exit(2, "MDS_SESSION_OR_BAR_COVERAGE_UNVERIFIED\n")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
