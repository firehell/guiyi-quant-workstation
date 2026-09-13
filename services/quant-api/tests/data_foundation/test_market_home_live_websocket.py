from __future__ import annotations

from collections import deque
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import CanonicalBar
from app.market_data.market_home_live import MarketHomeLiveItem, MarketHomeLiveSnapshot


NOW = datetime(2026, 8, 15, 1, 2, 2, tzinfo=UTC)
DAY = date(2026, 8, 15)


def test_home_live_websocket_subscribes_fixed_scope_before_snapshot_and_dedupes(
    monkeypatch,
) -> None:
    """Catches per-product sockets, a subscribe/snapshot gap, or duplicate/old quotes."""
    first = MarketHomeLiveSnapshot(
        NOW,
        (
            _item("j", "J2609", "101", NOW - timedelta(minutes=1)),
            _item("jm", "JM2609", "901", NOW - timedelta(minutes=1)),
        ),
    )
    reset = MarketHomeLiveSnapshot(
        NOW + timedelta(seconds=1),
        (
            _item("j", "J2701", "102", NOW),
            _item("jm", "JM2609", "901", NOW - timedelta(minutes=1)),
        ),
    )
    pubsub = FakeHomePubSub(
        (
            {"channel": "live:bar:j:1m", "data": _payload("101", NOW - timedelta(minutes=1))},
            {"channel": "live:bar:j:1m", "data": _payload("102", NOW)},
            {"channel": "market:state", "data": "{}"},
        )
    )
    redis = FakeAsyncRedis(pubsub)
    snapshots = deque((first, reset))

    async def read(previous=None):
        assert pubsub.subscribed
        return snapshots.popleft()

    async def read_item(symbol, previous):
        assert symbol == "j"
        assert previous.physical_contract == "J2609"
        return _item("j", "J2609", "102", NOW)

    monkeypatch.setattr("app.api.market_live.load_operational_products", lambda: ("j", "jm"))
    monkeypatch.setattr("app.api.market_live._read_home_live_snapshot", read)
    monkeypatch.setattr("app.api.market_live._read_home_live_item", read_item)
    monkeypatch.setattr("app.api.market_live._home_live_now", lambda: NOW + timedelta(seconds=2))
    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", lambda: redis)

    with TestClient(app).websocket_connect("/api/v1/market/research/home-live/ws") as websocket:
        messages = [websocket.receive_json() for _ in range(4)]

    assert [message["type"] for message in messages] == [
        "snapshot",
        "quote",
        "reset",
        "unavailable",
    ]
    assert pubsub.channels == (
        "live:bar:j:1m",
        "live:bar:jm:1m",
        "market:state",
    )
    assert messages[0]["scope"] == "operational"
    assert messages[1]["item"]["symbol"] == "j"
    assert messages[1]["item"]["price"] == "102"
    assert messages[2]["reason"] == "AUTHORITY_CHANGED"
    assert messages[2]["items"][0]["physical_contract"] == "J2701"
    assert messages[3]["code"] == "MARKET_HOME_LIVE_UNAVAILABLE"
    assert pubsub.closed and redis.closed


def test_home_live_pubsub_is_only_a_wakeup_and_owner_change_resets(monkeypatch) -> None:
    """Catches a provenance-free Pub/Sub payload being labeled with the old owner."""
    initial = MarketHomeLiveSnapshot(
        NOW,
        (_item("j", "J2609", "101", NOW - timedelta(minutes=1)),),
    )
    pubsub = FakeHomePubSub(
        ({"channel": "live:bar:j:1m", "data": _payload("999", NOW)},)
    )
    redis = FakeAsyncRedis(pubsub)

    async def read(previous=None):
        return initial

    async def read_item(symbol, previous):
        return _item("j", "J2701", "202", NOW)

    monkeypatch.setattr("app.api.market_live.load_operational_products", lambda: ("j",))
    monkeypatch.setattr("app.api.market_live._read_home_live_snapshot", read)
    monkeypatch.setattr("app.api.market_live._read_home_live_item", read_item)
    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", lambda: redis)

    with TestClient(app).websocket_connect("/api/v1/market/research/home-live/ws") as websocket:
        assert websocket.receive_json()["type"] == "snapshot"
        reset = websocket.receive_json()

    assert reset["type"] == "reset"
    assert reset["items"][0]["physical_contract"] == "J2701"
    assert reset["items"][0]["price"] == "202"


def test_home_live_websocket_rejects_client_subscription_parameters(monkeypatch) -> None:
    """Catches callers expanding the fixed operational scope through query parameters."""
    called = False

    def redis_connection():
        nonlocal called
        called = True
        raise AssertionError("must not connect")

    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", redis_connection)

    with TestClient(app) as client:
        try:
            with client.websocket_connect(
                "/api/v1/market/research/home-live/ws?symbol=j"
            ) as websocket:
                websocket.receive_json()
        except Exception:
            pass

    assert called is False


def test_home_live_websocket_recovers_availability_without_waiting_for_a_bar(
    monkeypatch,
) -> None:
    """Catches a disconnected/unavailable stream that can recover only after a quote."""
    historical = MarketHomeLiveSnapshot(
        NOW,
        (_item("j", "J2609", "100", NOW - timedelta(days=1), source="completed_1d", availability="historical"),),
    )
    live = MarketHomeLiveSnapshot(
        NOW + timedelta(seconds=5),
        (_item("j", "J2609", "101", NOW - timedelta(minutes=1)),),
    )
    pubsub = FakeHomePubSub((None,))
    redis = FakeAsyncRedis(
        pubsub,
        heartbeat=(
            json.dumps({"available": False}),
            json.dumps({"available": True}),
        ),
    )
    snapshots = deque((historical, live))

    async def read(previous=None):
        return snapshots.popleft()

    monkeypatch.setattr("app.api.market_live.load_operational_products", lambda: ("j",))
    monkeypatch.setattr("app.api.market_live._read_home_live_snapshot", read)
    monkeypatch.setattr("app.api.market_live._HOME_LIVE_STATUS_REFRESH_SECONDS", 0)
    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", lambda: redis)

    with TestClient(app).websocket_connect("/api/v1/market/research/home-live/ws") as websocket:
        initial = websocket.receive_json()
        recovered = websocket.receive_json()

    assert initial["type"] == "snapshot"
    assert initial["items"][0]["availability"] == "historical"
    assert recovered["type"] == "reset"
    assert recovered["items"][0]["availability"] == "live"
    assert pubsub.closed and redis.closed


def test_home_live_checks_availability_while_pubsub_messages_are_continuous(
    monkeypatch,
) -> None:
    """Catches status recovery being starved whenever Pub/Sub never goes idle."""
    historical = MarketHomeLiveSnapshot(
        NOW,
        (_item("j", "J2609", "100", NOW - timedelta(days=1), source="completed_1d", availability="historical"),),
    )
    live = MarketHomeLiveSnapshot(
        NOW + timedelta(seconds=5),
        (_item("j", "J2609", "101", NOW - timedelta(minutes=1)),),
    )
    pubsub = FakeHomePubSub(({"channel": "unrelated", "data": "{}"},))
    redis = FakeAsyncRedis(
        pubsub,
        heartbeat=(
            json.dumps({"available": False}),
            json.dumps({"available": True}),
        ),
    )
    snapshots = deque((historical, live))

    async def read(previous=None):
        return snapshots.popleft()

    monkeypatch.setattr("app.api.market_live.load_operational_products", lambda: ("j",))
    monkeypatch.setattr("app.api.market_live._read_home_live_snapshot", read)
    monkeypatch.setattr("app.api.market_live._HOME_LIVE_STATUS_REFRESH_SECONDS", 0)
    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", lambda: redis)

    with TestClient(app).websocket_connect("/api/v1/market/research/home-live/ws") as websocket:
        assert websocket.receive_json()["type"] == "snapshot"
        recovered = websocket.receive_json()

    assert recovered["type"] == "reset"
    assert recovered["items"][0]["availability"] == "live"


def _item(
    symbol: str,
    contract: str,
    price: str,
    bar_end: datetime,
    *,
    source="completed_1m",
    availability="live",
) -> MarketHomeLiveItem:
    value = Decimal(price)
    return MarketHomeLiveItem(
        symbol,
        contract,
        DAY if source == "completed_1m" else DAY - timedelta(days=1),
        bar_end,
        value,
        Decimal("100"),
        value / Decimal("100") - Decimal(1),
        source,
        availability,
        "TRADING" if source == "completed_1m" else "CLOSED",
        None,
    )


def _payload(close: str, bar_end: datetime) -> str:
    value = Decimal(close)
    bar = CanonicalBar(bar_end, DAY, value, value, value, value, Decimal("1"), None, None)
    return json.dumps(
        {
            "bar_end": bar.bar_end.isoformat(),
            "trading_day": bar.trading_day.isoformat(),
            "open": str(bar.open),
            "high": str(bar.high),
            "low": str(bar.low),
            "close": str(bar.close),
            "volume": str(bar.volume),
            "turnover": None,
            "open_interest": None,
        }
    )


class FakeHomePubSub:
    def __init__(self, messages) -> None:
        self.messages = deque(messages)
        self.subscribed = False
        self.channels = ()
        self.closed = False

    async def subscribe(self, *channels):
        self.subscribed = True
        self.channels = channels

    async def get_message(self, *, ignore_subscribe_messages, timeout):
        if self.messages:
            return self.messages.popleft()
        raise RuntimeError("fake stream ended")

    async def unsubscribe(self, *channels):
        return None

    async def aclose(self):
        self.closed = True


class FakeAsyncRedis:
    def __init__(self, pubsub, *, heartbeat=(json.dumps({"available": True}),)) -> None:
        self._pubsub = pubsub
        self._heartbeat = deque(heartbeat)
        self.closed = False

    def pubsub(self):
        return self._pubsub

    async def get(self, key):
        assert key == "live:heartbeat"
        if len(self._heartbeat) > 1:
            return self._heartbeat.popleft()
        return self._heartbeat[0]

    async def aclose(self):
        self.closed = True
