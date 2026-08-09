from __future__ import annotations

import json
from collections import deque
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import CanonicalBar
from app.market_data.market_read import MarketReadState


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
        return self._states[0] if len(self._states) == 1 else self._states.popleft()

    def live_snapshot(self, identity: object, after: datetime | None, now: datetime) -> tuple[CanonicalBar, ...]:
        assert self.subscribed is True
        self.snapshot_after = after
        return (self.race_bar,)


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


def test_market_websocket_subscribes_before_snapshot_dedupes_race_and_resets(monkeypatch) -> None:
    """Catches a REST-to-WS gap, duplicate race bar, or missing rank1/trading-day reset."""
    read_service = FakeReadService()
    pubsub = FakePubSub(read_service)
    redis = FakeAsyncRedis(pubsub)
    monkeypatch.setattr("app.api.market_live.build_market_read_service", lambda _session: read_service)
    monkeypatch.setattr("app.api.market_live.get_async_redis_connection", lambda: redis)

    with TestClient(app).websocket_connect(
        "/api/v1/market/ws?series_kind=actual_dominant&symbol=j&frequency=1m"
    ) as websocket:
        messages = [websocket.receive_json() for _ in range(5)]

    assert [message["type"] for message in messages] == ["state", "snapshot", "bar", "reset", "state"]
    assert pubsub.channels == ("live:bar:j:1m", "market:state")
    assert read_service.snapshot_after == _bar(1).bar_end
    assert [bar["bar_end"] for bar in messages[1]["bars"]] == ["2025-01-02T01:02:00Z"]
    assert messages[2]["bar"]["bar_end"] == "2025-01-02T01:03:00Z"
    assert messages[3] == {"type": "reset", "trading_day": "2025-01-03", "contract": "J2509"}
