"""Audit what an ATR14 or opening-gap hypothesis could know at protection landmarks."""

import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path

from lms405_portfolio_replay import CONTRACTS
from lms405_replay import check_session_coverage, display, ohlc, read_local
from lms405_right_side_study import ONE, US, at
from lms_near405_replay import encoded, sha

PERIOD = 14
GEOMETRY_SHA256 = "2027efac0027821f4c16e88fadb60abfe56f5a22370582f8d11dda54838fe455"
PORTFOLIO_DAY = date(2026, 10, 27)
CHECKS_AFTER_CLOSE = {
    "oi": ("2026-06-03T10:31", "2026-06-03T10:33", "2026-06-03T10:45"),
    "iron": ("2026-10-26T21:45", "2026-10-27T11:09"),
    "sh": ("2026-10-22T21:01", "2026-10-22T22:08"),
    "jm_control": ("2025-07-22T09:12", "2025-07-22T09:15"),
}
METRICS = ("trading_day_range", "trading_day_true_range", "opening_gap_abs", "day_reopen_gap_abs")


def prior_atr(dailies, *, expected, before):
    if (len(expected) != PERIOD + 1 or [b.trading_day for b in dailies] != list(expected)
            or any(left.bar_end >= right.bar_end for left, right in zip(dailies, dailies[1:]))
            or any(b.bar_end + US >= before or min(ohlc(b)) <= 0 for b in dailies)):
        raise ValueError("ATR_DAILY_PREFIX_UNVERIFIED")
    values = [max(bar.high, prev.close) - min(bar.low, prev.close)
              for prev, bar in zip(dailies, dailies[1:])]
    total = sum(values)
    if total <= 0:
        raise ValueError("ATR_ZERO_HISTORY")
    return total, [str(value) for value in values]


def minute_context(bars, *, initial_close, atr_total, day_reopen_end, as_of):
    """Running high/low and gap figures only use visible completed minutes."""
    high = low = opening = day_gap = None
    previous = None
    result = []
    for bar in bars:
        available = bar.bar_end + US
        if available >= as_of:
            break
        high = bar.high if high is None else max(high, bar.high)
        low = bar.low if low is None else min(low, bar.low)
        if opening is None:
            opening = bar.open - initial_close
        if bar.bar_end == day_reopen_end:
            if previous is None:
                raise ValueError("DAY_REOPEN_NEEDS_PRIOR_NIGHT_CLOSE")
            day_gap = bar.open - previous.close
        previous = bar
        metrics = dict(
            trading_day_range=high - low,
            trading_day_true_range=max(high, initial_close) - min(low, initial_close),
            opening_gap_abs=abs(opening),
            day_reopen_gap_abs=abs(day_gap) if day_gap is not None else None,
        )
        exceeded = {key: value * PERIOD > atr_total if value is not None else None
                    for key, value in metrics.items()}
        result.append(dict(
            bar_end=bar.bar_end, known_at=available, open_gap_signed=opening, day_reopen_gap_signed=day_gap,
            measures=metrics, exceeds_atr14=exceeded,
        ))
    return result


def before_shape_checks(reference, rows):
    by_variant = {}
    for variant, hypothesis in reference["hypotheses"].items():
        step = timedelta(minutes=int(variant.split("m_to_")[0]))
        checks = []
        for event in hypothesis["events"]:
            start = datetime.fromisoformat(event["shape_end"]) - step
            context = next((row for row in reversed(rows) if row["known_at"] < start), None)
            checks.append(dict(
                shape_start=start, confirmed_at=datetime.fromisoformat(event["confirmed_at"]),
                context_bar_end=context["bar_end"] if context is not None else None,
                known_before_shape=context["exceeds_atr14"] if context is not None else None,
            ))
        by_variant[variant] = checks
    return by_variant


def study(session, market, geometry):
    from app.market_data.session_clock import resolved_session_windows_for_trading_day
    from app.market_data.market_data_service import MarketDataError

    cases, portfolio = {}, {}
    requests = [(name, row["contract"], date.fromisoformat(row["trading_day"]), row)
                for name, row in geometry["cases"].items()]
    requests += [(None, contract, PORTFOLIO_DAY, None) for contract in CONTRACTS]
    cache = {}
    for name, contract, day, reference in requests:
        key = contract, day
        if key not in cache:
            try:
                cache[key] = read_inputs(session, market, contract, day, resolved_session_windows_for_trading_day)
            except MarketDataError as exc:
                cache[key] = {"blocked": exc.code}
            except (ValueError, KeyError) as exc:
                cache[key] = {"blocked": str(exc)}
        inputs = cache[key]
        target = cases if name is not None else portfolio
        identity = name or contract
        if "blocked" in inputs:
            target[identity] = dict(contract=contract, trading_day=day, status="LOCAL_DATA_UNVERIFIED",
                                    reason=inputs["blocked"])
            continue
        minutes, dailies, reopen = inputs["minutes"], inputs["dailies"], inputs["day_reopen"]
        if reference and inputs["minute_sha256"] != reference["market"]["1m"]["sha256"]:
            raise ValueError("FROZEN_TIMEFRAME_MINUTES_CHANGED")
        args = dict(initial_close=dailies[-1].close, atr_total=inputs["atr_total"], day_reopen_end=reopen)
        final_cut = at(reference["as_of"]) if reference else minutes[-1].bar_end + 2 * US
        rows = minute_context(minutes, as_of=final_cut, **args)
        if not rows:
            raise ValueError("VOLATILITY_WINDOW_EMPTY")
        checkpoints = {}
        for label in CHECKS_AFTER_CLOSE.get(name, ()):
            close = at(label)
            count = sum(bar.bar_end <= close for bar in minutes)
            cut = close + 2 * US
            earlier = minute_context(minutes[:count], as_of=cut, **args)
            if (not earlier or earlier[-1]["bar_end"] != close
                    or earlier != [row for row in rows if row["known_at"] < cut]):
                raise ValueError("VOLATILITY_PREFIX_DIVERGED")
            checkpoints[label] = earlier[-1]
        first_above = {
            metric: next((display(row["bar_end"]) for row in rows if row["exceeds_atr14"][metric] is True), None)
            for metric in METRICS
        }
        target[identity] = dict(
            contract=contract, trading_day=day, status="LOCAL_DATA_VERIFIED", prior_anchor=dailies[-1].bar_end,
            prior_close=dailies[-1].close, prior_trading_days=[bar.trading_day for bar in dailies],
            daily_ohlc_sha256=inputs["daily_sha256"], previous_fourteen_true_ranges=inputs["true_ranges"],
            atr14_sma=inputs["atr_total"] / PERIOD, atr14_sum=inputs["atr_total"],
            minute_sha256=inputs["minute_sha256"], minute_bars_at_cut=len(rows),
            first_exceeds=first_above, checkpoints=checkpoints, final=rows[-1],
            geometry_context_before_shape=before_shape_checks(reference, rows) if reference is not None else None,
        )
    return dict(
        version="lms405-volatility-context-audit-v1",
        method="SMA_14_COMPLETED_PRIOR_TRUE_RANGES; EXACT_STRICT_1_ATR_COMPARISON",
        opening_gap_policy="FIRST_TRADING_DAY_MINUTE_VS_PRIOR_TRADING_DAY_CLOSE; FIRST_DAY_MINUTE_VS_LAST_NIGHT_MINUTE",
        cases=cases, nine_contract_control=portfolio, source_id="WRnTjn0HU8",
        source_rule_confirmed=False, automatic_timeframe=None, author_signal=None, executable=False,
    )


def bars_sha(bars):
    rows = [[bar.bar_end.isoformat(), *map(str, ohlc(bar))] for bar in bars]
    return sha(encoded(rows).encode())


def prior_days(calendar, day):
    all_dates = [value for value, trading in calendar if trading]
    if len(all_dates) < PERIOD + 2 or all_dates[-1] != day:
        raise ValueError("TRADING_CALENDAR_PREFIX_UNVERIFIED")
    dates = all_dates[-(PERIOD + 2):-1]
    expected = [dates[0] + timedelta(days=offset) for offset in range((day - dates[0]).days + 1)]
    if [value for value, _ in calendar if value >= dates[0]] != expected:
        raise ValueError("TRADING_CALENDAR_PREFIX_GAP")
    return dates


def read_inputs(session, market, contract, day, session_resolver):
    symbol = contract[:-4].lower()
    calendar = market.catalog.calendar_days(symbol, day - timedelta(days=45), day)
    dates = prior_days(calendar, day)
    exchange = market.catalog.exchange_for_symbol(symbol)
    windows = session_resolver(session, exchange=exchange, symbol=symbol, trading_day=day)
    minutes = read_local(market, symbol, contract, "1m", day, day).bars
    check_session_coverage(minutes, {day: windows}, ONE)
    dailies = read_local(market, symbol, contract, "1d", dates[0], dates[-1]).bars
    atr_total, true_ranges = prior_atr(dailies, expected=dates, before=minutes[0].bar_end - ONE)
    prior_minutes = read_local(market, symbol, contract, "1m", dates[-1], dates[-1]).bars
    prior_windows = session_resolver(session, exchange=exchange, symbol=symbol, trading_day=dates[-1])
    check_session_coverage(prior_minutes, {dates[-1]: prior_windows}, ONE)
    if prior_minutes[-1].close != dailies[-1].close:
        raise ValueError("PRIOR_CLOSE_DAILY_MINUTE_DISAGREEMENT")
    day_reopen = min((row.window.start + ONE for row in windows if not row.is_night), default=None)
    if not any(row.is_night for row in windows):
        day_reopen = None
    return dict(minutes=minutes, dailies=dailies, day_reopen=day_reopen,
                atr_total=atr_total, true_ranges=true_ranges,
                minute_sha256=bars_sha(minutes), daily_sha256=bars_sha(dailies))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
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
        report_input = args.geometry.read_bytes()
        if sha(report_input) != GEOMETRY_SHA256:
            raise ValueError("FROZEN_TIMEFRAME_REPORT_CHANGED")
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session), json.loads(report_input))
        result["timeframe_input_sha256"] = GEOMETRY_SHA256
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
