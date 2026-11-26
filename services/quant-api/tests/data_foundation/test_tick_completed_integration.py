from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal

import pytest

from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.domain import BarFrequency
from app.market_data.live_market import RedisLiveStore
from app.market_data.market_feed import DurableLiveMarketService, FeedLiveStore, MarketFeedService, StreamLiveProvider
from app.market_data.observation_stream import ObservationStream
from app.market_data.tick_feed import TickMarketDataProvider, TickPreviewStore
from app.subing_portfolio_worker import read_completed
from tests.data_foundation import test_observation_stream as stream_tests
from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _phase
from tests.data_foundation.test_tick_market import DAY, MINUTE, OPEN


@pytest.fixture
def isolated_redis():
    yield from stream_tests.isolated_redis.__wrapped__()


class Client:
    def subscribe(self, channels):
        assert channels == ["tick_AU2612"]

    def listen(self, *, handler):
        self.handler = handler

    def close(self):
        pass


def test_tick_minute_closure_drives_existing_paper_and_h1_paths_after_restart(isolated_redis):
    window = SessionWindow(OPEN, OPEN + 75 * MINUTE)
    client = Client()
    current = [OPEN]
    clock = lambda: current[0]  # noqa: E731 - explicit shared source and polling clock
    preview = TickPreviewStore()
    store = RedisLiveStore(isolated_redis)
    store.set_subscriptions(DAY, {"au": "AU2612"})
    source = ObservationStream(isolated_redis, kind="source")
    source.initialize("live", DAY, cursor="0-0")
    stream = ObservationStream(isolated_redis, kind="completed")
    stream.initialize("alert", DAY, cursor="0-0")
    args = dict(
        dominant_source=FakeDominants({("au", DAY): "AU2612"}),
        phase_resolver=FakePhases({"au": _phase("au", DAY, window)}),
        coverage_sessions=lambda *_: (window,),
        operational_products=("au",), authoritative_dominants=True, clock=clock,
    )
    feed = MarketFeedService(
        source_stream=source, store=FeedLiveStore(isolated_redis), tick_source=True,
        provider_factory=lambda: TickMarketDataProvider(
            client, connection_identity=lambda: client, preview=preview, clock=clock,
        ), shutdown_guard_factory=nullcontext, **args,
    )

    def durable():
        return DurableLiveMarketService(source_provider=StreamLiveProvider(source), store=store, **args)

    compute = durable()
    assert feed.poll(OPEN) is None
    assert compute.poll(OPEN) is None
    for minute in range(61):
        seen = OPEN + minute * MINUTE
        current[0] = seen + timedelta(milliseconds=10)
        client.handler({"channel": "tick_AU2612", "action": "feed", "order_book_id": "AU2612",
                        "datetime": seen, "volume": minute, "last": 101 + minute,
                        "total_turnover": 100 * minute, "open_interest": 51})
        current[0] = seen + timedelta(seconds=3)
        assert feed.poll(current[0]) is None
        if minute == 35:
            compute = durable()  # cursor and minutes survive losing all process state
        assert compute.poll(current[0]) is None

    assert source.cursor("live", DAY) == source.tail(DAY)
    originals = stream.read("alert", DAY)
    assert len(originals) == 79
    assert len({item.observation_id for item in originals}) == len(originals)
    last = originals[-1]
    assert last.channel == "live:bar:au:60m"
    assert last.source_generation.startswith("rqdata-tick:")
    assert last.source_observed_at == OPEN + 60 * MINUTE
    assert last.raw_received_at == last.source_observed_at + timedelta(milliseconds=10)
    assert last.confirmed_at == last.source_observed_at + timedelta(seconds=3)
    def read_bars(frequency):
        return tuple(item.bar for item in store.bar_observations(
            DAY, "au", frequency, OPEN, current[0], inclusive_after=False, expected_contract="AU2612",
        ))
    minute_bars = read_bars("1m")
    h1_bars = read_bars("60m")
    expected = aggregate_from_1m(minute_bars, target_frequency=BarFrequency.H1,
                                sessions=(SessionWindow(OPEN, OPEN + 60 * MINUTE),))
    assert h1_bars == expected
    assert h1_bars[0].volume == Decimal("59")
    assert h1_bars[0].turnover == Decimal("5900")

    context = {"contract": "AU2612", "expected_1m": [item.bar_end.isoformat() for item in minute_bars],
               "expected_30m": [(OPEN + n * MINUTE).isoformat() for n in (30, 60)],
               "expected_60m": [(OPEN + 60 * MINUTE).isoformat()]}
    paper_events, tail = read_completed(stream, DAY, {"au": context}, "0-0")
    assert len(paper_events) == 63 and tail == stream.tail(DAY)
    assert read_completed(stream, DAY, {"au": context}, tail) == ({}, tail)
    assert durable().poll(current[0]) is None
    assert stream.tail(DAY) == tail

    # The callback can race ahead of a clock captured at cycle start. Durable
    # publication must wait until its confirming clock covers the real arrival.
    edge = OPEN + 61 * MINUTE
    current[0] = edge + timedelta(seconds=3, milliseconds=50)
    client.handler({"channel": "tick_AU2612", "action": "feed", "order_book_id": "AU2612",
                    "datetime": edge, "volume": 61, "last": 162,
                    "total_turnover": 6100, "open_interest": 51})
    assert feed.poll(edge + timedelta(seconds=3)) is None
    restarted = durable()
    assert restarted.poll(edge + timedelta(seconds=3)) is None
    assert stream.tail(DAY) == tail
    assert restarted.poll(edge + timedelta(seconds=4)) is None
    assert stream.tail(DAY) != tail
