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
from lms405_locked_exit_audit import confirmed_shapes, verify_aggregation
from lms405_replay import check_session_coverage, read_local

SYMBOL, CONTRACT = "oi", "OI2609"
DAYS = tuple(date(2026, 6, day) for day in (3, 4, 5))
PERIODS = {"1m": 1, "5m": 5, "15m": 15}
SHANGHAI = ZoneInfo("Asia/Shanghai")
JUNE3_POST = datetime(2026, 6, 3, 10, 13, tzinfo=SHANGHAI)
EARLY_BASELINE_SHA256 = "b1b35238a8ff776b243dc9b3490865c7339f71ac68aa1cd26559d464acc113dc"
EARLY_BANDS = {
    "NEAR_HIGH_VOLATILITY": (Decimal("10175"), Decimal("10197")),
    "FAR_BASELINE": (Decimal("10019"), Decimal("10151")),
}
ONE = timedelta(minutes=1)


def local_time(end):
    return end.astimezone(SHANGHAI).isoformat(timespec="minutes")


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


def observe_band(bars, lower, upper):
    """Band contact, arrival at the near edge and break of the far edge are separate."""
    events = {
        "intersects": lambda bar: bar.low <= upper and bar.high >= lower,
        "close_reaches_near_edge": lambda bar: bar.close <= upper,
        "close_strictly_below_far_edge": lambda bar: bar.close < lower,
    }
    return {
        key: next((bar.bar_end for bar in bars if event(bar)), None)
        for key, event in events.items()
    }


def early_protection_path(series, coverage, *, as_of):
    available = JUNE3_POST + ONE
    after_post = {
        period: [bar for bar in series[period] if bar.trading_day == DAYS[0]
                 and not coverage[period][bar.bar_end][1]
                 and available <= bar.bar_end - timedelta(minutes=step) and bar.bar_end < as_of]
        for period, step in PERIODS.items()
    }
    path = {
        name: {period: observe_band(bars, lower, upper) for period, bars in after_post.items()}
        for name, (lower, upper) in EARLY_BANDS.items()
    }
    # Prior completed parents may describe geometry; the candidate shape must start
    # after plan availability and its confirmation must itself be known at as_of.
    step = timedelta(minutes=5)
    fives = [Bar(CONTRACT, bar.bar_end, bar.open, bar.high, bar.low, bar.close,
                 start=bar.bar_end - step) for bar in series["5m"]
             if bar.trading_day == DAYS[0] and bar.bar_end < as_of]
    touches = {name: periods["1m"]["intersects"] for name, periods in path.items()}
    contact_ends = {
        name: [bar.bar_end for bar in after_post["1m"] if bar.low <= upper and bar.high >= lower]
        for name, (lower, upper) in EARLY_BANDS.items()
    }
    minute_by_end = {bar.bar_end: bar for bar in after_post["1m"]}
    run_starts = {}
    for end in minute_by_end:
        run_starts[end] = run_starts.get(end - ONE, end - ONE)

    def describe_confirmation(when):
        if when is None:
            return None
        bar = minute_by_end[when]
        band_checks = {}
        for name, (lower, upper) in EARLY_BANDS.items():
            latest = next((end for end in reversed(contact_ends[name]) if end < when), None)
            band_checks[name] = dict(
                close_in_band=lower <= bar.close <= upper,
                close_minus_upper=str(bar.close - upper),
                earlier_contact=local_time(latest) if latest is not None else None,
                earlier_contact_same_contiguous_run=(
                    run_starts[latest] == run_starts[when] if latest is not None else None),
                first_contact_same_end=touches[name] == when,
            )
        return dict(bar_end=local_time(when), close=str(bar.close), bands=band_checks)

    eligible_ends = {local_time(bar.bar_end) for bar in after_post["5m"]}
    verify_aggregation([bar for bar in fives if local_time(bar.end) in eligible_ends], after_post["1m"])
    all_short_shapes = confirmed_shapes(fives, after_post["1m"], start=available, through=as_of, side="SHORT")
    rows = []
    for row in all_short_shapes:
        shape_at = local_time(datetime.fromisoformat(row["shape_at"]))
        if shape_at not in eligible_ends:
            continue
        confirmations = {kind: datetime.fromisoformat(row[field]) if row[field] else None
                         for kind, field in (("1M_CLOSE", "fast_at"), ("5M_CLOSE", "slow_at"))}
        rows.append(dict(
            shape_at=shape_at, shape_low=row["level"],
            evidence={kind: describe_confirmation(when) for kind, when in confirmations.items()},
        ))
    return dict(
        version="lms405-oi2609-early-protection-path-v1", contract=CONTRACT,
        as_of=as_of.isoformat(), conservative_post_available_at=available.isoformat(),
        band_levels={name: [str(low), str(high)] for name, (low, high) in EARLY_BANDS.items()},
        band_path={name: {period: {kind: local_time(when) if when else None for kind, when in times.items()}
                          for period, times in periods.items()} for name, periods in path.items()},
        bar_counts={period: len(bars) for period, bars in after_post.items()},
        shape_substitute_version="lms-keybar-approx-v1", short_keybar_geometry=rows,
        source_id="S5305666088472874", scope="CURRENT_READABLE_SOURCE_HISTORICAL_EDIT_UNVERIFIED",
        source_suggested_context_period="15m", author_signal_formula=None,
        high_volatility_threshold=None, actual_position_and_permission=None,
        protection_status="INDETERMINATE", author_action_at=None, author_prediction_samples=0,
        action=None, fill=None, pnl=None, executable=False,
    )


def compute(market, sessions, *, early_baseline=None):
    levels = {
        DAYS[0]: ("10197", "10175", "10151", "10019"),
        DAYS[1]: ("10315", "10273", "10230"),
        DAYS[2]: ("10315", "10273", "10230", "9970"),
    }
    series, coverage, prices, hashes = {}, {}, {}, {}
    for period, minutes in PERIODS.items():
        bars = read_local(market, SYMBOL, CONTRACT, period, DAYS[0], DAYS[-1]).bars
        coverage[period] = check_session_coverage(bars, sessions, timedelta(minutes=minutes))
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
    if early_baseline is not None:
        if hashes != early_baseline["input_ohlc_sha256"]:
            raise ValueError("FROZEN_MARKET_INPUT_CHANGED")
        report = early_protection_path(
            series, coverage, as_of=datetime(2026, 6, 3, 15, tzinfo=SHANGHAI) + timedelta(microseconds=1),
        )
        return dict(input_ohlc_sha256=hashes, reference_baseline_sha256=EARLY_BASELINE_SHA256, **report)
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
    parser.add_argument("--early-protection-baseline", type=Path,
                        help="Run the 6/3 protection-path audit against the frozen June comparison.")
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
        baseline = None
        if args.early_protection_baseline:
            raw = args.early_protection_baseline.read_bytes()
            if sha256(raw).hexdigest() != EARLY_BASELINE_SHA256:
                raise ValueError("FROZEN_COMPARISON_MISMATCH")
            baseline = json.loads(raw)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=30):
            market = build_market_data_service(session)
            exchange = market.catalog.exchange_for_symbol(SYMBOL)
            sessions = {day: resolved_session_windows_for_trading_day(
                session, exchange=exchange, symbol=SYMBOL, trading_day=day) for day in DAYS}
            report = compute(market, sessions, early_baseline=baseline)
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, IndexError, KeyError):
        parser.exit(2, "MDS_SESSION_OR_BAR_COVERAGE_UNVERIFIED\n")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
