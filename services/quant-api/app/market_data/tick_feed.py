"""Bounded Tick intake and display preview for an explicitly isolated feed."""
from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from app.market_data.aggregation import (
    SessionWindow, aggregate_bucket, bucket_window_for_bar, expected_intraday_ends,
)
from app.market_data.domain import BarFrequency, CanonicalBar, normalize_contract_for_symbol
from app.market_data.live_market import RQDataLiveProvider
from app.market_data.market_display_preview import MarketActivity, MarketPreview, MarketQuote
from app.market_data.tick_market import MarketTick, TickMinuteBuilder, TickMinuteUpdate, decode_rqdata_tick

_MINUTE = timedelta(minutes=1)
_MAX_DAY_MINUTES = 24 * 60


@dataclass(frozen=True, slots=True)
class TickSourceProof:
    generation: str
    observed_at: datetime
    received_at: datetime


@dataclass(slots=True)
class _PreviewState:
    quote: MarketQuote
    active: CanonicalBar | None
    sessions: tuple[SessionWindow, ...]
    completed: deque[CanonicalBar]


class TickPreviewStore:
    """Latest quote plus at most one trading day's minute preview inputs per owner."""

    def __init__(self) -> None:
        self._day: date | None = None
        self._by_contract: dict[tuple[str, str], _PreviewState] = {}
        self._lock = Lock()

    def publish(
        self, symbol: str, tick: MarketTick, update: TickMinuteUpdate,
        sessions: tuple[SessionWindow, ...], *, generation: str,
    ) -> None:
        key = (symbol, tick.contract)
        quote = MarketQuote(tick.trading_day, tick.contract, generation, tick.observed_at,
                            tick.received_at, tick.last, tick.bid, tick.ask)
        with self._lock:
            if self._day is not None and tick.trading_day < self._day:
                return
            if tick.trading_day != self._day:
                self._by_contract.clear()
                self._day = tick.trading_day
            prior = self._by_contract.get(key)
            completed = deque(maxlen=_MAX_DAY_MINUTES) if prior is None else prior.completed
            if update.completed is not None:
                completed.append(update.completed)
            self._by_contract[key] = _PreviewState(quote, update.active, sessions, completed)

    def clear_activity(self, day: date | None, *, contract: str | None = None, stale: bool = False) -> None:
        with self._lock:
            if self._day == day:
                for (_symbol, owner), entry in self._by_contract.items():
                    if contract is None or owner == contract:
                        entry.active = None
                        if stale:
                            entry.quote = replace(entry.quote, stale=True)

    def snapshot(
        self, *, trading_day: date, symbol: str, contract: str, frequency: BarFrequency,
    ) -> MarketPreview:
        with self._lock:
            entry = self._by_contract.get((symbol, contract)) if self._day == trading_day else None
            if entry is None:
                return MarketPreview()
            quote, active, sessions = entry.quote, entry.active, entry.sessions
            completed = tuple(entry.completed) if active is not None and frequency != BarFrequency.M1 else ()
        if active is not None and frequency != BarFrequency.M1:
            active = self._derive(frequency, active, completed, sessions)
        activity = None if active is None else MarketActivity(
            contract, quote.generation, active, quote.observed_at, quote.received_at,
        )
        return MarketPreview(quote=quote, activity=activity)

    @staticmethod
    def _derive(frequency, active, completed, sessions) -> CanonicalBar | None:
        if frequency is BarFrequency.W1:
            # The shared read service owns settled prior D1 and weekly identity.
            return None
        window = next((item for item in sessions if item.start < active.bar_end <= item.end), None)
        if window is None:
            return None
        if frequency is BarFrequency.D1:
            expected = tuple(end for end in expected_intraday_ends(sessions, BarFrequency.M1)
                             if end < active.bar_end)
            prefix = completed
            end = sessions[-1].end
        else:
            bucket = bucket_window_for_bar(window, frequency, active.bar_end)
            count = (active.bar_end - bucket.start) // _MINUTE
            expected = tuple(bucket.start + offset * _MINUTE for offset in range(1, count))
            prefix = tuple(bar for bar in completed if bar.bar_end > bucket.start)
            end = bucket.end
        if tuple(bar.bar_end for bar in prefix) != expected:
            return None
        return aggregate_bucket((*prefix, active), bucket_end=end)


class TickPreviewSink(Protocol):
    def publish(self, symbol: str, tick: MarketTick, update: TickMinuteUpdate,
                sessions: tuple[SessionWindow, ...], *, generation: str) -> None: ...

    def clear_activity(self, day: date | None, *, contract: str | None = None,
                       stale: bool = False) -> None: ...


class TickMarketDataProvider(RQDataLiveProvider):
    """Translate logical minute channels, keep the SDK callback bounded, emit proved minutes."""

    def __init__(
        self, client, *, connection_identity: Callable[[], object], preview: TickPreviewSink,
        clock: Callable[[], datetime] | None = None, capacity: int = 8192,
        batch_size: int = 1024, dispatch: Callable[..., Any] | None = None,
        flush_preview: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__(client)
        if not 1 <= capacity <= 65_536 or not 1 <= batch_size <= 8192:
            raise ValueError("TICK_BUFFER_CONFIG_INVALID")
        self._connection_identity = connection_identity
        self._preview = preview
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tick_messages: deque[tuple[Mapping[str, Any], datetime, object]] = deque()
        self._capacity = capacity
        self._batch_size = batch_size
        self._dispatch = dispatch
        self._flush_preview = flush_preview
        self._overflow = False
        self._day: date | None = None
        self._owners: dict[str, tuple[str, tuple[SessionWindow, ...]]] = {}
        self._builders: dict[str, TickMinuteBuilder] = {}
        self._proofs: dict[tuple[str, CanonicalBar], TickSourceProof] = {}
        self._last_connection: object | None = None
        self._generation = 0
        self._instance = uuid4().hex
        self.diagnostics: Counter[str] = Counter()

    @staticmethod
    def _tick_channels(channels: tuple[str, ...]) -> tuple[str, ...]:
        if any(not channel.startswith("bar_") for channel in channels):
            raise ValueError("TICK_CHANNEL_INVALID")
        return tuple("tick_" + channel[4:] for channel in channels)

    def subscribe(self, channels: tuple[str, ...]) -> None:
        if any(channel[4:] not in self._owners for channel in channels):
            raise ValueError("TICK_OWNER_UNPROVED")
        super().subscribe(self._tick_channels(channels))

    def unsubscribe(self, channels: tuple[str, ...]) -> None:
        super().unsubscribe(self._tick_channels(channels))

    def configure(self, day: date, owners: Mapping[str, tuple[str, tuple[SessionWindow, ...]]]) -> None:
        by_contract = {contract: (symbol, sessions) for symbol, (contract, sessions) in owners.items()}
        if self._day == day and self._owners == by_contract:
            return
        if len(owners) != len(by_contract) or not 1 <= len(owners) <= 70 or any(
            normalize_contract_for_symbol(symbol, contract) != contract
            for contract, (symbol, _sessions) in by_contract.items()
        ):
            raise ValueError("TICK_OWNER_INVALID")
        with self._message_lock:
            if self._tick_messages or self._day is not None and day <= self._day:
                raise ValueError("TICK_OWNER_CHANGED_WITH_PENDING_INPUT")
            self._preview.clear_activity(self._day)
            self._day = day
            self._owners = by_contract
            self._builders = {contract: TickMinuteBuilder(sessions)
                              for contract, (_symbol, sessions) in self._owners.items()}

    def _buffer_message(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            return
        received_at = self._clock()
        connection = self._connection_identity()
        with self._message_lock:
            if len(self._tick_messages) >= self._capacity:
                self._overflow = True
            if not self._overflow:
                self._tick_messages.append((payload, received_at, connection))

    def buffered_message_count(self) -> int:
        with self._message_lock:
            return len(self._tick_messages)

    def poll_buffered(self) -> tuple[tuple[str, CanonicalBar], ...]:
        with self._message_lock:
            if self._overflow:
                self.diagnostics["TICK_BUFFER_OVERFLOW"] += 1
                self._preview.clear_activity(self._day, stale=True)
                self._flush_preview()
                raise ConnectionError("TICK_BUFFER_OVERFLOW")
            messages = tuple(self._tick_messages.popleft() for _ in range(min(len(self._tick_messages), self._batch_size)))
            stopped = self._listener is not None and not self._listener.is_alive()
        if not messages and stopped:
            self.close()
            raise ConnectionError("TICK_LISTENER_STOPPED")
        self._proofs.clear()
        if self._dispatch is None:
            result = self._process(messages)
        else:
            result = self._dispatch(self._process, messages) if messages else ()
        self._flush_preview()
        return result

    def _process(self, messages) -> tuple[tuple[str, CanonicalBar], ...]:
        completed = []
        for payload, received_at, connection in messages:
            if connection is None:
                raise ConnectionError("TICK_CONNECTION_UNPROVED")
            if connection is not self._last_connection:
                if self._last_connection is not None:
                    self.diagnostics["TICK_RECONNECT"] += 1
                    for builder in self._builders.values():
                        builder.gap()
                    self._preview.clear_activity(self._day, stale=True)
                self._last_connection = connection
                self._generation += 1
            assert self._day is not None
            tick = decode_rqdata_tick(payload, trading_day=self._day, received_at=received_at,
                                      connection=self._generation)
            if tick is None or tick.contract not in self._builders:
                self.diagnostics["TICK_INVALID"] += 1
                channel = payload.get("channel")
                if isinstance(channel, str) and channel.startswith("tick_"):
                    owner = channel[5:].upper()
                    if owner in self._builders:
                        self._builders[owner].gap()
                        self._preview.clear_activity(self._day, contract=owner, stale=True)
                continue
            builder = self._builders[tick.contract]
            update = builder.ingest(tick)
            if update.issue:
                self.diagnostics[update.issue] += 1
            if not update.accepted:
                continue
            generation = f"rqdata-tick:{self._instance}:{self._generation}"
            symbol, sessions = self._owners[tick.contract]
            if not self._closed:
                self._preview.publish(symbol, tick, update, sessions, generation=generation)
            if update.completed is not None:
                item = (tick.contract, update.completed)
                completed.append(item)
                self._proofs[item] = TickSourceProof(generation, tick.observed_at, tick.received_at)
        return tuple(completed)

    @property
    def trading_day(self) -> date | None:
        return self._day

    def source_observed_at(self, contract: str, bar: CanonicalBar) -> datetime | None:
        return self.source_proof(contract, bar).received_at

    def source_proof(self, contract: str, bar: CanonicalBar) -> TickSourceProof:
        return self._proofs[(contract, bar)]

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._preview.clear_activity(self._day, stale=True)
            self._flush_preview()
