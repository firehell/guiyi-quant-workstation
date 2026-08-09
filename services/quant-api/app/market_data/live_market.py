"""Live 当日观察的短暂 Redis 存储；不参与 historical Canonical 发布。"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping, Protocol

from app.market_data.aggregation import SessionWindow, aggregate_from_1m, bucket_window_for_bar
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.market_phase import MarketPhase, ProductMarketPhase


_LIVE_TTL_SECONDS = 3 * 24 * 60 * 60
_HEARTBEAT_TTL_SECONDS = 30
_FINALIZATION_DELAY = timedelta(seconds=2)
_PROVIDER_RETRY_DELAY = timedelta(seconds=10)
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
        self._redis.expire("live:heartbeat", _HEARTBEAT_TTL_SECONDS)

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


class LiveProvider(Protocol):
    """最小 provider 边界；service 不持有 RQData 全局客户端。"""

    def subscribe(self, channels: tuple[str, ...]) -> None: ...

    def unsubscribe(self, channels: tuple[str, ...]) -> None: ...

    def poll(self) -> Iterable[tuple[str, CanonicalBar]]: ...


class DominantSource(Protocol):
    def dominant_for_day(self, symbol: str, trading_day: date) -> str: ...


class PhaseResolver(Protocol):
    def resolve(self, symbol: str, now: datetime) -> ProductMarketPhase: ...


class _ProviderUnavailable(RuntimeError):
    """将 provider 建连/订阅错误与 Redis 写入错误分开处理。"""


class LiveMarketService:
    """当日 rank1 合约观察服务，仅使用瞬态 Redis 与已知 Session facts。

    本类不写 Catalog/MainContractMap/Parquet，也不会在 Redis 失败时读取本地文件。
    """

    def __init__(
        self,
        *,
        provider_factory: Callable[[], LiveProvider],
        dominant_source: DominantSource,
        phase_resolver: PhaseResolver,
        store: RedisLiveStore,
        operational_products: tuple[str, ...],
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider_factory = provider_factory
        self._dominant_source = dominant_source
        self._phase_resolver = phase_resolver
        self._store = store
        self._products = tuple(item.strip().lower() for item in operational_products)
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self._provider: LiveProvider | None = None
        self._trading_day: date | None = None
        self._contracts: dict[str, str] = {}
        self._channels: set[str] = set()
        self._pending: dict[tuple[str, datetime], tuple[CanonicalBar, SessionWindow]] = {}
        self._finalized: set[tuple[str, datetime]] = set()
        self._last_bar_at: datetime | None = None
        self._available = True
        self.next_provider_retry_at: datetime | None = None
        self.rejections: list[str] = []

    def reconcile(self, now: datetime) -> str | None:
        """按当前交易日一次性解析 rank1，并与 provider 订阅作差量同步。"""
        phases = self._phases(now)
        trading_days = {
            phase.trading_day
            for phase in phases.values()
            if phase.phase is MarketPhase.TRADING and phase.trading_day is not None
        }
        if not trading_days:
            self.next_provider_retry_at = None
            self._publish_heartbeat(now, phases)
            return None
        if len(trading_days) != 1:
            return "LIVE_TRADING_DAY_INCONSISTENT"
        trading_day = next(iter(trading_days))
        assert trading_day is not None
        if trading_day != self._trading_day:
            snapshot = {
                symbol: self._dominant_source.dominant_for_day(symbol, trading_day)
                for symbol in self._products
            }
            self._store.set_subscriptions(trading_day, snapshot)
            self._trading_day = trading_day
            self._contracts = {symbol: str(contract).upper() for symbol, contract in snapshot.items()}
        desired = {f"bar_{contract}" for contract in self._contracts.values()}
        try:
            provider = self._provider_or_create()
        except Exception as exc:  # noqa: BLE001 - provider boundary is intentionally minimal
            raise _ProviderUnavailable() from exc
        removed = tuple(sorted(self._channels - desired))
        added = tuple(sorted(desired - self._channels))
        try:
            if removed:
                provider.unsubscribe(removed)
            if added:
                provider.subscribe(added)
        except Exception as exc:  # noqa: BLE001 - see _ProviderUnavailable
            raise _ProviderUnavailable() from exc
        self._channels = desired
        self._publish_heartbeat(now, phases)
        return None

    def ingest(self, contract: str, bar: CanonicalBar, *, now: datetime) -> str | None:
        """保留最新未完成 payload；完成后不允许覆盖。"""
        symbol = next(
            (item for item, current in self._contracts.items() if current == contract.strip().upper()),
            None,
        )
        if symbol is None:
            return self._reject("LIVE_CONTRACT_NOT_SUBSCRIBED")
        phase = self._phase_resolver.resolve(symbol, now)
        if phase.trading_day != bar.trading_day or phase.current_session is None:
            return self._reject("LIVE_BAR_OUTSIDE_SESSION")
        window = phase.current_session
        elapsed = (bar.bar_end - window.start).total_seconds()
        if (
            not window.start < bar.bar_end <= window.end
            or bar.bar_end.second != 0
            or bar.bar_end.microsecond != 0
            or elapsed % 60 != 0
        ):
            return self._reject("LIVE_BAR_OUTSIDE_SESSION")
        key = (symbol, bar.bar_end)
        if key in self._finalized:
            return self._reject("LIVE_BAR_FINALIZED")
        self._pending[key] = (bar, window)
        return None

    def flush_due(self, now: datetime) -> tuple[CanonicalBar, ...]:
        """仅在 bar_end 两秒后发布一次 completed 1m，并增量生成派生频率。"""
        finalized: list[CanonicalBar] = []
        for key, (bar, window) in tuple(self._pending.items()):
            if now < bar.bar_end + _FINALIZATION_DELAY:
                continue
            symbol, _ = key
            self._pending.pop(key)
            self._finalized.add(key)
            try:
                self._store.put_bar(bar.trading_day, symbol, BarFrequency.M1, bar)
                self._store.publish_bar(symbol, BarFrequency.M1, bar)
                self._derive(symbol, bar, window)
            except Exception:  # noqa: BLE001 - Redis is an explicit unavailable boundary
                self._available = False
                self._reject("LIVE_REDIS_UNAVAILABLE")
                continue
            self._available = True
            self._last_bar_at = bar.bar_end
            finalized.append(bar)
        return tuple(finalized)

    def poll(self, now: datetime) -> str | None:
        """执行单个前台 poll cycle；TRADING provider 故障固定十秒重试。"""
        phases = self._phases(now)
        try:
            result = self.reconcile(now)
        except _ProviderUnavailable:
            return self._schedule_provider_retry(now, phases)
        except Exception:  # noqa: BLE001 - Redis is a fail-closed Live boundary
            self._available = False
            return self._reject("LIVE_REDIS_UNAVAILABLE")
        self.flush_due(now)
        if result is not None:
            return result
        if not any(item.phase is MarketPhase.TRADING for item in phases.values()):
            # BREAK/CLOSED 不把无新 bar 当成断线，也不创建/消费 provider。
            self.next_provider_retry_at = None
            return None
        if not self._channels:
            return None
        if self.next_provider_retry_at is not None and now < self.next_provider_retry_at:
            return None
        try:
            provider = self._provider_or_create()
            for contract, bar in provider.poll():
                self.ingest(contract, bar, now=now)
            self.flush_due(now)
        except Exception:  # noqa: BLE001 - provider exception is normalized at boundary
            return self._schedule_provider_retry(now, phases)
        return None

    def run_forever(self) -> None:
        """前台循环；由 CLI/launchd 管理进程，不在 Python 内 daemonize。"""
        if self._sleep is None:
            from time import sleep

            self._sleep = sleep
        while True:
            self.poll(self._clock())
            self._sleep(1)

    def _derive(self, symbol: str, bar: CanonicalBar, session: SessionWindow) -> None:
        for frequency in (BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1):
            bucket = bucket_window_for_bar(session, frequency, bar.bar_end)
            if bar.bar_end != bucket.end:
                continue
            source = tuple(
                item
                for item in self._store.bars_between(
                    bar.trading_day, symbol, BarFrequency.M1, bucket.start, bucket.end
                )
                if bucket.start < item.bar_end <= bucket.end
            )
            expected_ends = tuple(
                bucket.start + timedelta(minutes=minute)
                for minute in range(1, int((bucket.end - bucket.start).total_seconds() // 60) + 1)
            )
            if tuple(item.bar_end for item in source) != expected_ends:
                continue
            derived = aggregate_from_1m(
                source, target_frequency=frequency, sessions=(bucket,)
            )[0]
            self._store.put_bar(bar.trading_day, symbol, frequency, derived)
            self._store.publish_bar(symbol, frequency, derived)

    def _phases(self, now: datetime) -> dict[str, ProductMarketPhase]:
        return {symbol: self._phase_resolver.resolve(symbol, now) for symbol in self._products}

    def _provider_or_create(self) -> LiveProvider:
        if self._provider is None:
            self._provider = self._provider_factory()
        return self._provider

    def _schedule_provider_retry(
        self,
        now: datetime,
        phases: Mapping[str, ProductMarketPhase],
    ) -> str | None:
        if any(item.phase is MarketPhase.TRADING for item in phases.values()):
            self._provider = None
            # 新 client 没有旧订阅；下一次 reconcile 会重建完整订阅集。
            self._channels = set()
            self.next_provider_retry_at = now + _PROVIDER_RETRY_DELAY
            return "LIVE_PROVIDER_RETRY_SCHEDULED"
        self.next_provider_retry_at = None
        return None

    def _publish_heartbeat(self, now: datetime, phases: Mapping[str, ProductMarketPhase]) -> None:
        counts = Counter(phase.phase.value for phase in phases.values())
        self._store.set_heartbeat(
            {
                "generated_at": now.astimezone(UTC).isoformat(),
                "operational_count": len(self._products),
                "subscribed_count": len(self._channels),
                "last_bar_at": None if self._last_bar_at is None else self._last_bar_at.isoformat(),
                "phase_counts": dict(sorted(counts.items())),
                "available": self._available,
            }
        )

    def _reject(self, code: str) -> str:
        self.rejections.append(code)
        return code
