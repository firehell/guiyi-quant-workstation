"""Check disclosed case levels and shared moves without inferring protection orders."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_replay import check_session_coverage, display, read_local, read_session_series
from lms405_right_side_study import ONE, US
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

CASES = (
    ("jm_april", "JM2609", "2026-04-23", "S5290900347693045",
     {"high": "1292.5", "low": "1252"},
     {"target": ("1285.5", "1295.5"), "prior_protection": ("1262", "1265.5"),
      "advanced_protection": ("1269", "1275.5")}),
    ("pvc_april", "V2609", "2026-04-23", "S5290904148773752",
     {"high": "5267"}, {"target": ("5226", "5262")}),
    ("oi_february", "OI2605", "2026-02-26", "S5270619778451962",
     {"low": "9166"}, {"extreme_m": ("9137", "9203"), "long_protection": ("9230", "9250")}),
    ("ta_february", "TA2605", "2026-02-27", "S5270983386071371",
     {"close": "5250", "low": "5182"}, {"separator": ("5254", "5266"), "short_target": ("5192", "5204")}),
)
PORTFOLIO_POSTS = ("S5310365073410706", "S5293418477784772", "S5244966513415009")


def locate(bars, predicate):
    bar = next((row for row in bars if predicate(row)), None)
    return dict(end=display(bar.bar_end), close=bar.close) if bar else None


def scope_path(bars, bounds):
    highs, lows = max(row.high for row in bars), min(row.low for row in bars)
    return dict(
        open=bars[0].open, high=highs, low=lows, close=bars[-1].close, minute_count=len(bars),
        first_high=locate(bars, lambda bar: bar.high == highs), first_low=locate(bars, lambda bar: bar.low == lows),
        levels={name: dict(
            first_contact=locate(bars, lambda bar: bar.low <= upper and bar.high >= lower),
            first_close_below=locate(bars, lambda bar: bar.close < lower),
            first_close_above=locate(bars, lambda bar: bar.close > upper),
        ) for name, (lower, upper) in bounds.items()},
    )


def shared_directions(first, second):
    def moves(bars):
        return {b.bar_end: b.close.compare(a.close) for a, b in zip(bars, bars[1:])
                if b.bar_end - a.bar_end == ONE}

    left, right = moves(first), moves(second)
    tags = [(left[end], right[end]) for end in left.keys() & right.keys()]
    paired = [(a, b) for a, b in tags if a and b]
    return dict(
        overlapping_contiguous_moves=len(tags), both_nonzero=len(paired),
        same_direction=sum(a == b for a, b in paired),
        opposite_direction=sum(a != b for a, b in paired), flat_on_at_least_one=len(tags) - len(paired),
    )


def verified_prior_day(market, symbol, day):
    calendar = market.catalog.calendar_days(symbol, day - timedelta(days=15), day)
    prior = [d for d, enabled in calendar if d < day and enabled]
    if not prior or (day, True) not in calendar:
        raise ValueError("PRIOR_TRADING_DAY_UNKNOWN")
    recent = [d for d, _ in calendar if prior[-1] <= d <= day]
    if recent != [prior[-1] + timedelta(days=n) for n in range((day - prior[-1]).days + 1)]:
        raise ValueError("PRIOR_TRADING_CALENDAR_GAP")
    return prior[-1]


def source_record(source):
    path = ARCHIVE.parent / source["archive_path"]
    return dict(url=source["source_url"], published_at=source["published_at"], archive_sha256=sha(path.read_bytes()))


def study(session, market):
    from app.market_data.market_data_service import MarketDataError
    from app.market_data.session_clock import resolved_session_windows_for_trading_day

    sources = input_sources()
    cases, daytime = {}, {}
    for case, contract, date_text, source, levels, bounds in CASES:
        day, symbol = date.fromisoformat(date_text), contract[:-4].lower()
        published = datetime.fromisoformat(sources[source]["published_at"])
        definition = cases[case] = dict(contract=contract, trading_day=day, source=source_record(sources[source]))
        try:
            exchange = market.catalog.exchange_for_symbol(symbol)
            windows = resolved_session_windows_for_trading_day(session, exchange=exchange, symbol=symbol, trading_day=day)
            raw = read_local(market, symbol, contract, "1m", day, day).bars
            coverage = check_session_coverage(raw, {day: windows}, ONE)
        except MarketDataError as exc:
            definition.update(status="LOCAL_DATA_UNVERIFIED", reason=exc.code)
            continue
        except ValueError as exc:
            definition.update(status="LOCAL_DATA_UNVERIFIED", reason=str(exc))
            continue
        if raw[-1].bar_end + US >= published:
            raise ValueError("POST_CUTOFF_DOES_NOT_COVER_TRADING_DAY")
        day_bars = [row for row in raw if not coverage[row.bar_end][1]]
        night_bars = [row for row in raw if coverage[row.bar_end][1]]
        if not day_bars or not night_bars:
            raise ValueError("REQUIRED_NIGHT_AND_DAY_COVERAGE")
        daytime[case] = day_bars
        bands = {name: tuple(map(Decimal, band)) for name, band in bounds.items()}
        paths = {name: scope_path(bars, bands)
                 for name, bars in (("trading_day", raw), ("day", day_bars), ("night", night_bars))}
        open_gap = prior_hash = None
        gap_status = "LOCAL_DATA_VERIFIED"
        try:
            prior_day = verified_prior_day(market, symbol, day)
            prior = read_session_series(session, market, symbol, contract, "1m", ONE, (prior_day,))
            if prior[-1].bar_end >= raw[0].bar_end - ONE:
                raise ValueError("PRIOR_MINUTE_NOT_BEFORE_OPEN")
            open_gap = raw[0].open - prior[-1].close
            prior_hash = bars_sha(prior)
        except MarketDataError as exc:
            gap_status = exc.code
        except ValueError as exc:
            gap_status = str(exc)
        definition.update(
            status="LOCAL_DATA_VERIFIED", minute_sha256=bars_sha(raw), prior_session_minute_sha256=prior_hash,
            paths=paths, trading_day_open_gap=open_gap, gap_status=gap_status,
            day_reopen_gap=day_bars[0].open - night_bars[-1].close,
            reported_prices={name: dict(
                value=Decimal(value), trading_day_matches=paths["trading_day"][name] == Decimal(value),
                day_session_matches=paths["day"][name] == Decimal(value),
            ) for name, value in levels.items()},
            historical_plan_revision_verified=False, actual_protection_signal=None, author_action_at=None,
        )
    joint = None
    if {"jm_april", "pvc_april"} <= daytime.keys():
        joint = shared_directions(daytime["jm_april"], daytime["pvc_april"])
    return dict(
        version="lms405-resonance-evidence-v1", cases=cases, april_day_session_comovement=joint,
        other_author_posts={key: source_record(sources[key]) for key in PORTFOLIO_POSTS},
        event_risk_rule=None, portfolio_trigger=None, author_action_samples=0, executable=False,
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
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
