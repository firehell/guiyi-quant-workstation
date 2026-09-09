from __future__ import annotations

import asyncio
import json
from collections import deque
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.api.market_live import market_websocket
from app.market_data.live_market import LiveMarketService, RedisLiveStore
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.main import app
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketDisplaySnapshot, MarketReadState


def _bar(minute: int) -> CanonicalBar:
    return CanonicalBar(
        bar_end=datetime(2025, 1, 2, 1, minute, tzinfo=UTC),
        trading_day=date(2025, 1, 2),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        open_interest=Decimal("20"),
    )


def _state(*, contract: str = "J2505", trading_day: date = date(2025, 1, 2)) -> MarketReadState:
    return MarketReadState(
        symbol="j",
        series_kind="actual_dominant",
        frequency="1m",
        operational=True,
        phase="TRADING",
        trading_day=trading_day,
        live_eligible=True,
        live_available=True,
        live_contract=contract,
        canonical_end=_bar(1).bar_end,
        after_market={},
    )


def _payload(bar: CanonicalBar) -> str:
    return json.dumps(
        {
            "bar_end": bar.bar_end.isoformat(),
            "trading_day": bar.trading_day.isoformat(),
            "open": str(bar.open),
            "high": str(bar.high),
            "low": str(bar.low),
            "close": str(bar.close),
            "volume": str(bar.volume),
            "turnover": str(bar.turnover),
            "open_interest": str(bar.open_interest),
        }
    )


class FakeReadService:
    def __init__(self) -> None:
        self.subscribed = False
        self.snapshot_after: datetime | None = None
        self._states = deque((_state(), _state(contract="J2509", trading_day=date(2025, 1, 3))))
        self.race_bar = _bar(2)

    def state(self, identity: object, now: datetime) -> MarketReadState:
        assert self.subscribed is True
        return self._states[0] if len(self._states) == 1 else self._states.popleft()

    def live_snapshot(self, identity: object, after: datetime | None, now: datetime) -> tuple[CanonicalBar, ...]:
        assert self.subscribed is True
        self.snapshot_after = after
        return (self.race_bar,)

    def display_snapshot(
        self,
        identity: object,
        after: datetime | None,
        now: datetime,
    ) -> MarketDisplaySnapshot:
        assert self.subscribed is True
        state = self.state(identity, now)
        assert state.canonical_end is not None
        self.snapshot_after = state.canonical_end if after is None else max(after, state.canonical_end)
        return MarketDisplaySnapshot(
            state=state,
            source="realtime",
            trading_day=state.trading_day,
            contract=state.live_contract,
            bars=(self.race_bar,),
        )


class FakePubSub:
    def __init__(self, read_service: FakeReadService) -> None:
        self._read_service = read_service
        self.channels: tuple[str, ...] = ()
        self.messages: deque[dict[str, Any]] = deque()
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        self.channels = channels
        self._read_service.subscribed = True
        self.messages.extend(
            (
                {"type": "message", "channel": channels[0], "data": _payload(self._read_service.race_bar)},
                {"type": "message", "channel": channels[0], "data": _payload(_bar(3))},
                {"type": "message", "channel": "market:state", "data": '{"state":"changed"}'},
            )
        )

    async def get_message(self, *, ignore_subscribe_messages: bool, timeout: float) -> dict[str, Any] | None:
        return self.messages.popleft() if self.messages else None

    async def unsubscribe(self, *channels: str) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


class FakeAsyncRedis:
    def __init__(self, pubsub: FakePubSub) -> None:
        self._pubsub = pubsub
        self.closed = False

    def pubsub(self) -> FakePubSub:
        return self._pubsub

    async def aclose(self) -> None:
        self.closed = True


def _mock_read_scope(monkeypatch, service, session=None):
    @contextmanager
    def scope():
        owned = session or TrackingSession()
        try:
            yield service
        finally:
            owned.close()
    monkeypatch.setattr("app.api.market_live.open_market_read_service", scope)


def test_market_websocket_subscribes_before_snapshot_dedupes_race_and_resets(monkeypatch) -> None:
    """Catches a REST-to-WS gap, duplicate race bar, or missing rank1/trading-day reset."""
    read_service = FakeReadService()
    pubsub = FakePubSub(read_service)
    redis = FakeAsyncRedis(pubsub)
    _mock_read_scope(monkeypatch, read_service)
    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", lambda: redis)

    with TestClient(app).websocket_connect(
        "/api/v1/market/ws?series_kind=actual_dominant&symbol=j&frequency=1m"
    ) as websocket:
        messages = [websocket.receive_json() for _ in range(5)]

    assert [message["type"] for message in messages] == ["state", "snapshot", "bar", "reset", "state"]
    assert pubsub.channels == ("live:bar:j:1m", "market:state")
    assert read_service.snapshot_after == _bar(1).bar_end
    assert messages[1]["source"] == "realtime"
    assert messages[1]["trading_day"] == "2025-01-02"
    assert messages[1]["contract"] == "J2505"
    assert [bar["bar_end"] for bar in messages[1]["bars"]] == ["2025-01-02T01:02:00Z"]
    assert messages[2]["bar"]["bar_end"] == "2025-01-02T01:03:00Z"
    assert messages[3] == {"type": "reset", "trading_day": "2025-01-03", "contract": "J2509"}


class StaticReadService:
    def __init__(self, state: MarketReadState) -> None:
        self._state = state

    def state(self, identity: object, now: datetime) -> MarketReadState:
        return self._state

    def live_snapshot(self, identity: object, after: datetime | None, now: datetime) -> tuple[CanonicalBar, ...]:
        return ()

    def display_snapshot(
        self,
        identity: object,
        after: datetime | None,
        now: datetime,
    ) -> MarketDisplaySnapshot:
        return MarketDisplaySnapshot(
            state=self._state,
            source="none",
            trading_day=None,
            contract=None,
            bars=(),
        )


class ClosingPubSub:
    def __init__(self) -> None:
        self.channels: tuple[str, ...] = ()
        self.messages: deque[dict[str, Any]] = deque()
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        self.channels = channels
        self.messages.append({"type": "message", "channel": channels[0], "data": _payload(_bar(2))})

    async def get_message(self, *, ignore_subscribe_messages: bool, timeout: float) -> dict[str, Any] | None:
        if self.messages:
            return self.messages.popleft()
        raise RuntimeError("fake pubsub complete")

    async def unsubscribe(self, *channels: str) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("query", "state"),
    (
        (
            "series_kind=continuous&symbol=j&frequency=1m",
            MarketReadState("j", "continuous", "1m", True, "TRADING", date(2025, 1, 2), False, False, "J2505", _bar(1).bar_end, {}),
        ),
        (
            "series_kind=contract&symbol=j&contract=J2509&frequency=1m",
            MarketReadState("j", "contract", "1m", True, "TRADING", date(2025, 1, 2), False, False, "J2505", _bar(1).bar_end, {}),
        ),
        (
            "series_kind=actual_dominant&symbol=j&frequency=1d",
            MarketReadState("j", "actual_dominant", "1d", True, "TRADING", date(2025, 1, 2), False, False, "J2505", _bar(1).bar_end, {}),
        ),
        (
            "series_kind=actual_dominant&symbol=j&frequency=1w",
            MarketReadState("j", "actual_dominant", "1w", True, "TRADING", date(2025, 1, 2), False, False, "J2505", _bar(1).bar_end, {}),
        ),
        (
            "series_kind=actual_dominant&symbol=j&frequency=1m",
            MarketReadState("j", "actual_dominant", "1m", True, "TRADING", date(2025, 1, 2), True, False, "J2505", _bar(1).bar_end, {}),
        ),
    ),
)
def test_market_websocket_never_forwards_bars_when_live_state_disallows_overlay(
    monkeypatch,
    query: str,
    state: MarketReadState,
) -> None:
    """Catches Pub/Sub bypassing the MarketReadService live eligibility and availability gate."""
    pubsub = ClosingPubSub()
    redis = FakeAsyncRedis(pubsub)  # type: ignore[arg-type]
    _mock_read_scope(monkeypatch, StaticReadService(state))
    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", lambda: redis)

    with TestClient(app).websocket_connect(f"/api/v1/market/ws?{query}") as websocket:
        assert websocket.receive_json()["type"] == "state"
        assert websocket.receive_json() == {
            "type": "snapshot",
            "source": "none",
            "trading_day": None,
            "contract": None,
            "bars": [],
        }
        with pytest.raises(WebSocketDisconnect) as disconnected:
            websocket.receive_json()

    assert disconnected.value.code == 1013
    assert pubsub.closed is True


class IdlePubSub(ClosingPubSub):
    async def get_message(self, *, ignore_subscribe_messages: bool, timeout: float) -> dict[str, Any] | None:
        return None


class DisconnectingWebSocket:
    def __init__(self) -> None:
        self.query_params = {
            "series_kind": "actual_dominant",
            "symbol": "j",
            "frequency": "1m",
        }
        self.client_state = SimpleNamespace(name="CONNECTED")
        self.sent: list[dict[str, object]] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    async def receive(self) -> dict[str, str]:
        return {"type": "websocket.disconnect"}

    async def close(self, *, code: int, reason: str) -> None:
        self.client_state.name = "DISCONNECTED"


class TrackingSession:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


@pytest.mark.asyncio
async def test_idle_websocket_detects_client_disconnect_and_closes_pubsub(monkeypatch) -> None:
    """Catches idle WebSockets retaining Redis or a database pool connection."""
    pubsub = IdlePubSub()
    redis = FakeAsyncRedis(pubsub)  # type: ignore[arg-type]
    websocket = DisconnectingWebSocket()
    session = TrackingSession()
    _mock_read_scope(monkeypatch, StaticReadService(_state()), session)
    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", lambda: redis)

    await asyncio.wait_for(market_websocket(websocket), timeout=0.05)  # type: ignore[arg-type]

    assert pubsub.closed is True
    assert redis.closed is True
    assert session.close_count == 1


class BridgeRedis:
    """同步 Live store 与 async Pub/Sub fake 共享的内存 Redis 边界。"""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []

    def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def expire(self, key: str, seconds: int) -> bool:
        return True

    def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1

    def zadd(self, key: str, mapping: dict[str, int]) -> int:
        return 0

    def zremrangebyscore(self, key: str, minimum: int, maximum: int) -> int:
        return 0

    def zrangebyscore(self, key: str, minimum: str | int, maximum: str | int) -> list[str]:
        return []

    def scan_iter(self, match: str) -> list[str]:
        return []

    def delete(self, *keys: str) -> int:
        return 0


class ProducerPhases:
    def __init__(self) -> None:
        self.day = date(2025, 1, 3)

    def resolve(self, symbol: str, now: datetime) -> ProductMarketPhase:
        return ProductMarketPhase(symbol, MarketPhase.TRADING, self.day, None, None)


class ProducerDominants:
    def dominant_for_day(self, symbol: str, trading_day: date) -> str:
        assert (symbol, trading_day) == ("j", date(2025, 1, 3))
        return "J2509"


class ProducerProvider:
    def subscribe(self, channels: tuple[str, ...]) -> None:
        return None

    def unsubscribe(self, channels: tuple[str, ...]) -> None:
        return None

    def poll(self) -> tuple[tuple[str, CanonicalBar], ...]:
        return ()

    def poll_buffered(self) -> tuple[tuple[str, CanonicalBar], ...]:
        return ()


class ProducerStatePubSub:
    def __init__(self, producer: LiveMarketService, redis: BridgeRedis) -> None:
        self._producer = producer
        self._redis = redis
        self._published_index = 0
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        self._producer.reconcile(datetime(2025, 1, 3, 1, 1, tzinfo=UTC))

    async def get_message(self, *, ignore_subscribe_messages: bool, timeout: float) -> dict[str, Any] | None:
        if self._published_index >= len(self._redis.published):
            return None
        channel, data = self._redis.published[self._published_index]
        self._published_index += 1
        return {"type": "message", "channel": channel, "data": data}

    async def unsubscribe(self, *channels: str) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


def test_rank1_subscription_change_publishes_state_that_resets_websocket(monkeypatch) -> None:
    """Catches a Live rank1 change being persisted in Redis but never reaching WebSocket consumers."""
    bridge = BridgeRedis()
    producer = LiveMarketService(
        provider_factory=ProducerProvider,
        dominant_source=ProducerDominants(),
        phase_resolver=ProducerPhases(),
        store=RedisLiveStore(bridge),
        operational_products=("j",),
    )
    pubsub = ProducerStatePubSub(producer, bridge)
    redis = FakeAsyncRedis(pubsub)  # type: ignore[arg-type]
    read_service = FakeReadService()
    read_service.race_bar = _bar(1)
    read_service.subscribed = True
    _mock_read_scope(monkeypatch, read_service)
    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", lambda: redis)

    with TestClient(app).websocket_connect(
        "/api/v1/market/ws?series_kind=actual_dominant&symbol=j&frequency=1m"
    ) as websocket:
        messages = [websocket.receive_json() for _ in range(4)]

    assert [message["type"] for message in messages] == ["state", "snapshot", "reset", "state"]
    assert bridge.values["live:subscription:2025-01-03"] == '{"j":"J2509"}'
    assert bridge.published == [("market:state", '{"trading_day":"2025-01-03"}')]
    assert messages[2] == {"type": "reset", "trading_day": "2025-01-03", "contract": "J2509"}


@pytest.mark.asyncio
async def test_slow_snapshot_does_not_block_event_loop(monkeypatch):
    from threading import Event, Thread, get_ident
    from contextlib import contextmanager
    from app.api import market_live

    started, release = Event(), Event()
    loop_thread = get_ident()
    phases = []

    class SlowService(StaticReadService):
        def display_snapshot(self, *args):
            phases.append(("read", get_ident()))
            started.set()
            assert release.wait(2)
            return super().display_snapshot(*args)

    service = SlowService(_state())
    @contextmanager
    def scope():
        phases.append(("open", get_ident()))
        try:
            yield service
        finally:
            phases.append(("close", get_ident()))

    # A watchdog prevents an old synchronous implementation from hanging pytest.
    watchdog = Thread(target=lambda: (started.wait(2), release.wait(0.5), release.set()), daemon=True)
    watchdog.start()
    monkeypatch.setattr(market_live, "open_market_read_service", scope, raising=False)
    monkeypatch.setattr(market_live, "build_market_read_service", lambda _: service)
    monkeypatch.setattr(market_live, "get_async_redis_connection", lambda: FakeAsyncRedis(IdlePubSub()))
    websocket = DisconnectingWebSocket()
    task = asyncio.create_task(market_websocket(websocket))
    try:
        while not started.is_set():
            await asyncio.sleep(0)
        assert not release.is_set(), "synchronous snapshot blocked the event loop until watchdog fired"
    finally:
        release.set()
        await task
        watchdog.join(1)
    assert [name for name, _ in phases] == ["open", "read", "close"]
    assert len({thread for _, thread in phases}) == 1
    assert phases[0][1] != loop_thread


@pytest.mark.asyncio
async def test_cancelled_read_keeps_capacity_until_worker_releases_resources(monkeypatch):
    from threading import BoundedSemaphore, Event
    from app.api import market_live

    slots = BoundedSemaphore(1)
    entered, release, closed = Event(), Event(), Event()
    @contextmanager
    def scope():
        try:
            yield object()
        finally:
            closed.set()
    def slow(_service):
        entered.set()
        assert release.wait(2)
    monkeypatch.setattr(market_live, "_READ_SLOTS", slots)
    monkeypatch.setattr(market_live, "open_market_read_service", scope)
    task = asyncio.create_task(market_live._read_in_worker(slow))
    try:
        while not entered.is_set():
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(RuntimeError, match="MARKET_READ_BUSY"):
            await market_live._read_in_worker(lambda _: None)
        assert not closed.is_set()
    finally:
        release.set()
        while not closed.is_set():
            await asyncio.sleep(0)
        # The future releases admission after the resource scope has exited.
        while not slots.acquire(blocking=False):
            await asyncio.sleep(0)
        slots.release()
    assert await market_live._read_in_worker(lambda _: 42) == 42


@pytest.mark.asyncio
async def test_worker_owns_session_and_sync_redis_on_success_and_error(monkeypatch):
    from threading import get_ident
    from app.api import market_live
    from app.market_data import composition

    loop_thread = get_ident()
    resources = []
    class Resource:
        def __init__(self):
            self.created = get_ident()
            self.closed = None
            resources.append(self)
        def __enter__(self):
            assert get_ident() == self.created
            return self
        def __exit__(self, *args):
            self.close()
        def close(self):
            self.closed = get_ident()
    def build(session, *, redis):
        assert session.created == redis.created == get_ident()
        assert session.closed is None and redis.closed is None
        return session
    monkeypatch.setattr(composition, "SessionLocal", Resource)
    monkeypatch.setattr(composition, "get_redis_connection", Resource)
    monkeypatch.setattr(composition, "build_market_read_service", build)
    assert await market_live._read_in_worker(lambda service: service.created) != loop_thread
    def fail(service):
        raise ValueError("isolated failure")
    with pytest.raises(ValueError, match="isolated failure"):
        await market_live._read_in_worker(fail)
    assert len(resources) == 4
    assert all(item.created == item.closed != loop_thread for item in resources)


@pytest.mark.asyncio
async def test_pubsub_cleanup_failure_still_closes_all_clients(monkeypatch):
    class FailingUnsubscribe(IdlePubSub):
        async def unsubscribe(self, *channels):
            raise RuntimeError("unsubscribe failed")
    pubsub = FailingUnsubscribe()
    redis = FakeAsyncRedis(pubsub)
    _mock_read_scope(monkeypatch, StaticReadService(_state()))
    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", lambda: redis)
    with pytest.raises(RuntimeError, match="unsubscribe failed"):
        await market_websocket(DisconnectingWebSocket())
    assert pubsub.closed and redis.closed
