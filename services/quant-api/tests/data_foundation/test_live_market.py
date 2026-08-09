from __future__ import annotations

import importlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fnmatch import fnmatch
from typing import Any

from app.market_data.domain import CanonicalBar


class FakeRedis:
    """Small in-memory Redis boundary fake; no configured Redis is ever touched."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.zsets: dict[str, dict[str, int]] = {}
        self.ttls: dict[str, int] = {}
        self.published: list[tuple[str, str]] = []

    def zadd(self, key: str, mapping: dict[str, int]) -> int:
        self.zsets.setdefault(key, {}).update(mapping)
        return len(mapping)

    def zremrangebyscore(self, key: str, minimum: int, maximum: int) -> int:
        values = self.zsets.get(key, {})
        members = [member for member, score in values.items() if minimum <= score <= maximum]
        for member in members:
            del values[member]
        return len(members)

    def zrangebyscore(self, key: str, minimum: str | int, maximum: str | int) -> list[str]:
        lower_exclusive = isinstance(minimum, str) and minimum.startswith("(")
        lower = float("-inf") if minimum == "-inf" else int(str(minimum).lstrip("("))
        upper = float("inf") if maximum == "+inf" else int(maximum)
        return [
            member
            for member, score in sorted(self.zsets.get(key, {}).items(), key=lambda item: (item[1], item[0]))
            if (score > lower if lower_exclusive else score >= lower) and score <= upper
        ]

    def set(self, key: str, value: str) -> bool:
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return True

    def scan_iter(self, match: str) -> list[str]:
        return [key for key in (*self.values, *self.zsets) if fnmatch(key, match)]

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            existed = key in self.values or key in self.zsets
            self.values.pop(key, None)
            self.zsets.pop(key, None)
            self.ttls.pop(key, None)
            deleted += int(existed)
        return deleted

    def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


def _bar(minute: int, *, price: str = "100.1250") -> CanonicalBar:
    return CanonicalBar(
        bar_end=datetime(2025, 1, 2, 1, minute, tzinfo=UTC),
        trading_day=date(2025, 1, 2),
        open=Decimal(price),
        high=Decimal("101.0000"),
        low=Decimal("99.0000"),
        close=Decimal("100.7500"),
        volume=Decimal("12.500"),
        turnover=Decimal("1253.125000"),
        open_interest=Decimal("70.000"),
    )


def _store(fake: FakeRedis) -> Any:
    module = importlib.import_module("app.market_data.live_market")
    return module.RedisLiveStore(fake)


def test_live_bars_are_score_ordered_after_exclusive_and_decimal_lossless() -> None:
    """Catches score rounding, inclusive cursors, and JSON number coercion."""
    fake = FakeRedis()
    store = _store(fake)
    day = date(2025, 1, 2)
    later, earlier = _bar(2), _bar(1)

    store.put_bar(day, "RB", "1m", later)
    store.put_bar(day, "RB", "1m", earlier)

    assert store.bars_after(day, "RB", "1m", None) == (earlier, later)
    assert store.bars_after(day, "RB", "1m", earlier.bar_end) == (later,)
    assert store.bars_between(day, "RB", "1m", earlier.bar_end, later.bar_end) == (earlier, later)
    assert fake.ttls["live:bars:2025-01-02:RB:1m"] == timedelta(days=3).total_seconds()
    member = next(
        member
        for member in fake.zsets["live:bars:2025-01-02:RB:1m"]
        if json.loads(member)["bar_end"] == "2025-01-02T01:01:00+00:00"
    )
    assert fake.zsets["live:bars:2025-01-02:RB:1m"][member] == 1735779660000
    payload = json.loads(member)
    assert payload["open"] == "100.1250"
    assert payload["volume"] == "12.500"


def test_subscriptions_are_trading_day_isolated_and_expire() -> None:
    """Catches subscription state leaking across trading days or losing its TTL."""
    fake = FakeRedis()
    store = _store(fake)
    first_day = date(2025, 1, 2)
    next_day = date(2025, 1, 3)
    mapping = {"RB": ["1m", "5m"]}

    store.set_subscriptions(first_day, mapping)

    assert store.subscriptions(first_day) == mapping
    assert store.subscriptions(next_day) is None
    assert fake.ttls["live:subscription:2025-01-02"] == timedelta(days=3).total_seconds()


def test_cleanup_removes_only_requested_trading_day() -> None:
    """Catches cleanup deleting another day's transient observation state."""
    fake = FakeRedis()
    store = _store(fake)
    first_day = date(2025, 1, 2)
    next_day = date(2025, 1, 3)
    store.put_bar(first_day, "RB", "1m", _bar(1))
    store.set_subscriptions(first_day, {"RB": ["1m"]})
    store.put_bar(next_day, "RB", "1m", _bar(1))
    store.set_subscriptions(next_day, {"RB": ["1m"]})

    store.cleanup_trading_day(first_day)

    assert store.bars_after(first_day, "RB", "1m", _bar(1).bar_end) == ()
    assert store.subscriptions(first_day) is None
    assert store.bars_after(next_day, "RB", "1m", _bar(1).bar_end - timedelta(minutes=1)) == (_bar(1),)
    assert store.subscriptions(next_day) == {"RB": ["1m"]}


def test_public_pubsub_channel_contract_and_compact_payloads() -> None:
    """Catches publish methods drifting from the public WebSocket channel contract."""
    fake = FakeRedis()
    module = importlib.import_module("app.market_data.live_market")
    store = _store(fake)
    bar = _bar(1)

    store.set_heartbeat({"state": "healthy"})
    store.publish_bar("RB", "1m", bar)
    store.publish_state({"state": "healthy"})

    assert module.live_bar_channel("RB", "1m") == "live:bar:RB:1m"
    assert module.LIVE_STATE_CHANNEL == "live:state"
    assert store.heartbeat() == {"state": "healthy"}
    assert fake.published == [
        (
            "live:bar:RB:1m",
            '{"bar_end":"2025-01-02T01:01:00+00:00","trading_day":"2025-01-02","open":"100.1250","high":"101.0000","low":"99.0000","close":"100.7500","volume":"12.500","turnover":"1253.125000","open_interest":"70.000"}',
        ),
        ("live:state", '{"state":"healthy"}'),
    ]
