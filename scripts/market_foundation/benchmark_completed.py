"""Exercise the minute journals and five intraday frequencies in disposable Redis."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import timedelta
import json
import resource
from time import perf_counter

from redis import Redis

from app.market_data.aggregation import expected_intraday_ends
from app.market_data.domain import BarFrequency
from app.market_data.live_market import RedisLiveStore
from app.market_data.market_feed import DurableLiveMarketService, FeedLiveStore, MarketFeedService, StreamLiveProvider
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.observation_stream import ObservationStream
from app.market_data.tick_feed import TickMarketDataProvider, TickPreviewStore
from app.market_data.tick_veighna import VeighNaTickDispatch
from app.subing_portfolio_worker import read_completed
from benchmark_tick import _DAY, _ORIGIN, _percentile, _products_owners

_MINUTE = timedelta(minutes=1)
_FREQUENCIES = (BarFrequency.M1, BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1)


class _Authority:
    def __init__(self, owners):
        self.owners = owners

    def dominant_for_day(self, symbol, day):
        if day != _DAY:
            raise ValueError("BENCHMARK_TRADING_DAY_MISMATCH")
        return self.owners[symbol][0]

    def sessions(self, symbol, day):
        if day != _DAY:
            raise ValueError("BENCHMARK_TRADING_DAY_MISMATCH")
        return self.owners[symbol][1]

    def resolve(self, symbol, now):
        windows = self.sessions(symbol, _DAY)
        current = next((item for item in windows if item.start <= now < item.end), None)
        upcoming = next((item.start for item in windows if item.start > now), windows[-1].end + timedelta(hours=6))
        phase = MarketPhase.TRADING if current else (
            MarketPhase.BREAK if windows[0].start < now < windows[-1].end else MarketPhase.CLOSED
        )
        return ProductMarketPhase(symbol, phase, _DAY, current, upcoming)


class _ReplaySocket:
    def __init__(self):
        self._channels = set()
        self.handler = None

    def subscribe(self, channels):
        self._channels.update(channels)

    def unsubscribe(self, channels):
        self._channels.difference_update(channels)

    def listen(self, *, handler):
        self.handler = handler

    def push(self, contract, observed_at, counter):
        channel = f"tick_{contract}"
        if channel in self._channels:
            assert self.handler is not None
            self.handler({"action": "feed", "channel": channel, "order_book_id": contract,
                          "datetime": observed_at, "last": 100 + counter % 11, "volume": counter,
                          "total_turnover": 100 * counter, "open_interest": 123})


def run(redis, products):
    if redis.dbsize() != 0:
        raise ValueError("BENCHMARK_REDIS_MUST_BE_EMPTY")
    owners = _products_owners(products)
    authority = _Authority(owners)
    store = RedisLiveStore(redis)
    source = ObservationStream(redis, kind="source")
    stream = ObservationStream(redis, kind="completed")
    source.initialize("live", _DAY, cursor="0-0")
    stream.initialize("alert", _DAY, cursor="0-0")
    store.set_subscriptions(_DAY, {symbol: contract for symbol, (contract, _windows) in owners.items()})
    client = _ReplaySocket()
    current = [_ORIGIN]
    dispatch = VeighNaTickDispatch()
    preview = TickPreviewStore()

    def clock():
        return current[0]

    def provider():
        return TickMarketDataProvider(client, connection_identity=lambda: client, preview=preview,
                                      clock=clock, dispatch=dispatch)

    args = dict(dominant_source=authority, phase_resolver=authority, coverage_sessions=authority.sessions,
                operational_products=tuple(owners), authoritative_dominants=True, clock=clock)
    feed = MarketFeedService(source_stream=source, provider_factory=provider, store=FeedLiveStore(redis),
                             tick_source=True, shutdown_guard_factory=nullcontext, **args)

    def completed():
        return DurableLiveMarketService(
            source_provider=StreamLiveProvider(source, require_tick=True), store=store, **args,
        )

    live = completed()
    counters = dict.fromkeys((owner[0] for owner in owners.values()), 0)
    schedule = {}
    opening = set()
    for contract, windows in owners.values():
        for window in windows:
            opening.add(window.start)
            offset = 0
            while window.start + offset * _MINUTE <= window.end:
                at = window.start + offset * _MINUTE
                schedule.setdefault(at, []).append(contract)
                offset += 1
    expected = {(symbol, frequency.value): expected_intraday_ends(windows, frequency)
                for symbol, (_contract, windows) in owners.items() for frequency in _FREQUENCIES}
    samples = []
    started = perf_counter()
    before = resource.getrusage(resource.RUSAGE_SELF)
    try:
        for round_index, (at, active) in enumerate(sorted(schedule.items())):
            current[0] = at
            if at in opening:
                if failure := feed.poll(at):
                    raise ValueError(failure)
            current[0] = at + timedelta(milliseconds=10)
            for contract in active:
                counters[contract] += 1
                client.push(contract, at, counters[contract])
            current[0] = at + timedelta(seconds=3)
            minute_round = perf_counter()
            if failure := feed.poll(current[0]):
                raise ValueError(failure)
            if round_index == len(schedule) // 2:
                live = completed()
            if failure := live.poll(current[0]):
                raise ValueError(failure)
            samples.append((perf_counter() - minute_round) * 1000)
    finally:
        dispatch.close()
    after = resource.getrusage(resource.RUSAGE_SELF)
    actual = {}
    for (symbol, frequency), ends in expected.items():
        contract = owners[symbol][0]
        bars = store.bar_observations(_DAY, symbol, frequency, ends[0], ends[-1],
                                      inclusive_after=True, expected_contract=contract)
        output = tuple(item.bar.bar_end for item in bars)
        if output != ends:
            raise ValueError(f"COMPLETED_ENDPOINT_MISMATCH {symbol} {frequency} {len(output)}/{len(ends)}")
        actual[symbol, frequency] = len(output)
    count = sum(actual.values())
    if source.cursor("live", _DAY) != source.tail(_DAY) or redis.xlen(stream.key(_DAY)) != count:
        raise ValueError("COMPLETED_FRONTIER_MISMATCH")
    contexts = {symbol: {"contract": contract, **{
        f"expected_{frequency}": [when.isoformat() for when in expected[symbol, frequency]]
        for frequency in ("1m", "30m", "60m")}}
        for symbol, (contract, _window) in owners.items()}
    paper, cursor = read_completed(stream, _DAY, contexts, "0-0")
    if len(paper) != sum(count for (_symbol, frequency), count in actual.items()
                         if frequency in ("1m", "30m", "60m")) or cursor != stream.tail(_DAY):
        raise ValueError("COMPLETED_PAPER_INPUT_MISMATCH")
    return {
        "kind": "synthetic_minute_boundary_replay_with_native_redis", "products": products,
        "completed_by_frequency": {frequency.value: sum(count for (_symbol, name), count in actual.items()
                                                       if name == frequency.value) for frequency in _FREQUENCIES},
        "total_completed": count, "paper_inputs": len(paper), "restart_after_minute_round": len(schedule) // 2,
        "minute_rounds": len(samples), "minute_round_redis_commit_p95_ms": round(_percentile(samples, .95), 3),
        "minute_round_redis_commit_p99_ms": round(_percentile(samples, .99), 3),
        "duration_s": round(perf_counter() - started, 3),
        "redis_used_bytes": redis.info("memory")["used_memory"],
        "rss_max_bytes": after.ru_maxrss,
        "cpu_seconds": round(after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime, 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", type=int, choices=(60, 70), required=True)
    parser.add_argument("--redis-port", type=int, required=True)
    parser.add_argument("--redis-db", type=int, choices=(13, 14, 15), required=True)
    args = parser.parse_args()
    if not 1024 <= args.redis_port <= 65535 or args.redis_port == 6379:
        parser.error("a disposable non-default Redis port is required")
    with Redis(host="127.0.0.1", port=args.redis_port, db=args.redis_db, decode_responses=True) as redis:
        print(json.dumps(run(redis, args.products), indent=2))


if __name__ == "__main__":
    main()
