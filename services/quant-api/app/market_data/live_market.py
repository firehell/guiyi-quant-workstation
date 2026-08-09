"""Live 当日观察的短暂 Redis 存储；不参与 historical Canonical 发布。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Mapping, Protocol

from app.market_data.domain import BarFrequency, CanonicalBar


_LIVE_TTL_SECONDS = 3 * 24 * 60 * 60
LIVE_BAR_CHANNEL_PREFIX = "live:bar"
LIVE_STATE_CHANNEL = "market:state"


class RedisClient(Protocol):
    def zadd(self, key: str, mapping: Mapping[str, int]) -> int: ...

    def zremrangebyscore(self, key: str, minimum: int, maximum: int) -> int: ...

    def zrangebyscore(self, key: str, minimum: str | int, maximum: str | int) -> list[str | bytes]: ...

    def set(self, key: str, value: str) -> bool: ...

    def get(self, key: str) -> str | bytes | None: ...

    def expire(self, key: str, seconds: int) -> bool: ...

    def scan_iter(self, match: str) -> Any: ...

    def delete(self, *keys: str) -> int: ...

    def publish(self, channel: str, message: str) -> int: ...


class RedisLiveStore:
    """Redis-backed, trading-day-scoped live observation store."""

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    def put_bar(
        self,
        trading_day: date,
        symbol: str,
        frequency: BarFrequency | str,
        bar: CanonicalBar,
    ) -> None:
        key = self._bars_key(trading_day, symbol, frequency)
        score = _epoch_millis(bar.bar_end)
        self._redis.zremrangebyscore(key, score, score)
        self._redis.zadd(key, {_compact_json(_bar_payload(bar)): score})
        self._redis.expire(key, _LIVE_TTL_SECONDS)

    def bars_after(
        self,
        trading_day: date,
        symbol: str,
        frequency: BarFrequency | str,
        after: datetime | None,
    ) -> tuple[CanonicalBar, ...]:
        minimum: str | int = "-inf" if after is None else f"({_epoch_millis(after)}"
        return self._read_bars(self._bars_key(trading_day, symbol, frequency), minimum, "+inf")

    def bars_between(
        self,
        trading_day: date,
        symbol: str,
        frequency: BarFrequency | str,
        start: datetime,
        end: datetime,
    ) -> tuple[CanonicalBar, ...]:
        return self._read_bars(
            self._bars_key(trading_day, symbol, frequency),
            _epoch_millis(start),
            _epoch_millis(end),
        )

    def set_subscriptions(self, trading_day: date, mapping: Mapping[str, Any]) -> None:
        key = self._subscription_key(trading_day)
        self._redis.set(key, _compact_json(dict(mapping)))
        self._redis.expire(key, _LIVE_TTL_SECONDS)

    def subscriptions(self, trading_day: date) -> dict[str, Any] | None:
        raw = self._redis.get(self._subscription_key(trading_day))
        return None if raw is None else _decode_mapping(raw)

    def set_heartbeat(self, payload: Mapping[str, Any]) -> None:
        self._redis.set("live:heartbeat", _compact_json(dict(payload)))

    def heartbeat(self) -> dict[str, Any] | None:
        raw = self._redis.get("live:heartbeat")
        return None if raw is None else _decode_mapping(raw)

    def cleanup_trading_day(self, trading_day: date) -> None:
        keys = [_as_text(key) for key in self._redis.scan_iter(match=f"live:bars:{trading_day.isoformat()}:*")]
        keys.append(self._subscription_key(trading_day))
        self._redis.delete(*keys)

    def publish_bar(self, symbol: str, frequency: BarFrequency | str, bar: CanonicalBar) -> None:
        self._redis.publish(live_bar_channel(symbol, frequency), _compact_json(_bar_payload(bar)))

    def publish_state(self, payload: Mapping[str, Any]) -> None:
        self._redis.publish(LIVE_STATE_CHANNEL, _compact_json(dict(payload)))

    def _read_bars(self, key: str, minimum: str | int, maximum: str | int) -> tuple[CanonicalBar, ...]:
        return tuple(_bar_from_payload(_as_text(member)) for member in self._redis.zrangebyscore(key, minimum, maximum))

    @staticmethod
    def _bars_key(trading_day: date, symbol: str, frequency: BarFrequency | str) -> str:
        return f"live:bars:{trading_day.isoformat()}:{symbol}:{BarFrequency(frequency).value}"

    @staticmethod
    def _subscription_key(trading_day: date) -> str:
        return f"live:subscription:{trading_day.isoformat()}"


def _epoch_millis(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("LIVE_TIMEZONE_REQUIRED")
    normalized = value.astimezone(UTC)
    return int(normalized.timestamp()) * 1000 + normalized.microsecond // 1000


def live_bar_channel(symbol: str, frequency: BarFrequency | str) -> str:
    """返回单一、稳定的 live bar PubSub channel 名。"""
    return f"{LIVE_BAR_CHANNEL_PREFIX}:{symbol}:{BarFrequency(frequency).value}"


def _bar_payload(bar: CanonicalBar) -> dict[str, str | None]:
    return {
        "bar_end": bar.bar_end.isoformat(),
        "trading_day": bar.trading_day.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "turnover": None if bar.turnover is None else str(bar.turnover),
        "open_interest": None if bar.open_interest is None else str(bar.open_interest),
    }


def _bar_from_payload(raw: str) -> CanonicalBar:
    payload = json.loads(raw)
    return CanonicalBar(
        bar_end=datetime.fromisoformat(payload["bar_end"]),
        trading_day=date.fromisoformat(payload["trading_day"]),
        open=Decimal(payload["open"]),
        high=Decimal(payload["high"]),
        low=Decimal(payload["low"]),
        close=Decimal(payload["close"]),
        volume=Decimal(payload["volume"]),
        turnover=None if payload["turnover"] is None else Decimal(payload["turnover"]),
        open_interest=None if payload["open_interest"] is None else Decimal(payload["open_interest"]),
    )


def _compact_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _decode_mapping(raw: str | bytes) -> dict[str, Any]:
    payload = json.loads(_as_text(raw))
    if not isinstance(payload, dict):
        raise ValueError("LIVE_MAPPING_INVALID")
    return payload


def _as_text(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value
