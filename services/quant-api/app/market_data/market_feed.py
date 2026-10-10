"""Optional independent RQData feed and durable Live computation composition."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from collections import deque
from hashlib import sha256
import json
from typing import Any

from app.market_data.aggregation import aggregate_from_1m, bucket_window_for_bar
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.captured_recovery_runtime import runtime_heartbeat_identity
from app.market_data.live_market import (
    LiveMarketService, LiveProvider, RedisLiveStore, _bar_from_payload, _bar_payload, _compact_json,
    _epoch_millis, live_bar_channel,
)
from app.market_data.live_recovery_scripts import COMMIT_OBSERVATIONS
from app.market_data.market_phase import MarketPhase
from app.market_data.observation_stream import (
    DAILY_LIMIT, TTL_SECONDS, ObservationEnvelope, ObservationStream,
)


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

    def __init__(self, *, source_stream: ObservationStream, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.source_stream = source_stream
        self._input_failure: str | None = None
        self._last_input_received_at: datetime | None = None

    def _discard_provider(self) -> None:
        """Never declare the feed parked until the sole reader actually retires."""
        provider = self._provider
        if provider is None:
            return
        try:
            verifier = getattr(provider, 'close_verified', None)
            if verifier is None:
                raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
            verifier()
            # A callback may have accepted a final raw input during close. Once
            # the listener is dead its remaining buffer is finite and must reach
            # the journal before ownership can be handed off.
            drain = getattr(provider, 'poll_buffered', None)
            if drain is not None:
                for contract, bar in drain():
                    observed = getattr(provider, 'source_observed_at', lambda *_: None)(contract, bar)
                    failure = self.ingest(contract, bar, now=observed or self._clock())
                    if failure is not None:
                        raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
        except Exception:  # noqa: BLE001 - retain the provider and reject further mutations
            self._input_failure = 'LIVE_PROVIDER_CLOSE_UNKNOWN'
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
        })

    def poll(self, now):
        if self._input_failure is not None:
            return self._reject(self._input_failure)
        return super().poll(now)

    def _reconcile_prepared(self, now):
        if hasattr(self, 'assert_owned'):
            self.assert_owned()
        return super()._reconcile_prepared(now)

    def _restore_frozen_day(self, trading_day):
        if self._trading_day != trading_day:
            self.source_stream.prepare_registered_day(trading_day)
            ObservationStream(self.source_stream.redis, kind='completed').prepare_registered_day(trading_day)
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
    def __init__(self, *, source_provider: StreamLiveProvider, **kwargs: Any) -> None:
        super().__init__(provider_factory=lambda: source_provider, **kwargs)
        self.source_provider = source_provider
        self.completed_stream = ObservationStream(self._store._redis, kind='completed')
        self._halted: str | None = None

    def poll(self, now: datetime) -> str | None:
        if self._halted:
            return self._reject(self._halted)
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
                if any(day > registered_day for day in trading_days):
                    # The feed owns atomic day initialization after every prior
                    # consumer is drained. Waiting here permits that handshake;
                    # it never invents a cursor or acknowledges unseen input.
                    self._available = False
                    self._publish_heartbeat(now, phases)
                    return self._reject('OBSERVATION_DAY_AWAITING_FEED')
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
            return self._schedule_recovery_safely(now, phases)
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
            original_confirmation = confirmed_at
            existing = stream.redis.hget(self.completed_stream.identity_key(source.day), identity)
            if existing is not None:
                record = json.loads(existing)
                prior = ObservationEnvelope.from_json(record['payload'])
                original_confirmation = prior.confirmed_at
            envelope = ObservationEnvelope(identity, bar.trading_day, observed_at, channel, payload, True,
                                           raw_received_at=observed_at, confirmed_at=original_confirmation)
            plan.append({'key_index': keys.index(key) + 1, 'score': _epoch_millis(bar.bar_end),
                         'payload': _compact_json(payload), 'identity': identity,
                         'channel': channel, 'envelope': envelope.to_json()})
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
