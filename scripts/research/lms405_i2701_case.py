"""Read-only comparison of the I2701 source snapshots and price paths."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from lms405_replay import display, keybar_windows, ohlc, photo_comparison, read_session_series
from lms405_sizing_audit import SPECS, load_specs

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
FROZEN_COMPARISON_SHA256 = "12aba77f900209d38ea180daae08dadc398a83d57c8d60c7024532da24b9bdba"


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


def rounded_average_ticks(shown, lots, tick):
    """Total integer ticks compatible with a positive two-decimal half-up display."""
    half_cent = Decimal("0.005")
    lower = (shown - half_cent) * lots / tick
    upper = (shown + half_cent) * lots / tick
    return range(int(lower.to_integral_value(rounding=ROUND_CEILING)),
                 int(upper.to_integral_value(rounding=ROUND_CEILING)))


def average_envelope(bars, tick, lots, totals):
    """OHLC range is a necessary condition. Intrabar prices and quantities are unknown."""
    if not bars:
        return dict(count=0, geometry="NO_COMPLETED_BAR_IN_WINDOW")
    low, high = min(bar.low for bar in bars), max(bar.high for bar in bars)
    single_minutes = [
        display(bar.bar_end) for bar in bars
        if any(bar.low * lots <= tick * total <= bar.high * lots for total in totals)
    ]
    return dict(
        count=len(bars), start=display(bars[0].bar_end - ONE), last_bar_end=display(bars[-1].bar_end),
        low=str(low), high=str(high),
        envelope_allows_average=any(low * lots <= tick * total <= high * lots for total in totals),
        same_minute_envelope_count=len(single_minutes), first_same_minute_envelope=next(iter(single_minutes), None),
    )


def protection_path(minutes, fives, tick, quantity, shown):
    night_open = datetime(2026, 10, 26, 21, tzinfo=LOCAL)
    day_open, midday, early_post = at("09:00"), at("11:30"), at("10:13")
    night = [bar for bar in minutes if night_open < bar.bar_end <= day_open]
    morning = [bar for bar in minutes if day_open < bar.bar_end <= midday]
    if not night or not morning or night[0].bar_end != night_open + ONE or morning[-1].bar_end != midday:
        raise ValueError("PROTECTION_WINDOW_NOT_COVERED")

    def price_gate(bars, predicate):
        first = next((bar for bar in bars if predicate(bar)), None)
        # The trigger minute may also have traded the average-supporting range.
        # The after-confirmation test excludes it since the OHLC reveals no order.
        # The next row is the next trading minute; a session break may intervene.
        following = [bar for bar in bars if first and first.bar_end < bar.bar_end]
        return dict(
            first_trigger_bar_end=display(first.bar_end) if first else None,
            trigger_minute=average_envelope([first] if first else [], tick, quantity, totals),
            next_minute=average_envelope(following[:1], tick, quantity, totals),
            rest_of_session_window=average_envelope(following, tick, quantity, totals),
        )

    totals = rounded_average_ticks(shown, quantity, tick)
    windows = dict(
        night_first_minute=night[:1], night=night, morning=morning,
        after_early_post_minute=[bar for bar in morning if bar.bar_end - ONE >= early_post + ONE],
    )
    gates = {}
    for label, bars, predicate in (
        ("night_touch_671", night, lambda bar: bar.high >= Decimal("671")),
        ("night_close_above_671", night, lambda bar: bar.close > Decimal("671")),
        ("morning_touch_resistance_664_5", morning, lambda bar: bar.high >= Decimal("664.5")),
        ("after_early_post_touch_resistance_664_5", windows["after_early_post_minute"],
         lambda bar: bar.high >= Decimal("664.5")),
        ("morning_touch_protection_667", morning, lambda bar: bar.high >= Decimal("667")),
        ("morning_close_above_667", morning, lambda bar: bar.close > Decimal("667")),
        ("morning_high_above_667", morning, lambda bar: bar.high > Decimal("667")),
    ):
        gates[label] = price_gate(bars, predicate)

    return dict(
        minute_windows={name: average_envelope(bars, tick, quantity, totals) for name, bars in windows.items()},
        area_conditions=gates,
        keybar=keybar_windows(fives, minutes, night_open, midday + ONE, contract="I2701", long=True),
        tick_size=str(tick), quantity=quantity, displayed_opening_average=str(shown),
        display_rounding_assumption="TWO_DECIMAL_NEAREST_HALF_UP",
        compatible_tick_totals=list(totals),
        compatible_exact_averages=[str(tick * total / quantity) for total in totals],
        first_night_bar_ohlc=list(map(str, ohlc(night[0]))),
        midday_quote_at=display(midday), early_post_at=display(early_post),
        early_post_position_time=None, unlisted_early_long=None, account_continuity=None,
        actual_signal_at=None, fills=None, author_prediction_samples=0, executable=False,
    )


def compute_protection(session, market, baseline):
    minutes = read_session_series(session, market, "i", "I2701", "1m", ONE, DAYS[:1])
    fives = read_session_series(session, market, "i", "I2701", "5m", FIVE, DAYS[:1])
    day = DAYS[0].isoformat()
    actual = dict(minute=readback(minutes)[day], five_minute=readback(fives)[day])
    if actual != dict(minute=baseline["market_1m"]["i"][day], five_minute=baseline["i2701_5m"][day]):
        raise ValueError("FROZEN_MARKET_INPUT_CHANGED")
    spec = load_specs(json.loads(SPECS.read_bytes()))["I2701"]
    report = protection_path(minutes, fives, spec["tick"], 16, Decimal("663.34"))
    return dict(
        version="lms405-i2701-protection-path-v1", market=actual,
        reference_baseline_sha256=FROZEN_COMPARISON_SHA256,
        plan_source="A5358325549629506", plan_historical_text_verified=False,
        opening_average_source="WRoAkcEppg", early_holdings_sources=["WRov1j6e10", "WRozNbg3en"],
        tick_spec_sha256=spec["source_sha256"], **report,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protection-baseline", type=Path,
                        help="Run the protection path audit against an existing frozen comparison.")
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
        baseline = None
        if args.protection_baseline:
            raw = args.protection_baseline.read_bytes()
            if sha256(raw).hexdigest() != FROZEN_COMPARISON_SHA256:
                raise ValueError("FROZEN_COMPARISON_MISMATCH")
            baseline = json.loads(raw)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            market = build_market_data_service(session)
            report = compute_protection(session, market, baseline) if baseline is not None else compute(session, market)
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError):
        parser.exit(2, "MDS_SESSION_OR_BAR_COVERAGE_UNVERIFIED\n")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
