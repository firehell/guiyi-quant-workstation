from datetime import date, datetime, timezone
from decimal import Decimal
import os
from types import SimpleNamespace
import json

from app.reference_trading.live_wake import ForwardLiveWake
from app.market_data.domain import CanonicalBar
from app.market_data.live_market import RedisLiveStore


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
    def enabled_forward_routes(self, product, frequency):
        return tuple(item for item in ("rb-60m", "rb-1d", "cu-60m")
                     if item == f"{product}-{frequency}")


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


def test_isolated_redis_publish_bar_reaches_exact_forward_wake():
    url = os.getenv("GUIYI_ISOLATED_REDIS_URL")
    if not url:
        import pytest
        pytest.skip("GUIYI_ISOLATED_REDIS_URL is required")
    from redis import Redis

    redis = Redis.from_url(url)
    worker = Worker()
    wake = ForwardLiveWake(redis, Repository(), worker, Market())
    end = datetime(2026, 9, 23, 1, tzinfo=timezone.utc)
    bar = CanonicalBar(
        end, date(2026, 9, 23), Decimal("3500"), Decimal("3510"),
        Decimal("3490"), Decimal("3505"), Decimal("100"), None, None,
    )
    try:
        wake.subscribe()
        RedisLiveStore(redis).publish_bar("rb", "60m", bar, contract="RB2610")
        wake.wait(2)
        assert worker.wakes == [("rb-60m", "live_event", end)]
    finally:
        wake.close()
        redis.close()
