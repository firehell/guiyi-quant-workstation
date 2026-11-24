"""Replay two completed-bar timing interpretations and peer observations."""

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_near405 import US, context
from lms405_locked_exit_audit import verify_aggregation
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

LOCAL = ZoneInfo("Asia/Shanghai")
DAYS = (date(2025, 11, 27), date(2025, 11, 28), date(2025, 12, 1))
ONE, FIVE = timedelta(minutes=1), timedelta(minutes=5)
ANCHOR = Decimal("1053.5")
POSITION_PRICE = Decimal("1061.5")
DAY_START = datetime(2025, 12, 1, 9, 0, tzinfo=LOCAL)
AFTER_0934 = DAY_START + timedelta(minutes=35)
CUTOFF = DAY_START + timedelta(minutes=64)


def point(left, bar, right):
    low = bar.low < min(left.low, right.low)
    high = bar.high > max(left.high, right.high)
    if low == high:
        return None
    return dict(kind="LOW" if low else "HIGH", price=bar.low if low else bar.high,
                bar_end=bar.end, known_at=right.end + US)


def structure_trace(bars, *, as_of):
    """Strict pivots use one neighbor each side; no labels before right close."""
    pivots, observed, rows, resolved = [], [], [], set()
    for i, bar in enumerate(bars):
        if bar.end + US >= as_of:
            break
        if i and bars[i - 1].end != bar.start:
            pivots = []
        vertices = pivots[-3:]
        if [vertex["kind"] for vertex in vertices] == ["LOW", "HIGH", "LOW"]:
            first, high, second = vertices
            key = tuple(v["bar_end"] for v in vertices)
            if key not in resolved:
                if bar.low < second["price"]:
                    resolved.add(key)
                elif bars[i - 1].close <= high["price"] < bar.close:
                    resolved.add(key)
                    rows.append(dict(timing="PREVIOUSLY_CONFIRMED_PIVOTS", pivots=vertices,
                                     close=bar.close, confirmation_bar_end=bar.end,
                                     available_at=bar.end + US, higher_second_low=second["price"] > first["price"]))
        # A newly revealed pivot enters the sequential rule from the next bar.
        if i >= 2 and bars[i - 2].end == bars[i - 1].start and bars[i - 1].end == bar.start:
            pivot = point(*bars[i - 2 : i + 1])
            if pivot is not None:
                pivots.append(pivot)
                observed.append(pivot)
                vertices = pivots[-3:]
                if [vertex["kind"] for vertex in vertices] == ["LOW", "HIGH", "LOW"]:
                    first, high, second = vertices
                    if bars[i - 1].close <= high["price"] < bar.close:
                        # This is a separate joint condition at one completed close.
                        # No ordering between that close's two observations is inferred.
                        rows.append(dict(timing="JOINT_COMPLETED_BAR", pivots=vertices,
                                         close=bar.close, confirmation_bar_end=bar.end,
                                         available_at=bar.end + US, higher_second_low=second["price"] > first["price"]))
    return dict(pivots=observed, breakouts=rows)


def peer_observation(series, end):
    index = next((i for i, bar in enumerate(series) if bar.end == end), None)
    if index is None:
        return None
    bar = series[index]
    day_open = next((b.open for b in series[: index + 1] if b.start == DAY_START), None)
    frame = context(series, index)
    morning_only = frame and datetime.fromisoformat(frame["window_start"]) > DAY_START
    return dict(contract=bar.contract, open=bar.open, high=bar.high, low=bar.low, close=bar.close, day_open=day_open,
                above_day_open=bar.close > day_open if day_open is not None else None,
                context=frame["environment"] if frame else None,
                morning_context=frame["environment"] if morning_only else None,
                context_end=frame["window_end"] if frame else None)


def market_rows(raw, contract, cutoff):
    bars = [Bar(contract, row.bar_end, *ohlc(row), start=row.bar_end - FIVE) for row in raw["5m"]]
    verify_aggregation(bars, raw["1m"])
    # Truncate by knowledge time for the historical observations; coverage was checked first.
    return [b for b in bars if b.end + US < cutoff]


def anchor_report(minutes, fives):
    by_day = defaultdict(lambda: dict(exact_1053_5_minute_lows=[], exact_1053_5_five_minute_lows=[],
                                      bars_containing_1061_5=0, exact_1061_5_closes=0, low=None,
                                      daily_low_minutes=[]))
    for bar in minutes:
        day = by_day[bar.trading_day.isoformat()]
        end = bar.bar_end.astimezone(LOCAL)
        if day["low"] is None or bar.low < day["low"]:
            day.update(low=bar.low, daily_low_minutes=[])
        if bar.low == day["low"]:
            day["daily_low_minutes"].append(end)
        if bar.low == ANCHOR:
            day["exact_1053_5_minute_lows"].append(end)
        day["bars_containing_1061_5"] += bar.low <= POSITION_PRICE <= bar.high
        day["exact_1061_5_closes"] += bar.close == POSITION_PRICE
    for bar in fives:
        if bar.low == ANCHOR:
            by_day[bar.trading_day.isoformat()]["exact_1053_5_five_minute_lows"].append(bar.bar_end.astimezone(LOCAL))
    return by_day


def study(session, market):
    from app.market_data.market_data_service import MarketDataError

    raw, bars, evidence = {}, {}, {}
    for symbol in ("jm", "i", "rb"):
        contract = "JM2601" if symbol == "jm" else None
        days = DAYS if symbol == "jm" else DAYS[-1:]
        try:
            if contract is None:
                contract = market.dominant_segment_for_day(symbol, days[0]).contract
            series = {period: read_session_series(session, market, symbol, contract, period, step, days)
                      for period, step in (("1m", ONE), ("5m", FIVE))}
            bars[symbol] = market_rows(series, contract, CUTOFF)
        except MarketDataError as exc:
            evidence[symbol] = dict(contract=contract, status=exc.code)
            continue
        except (ValueError, KeyError):
            evidence[symbol] = dict(contract=contract, status="SESSION_OR_AGGREGATION_UNVERIFIED")
            continue
        raw[symbol] = series
        evidence[symbol] = dict(contract=contract, status="READABLE", selection="AUTHOR_CONTRACT" if symbol == "jm"
                               else "LOCAL_RANK1_AT_TRADING_DAY_AUTHOR_CONTRACT_UNKNOWN", bars={
                                   period: dict(count=len(records), hash=sha(encoded([
                                       (b.bar_end.isoformat(), *map(str, ohlc(b))) for b in records
                                   ]).encode())) for period, records in series.items()
                               })
    events, morning, pivots = [], [], []
    if "jm" in bars:
        trace = structure_trace(bars["jm"], as_of=CUTOFF)
        pivots = [row for row in trace["pivots"] if DAY_START < row["bar_end"]]
        events = [row for row in trace["breakouts"]
                  if DAY_START < row["confirmation_bar_end"]]
        for end in (DAY_START + FIVE * i for i in range(1, 13)):
            peers = {name: peer_observation(bars.get(name, ()), end) for name in ("i", "rb")}
            jm = peer_observation(bars["jm"], end)
            morning.append(dict(bar_end=end.astimezone(LOCAL), available_at=end + US,
                                jm=jm, peers=peers, after_0934=end > AFTER_0934))
        rows_by_end = {r["bar_end"]: r for r in morning}
        for event in events:
            event["aligned_market"] = rows_by_end[event["confirmation_bar_end"]]
    return dict(version="lms405-jm2601-structure-and-peers-v1", author_sources=["N01", "N02", "N04", "O02", "KB15"],
                cutoff=CUTOFF, input=evidence,
                anchor=anchor_report(raw["jm"]["1m"], raw["jm"]["5m"]) if "jm" in raw else None,
                anchor_scope="RETROSPECTIVE_FULL_TRADING_DAYS_NOT_CUTOFF_INPUT",
                morning=morning, pivots=pivots, events=events, admitted_author_samples=0, author_matches=None,
                author_period=None, author_event_at=None, executable=False, fills=None)


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
