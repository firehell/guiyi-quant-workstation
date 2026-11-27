"""Cross-process, display-only projection of the Tick feed's latest observations."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
import json
import re

from redis.exceptions import RedisError

from app.market_data.domain import BarFrequency, normalize_contract_for_symbol
from app.market_data.live_market import RedisLiveStore, _bar_from_payload, _bar_payload
from app.market_data.market_display_preview import MarketActivity, MarketPreview, MarketQuote
from app.market_data.tick_feed import TickPreviewStore

_GENERATION = "live:tick-preview:generation"
_LIFETIME_SECONDS = 30
_GENERATION_FORMAT = re.compile(r"rqdata-tick:[0-9a-f]{32}:[1-9][0-9]*")


def _key(day: date, symbol: str, contract: str) -> str:
    return f"live:tick-preview:{day}:{symbol}:{contract}"


class RedisTickPreviewPublisher:
    """Write at most one value per owner per intake batch and never retain raw Tick."""

    def __init__(self, redis, *, assert_owned: Callable[[], None]) -> None:
        self._redis = redis
        self._assert_owned = assert_owned
        self._pending: dict[str, str | None] = {}
        self._generation: str | None = None
        self._generation_dirty = False
        self._keys: dict[str, str] = {}

    def publish(self, symbol, tick, update, sessions, *, generation):
        if generation != self._generation:
            self._pending.clear()
            self._generation = generation
            self._generation_dirty = True
            self._keys.clear()
        key = self._keys[tick.contract] = _key(tick.trading_day, symbol, tick.contract)
        self._pending[key] = json.dumps({
            "day": str(tick.trading_day), "contract": tick.contract,
            "generation": generation,
            "observed_at": tick.observed_at.isoformat(), "received_at": tick.received_at.isoformat(),
            "last": str(tick.last),
            "bid": [(str(price), str(size)) for price, size in tick.bid],
            "ask": [(str(price), str(size)) for price, size in tick.ask],
            "active": _bar_payload(update.active) if update.active is not None else None,
        }, separators=(",", ":"))

    def clear_activity(self, day, *, contract=None, stale=False):
        if contract is None:
            self._pending.clear()
            self._generation = None
            self._generation_dirty = True
            self._keys.clear()
            return
        # Invalid data for one contract must not invalidate unrelated owners.
        key = self._keys.pop(contract, None)
        if key is not None:
            self._pending[key] = None

    def flush(self):
        if not self._pending and not self._generation_dirty:
            return
        self._assert_owned()
        try:
            with self._redis.pipeline(transaction=True) as pipeline:
                if self._generation is None:
                    pipeline.delete(_GENERATION)
                else:
                    pipeline.set(_GENERATION, self._generation, ex=_LIFETIME_SECONDS)
                for key, value in self._pending.items():
                    if value is None:
                        pipeline.delete(key)
                    else:
                        pipeline.set(key, value, ex=_LIFETIME_SECONDS)
                pipeline.execute()
        except RedisError:
            # This cache has no effect on completed publication or forward eligibility.
            # Compare-and-read of the generation and the short TTL fence stale entries.
            return
        self._generation_dirty = False
        self._pending.clear()


class RedisTickPreviewReader:
    """Read one coherent preview, deriving higher periods from a proved minute prefix."""

    def __init__(self, redis, *, sessions) -> None:
        self._redis = redis
        self._live = RedisLiveStore(redis)
        self._sessions = sessions

    def snapshot(self, *, trading_day, symbol, contract, frequency):
        if normalize_contract_for_symbol(symbol, contract) != contract:
            return MarketPreview()
        try:
            if (self._live.subscriptions(trading_day) or {}).get(symbol) != contract:
                return MarketPreview()
            generation, raw = self._redis.mget(_GENERATION, _key(trading_day, symbol, contract))
            if generation is None or raw is None:
                return MarketPreview()
            if isinstance(generation, bytes):
                generation = generation.decode("ascii")
            record = json.loads(raw)
            if (not _GENERATION_FORMAT.fullmatch(generation) or record["generation"] != generation
                    or record["contract"] != contract or record["day"] != str(trading_day)):
                return MarketPreview()
            observed_at = datetime.fromisoformat(record["observed_at"])
            received_at = datetime.fromisoformat(record["received_at"])
            last = Decimal(record["last"])
            if (observed_at.utcoffset() is None or received_at.utcoffset() is None
                    or not observed_at <= received_at or not last.is_finite() or last <= 0):
                return MarketPreview()
            quote = MarketQuote(trading_day, contract, generation, observed_at, received_at, last,
                                _book(record["bid"]), _book(record["ask"]))
            active = record["active"]
            if active is None:
                return MarketPreview(quote=quote)
            bar = _bar_from_payload(json.dumps(active))
            if bar.trading_day != trading_day or observed_at > bar.bar_end:
                return MarketPreview()
            if frequency != BarFrequency.M1:
                sessions = self._sessions(symbol=symbol, trading_day=trading_day)
                prefix = self._live.bar_observations(
                    trading_day, symbol, BarFrequency.M1, None, bar.bar_end,
                    inclusive_after=False, expected_contract=contract,
                )
                completed = tuple(value.bar for value in prefix if value.bar.bar_end < bar.bar_end)
                bar = TickPreviewStore._derive(frequency, bar, completed, sessions)
                current = self._redis.get(_GENERATION)
                if current not in {generation, generation.encode("ascii")}:
                    return MarketPreview()
            return MarketPreview(quote, None if bar is None else MarketActivity(
                contract, generation, bar, observed_at, received_at,
            ))
        except (RedisError, ValueError, ArithmeticError, KeyError, TypeError, UnicodeError):
            return MarketPreview()


def _book(levels):
    if not isinstance(levels, list) or len(levels) > 5:
        raise ValueError("TICK_PREVIEW_DEPTH_INVALID")
    result = tuple((Decimal(price), Decimal(size)) for price, size in levels)
    if any(not price.is_finite() or not size.is_finite() for price, size in result):
        raise ValueError("TICK_PREVIEW_DEPTH_INVALID")
    return result
