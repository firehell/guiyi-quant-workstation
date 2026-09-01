"""Live 当日观察的短暂 Redis 存储；不参与 historical Canonical 发布。"""

from __future__ import annotations

import json
from collections import Counter
from collections import deque
from collections.abc import Callable, Iterable, Mapping as MappingABC
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Lock
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo

from app.market_data.aggregation import SessionWindow, aggregate_from_1m, bucket_window_for_bar
from app.market_data.domain import BarFrequency, CanonicalBar, normalize_contract_for_symbol
from app.market_data.market_phase import MarketPhase, ProductMarketPhase


_LIVE_TTL_SECONDS = 3 * 24 * 60 * 60
_HEARTBEAT_TTL_SECONDS = 30
_FINALIZATION_DELAY = timedelta(seconds=2)
LIVE_SESSION_END_ARRIVAL_GRACE = timedelta(seconds=60)
_PROVIDER_RETRY_DELAY = timedelta(seconds=10)
_LIVE_BAR_FRESHNESS = timedelta(minutes=5)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
LIVE_BAR_CHANNEL_PREFIX = "live:bar"
LIVE_STATE_CHANNEL = "market:state"


@dataclass(frozen=True, slots=True)
class LiveBarObservation:
    bar: CanonicalBar
    contract: str


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
        *,
        contract: str,
    ) -> None:
        normalized_contract = normalize_contract_for_symbol(symbol, contract)
        if normalized_contract is None:
            raise ValueError("LIVE_BAR_PROVENANCE_INVALID")
        key = self._bars_key(trading_day, symbol, frequency)
        score = _epoch_millis(bar.bar_end)
        self._redis.zremrangebyscore(key, score, score)
        self._redis.zadd(
            key,
            {_compact_json(_bar_payload(bar, contract=normalized_contract)): score},
        )
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

    def bar_observations(
        self,
        trading_day: date,
        symbol: str,
        frequency: BarFrequency | str,
        after: datetime | None,
        until: datetime,
        *,
        inclusive_after: bool,
        expected_contract: str,
    ) -> tuple[LiveBarObservation, ...]:
        normalized_expected = normalize_contract_for_symbol(symbol, expected_contract)
        if normalized_expected is None or expected_contract != normalized_expected:
            raise ValueError("LIVE_BAR_PROVENANCE_INVALID")
        if after is None:
            minimum: str | int = "-inf"
        elif inclusive_after:
            minimum = _epoch_millis(after)
        else:
            minimum = f"({_epoch_millis(after)}"
        members = self._redis.zrangebyscore(
            self._bars_key(trading_day, symbol, frequency),
            minimum,
            _epoch_millis(until),
        )
        return tuple(
            _bar_observation_from_payload(
                _as_text(member),
                symbol=symbol,
                expected_contract=normalized_expected,
            )
            for member in members
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


def _bar_payload(
    bar: CanonicalBar,
    *,
    contract: str | None = None,
) -> dict[str, str | None]:
    payload = {
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
    if contract is not None:
        payload["contract"] = contract
    return payload


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


def _bar_observation_from_payload(
    raw: str,
    *,
    symbol: str,
    expected_contract: str,
) -> LiveBarObservation:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("LIVE_BAR_PROVENANCE_INVALID")
    stored_contract = payload.get("contract")
    normalized_contract = normalize_contract_for_symbol(symbol, stored_contract)
    if (
        not isinstance(stored_contract, str)
        or normalized_contract is None
        or stored_contract != normalized_contract
        or normalized_contract != expected_contract
    ):
        raise ValueError("LIVE_BAR_PROVENANCE_INVALID")
    return LiveBarObservation(
        bar=_bar_from_payload(raw),
        contract=normalized_contract,
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


def _canonical_bar_from_raw_feed(
    payload: Mapping[str, Any],
) -> tuple[str, CanonicalBar] | None:
    """将已明确完整的 RQData 1m feed 映射为 CanonicalBar；任何歧义均丢弃。"""
    if payload.get("action") != "feed":
        return None
    channel = payload.get("channel")
    contract = payload.get("order_book_id")
    if not isinstance(channel, str) or not channel.startswith("bar_"):
        return None
    if not isinstance(contract, str) or not contract.strip():
        return None
    if channel != f"bar_{contract.strip()}":
        return None
    required = ("datetime", "trading_date", "open", "high", "low", "close", "volume")
    if any(payload.get(field) is None for field in required):
        return None
    try:
        return (
            contract.strip().upper(),
            CanonicalBar(
                bar_end=_raw_datetime(payload["datetime"]),
                trading_day=_raw_date(payload["trading_date"]),
                open=Decimal(str(payload["open"])),
                high=Decimal(str(payload["high"])),
                low=Decimal(str(payload["low"])),
                close=Decimal(str(payload["close"])),
                volume=Decimal(str(payload["volume"])),
                turnover=_optional_raw_decimal(payload.get("turnover", payload.get("total_turnover"))),
                open_interest=_optional_raw_decimal(payload.get("open_interest")),
            ),
        )
    except (ArithmeticError, TypeError, ValueError):
        return None


def _raw_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=_SHANGHAI).astimezone(UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=_SHANGHAI).astimezone(UTC)
        return parsed.astimezone(UTC)
    digits = str(value)
    if not digits.isdigit() or len(digits) < 14:
        raise ValueError("LIVE_RAW_DATETIME_INVALID")
    return datetime.strptime(digits[:14], "%Y%m%d%H%M%S").replace(tzinfo=_SHANGHAI).astimezone(UTC)


def _raw_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    digits = str(value).replace("-", "")
    if not digits.isdigit() or len(digits) != 8:
        raise ValueError("LIVE_RAW_TRADING_DATE_INVALID")
    return datetime.strptime(digits, "%Y%m%d").date()


def _optional_raw_decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


class LiveProvider(Protocol):
    """最小 provider 边界；service 不持有 RQData 全局客户端。"""

    def subscribe(self, channels: tuple[str, ...]) -> None: ...

    def unsubscribe(self, channels: tuple[str, ...]) -> None: ...

    def poll(self) -> Iterable[tuple[str, CanonicalBar]]: ...

    def poll_buffered(self) -> Iterable[tuple[str, CanonicalBar]]: ...

    def close(self) -> None: ...


class RawLiveMarketClient(Protocol):
    """RQData 的最小 raw Live 接口；构造仍留在调用方的延迟 factory 中。"""

    def subscribe(self, channels: list[str]) -> Any: ...

    def unsubscribe(self, channels: list[str]) -> Any: ...

    def listen(self, *, handler: Callable[[Mapping[str, Any]], Any]) -> LiveListener: ...

    def close(self) -> Any: ...


class LiveListener(Protocol):
    """Minimal listener-thread boundary returned by RQData handler mode."""

    def is_alive(self) -> bool: ...


class RQDataLiveProvider:
    """唯一的 RQData raw-feed adapter：注册 handler、缓冲 raw dict、输出 CanonicalBar。

    仅接受完整的 1m OHLCV feed；tick、partial 或未知 payload 一律不进入服务层。
    """

    def __init__(self, client: RawLiveMarketClient) -> None:
        self._client = client
        self._messages: deque[Mapping[str, Any]] = deque()
        self._message_lock = Lock()
        self._listener: LiveListener | None = None
        self._closed = False

    def subscribe(self, channels: tuple[str, ...]) -> None:
        self._client.subscribe(list(channels))

    def unsubscribe(self, channels: tuple[str, ...]) -> None:
        self._client.unsubscribe(list(channels))

    def poll(self) -> tuple[tuple[str, CanonicalBar], ...]:
        if self._closed:
            raise ConnectionError("LIVE_PROVIDER_CLOSED")
        if self._listener is None:
            # RQData handler mode owns its background socket reader; this method only drains memory.
            self._listener = self._client.listen(handler=self._buffer_message)
        return self.poll_buffered()

    def poll_buffered(self) -> tuple[tuple[str, CanonicalBar], ...]:
        with self._message_lock:
            messages = self._messages
            self._messages = deque()
            listener_stopped = (
                self._listener is not None and not self._listener.is_alive()
            )
        buffered = tuple(
            item
            for message in messages
            if (item := _canonical_bar_from_raw_feed(message)) is not None
        )
        # Preserve a valid final Bar that the handler accepted immediately before
        # its listener stopped. The next poll reports the dead provider.
        if buffered:
            return buffered
        if listener_stopped:
            self.close()
            raise ConnectionError("LIVE_PROVIDER_LISTENER_STOPPED")
        return ()

    def close(self) -> None:
        """Idempotently retire a client that the service will never reuse."""
        if self._closed:
            return
        self._closed = True
        self._listener = None
        self._client.close()

    def _buffer_message(self, message: object) -> None:
        if isinstance(message, MappingABC):
            with self._message_lock:
                self._messages.append(message)


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
        self._pending: dict[
            tuple[str, datetime],
            tuple[CanonicalBar, SessionWindow, str],
        ] = {}
        self._finalized: set[tuple[str, datetime]] = set()
        self._known_sessions: dict[tuple[str, date], tuple[SessionWindow, ...]] = {}
        self._last_bar_at: datetime | None = None
        self._available = True
        self._provider_available = True
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
            self._sync_provider_channels(
                self._channels_in_session_grace(now),
                create_if_missing=False,
            )
            self._publish_heartbeat(now, phases)
            return None
        if len(trading_days) != 1:
            return "LIVE_TRADING_DAY_INCONSISTENT"
        trading_day = next(iter(trading_days))
        assert trading_day is not None
        active_symbols = tuple(
            symbol
            for symbol in self._products
            if phases[symbol].phase is MarketPhase.TRADING
            and phases[symbol].trading_day == trading_day
        )
        if trading_day != self._trading_day:
            stored_contracts = self._store.subscriptions(trading_day)
            current_contracts: dict[str, str] = {}
            if stored_contracts is not None:
                for symbol, contract in stored_contracts.items():
                    if symbol not in self._products:
                        return "LIVE_RANK1_CONTRACT_INVALID"
                    normalized = normalize_contract_for_symbol(symbol, contract)
                    if normalized is None:
                        return "LIVE_RANK1_CONTRACT_INVALID"
                    current_contracts[symbol] = normalized
            self._trading_day = trading_day
            self._contracts = current_contracts
        else:
            current_contracts = dict(self._contracts)
        # Freeze one complete operational-universe rank1 snapshot for the day.
        # Provider channels remain phase-scoped below; the snapshot is also the
        # immutable reconciliation input consumed by the after-market runner.
        unresolved = tuple(symbol for symbol in self._products if symbol not in current_contracts)
        if unresolved:
            raw_snapshot = {
                symbol: self._dominant_source.dominant_for_day(symbol, trading_day)
                for symbol in unresolved
            }
            snapshot = {
                symbol: normalize_contract_for_symbol(symbol, contract)
                for symbol, contract in raw_snapshot.items()
            }
            if any(contract is None for contract in snapshot.values()):
                return "LIVE_RANK1_CONTRACT_INVALID"
            current_contracts.update(
                (symbol, contract)
                for symbol, contract in snapshot.items()
                if contract is not None
            )
            self._store.set_subscriptions(trading_day, current_contracts)
            self._store.publish_state({"trading_day": trading_day.isoformat()})
            self._trading_day = trading_day
            self._contracts = current_contracts
        desired = {
            f"bar_{self._contracts[symbol]}" for symbol in active_symbols
        } | self._channels_in_session_grace(now)
        self._sync_provider_channels(desired, create_if_missing=True)
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
        frozen_contract = normalize_contract_for_symbol(symbol, contract)
        if frozen_contract is None or frozen_contract != self._contracts[symbol]:
            return self._reject("LIVE_CONTRACT_NOT_SUBSCRIBED")
        phase = self._phase_resolver.resolve(symbol, now)
        window = self._session_for_bar(symbol, bar, phase, now)
        if window is None:
            return self._reject("LIVE_BAR_OUTSIDE_SESSION")
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
        self._pending[key] = (bar, window, frozen_contract)
        return None

    def flush_due(self, now: datetime) -> tuple[CanonicalBar, ...]:
        """仅在 bar_end 两秒后发布一次 completed 1m，并增量生成派生频率。"""
        finalized: list[CanonicalBar] = []
        for key, (bar, window, frozen_contract) in tuple(self._pending.items()):
            if now < bar.bar_end + _FINALIZATION_DELAY:
                continue
            symbol, _ = key
            try:
                self._store.put_bar(
                    bar.trading_day,
                    symbol,
                    BarFrequency.M1,
                    bar,
                    contract=frozen_contract,
                )
                self._store.publish_bar(symbol, BarFrequency.M1, bar)
            except Exception:  # noqa: BLE001 - Redis is an explicit unavailable boundary
                self._available = False
                self._reject("LIVE_REDIS_UNAVAILABLE")
                continue
            self._pending.pop(key)
            self._finalized.add(key)
            self._available = True
            self._last_bar_at = max(self._last_bar_at, bar.bar_end) if self._last_bar_at else bar.bar_end
            finalized.append(bar)
            try:
                self._derive(symbol, bar, window, contract=frozen_contract)
            except Exception:  # noqa: BLE001 - Derived only reads/writes transient Redis state
                self._available = False
                self._reject("LIVE_REDIS_UNAVAILABLE")
        return tuple(finalized)

    def poll(self, now: datetime) -> str | None:
        """执行单个前台 poll cycle；TRADING provider 故障固定十秒重试。"""
        phases = self._phases(now)
        if not any(item.phase is MarketPhase.TRADING for item in phases.values()):
            self.next_provider_retry_at = None
            try:
                self._drain_session_grace(now)
                self.flush_due(now)
                self._sync_provider_channels(
                    self._channels_in_session_grace(now),
                    create_if_missing=False,
                )
                self._publish_heartbeat(now, phases)
            except _ProviderUnavailable:
                self._discard_provider()
                self._provider_available = False
                try:
                    self._publish_heartbeat(now, phases)
                except Exception:  # noqa: BLE001 - Redis remains the explicit state boundary
                    self._available = False
                    return self._reject("LIVE_REDIS_UNAVAILABLE")
                return self._reject("LIVE_PROVIDER_UNAVAILABLE")
            except Exception:  # noqa: BLE001 - Live has no local fallback path
                self._available = False
                return self._reject("LIVE_REDIS_UNAVAILABLE")
            return None
        if self.next_provider_retry_at is not None and now < self.next_provider_retry_at:
            self.flush_due(now)
            return None
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
        if not self._channels:
            return None
        try:
            provider = self._provider_or_create()
            for contract, bar in provider.poll():
                self.ingest(contract, bar, now=now)
            self.flush_due(now)
            if not self._provider_available:
                self._provider_available = True
                self._publish_heartbeat(now, phases)
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

    def _derive(
        self,
        symbol: str,
        bar: CanonicalBar,
        session: SessionWindow,
        *,
        contract: str,
    ) -> None:
        for frequency in (BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1):
            bucket = bucket_window_for_bar(session, frequency, bar.bar_end)
            if bar.bar_end != bucket.end:
                continue
            source = tuple(
                item.bar
                for item in self._store.bar_observations(
                    bar.trading_day,
                    symbol,
                    BarFrequency.M1,
                    bucket.start,
                    bucket.end,
                    inclusive_after=False,
                    expected_contract=contract,
                )
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
            self._store.put_bar(
                bar.trading_day,
                symbol,
                frequency,
                derived,
                contract=contract,
            )
            self._store.publish_bar(symbol, frequency, derived)

    def _phases(self, now: datetime) -> dict[str, ProductMarketPhase]:
        phases = {symbol: self._phase_resolver.resolve(symbol, now) for symbol in self._products}
        for symbol, phase in phases.items():
            if phase.trading_day is not None and phase.current_session is not None:
                key = (symbol, phase.trading_day)
                known = self._known_sessions.get(key, ())
                if phase.current_session not in known:
                    self._known_sessions[key] = tuple(sorted((*known, phase.current_session), key=lambda item: item.start))
        return phases

    def _session_for_bar(
        self,
        symbol: str,
        bar: CanonicalBar,
        phase: ProductMarketPhase,
        now: datetime,
    ) -> SessionWindow | None:
        if phase.trading_day == bar.trading_day and phase.current_session is not None:
            return phase.current_session
        for window in self._known_sessions.get((symbol, bar.trading_day), ()):
            if (
                bar.bar_end == window.end
                and window.end <= now <= window.end + LIVE_SESSION_END_ARRIVAL_GRACE
            ):
                return window
        return None

    def _drain_session_grace(self, now: datetime) -> None:
        """休市边界只 drain 已启动 listener 的 final 1m，不创建、订阅或重连 provider。"""
        if self._provider is None:
            return
        try:
            buffered = self._provider.poll_buffered()
        except Exception as exc:  # noqa: BLE001 - provider failures stay outside Redis semantics
            raise _ProviderUnavailable() from exc
        for contract, bar in buffered:
            self.ingest(contract, bar, now=now)

    def _channels_in_session_grace(self, now: datetime) -> set[str]:
        """仅保留已经订阅、且仍可接收 Session final bar 的通道。"""
        grace_symbols = {
            symbol
            for (symbol, _trading_day), windows in self._known_sessions.items()
            if any(
                window.end <= now <= window.end + LIVE_SESSION_END_ARRIVAL_GRACE
                for window in windows
            )
        }
        return {
            channel
            for symbol, contract in self._contracts.items()
            if symbol in grace_symbols
            and (channel := f"bar_{contract}") in self._channels
        }

    def _sync_provider_channels(
        self,
        desired: set[str],
        *,
        create_if_missing: bool,
    ) -> None:
        """应用真实 provider 差量；失败时不伪造本地 channel 已收敛。"""
        removed = tuple(sorted(self._channels - desired))
        added = tuple(sorted(desired - self._channels))
        if not removed and not added:
            return
        if self._provider is None and not create_if_missing:
            return
        try:
            provider = self._provider_or_create()
            if removed:
                provider.unsubscribe(removed)
            if added:
                provider.subscribe(added)
        except Exception as exc:  # noqa: BLE001 - provider boundary is intentionally minimal
            raise _ProviderUnavailable() from exc
        self._channels = desired
        self._provider_available = True

    def _provider_or_create(self) -> LiveProvider:
        if self._provider is None:
            self._provider = self._provider_factory()
        return self._provider

    def _discard_provider(self) -> None:
        """Forget failed provider state so no closed client or stale channel can be reused."""
        provider = self._provider
        self._provider = None
        self._channels = set()
        if provider is None:
            return
        try:
            provider.close()
        except Exception:  # noqa: BLE001 - provider is discarded regardless of close outcome
            pass

    def _schedule_provider_retry(
        self,
        now: datetime,
        phases: Mapping[str, ProductMarketPhase],
    ) -> str | None:
        if any(item.phase is MarketPhase.TRADING for item in phases.values()):
            # 新 client 没有旧订阅；下一次 reconcile 会重建完整订阅集。
            self._discard_provider()
            self._provider_available = False
            self.next_provider_retry_at = now + _PROVIDER_RETRY_DELAY
            try:
                self._publish_heartbeat(now, phases)
            except Exception:  # noqa: BLE001 - Redis failure supersedes provider retry state
                self._available = False
                return self._reject("LIVE_REDIS_UNAVAILABLE")
            return "LIVE_PROVIDER_RETRY_SCHEDULED"
        self.next_provider_retry_at = None
        return None

    def _publish_heartbeat(self, now: datetime, phases: Mapping[str, ProductMarketPhase]) -> None:
        counts = Counter(phase.phase.value for phase in phases.values())
        bar_feed_fresh = True
        if counts[MarketPhase.TRADING.value] > 0:
            bar_feed_fresh = (
                self._last_bar_at is not None
                and timedelta(0) <= now - self._last_bar_at <= _LIVE_BAR_FRESHNESS
            )
        self._store.set_heartbeat(
            {
                "generated_at": now.astimezone(UTC).isoformat(),
                "operational_count": len(self._products),
                "subscribed_count": len(self._channels),
                "last_bar_at": None if self._last_bar_at is None else self._last_bar_at.isoformat(),
                "phase_counts": dict(sorted(counts.items())),
                "available": self._available and self._provider_available and bar_feed_fresh,
            }
        )

    def _reject(self, code: str) -> str:
        self.rejections.append(code)
        return code
