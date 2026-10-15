"""Optional independent RQData feed and durable Live computation composition."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from typing import Any

from app.market_data.aggregation import aggregate_from_1m, bucket_window_for_bar
from app.market_data.domain import BarFrequency, CanonicalBar, normalize_contract_for_symbol
from app.runtime_identity import runtime_heartbeat_identity
from app.market_data.live_market import (
    LiveMarketService, LiveProvider, RedisLiveStore, _bar_from_payload, _bar_payload, _compact_json,
    _epoch_millis, live_bar_channel,
)
from app.market_data.live_recovery_scripts import COMMIT_OBSERVATIONS
from app.market_data.market_phase import MarketPhase
from app.market_data.observation_stream import (
    DAILY_LIMIT, TTL_SECONDS, ObservationEnvelope, ObservationStream,
)


_DECIMAL_BAR_FIELDS = frozenset(('open', 'high', 'low', 'close', 'volume', 'turnover', 'open_interest'))


@dataclass(frozen=True, slots=True)
class _CleanupIsolation:
    day: date
    local_day: date | None
    provider: Any
    contracts: tuple[tuple[str, str], ...]
    retired: bool = False


def _closed_cleaned_idle_proof(service, source_stream, now, phases):
    """Prove a terminal cleaned day; never manufacture its missing snapshot."""
    callback = service.closed_cleanup_evidence
    if (callback is None or set(phases) != set(service._products) or not phases
            or service._pending or service._provider is not None
            or getattr(service, '_input_failure', None) is not None
            or getattr(service, '_halted', None) is not None
            or getattr(service, '_metadata_preparation_error', None) is not None
            or getattr(service, '_last_flush_failed', False)
            or any(phase.phase is not MarketPhase.CLOSED
                   or phase.next_session_start is None or phase.next_session_start <= now
                   for phase in phases.values())):
        return None
    try:
        day = source_stream.registered_day('live')
        if any(phase.trading_day is not None and phase.trading_day != day for phase in phases.values()):
            return None
        evidence = callback(day, now)
        if (not isinstance(evidence, dict) or evidence.get('trading_day') != day.isoformat()
                or evidence.get('cleanup_verified') is not True):
            return None
        count = 0
        for stream in (source_stream, ObservationStream(source_stream.redis, kind='completed')):
            prefix = f'live:observations:registered:{stream.kind}:'
            consumers = set()
            for raw in stream.redis.scan_iter(match=prefix + '*'):
                key = raw.decode() if isinstance(raw, bytes) else raw
                consumer = key[len(prefix):]
                if (stream.registered_day(consumer) != day
                        or stream.cursor(consumer, day) != stream.tail(day)):
                    return None
                consumers.add(consumer)
            if not consumers or stream.kind == 'source' and 'live' not in consumers:
                return None
            count += len(consumers)
    except Exception:
        return None
    return {**evidence, 'status': 'CLOSED_CLEANED', 'consumer_count': count,
            'source_cursor': source_stream.cursor('live', day), 'pending_count': 0,
            'natural_bar_verified': False}



def _accept_closed_cleaned(service, proof, now, phases) -> date:
    service.closed_cleaned_proof = proof
    day = date.fromisoformat(proof['trading_day'])
    service._trading_day = day
    service._closed_cleaned_day = service._trading_day
    service._contracts = {}
    service._channels = set()
    service._available = service._provider_available = True
    service._publish_heartbeat(now, phases)
    return day


def _closed_cleanup_requires_proof(service, stream, phases):
    try:
        day = stream.registered_day('live')
        if getattr(service, '_closed_cleaned_day', None) == day:
            # Only authoritative advancement to a new day releases this fence.
            return not any(phase.trading_day is not None and phase.trading_day > day
                           for phase in phases.values())
        if not phases or any(phase.phase is not MarketPhase.CLOSED for phase in phases.values()):
            return False
        if any(phase.trading_day is not None and phase.trading_day != day for phase in phases.values()):
            return False
        # A terminal cleaned day cannot return to a normal snapshot happy path,
        # including after someone recreates that snapshot or proof is revoked.
        return service._store.subscriptions(day) is None
    except Exception:
        return True


def _reject_closed_cleanup(service, now, phases):
    service.closed_cleaned_proof = None
    service._available = False
    service._publish_heartbeat(now, phases)
    return service._reject('OBSERVATION_CLEANUP_UNPROVEN')


def _equivalent_bar_payload(left: dict, right: dict) -> bool:
    """Compare exact identity and finite Decimal facts without a binary-float conversion."""
    if type(left) is not dict or type(right) is not dict or left.keys() != right.keys():
        return False
    for field, value in left.items():
        other = right[field]
        if field not in _DECIMAL_BAR_FIELDS:
            if type(value) is not type(other) or value != other:
                return False
        elif value is None or other is None:
            if value is not other:
                return False
        else:
            if type(value) is not str or type(other) is not str:
                return False
            try:
                a, b = Decimal(value), Decimal(other)
            except InvalidOperation:
                return False
            if not a.is_finite() or not b.is_finite() or a != b:
                return False
    return True


class FeedLiveStore(RedisLiveStore):
    """Separate heartbeat; input feed never impersonates completed Live readiness."""
    def set_heartbeat(self, payload):
        self._redis.set('live:feed:heartbeat', _compact_json(dict(payload)), ex=30)

    def publish_state(self, payload):
        pass


class MarketFeedService(LiveMarketService):
    """Same authoritative subscription/session lifecycle, no completed publications."""
    _provider: LiveProvider | None
    _channels: set[str]

    def __init__(self, *, source_stream: ObservationStream, closed_cleanup_evidence=None,
                 shutdown_guard_factory=None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.source_stream = source_stream
        self._shutdown_guard_factory = shutdown_guard_factory
        self._input_failure: str | None = None
        self._last_input_received_at: datetime | None = None
        self.closed_cleanup_evidence = closed_cleanup_evidence
        self.closed_cleaned_proof = None
        self._closed_restore_day = None
        self._closed_cleaned_day = None
        self._closed_retirement_failed = False
        self._cleanup_isolation: _CleanupIsolation | None = None

    def _isolate_cleaned_day(self, day, provider, contracts) -> None:
        if self._cleanup_isolation is None:
            self._cleanup_isolation = _CleanupIsolation(
                day, self._trading_day, provider, tuple(sorted(contracts.items())))

    def _observe_old_day_cleanup(self) -> None:
        """Phase-independent: the first poll can already belong to a new Session."""
        if self._cleanup_isolation is not None:
            return
        day = self._trading_day or self.source_stream.registered_day('live')
        if self._store.subscriptions(day) is None:
            self._isolate_cleaned_day(day, self._provider, self._contracts)

    def _fail_closed_retirement(self) -> None:
        self._closed_retirement_failed = True
        self._input_failure = 'LIVE_PROVIDER_CLOSE_UNKNOWN'

    def _retire_closed_provider(self) -> bool:
        """Resolve the retained old-day object; never consume its late raw input."""
        isolation = self._cleanup_isolation
        if isolation is None:
            return False
        if isolation.retired:
            return self._provider is None
        if hasattr(self, 'assert_owned'):
            self.assert_owned()
        provider = isolation.provider
        ownership_lost = False
        try:
            if self._provider is not provider or self._pending:
                raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
            # No socket exists in a cold/previously retired instance. All idle
            # authority still comes from _closed_cleaned_idle_proof, never this fact.
            if provider is not None:
                close_verified = getattr(provider, 'close_verified', None)
                if not callable(close_verified):
                    raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
                close_verified()  # Bounded join outside the maintenance mutex.
                if self._shutdown_guard_factory is None:
                    raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
                with self._shutdown_guard_factory():
                    if hasattr(self, 'assert_owned'):
                        try:
                            self.assert_owned()
                        except Exception:
                            ownership_lost = True
                            raise
                    if (self._cleanup_isolation is not isolation
                            or set(dict(isolation.contracts)) != set(self._products)
                            or self._provider is not provider
                            or self._trading_day != isolation.local_day
                            or tuple(sorted(self._contracts.items())) != isolation.contracts
                            or self.source_stream.registered_day('live') != isolation.day
                            or self._store.subscriptions(isolation.day) is not None
                            or self.source_stream.cursor('live', isolation.day) != self.source_stream.tail(isolation.day)
                            or self._pending):
                        raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
                    count = provider.buffered_message_count()
                    if type(count) is not int or count != 0:
                        raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
                    # Sole cleanup retirement point: listener dead, locked count
                    # zero, exact old object/day and cursor still proven.
                    self._provider = None
                    self._channels = set()
            self._cleanup_isolation = replace(isolation, retired=True)
            return True
        except Exception:
            self._fail_closed_retirement()
            if ownership_lost:
                raise
            return False

    @contextmanager
    def _buffer_publication_guard(self, provider, day, contracts):
        """One old-day fence shared by ordinary grace and shutdown drains."""
        if self._shutdown_guard_factory is None:
            raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
        with self._shutdown_guard_factory():
            if hasattr(self, 'assert_owned'):
                self.assert_owned()
            snapshot = self._store.subscriptions(day) if day is not None else None
            if snapshot is None and day is not None:
                self._isolate_cleaned_day(day, provider, contracts)
            if (day is None or self._provider is not provider
                    or self._trading_day != day or self._contracts != contracts
                    or set(contracts) != set(self._products)
                    or self.source_stream.registered_day('live') != day
                    or snapshot != contracts):
                raise ValueError('OBSERVATION_CLEANUP_UNPROVEN')
            yield

    def _drain_session_grace(self, now):
        provider = self._provider
        if provider is None:
            return
        try:
            count = provider.buffered_message_count()
            if type(count) is not int or count < 0:
                raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
            if count == 0:
                # No buffer take/publication exists to fence. In particular, a
                # normal empty CLOSED poll must not contend with 18:05 maintenance.
                # A callback after this locked count remains for the next poll.
                return
            with self._buffer_publication_guard(provider, self._trading_day, dict(self._contracts)):
                super()._drain_session_grace(now)
        except Exception:
            if self._cleanup_isolation is None:
                self._fail_closed_retirement()
            raise

    def _discard_provider(self) -> None:
        """Never declare the feed parked until the sole reader actually retires."""
        if self._closed_retirement_failed:
            # Preserve the retained object and its original buffer even during
            # run_forever's finally/drain. No old-day ingest is legal after cleanup.
            raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
        provider = self._provider
        if provider is None:
            return
        day, contracts = self._trading_day, dict(self._contracts)
        try:
            if (day is None or set(contracts) != set(self._products)
                    or self.source_stream.registered_day('live') != day
                    or self._store.subscriptions(day) != contracts):
                raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
            verifier = getattr(provider, 'close_verified', None)
            if verifier is None:
                raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
            # Never hold the maintenance guard across client close/listener join.
            verifier()
            with self._buffer_publication_guard(provider, day, contracts):
                # Natural cleanup uses this same guard. Only after the listener
                # is dead and exact original identity still exists may its finite
                # buffer be taken and published. A busy/unknown fence takes nothing.
                drain = getattr(provider, 'poll_buffered', None)
                if drain is not None:
                    for contract, bar in drain():
                        observed = getattr(provider, 'source_observed_at', lambda *_: None)(contract, bar)
                        failure = self.ingest(contract, bar, now=observed or self._clock())
                        if failure is not None:
                            raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
        except Exception:  # retain provider/buffer; an unknown shutdown is never retried
            self._fail_closed_retirement()
            raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN') from None
        self._provider = None
        self._channels = set()
        now = self._clock()
        self._publish_heartbeat(now, self._phases(now))

    def _publish_heartbeat(self, now, phases):
        trading = any(item.phase is MarketPhase.TRADING for item in phases.values())
        fresh = not trading or (self._last_input_received_at is not None and
            timedelta(0) <= now - self._last_input_received_at <= timedelta(minutes=5))
        self._store.set_heartbeat({
            'generated_at': now.astimezone(UTC).isoformat(), **runtime_heartbeat_identity(),
            'operational_count': len(self._products), 'subscribed_count': len(self._channels),
            'last_input_received_at': self._last_input_received_at.isoformat() if self._last_input_received_at else None,
            'phase_by_product': {symbol: phase.phase.value for symbol, phase in phases.items()},
            'available': bool(fresh and self._available and self._provider_available and
                self._input_failure is None and self._metadata_preparation_error is None and
                all(item.phase is not MarketPhase.UNKNOWN for item in phases.values())),
            'input_failure': self._input_failure,
            'input_pending_count': len(self._pending) + len(getattr(self._provider, '_messages', ())),
            'closed_cleaned': self.closed_cleaned_proof,
        })

    def poll(self, now):
        if self._input_failure is not None:
            return self._reject(self._input_failure)
        try:
            self._observe_old_day_cleanup()
        except Exception:
            self._fail_closed_retirement()
            return self._reject(self._input_failure)
        isolation = self._cleanup_isolation
        if isolation is not None and not self._retire_closed_provider():
            return _reject_closed_cleanup(self, now, self._phases(now))
        # Only a real bounded join advances the observation clock. Cold starts
        # keep their caller's exact timestamp and create no provider at all.
        if isolation is not None and not isolation.retired and isolation.provider is not None:
            now = max(now, self._clock())
        phases = self._phases(now)
        proof = _closed_cleaned_idle_proof(self, self.source_stream, now, phases)
        if proof is not None:
            if hasattr(self, 'assert_owned'):
                self.assert_owned()
            _accept_closed_cleaned(self, proof, now, phases)
            return None
        if isolation is not None:
            if not any(p.trading_day is not None and p.trading_day > isolation.day
                       for p in phases.values()):
                return _reject_closed_cleanup(self, now, phases)
            # Retirement permits a genuine new-day handshake, not old-day reuse
            # or a claim that the unavailable cleanup callback succeeded.
            self._cleanup_isolation = None
        if _closed_cleanup_requires_proof(self, self.source_stream, phases):
            return _reject_closed_cleanup(self, now, phases)
        self.closed_cleaned_proof = None
        self._closed_restore_day = None
        return super().poll(now)

    def _reconcile_prepared(self, now):
        if hasattr(self, 'assert_owned'):
            self.assert_owned()
        return super()._reconcile_prepared(now)

    def _restore_break_identity(self, phases):
        # CLOSED still carries the proven current Calendar day; it must not
        # initialize a future day inferred from an upcoming Session.
        if phases and all(p.phase in (MarketPhase.BREAK, MarketPhase.CLOSED) for p in phases.values()):
            days = {p.trading_day for p in phases.values() if p.trading_day is not None}
            if len(days) > 1:
                return "LIVE_TRADING_DAY_INCONSISTENT"
            if days:
                if all(phase.phase is MarketPhase.CLOSED for phase in phases.values()):
                    self._closed_restore_day = next(iter(days))
                return self._restore_frozen_day(next(iter(days)))
        return super()._restore_break_identity(phases)

    def _restore_frozen_day(self, trading_day):
        if self._trading_day != trading_day:
            streams = (self.source_stream, ObservationStream(self.source_stream.redis, kind='completed'))
            # Prove every registered prior consumer is at its real tail before
            # the producer creates even the target subscription snapshot.
            for stream in streams:
                prefix = f"live:observations:registered:{stream.kind}:"
                for raw in stream.redis.scan_iter(match=prefix + '*'):
                    key = raw.decode() if isinstance(raw, bytes) else raw
                    consumer = key[len(prefix):]
                    previous = stream.registered_day(consumer)
                    if previous > trading_day:
                        return "OBSERVATION_DAY_REGRESSION"
                    if previous < trading_day and stream.cursor(consumer, previous) != stream.tail(previous):
                        return "OBSERVATION_DAY_BASELINE_UNPROVEN"
                    if previous < trading_day and any(stream.redis.exists(key) for key in
                            (stream.key(trading_day), stream.identity_key(trading_day), stream.cursor_key(consumer, trading_day))):
                        return "OBSERVATION_DAY_BASELINE_UNPROVEN"
            mapping = {}
            try:
                for symbol in self._products:
                    contract = self._dominant_source.dominant_for_day(symbol, trading_day)
                    if normalize_contract_for_symbol(symbol, contract) != contract:
                        raise ValueError("LIVE_RANK1_CONTRACT_INVALID")
                    if self._coverage_session_source is None or not self._coverage_session_source(symbol, trading_day):
                        raise ValueError("LIVE_SESSION_AUTHORITY_UNAVAILABLE")
                    mapping[symbol] = contract
            except Exception:
                return "LIVE_RANK1_CATALOG_UNAVAILABLE"
            if hasattr(self, 'assert_owned'):
                self.assert_owned()
            snapshot = self._store.subscriptions(trading_day)
            if snapshot is None:
                if (self._closed_restore_day == trading_day
                        and self.source_stream.registered_day('live') == trading_day):
                    return 'OBSERVATION_CLEANUP_UNPROVEN'
                # Atomic absence-only creation. Another mapping is never replaced.
                self.source_stream.redis.eval(
                    "if redis.call('EXISTS', KEYS[1]) == 0 then "
                    "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]); return 1 end; return 0",
                    1, self._store._subscription_key(trading_day), _compact_json(mapping), TTL_SECONDS,
                )
                snapshot = self._store.subscriptions(trading_day)
            if snapshot != mapping:
                return "OBSERVATION_SUBSCRIPTION_CONFLICT"
            for stream in streams:
                stream.prepare_registered_day(trading_day)
        return super()._restore_frozen_day(trading_day)

    def ingest(self, contract: str, bar: CanonicalBar, *, now: datetime) -> str | None:
        failure = super().ingest(contract, bar, now=now)
        if failure is not None:
            return failure
        symbol = next(item for item, value in self._contracts.items() if value == contract)
        observed_at = now
        if self._provider is not None and hasattr(self._provider, 'source_observed_at'):
            observed_at = self._provider.source_observed_at(contract, bar) or now
        data: dict[str, Any] = _bar_payload(bar, contract=contract)
        data['subscription_snapshot'] = dict(self._contracts)
        content = _compact_json(data)
        identity = sha256(content.encode()).hexdigest()
        if hasattr(self, 'assert_owned'):
            self.assert_owned()
        try:
            self.source_stream.append(ObservationEnvelope(identity, bar.trading_day, observed_at,
                                                          live_bar_channel(symbol, '1m'), data, True,
                                                          raw_received_at=observed_at))
        except Exception as exc:  # noqa: BLE001 - unknown input publication requires readback
            self._input_failure = str(exc) if isinstance(exc, ValueError) else 'OBSERVATION_COMMIT_UNKNOWN'
            raise

        self._last_input_received_at = max(self._last_input_received_at or observed_at, observed_at)
        self._pending.pop((symbol, bar.bar_end))
        return None

    def quiescent(self, now: datetime) -> bool:
        """Read-only proof used by the migration coordinator."""
        phases = self._phases(now)
        if self._coverage_session_source is None:
            return False
        for symbol, phase in phases.items():
            if phase.trading_day is None or phase.phase not in (MarketPhase.BREAK, MarketPhase.CLOSED):
                return False
            try:
                windows = self._coverage_session_source(symbol, phase.trading_day)
            except Exception:  # noqa: BLE001 - missing Session authority cannot prove a quiet window
                return False
            if not windows or any(window.end <= now < window.end + timedelta(seconds=60) for window in windows):
                return False
        return bool(phases) and not self._pending and all(
            item.phase in (MarketPhase.BREAK, MarketPhase.CLOSED)
            for item in phases.values()
        ) and not self._channels_in_session_grace(now) and not (
            self._provider is not None and bool(getattr(self._provider, '_messages', None))
        )


class StreamLiveProvider:
    """Input journal adapter. Cursor commits belong to the atomic Live publisher."""
    def __init__(self, stream: ObservationStream, *, consumer: str = 'live') -> None:
        self.stream = stream
        self.consumer = consumer
        self.day: date | None = None
        self.after: str | None = None
        self.events: dict[tuple[str, datetime], ObservationEnvelope] = {}
        self.records: deque[tuple[str, tuple[str, datetime]]] = deque()

    def subscribe(self, channels):
        pass

    def unsubscribe(self, channels):
        pass

    def close(self):
        pass

    def select_day(self, day: date) -> None:
        if self.day != day:
            self.day = day
            self.after = self.stream.cursor(self.consumer, day)
            self.events.clear()
            self.records.clear()

    def poll(self):
        if self.day is None:
            raise ValueError('OBSERVATION_DAY_MISSING')
        frontier = self.stream.tail(self.day)
        latest = {}
        count = 0
        while self.after != frontier:
            events = self.stream.read(self.consumer, self.day, count=1024, after=self.after, through=frontier)
            if not events:
                break
            count += len(events)
            if count > DAILY_LIMIT:
                raise ValueError('OBSERVATION_CAPACITY_EXCEEDED')
            for event in events:
                if not event.notification_eligible:
                    raise ValueError('OBSERVATION_SOURCE_IDENTITY_INVALID')
                contract = event.data['contract']
                bar = _bar_from_payload(_compact_json(event.data))
                key = (contract, bar.bar_end)
                self.events[key] = event
                self.records.append((event.stream_id, key))
                latest[key] = bar
            self.after = events[-1].stream_id
        # A frozen input frontier must be read fully before deciding which raw
        # revision is final; page boundaries must never become bar boundaries.
        return tuple((contract, bar) for (contract, _), bar in latest.items())

    poll_buffered = poll


class DurableLiveMarketService(LiveMarketService):
    def __init__(self, *, source_provider: StreamLiveProvider, closed_cleanup_evidence=None, **kwargs: Any) -> None:
        super().__init__(provider_factory=lambda: source_provider, **kwargs)
        self.source_provider = source_provider
        self.completed_stream = ObservationStream(self._store._redis, kind='completed')
        self._halted: str | None = None
        self._durable_session_day: date | None = None
        self.closed_cleanup_evidence = closed_cleanup_evidence
        self.closed_cleaned_proof = None
        self._closed_cleaned_day = None

    def _retire_closed_provider(self) -> bool:
        source = self.source_provider
        if hasattr(self, 'assert_owned'):
            self.assert_owned()
        try:
            day = source.day or self._trading_day or source.stream.registered_day(source.consumer)
            if (self._provider is not source or source.records or source.events
                    or source.stream.cursor(source.consumer, day) != source.stream.tail(day)):
                raise ValueError('OBSERVATION_CLEANUP_UNPROVEN')
            source.close()  # This adapter has no socket/listener or background input.
        except Exception:
            self._halted = 'OBSERVATION_CLEANUP_UNPROVEN'
            return False
        self._provider = None
        self._channels = set()
        return True

    def _restore_frozen_day(self, trading_day: date) -> str | None:
        failure = super()._restore_frozen_day(trading_day)
        if failure or self._durable_session_day == trading_day:
            return failure
        if self._coverage_session_source is not None:
            # Restarted journal consumers have not observed the old Session.
            # Load its existing Calendar/Session authority before accepting a
            # final raw bar in the unchanged Session-end arrival grace.
            restored = {}
            try:
                for symbol in self._contracts:
                    windows = self._coverage_session_source(symbol, trading_day)
                    if not windows or tuple(sorted(windows, key=lambda w: w.start)) != windows:
                        raise ValueError("LIVE_SESSION_AUTHORITY_INVALID")
                    if any(left.end > right.start for left, right in zip(windows, windows[1:])):
                        raise ValueError("LIVE_SESSION_AUTHORITY_INVALID")
                    restored[(symbol, trading_day)] = windows
            except Exception:
                return "LIVE_SESSION_AUTHORITY_UNAVAILABLE"
            self._known_sessions.update(restored)
        self._durable_session_day = trading_day
        return None

    def poll(self, now: datetime) -> str | None:
        if self._halted:
            return self._reject(self._halted)
        # Independent of phase: a resumed process may first run in the next
        # Session. Never let select_day clear unresolved old-day memory/cursor.
        source = self.source_provider
        try:
            registered = source.stream.registered_day(source.consumer)
            original_day = source.day or self._trading_day or registered
            if self._store.subscriptions(original_day) is None:
                if (source.records or source.events or self._pending
                        or source.stream.cursor(source.consumer, original_day) != source.stream.tail(original_day)
                        or self._provider is not None and self._provider is not source):
                    raise ValueError('OBSERVATION_CLEANUP_UNPROVEN')
                if self._provider is source and not self._retire_closed_provider():
                    raise ValueError('OBSERVATION_CLEANUP_UNPROVEN')
        except Exception:
            self._halted = 'OBSERVATION_CLEANUP_UNPROVEN'
            return self._reject(self._halted)
        phases = self._phases(now)
        if not self.source_provider.records and not self.source_provider.events:
            proof = _closed_cleaned_idle_proof(self, self.source_provider.stream, now, phases)
            if proof is not None:
                if hasattr(self, 'assert_owned'):
                    self.assert_owned()
                day = _accept_closed_cleaned(self, proof, now, phases)
                self.source_provider.select_day(day)
                return None
        if _closed_cleanup_requires_proof(self, self.source_provider.stream, phases):
            source = self.source_provider
            try:
                day = source.stream.registered_day(source.consumer)
                unsettled = (source.records or source.events or self._pending
                             or source.stream.cursor(source.consumer, day) != source.stream.tail(day))
            except Exception:
                unsettled = True
            if unsettled:
                # Never drain a retained old-day record after its cleanup, even
                # if a later Session would otherwise release the CLOSED fence.
                self._halted = 'OBSERVATION_CLEANUP_UNPROVEN'
            return _reject_closed_cleanup(self, now, phases)
        self.closed_cleaned_proof = None
        failure = self._prepare_metadata(now)
        if failure:
            return failure
        try:
            phases = self._phases(now)
            source = self.source_provider
            registered_day = source.stream.registered_day(source.consumer)
            persisted = source.stream.cursor(source.consumer, registered_day)
            backlog = source.stream.tail(registered_day) != persisted
            if backlog or self._pending:
                # Drain the frozen previous subscription before a newer Session
                # day can replace its contract identity. Source time, not current
                # wall time, resolves the old observation's Session window.
                failure = self._restore_frozen_day(registered_day)
                if failure:
                    return self._reject(failure)
                source.select_day(registered_day)
            else:
                trading_days = {p.trading_day for p in phases.values() if p.trading_day is not None}
                for symbol, phase in phases.items():
                    if phase.phase is MarketPhase.CLOSED and phase.trading_day is None:
                        start = phase.next_session_start
                        if start is None or start <= now:
                            raise ValueError('OBSERVATION_DAY_MISSING')
                        upcoming = self._phase_resolver.resolve(symbol, start)
                        if (upcoming.phase is not MarketPhase.TRADING or upcoming.trading_day is None
                                or upcoming.current_session is None or upcoming.current_session.start != start):
                            raise ValueError('OBSERVATION_DAY_MISSING')
                        trading_days.add(upcoming.trading_day)
                if (len(trading_days) > 1 and all(p.phase in (MarketPhase.CLOSED, MarketPhase.BREAK)
                                                for p in phases.values())):
                    raise ValueError('LIVE_TRADING_DAY_INCONSISTENT')
                if any(day > registered_day for day in trading_days):
                    # The feed owns atomic day initialization after every prior
                    # consumer is drained. Waiting here permits that handshake;
                    # it never invents a cursor or acknowledges unseen input.
                    self._available = False
                    self._publish_heartbeat(now, phases)
                    return self._reject('OBSERVATION_DAY_AWAITING_FEED')
                if phases and all(p.phase in (MarketPhase.CLOSED, MarketPhase.BREAK)
                                  for p in phases.values()):
                    # Restarts in a quiet window have no TRADING phase to select
                    # a day. Restore only the already registered input identity,
                    # with the same Session and frozen-subscription authority.
                    if trading_days != {registered_day} or any(
                            p.phase is MarketPhase.BREAK and p.trading_day is None for p in phases.values()):
                        raise ValueError('OBSERVATION_DAY_MISSING')
                    frozen = self._store.subscriptions(registered_day)
                    if frozen is None or set(frozen) != set(self._products):
                        raise ValueError('OBSERVATION_SUBSCRIPTION_MISSING')
                    failure = self._restore_frozen_day(registered_day)
                    if failure:
                        return self._reject(failure)
                    self._available = True
                failure = self._reconcile_prepared(now)
                if failure:
                    return self._reject(failure)
                if self._trading_day is None:
                    return self._reject('OBSERVATION_DAY_MISSING')
                source.select_day(self._trading_day)
            for contract, bar in source.poll():
                event = source.events[(contract, bar.bar_end)]
                if event.data['subscription_snapshot'] != self._contracts:
                    raise ValueError('OBSERVATION_SUBSCRIPTION_CONFLICT')
                failure = self.ingest(contract, bar, now=event.source_observed_at)
                if failure == 'LIVE_BAR_FINALIZED':
                    existing = self._store.bars_between(bar.trading_day, event.channel.split(':')[2],
                        '1m', bar.bar_end, bar.bar_end)
                    if existing != (bar,):
                        raise ValueError('OBSERVATION_CONTENT_CONFLICT')
                elif failure:
                    self._halted = failure
                    return failure
            self.flush_due(now, phases=phases)
            if self._last_flush_failed:
                return 'LIVE_REDIS_UNAVAILABLE'
            # Empty/duplicate inputs still require a CAS progress commit.
            self._commit((), completed_keys=set(), confirmed_at=now)
            failure = self._schedule_recovery_safely(now, phases)
            self._publish_heartbeat(now, phases)
            return failure
        except Exception as exc:  # noqa: BLE001 - explicit journal failure boundary
            self._available = False
            code = str(exc) if isinstance(exc, ValueError) else 'OBSERVATION_COMMIT_UNKNOWN'
            self._halted = code
            return self._reject(code)

    def _flush_pending(self, now, phases, pending):
        due = [(key, bar, window, contract) for key, (bar, window, contract) in pending
               if (now - bar.bar_end).total_seconds() >= 2]
        if not due:
            return ()
        plan = []
        try:
            for (symbol, _), bar, window, contract in due:
                event = self.source_provider.events[(contract, bar.bar_end)]
                plan.append((symbol, BarFrequency.M1, bar, contract, event.source_observed_at))
                for frequency in (BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1):
                    bucket = bucket_window_for_bar(window, frequency, bar.bar_end)
                    if bar.bar_end != bucket.end:
                        continue
                    existing = {item.bar.bar_end: item.bar for item in self._store.bar_observations(
                        bar.trading_day, symbol, '1m', bucket.start, bucket.end,
                        inclusive_after=False, expected_contract=contract)}
                    # Include completed facts in this atomic batch before deriving.
                    existing.update({b.bar_end: b for (s, _), b, _, c in due
                                     if s == symbol and c == contract and bucket.start < b.bar_end <= bucket.end})
                    ends = tuple(bucket.start + timedelta(minutes=m) for m in range(
                        1, int((bucket.end - bucket.start).total_seconds() // 60) + 1))
                    if tuple(sorted(existing)) != ends:
                        continue
                    derived = aggregate_from_1m(tuple(existing[end] for end in ends),
                                                target_frequency=frequency, sessions=(bucket,))[0]
                    plan.append((symbol, frequency, derived, contract, event.source_observed_at))
            completed_keys = {(contract, bar.bar_end) for _, bar, _, contract in due}
            self._available = True
            previous_last_bar = self._last_bar_at
            self._last_bar_at = max([b.bar_end for _, b, _, _ in due] +
                                    ([previous_last_bar] if previous_last_bar else []))
            # Pub/Sub is only a wakeup, but legacy typed readers still require
            # readiness before any trigger can become visible.
            self._publish_heartbeat(now, phases or self._phases(now))
            self._commit(plan, completed_keys=completed_keys, confirmed_at=now)
            for key, bar, _, _ in due:
                self._pending.pop(key)
                self._finalized.add(key)
                self._coverage_dirty.add(key[0])
                self._last_bar_at = max(self._last_bar_at or bar.bar_end, bar.bar_end)
            self._publish_heartbeat(now, phases or self._phases(now))
            return tuple(item[1] for item in due)
        except Exception as exc:  # noqa: BLE001 - unknown commit requires readback, never automatic retry
            self._halted = str(exc) if isinstance(exc, ValueError) else 'OBSERVATION_COMMIT_UNKNOWN'
            self._last_flush_failed = True
            self._mark_redis_unavailable(now, phases)
            return ()

    def _commit(self, observations, *, completed_keys, confirmed_at):
        source = self.source_provider
        if source.day is None:
            raise ValueError('OBSERVATION_DAY_MISSING')
        stream = source.stream
        old = stream.cursor(source.consumer, source.day)
        finalized_keys = {(self._contracts[symbol], end) for symbol, end in self._finalized}
        eligible = finalized_keys | completed_keys
        next_id = old
        for identifier, key in source.records:
            if key not in eligible:
                break
            next_id = identifier
        keys = [stream.cursor_key(source.consumer, source.day), stream.key(source.day),
                self.completed_stream.key(source.day), self.completed_stream.identity_key(source.day)]
        plan = []
        for symbol, frequency, bar, contract, observed_at in observations:
            key = self._store._bars_key(bar.trading_day, symbol, frequency)
            if key not in keys:
                keys.append(key)
            payload = _bar_payload(bar, contract=contract)
            channel = live_bar_channel(symbol, frequency)
            identity = f'{bar.trading_day}:{contract}:{frequency.value}:{bar.bar_end.isoformat()}'
            score = _epoch_millis(bar.bar_end)
            serialized_payload = _compact_json(payload)
            existing_bars = stream.redis.zrangebyscore(key, score, score)
            if existing_bars:
                if len(existing_bars) != 1 or not _equivalent_bar_payload(json.loads(existing_bars[0]), payload):
                    raise ValueError('OBSERVATION_CONTENT_CONFLICT')
                # The Lua transaction still requires this exact value: a later writer cannot bypass CAS.
                serialized_payload = existing_bars[0]
                if isinstance(serialized_payload, bytes):
                    serialized_payload = serialized_payload.decode()
            expected_payload = serialized_payload if existing_bars else None
            original_confirmation = confirmed_at
            existing = stream.redis.hget(self.completed_stream.identity_key(source.day), identity)
            if existing is not None:
                record = json.loads(existing)
                prior = ObservationEnvelope.from_json(record['payload'])
                original_confirmation = prior.confirmed_at
            envelope = ObservationEnvelope(identity, bar.trading_day, observed_at, channel, payload, True,
                                           raw_received_at=observed_at, confirmed_at=original_confirmation)
            serialized_envelope = envelope.to_json()
            if existing is not None:
                # Preserve the old envelope byte-for-byte, including first arrival and confirmation.
                if (not _equivalent_bar_payload(prior.data, payload)
                        or replace(prior, data=payload, stream_id='').to_json() != serialized_envelope):
                    raise ValueError('OBSERVATION_CONTENT_CONFLICT')
                serialized_envelope = record['payload']
            plan.append({'key_index': keys.index(key) + 1, 'score': score,
                         'payload': serialized_payload, 'expected_payload': expected_payload, 'identity': identity,
                         'channel': channel, 'envelope': serialized_envelope})
        if hasattr(self, 'assert_owned'):
            self.assert_owned()
        result = stream.redis.eval(COMMIT_OBSERVATIONS, len(keys), *keys, old, next_id,
                                   _compact_json(plan), TTL_SECONDS, DAILY_LIMIT)
        if result != 1:
            raise ValueError({-1: 'OBSERVATION_CONTENT_CONFLICT', -2: 'OBSERVATION_CURSOR_DRIFT',
                              -3: 'OBSERVATION_CAPACITY_EXCEEDED', -4: 'OBSERVATION_KEY_TYPE_INVALID'}.get(
                                  result, 'OBSERVATION_COMMIT_UNKNOWN'))
        while source.records and tuple(map(int, source.records[0][0].split('-'))) <= tuple(map(int, next_id.split('-'))):
            source.records.popleft()
        remaining = {key for _, key in source.records}
        for key in tuple(source.events):
            if key not in remaining:
                source.events.pop(key)
