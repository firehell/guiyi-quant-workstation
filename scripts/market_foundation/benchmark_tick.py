"""Accelerated complete-session Tick replay on the target host (synthetic evidence)."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, date, datetime, timedelta
import json
import platform
import resource
from time import perf_counter

from app.market_data.aggregation import SessionWindow, expected_intraday_ends
from app.market_data.domain import BarFrequency
from app.market_data.operational_universe import load_operational_products
from app.market_data.tick_feed import TickMarketDataProvider, TickPreviewStore
from app.market_data.tick_veighna import VeighNaTickDispatch

_DAY = date(2026, 11, 26)
_ORIGIN = datetime(2026, 11, 25, 13, tzinfo=UTC)
_SECOND = timedelta(seconds=1)
_TICK_ARRIVAL_DELAY = timedelta(milliseconds=8)
_EXTRA = ("aa", "ab", "ac", "ad", "ae", "af", "ah", "ak", "aq", "aw", "ax", "ay", "az")


def _window(hours, minutes, duration):
    start = _ORIGIN + timedelta(hours=hours, minutes=minutes)
    return SessionWindow(start, start + timedelta(minutes=duration))


def _products_owners(count):
    products = load_operational_products()
    if len(products) != 60:
        raise ValueError("BENCHMARK_REQUIRES_OPERATIONAL_60")
    if count == 70:
        products += tuple(item for item in _EXTRA if item not in products)[:10]
    owners = {}
    for index, product in enumerate(products):
        night = 330 if index < 4 else 180 if index < 15 else 120 if index < 45 else 0
        sessions = ((_window(0, 0, night),) if night else ()) + (
            _window(12, 0, 75), _window(13, 30, 60), _window(16, 30, 90),
        )
        owners[product] = (product.upper() + "2701", sessions)
    return owners


def _percentile(values, percentile):
    return sorted(values)[int((len(values) - 1) * percentile)]


def benchmark(count, hz):
    owners = _products_owners(count)
    expected = {contract: expected_intraday_ends(windows, BarFrequency.M1)
                for contract, windows in owners.values()}
    schedule = {}
    for contract, sessions in owners.values():
        for session in sessions:
            start, end = (int((point - _ORIGIN).total_seconds()) for point in (session.start, session.end))
            for second in range(start, end + 1):
                schedule.setdefault(second, []).append((contract, second == end))
    totals = Counter()
    completed = {contract: [] for contract in expected}
    elapsed_batches = []
    enqueued = 0
    peak_pending = 0
    connection = object()
    arrival = [_ORIGIN]
    dispatched = VeighNaTickDispatch()
    preview = TickPreviewStore()
    provider = TickMarketDataProvider(
        object(), connection_identity=lambda: connection, preview=preview, dispatch=dispatched,
        clock=lambda: arrival[0],
    )
    provider.configure(_DAY, owners)

    wall_start = perf_counter()
    before = resource.getrusage(resource.RUSAGE_SELF)
    try:
        for second, active in sorted(schedule.items()):
            for fraction in range(hz):
                seen = _ORIGIN + second * _SECOND + fraction * (_SECOND / hz)
                arrival[0] = seen + _TICK_ARRIVAL_DELAY
                batch = perf_counter()
                for contract, endpoint in active:
                    if endpoint and fraction:
                        continue
                    totals[contract] += 1
                    volume = totals[contract]
                    last = 100 + volume % 11
                    provider._buffer_message({
                        "action": "feed", "channel": f"tick_{contract}", "order_book_id": contract,
                        "datetime": seen, "last": last, "volume": volume,
                        "total_turnover": volume * 102, "open_interest": 100_000,
                        "bid": [last - 1], "bid_vol": [1], "ask": [last + 1], "ask_vol": [2],
                    })
                    enqueued += 1
                peak_pending = max(peak_pending, provider.buffered_message_count())
                for contract, bar in provider.poll_buffered():
                    if bar.trading_day != _DAY:
                        raise ValueError("BENCHMARK_WRONG_TRADING_DAY")
                    completed[contract].append(bar.bar_end)
                elapsed_batches.append((perf_counter() - batch) * 1000)
    finally:
        dispatched.close()
    after = resource.getrusage(resource.RUSAGE_SELF)
    wall = perf_counter() - wall_start
    expected_count = sum(map(len, expected.values()))
    actual_count = sum(map(len, completed.values()))
    if any(tuple(completed[contract]) != ends for contract, ends in expected.items()):
        raise ValueError(f"BENCHMARK_ENDPOINT_MISMATCH expected={expected_count} actual={actual_count}")
    return {
        "kind": "synthetic_accelerated_complete_session",
        "platform": platform.platform(), "products": count, "frequency_hz_per_open_contract": hz,
        "ticks": enqueued, "completed_1m": actual_count, "expected_1m": expected_count,
        "duration_s": round(wall, 3), "ticks_per_wall_second": round(enqueued / wall),
        "callback_through_processing_ms_p50": round(_percentile(elapsed_batches, 0.50), 3),
        "callback_through_processing_ms_p95": round(_percentile(elapsed_batches, 0.95), 3),
        "callback_through_processing_ms_p99": round(_percentile(elapsed_batches, 0.99), 3),
        "callback_through_processing_ms_max": round(max(elapsed_batches), 3),
        "max_queue_depth": peak_pending, "end_queue_depth": provider.buffered_message_count(),
        "rss_max_bytes": after.ru_maxrss,
        "cpu_seconds": round(after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime, 3),
        "diagnostics": dict(provider.diagnostics),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", type=int, choices=(60, 70), required=True)
    parser.add_argument("--frequency-hz", type=int, choices=(1, 2, 5), default=2)
    args = parser.parse_args()
    result = benchmark(args.products, args.frequency_hz)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
