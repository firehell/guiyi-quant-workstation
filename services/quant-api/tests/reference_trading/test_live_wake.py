from datetime import date, datetime, timezone
from decimal import Decimal
import os
from types import SimpleNamespace
import json

from app.reference_trading.live_wake import ForwardLiveWake
from app.market_data.domain import CanonicalBar
from app.market_data.live_market import RedisLiveStore


class PubSub:
    def __init__(self):
        self.messages = [{"type": "psubscribe"}]
        self.closed = False

    def psubscribe(self, pattern):
        assert pattern == "live:bar:*"

    def get_message(self, *, timeout):
        return self.messages.pop(0) if self.messages else None

    def close(self):
        self.closed = True


class Redis:
    def __init__(self):
        self.source = PubSub()

    def pubsub(self, *, ignore_subscribe_messages):
        assert ignore_subscribe_messages is False
        return self.source


class Repository:
    def enabled_forward_routes(self, product, frequency):
        return tuple(item for item in ("rb-60m", "rb-1d", "cu-60m")
                     if item == f"{product}-{frequency}")


class Worker:
    def __init__(self):
        self.wakes = []

    def wake(self, stream_id, *, kind, bar_end):
        self.wakes.append((stream_id, kind, bar_end))


class Market:
    def dominant_segment_for_day(self, symbol, trading_day):
        assert symbol == "rb" and trading_day == date(2026, 9, 23)
        return SimpleNamespace(contract="RB2610")


def test_completed_live_pubsub_wakes_only_exact_product_and_frequency():
    redis, worker = Redis(), Worker()
    wake = ForwardLiveWake(redis, Repository(), worker, Market())
    wake.subscribe()
    end = datetime(2026, 9, 23, 1, tzinfo=timezone.utc)
    payload = {"bar_end": end.isoformat(), "trading_day": "2026-09-23", "contract": "RB2610"}
    redis.source.messages.append({"type": "pmessage", "channel": b"live:bar:rb:60m",
                                  "data": json.dumps(payload).encode()})
    wake.wait(5)
    assert worker.wakes == [("rb-60m", "live_event", end)]
    redis.source.messages.append({"type": "pmessage", "channel": b"live:bar:rb:60m",
                                  "data": json.dumps({**payload, "contract": "RB2701"}).encode()})
    wake.wait(5)
    assert len(worker.wakes) == 1
    wake.close()
    assert redis.source.closed


def test_isolated_redis_publish_bar_reaches_exact_forward_wake():
    url = os.getenv("GUIYI_ISOLATED_REDIS_URL")
    if not url:
        import pytest
        pytest.skip("GUIYI_ISOLATED_REDIS_URL is required")
    from redis import Redis

    redis = Redis.from_url(url)
    worker = Worker()
    wake = ForwardLiveWake(redis, Repository(), worker, Market())
    end = datetime(2026, 9, 23, 1, tzinfo=timezone.utc)
    bar = CanonicalBar(
        end, date(2026, 9, 23), Decimal("3500"), Decimal("3510"),
        Decimal("3490"), Decimal("3505"), Decimal("100"), None, None,
    )
    try:
        wake.subscribe()
        RedisLiveStore(redis).publish_bar("rb", "60m", bar, contract="RB2610")
        wake.wait(2)
        assert worker.wakes == [("rb-60m", "live_event", end)]
    finally:
        wake.close()
        redis.close()


def _durable_wake_with_backlog(*, background_busy=False):
    from app.reference_trading.live_wake import StreamForwardLiveWake
    from app.reference_trading.runtime import ForwardReferenceWorker
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    end = datetime(2026, 9, 23, 1, tzinfo=timezone.utc)
    seen, acknowledgements = [], []
    repository = Repository()
    repository.read_pending_capture = lambda _: None
    repository.enabled_forward_stream_ids = lambda **_: ()
    def read(stream_id, *_):
        seen.append(stream_id)
        if stream_id.startswith('canonical') and background_busy:
            raise ForwardInputUnavailable('SOURCE_BUSY')
        return None
    worker = ForwardReferenceWorker(repository, lambda _: SimpleNamespace(), read, enabled=True)
    for index in range(112):
        worker.wake(f'canonical-{index:03}')
    observation = SimpleNamespace(notification_eligible=True, confirmed_at=end,
        source_observed_at=end, stream_id='1-0', channel='live:bar:rb:60m',
        data={'bar_end': end.isoformat(), 'trading_day': '2026-09-23', 'contract': 'RB2610'})
    wake = StreamForwardLiveWake.__new__(StreamForwardLiveWake)
    wake.stop_requested = lambda: False
    wake._repository, wake._worker, wake._market_data = repository, worker, Market()
    wake._stream = SimpleNamespace(days=lambda: (end.date(),), cursor=lambda *_: '0-0',
        read=lambda *_, **__: (observation,), ack=lambda *args, **kwargs: acknowledgements.append((args, kwargs)))
    return wake, worker, seen, acknowledgements


def test_durable_observation_precedes_unrelated_canonical_backlog():
    wake, worker, seen, acknowledgements = _durable_wake_with_backlog()
    wake.wait(1)
    assert seen == ['rb-60m']
    assert worker.health().pending_keys == 112
    assert len(acknowledgements) == 1


def test_unrelated_canonical_source_busy_does_not_block_observation_ack():
    wake, worker, seen, acknowledgements = _durable_wake_with_backlog(background_busy=True)
    worker._blocked['canonical-000'] = 'SOURCE_BUSY'
    wake.wait(1)
    assert seen == ['rb-60m']
    assert worker.health().blocked == (('canonical-000', 'SOURCE_BUSY'),)
    assert len(acknowledgements) == 1


def test_target_failure_keeps_observation_unacknowledged_and_resets_timing():
    import pytest
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    wake, worker, seen, acknowledgements = _durable_wake_with_backlog()
    def unavailable(*_):
        raise ForwardInputUnavailable('LIVE_EVENT_IDENTITY_CONFLICT')
    worker._read_input = unavailable
    with pytest.raises(RuntimeError, match='REFERENCE_BUFFER_PROCESSING_BLOCKED'):
        wake.wait(1)
    assert seen == [] and acknowledgements == []
    assert worker.source_observed_at is None and worker.raw_received_at is None
    assert ('rb-60m', 'LIVE_EVENT_IDENTITY_CONFLICT') in worker.health().blocked


def test_durable_observation_preserves_original_timing_and_ack_cas():
    from datetime import timedelta
    wake, worker, seen, acknowledgements = _durable_wake_with_backlog()
    observation = wake._stream.read()[0]
    observation.source_observed_at -= timedelta(seconds=31)
    timing = []
    worker._read_input = lambda *_: timing.append((worker.source_observed_at, worker.raw_received_at))
    wake.wait(1)
    assert timing == [(observation.confirmed_at, observation.source_observed_at)]
    assert acknowledgements[0][1] == {'expected_cursor': '0-0', 'next_id': '1-0'}
    assert worker.source_observed_at is None and worker.raw_received_at is None


def test_no_ack_when_formal_ownership_is_rejected():
    import pytest
    wake, worker, _, acknowledgements = _durable_wake_with_backlog()
    def reject():
        raise RuntimeError('RUNTIME_GENERATION_CHANGED')
    worker.assert_owned = reject
    with pytest.raises(RuntimeError, match='RUNTIME_GENERATION_CHANGED'):
        wake.wait(1)
    assert acknowledgements == []


def test_pending_capture_finishes_before_current_observation_is_read():
    wake, worker, _, acknowledgements = _durable_wake_with_backlog()
    pending = {'rb-60m': object()}
    events = []
    worker._repository.read_pending_capture = lambda route: pending.get(route)
    def consume(route):
        events.append(('pending', route))
        pending.pop(route)
        return object()
    worker._service_for = lambda _: SimpleNamespace(process_pending=consume)
    worker._read_input = lambda route, kind, end: events.append(('read', route, kind, end))
    wake.wait(1)
    assert events[0] == ('pending', 'rb-60m')
    assert events[1][0:3] == ('read', 'rb-60m', 'live_event')
    assert len(acknowledgements) == 1
    assert worker.health().pending_keys == 112


def test_observation_ack_unknown_does_not_repeat_processing():
    import pytest
    wake, _, seen, _ = _durable_wake_with_backlog()
    calls = []
    def unknown(*_, **__):
        calls.append('ack')
        raise OSError('UNKNOWN_COMMIT')
    wake._stream.ack = unknown
    with pytest.raises(OSError, match='UNKNOWN_COMMIT'):
        wake.wait(1)
    assert seen == ['rb-60m'] and calls == ['ack']


def test_recovery_observation_has_no_formal_processing():
    wake, _, seen, acknowledgements = _durable_wake_with_backlog()
    wake._stream.read()[0].notification_eligible = False
    wake.wait(1)
    assert seen == [] and len(acknowledgements) == 1


def test_conflicting_physical_contract_keeps_observation_unacknowledged():
    import pytest
    wake, _, seen, acknowledgements = _durable_wake_with_backlog()
    wake._stream.read()[0].data['contract'] = 'RB2701'
    with pytest.raises(RuntimeError, match='REFERENCE_BUFFER_IDENTITY_INVALID'):
        wake.wait(1)
    assert seen == [] and acknowledgements == []


def test_grouped_live_finishes_four_routes_with_remaining_and_old_pending_before_ack():
    from app.reference_trading.runtime import WorkerBudget
    wake, worker, _, acknowledgements = _durable_wake_with_backlog()
    routes = ('rb-trend', 'rb-oscillation', 'rb-main-rise', 'rb-fusion')
    key = 'newow:rb:60m'
    repository = worker._repository
    repository.forward_work_key = lambda route: key if route in routes else route
    repository.enabled_forward_work_routes = lambda group: routes if group == key else (group,)
    repository.enabled_forward_routes = lambda *_: routes
    worker._budget = WorkerBudget(max_units_per_round=2)
    pending = {routes[2]: object()}
    repository.read_pending_capture = lambda route: pending.get(route)
    seen, consumed = [], []
    def consume(route):
        consumed.append(route)
        pending.pop(route)
        return object()
    worker._service_for = lambda _: SimpleNamespace(process_pending=consume)
    worker._read_input = lambda route, kind, end: seen.append((route, kind, end))
    worker.wake(routes[0])
    worker.run_round(only_keys=(key,))
    assert worker._remaining[key] == routes[2:]
    real_ack = wake._stream.ack
    def ack(*args, **kwargs):
        assert [route for route, kind, _ in seen if kind == 'live_event'] == list(routes)
        real_ack(*args, **kwargs)
    wake._stream.ack = ack
    wake.wait(1)
    assert consumed == [routes[2]]
    assert [route for route, kind, _ in seen if kind == 'live_event'] == list(routes)
    assert all(route in routes for route, _, _ in seen)
    assert tuple(worker._queue) == tuple(f'canonical-{index:03}' for index in range(112))
    assert len(acknowledgements) == 1


def test_nonblocking_poll_bounds_and_consumes_no_route_observations_without_sleep(monkeypatch):
    from copy import deepcopy
    wake, worker, seen, acknowledgements = _durable_wake_with_backlog()
    original = wake._stream.read()[0]
    observations = [deepcopy(original) for _ in range(129)]
    for index, observation in enumerate(observations):
        observation.stream_id = f'{index + 1}-0'
    wake._repository.enabled_forward_routes = lambda *_: ()
    cursor = ['0-0']
    requests = []
    def read(*_, count):
        requests.append(count)
        start = int(cursor[0].split('-')[0])
        return tuple(observations[start:start + count])
    def ack(*args, **kwargs):
        assert kwargs['expected_cursor'] == cursor[0]
        cursor[0] = kwargs['next_id']
        acknowledgements.append(kwargs)
    wake._stream.cursor = lambda *_: cursor[0]
    wake._stream.read, wake._stream.ack = read, ack
    monkeypatch.setattr('time.sleep', lambda _: (_ for _ in ()).throw(AssertionError('nonblocking poll slept')))
    assert wake.poll() is True
    assert len(acknowledgements) == 128 and cursor[0] == '128-0'
    assert wake.poll() is False
    assert len(acknowledgements) == 129 and cursor[0] == '129-0'
    assert requests == [128, 128] and seen == []
    assert worker.health().pending_keys == 112


def test_drain_stops_claiming_next_observation_after_current_ack():
    from copy import deepcopy
    wake, _, seen, acknowledgements = _durable_wake_with_backlog()
    first = wake._stream.read()[0]
    second = deepcopy(first)
    second.stream_id = '2-0'
    wake._stream.read = lambda *_, **__: (first, second)
    wake.stop_requested = lambda: bool(acknowledgements)
    assert wake.poll() is True
    assert len(acknowledgements) == 1 and seen == ['rb-60m']


def test_isolated_redis_durable_poll_128_target_only_and_cursor_cas():
    """Real journal/Lua progress, with randomized keys on the dedicated test endpoint."""
    import pytest
    from urllib.parse import urlparse
    from uuid import uuid4
    from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
    from redis import Redis as RealRedis
    url = os.getenv('GUIYI_ISOLATED_REDIS_URL')
    if not url:
        pytest.skip('GUIYI_ISOLATED_REDIS_URL is required')
    parsed = urlparse(url)
    if (parsed.scheme != 'redis' or parsed.hostname != '127.0.0.1'
            or parsed.port != 16389 or parsed.path != '/11' or parsed.username or parsed.password):
        pytest.fail('ISOLATED_REDIS_ENDPOINT_REQUIRED')
    namespace = f'test:reference-poll:{uuid4().hex}:'
    wake, worker, seen, _ = _durable_wake_with_backlog(background_busy=True)
    worker._blocked['canonical-000'] = 'SOURCE_BUSY'
    day = date(2026, 9, 23)
    end = datetime(2026, 9, 23, 1, tzinfo=timezone.utc)
    class IsolatedStream(ObservationStream):
        def key(self, day):
            return namespace + super().key(day)
        def cursor_key(self, consumer, day):
            return namespace + super().cursor_key(consumer, day)
        def registration_key(self, consumer):
            return namespace + super().registration_key(consumer)
        def days(self):
            return (day,)
    redis = RealRedis.from_url(url)
    journal = IsolatedStream(redis, kind='completed')
    try:
        assert redis.ping()
        assert list(redis.scan_iter(match=namespace + '*')) == []
        journal.initialize('reference', day, cursor='0-0')
        ids = []
        for index in range(129):
            frequency = '1m' if index < 127 else '60m'
            ids.append(journal.append(ObservationEnvelope(
                str(index), day, end, f'live:bar:rb:{frequency}',
                {'bar_end': end.isoformat(), 'trading_day': day.isoformat(), 'contract': 'RB2610'},
                True, raw_received_at=end, confirmed_at=end)))
        wake._stream = journal
        assert wake.poll() is True
        assert journal.cursor('reference', day) == ids[127]
        assert seen == ['rb-60m']
        assert worker.health().pending_keys == 112
        assert worker.health().blocked == (('canonical-000', 'SOURCE_BUSY'),)
        with pytest.raises(ValueError, match='OBSERVATION_CURSOR_DRIFT'):
            journal.ack('reference', day, expected_cursor='0-0', next_id=ids[128])
        assert journal.cursor('reference', day) == ids[127]
        # A recreated reader uses committed progress; it does not repeat the first 128.
        wake._stream = IsolatedStream(redis, kind='completed')
        assert wake.poll() is False
        assert journal.cursor('reference', day) == ids[128]
        assert seen == ['rb-60m', 'rb-60m']
        assert worker.health().pending_keys == 112
    finally:
        keys = list(redis.scan_iter(match=namespace + '*'))
        if keys:
            redis.delete(*keys)
        redis.close()
