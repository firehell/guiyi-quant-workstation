from datetime import date, datetime, timezone
from types import SimpleNamespace
import json

from app.reference_trading.live_wake import ForwardLiveWake


class PubSub:
    def __init__(self):
        self.messages = [{"type": "psubscribe"}]
        self.closed = False

    def psubscribe(self, pattern):
        assert pattern == "live:bar:*"

    def get_message(self, *, timeout):
        return self.messages.pop(0) if self.messages else None

    def close(self):
        self.closed = True


class Redis:
    def __init__(self):
        self.source = PubSub()

    def pubsub(self, *, ignore_subscribe_messages):
        assert ignore_subscribe_messages is False
        return self.source


class Repository:
    def enabled_forward_stream_ids(self, *, limit):
        assert limit == 512
        return ("rb-60m", "rb-1d", "cu-60m")

    def forward_source_context(self, stream_id):
        product, frequency = stream_id.split("-")
        return (SimpleNamespace(product=product, frequency=frequency),)


class Worker:
    def __init__(self):
        self.wakes = []

    def wake(self, stream_id, *, kind, bar_end):
        self.wakes.append((stream_id, kind, bar_end))


class Market:
    def dominant_segment_for_day(self, symbol, trading_day):
        assert symbol == "rb" and trading_day == date(2026, 9, 23)
        return SimpleNamespace(contract="RB2610")


def test_completed_live_pubsub_wakes_only_exact_product_and_frequency():
    redis, worker = Redis(), Worker()
    wake = ForwardLiveWake(redis, Repository(), worker, Market())
    wake.subscribe()
    end = datetime(2026, 9, 23, 1, tzinfo=timezone.utc)
    payload = {"bar_end": end.isoformat(), "trading_day": "2026-09-23", "contract": "RB2610"}
    redis.source.messages.append({"type": "pmessage", "channel": b"live:bar:rb:60m",
                                  "data": json.dumps(payload).encode()})
    wake.wait(5)
    assert worker.wakes == [("rb-60m", "live_event", end)]
    redis.source.messages.append({"type": "pmessage", "channel": b"live:bar:rb:60m",
                                  "data": json.dumps({**payload, "contract": "RB2701"}).encode()})
    wake.wait(5)
    assert len(worker.wakes) == 1
    wake.close()
    assert redis.source.closed
