"""Existing provider retirement after cleanup; every dependency is in memory."""
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.market_data.live_market import RQDataLiveProvider
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
import app.market_data.market_feed as feed

DAY = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolate_runtime_guard_bindings(monkeypatch):
    """Temporary real flock tests must never resolve the workstation registry."""
    import app.runtime_bindings as bindings
    monkeypatch.setattr(bindings, 'read_bindings', lambda **kwargs: None)
    monkeypatch.delenv('GUIYI_RUNTIME_HANDOVER_ENABLED', raising=False)


class Redis:
    def scan_iter(self, *, match):
        return (['live:observations:registered:source:live'] if ':source:' in match
                else ['live:observations:registered:completed:alert',
                      'live:observations:registered:completed:reference'])


class Journal:
    def __init__(self, redis, *, kind):
        self.redis, self.kind = redis, kind
        self.behind = False

    def registered_day(self, consumer):
        return DAY

    def cursor(self, consumer, day):
        return '0-0' if self.behind else '1-0'

    def tail(self, day):
        return '1-0'


class Store:
    def __init__(self):
        self.cleaned = False
        self.heartbeats = []
        self._redis = Redis()

    def subscriptions(self, day):
        return None if self.cleaned else {'rb': 'RB2701'}

    def set_heartbeat(self, payload):
        self.heartbeats.append(payload)

    def recovery_state(self, *args):
        return None

    def bars_between(self, *args):
        return ()

    def publish_state(self, *args):
        raise AssertionError('no publication after cleanup')


class Client:
    def __init__(self):
        self.unsubscribe_calls = []
        self.close_calls = 0
        self.on_close = lambda: None

    def unsubscribe(self, channels):
        self.unsubscribe_calls.append(channels)

    def close(self):
        self.close_calls += 1
        self.on_close()


def make_service(monkeypatch, *, durable=False):
    monkeypatch.setattr(feed, 'ObservationStream', Journal)
    store = Store()
    phase = ProductMarketPhase('rb', MarketPhase.CLOSED, DAY, None, NOW + timedelta(hours=3))
    kwargs = dict(dominant_source=SimpleNamespace(dominant_for_day=lambda *_: 'RB2701'),
                  phase_resolver=SimpleNamespace(resolve=lambda *_: phase), store=store,
                  operational_products=('rb',), clock=lambda: NOW,
                  closed_cleanup_evidence=lambda *_: (
                      {'trading_day': DAY.isoformat(), 'cleanup_verified': True}
                      if store.cleaned else None))
    client = Client()
    if durable:
        source = feed.StreamLiveProvider(Journal(store._redis, kind='source'))
        service = feed.DurableLiveMarketService(source_provider=source, **kwargs)
        provider = source
        service._durable_session_day = DAY
        # Isolate lifecycle from the already-covered journal Lua CAS.
        monkeypatch.setattr(service, '_commit', lambda *args, **kwargs: None)
    else:
        provider = RQDataLiveProvider(client)
        service = feed.MarketFeedService(source_stream=Journal(store._redis, kind='source'),
                                        provider_factory=lambda: provider, shutdown_guard_factory=nullcontext, **kwargs)
    service._provider = provider
    service._trading_day = DAY
    service._contracts = {'rb': 'RB2701'}
    service._channels = {'bar_RB2701'}
    return service, store, provider, client


@pytest.mark.parametrize('durable', [False, True])
def test_natural_closed_unsubscribe_then_cleanup_retires_existing_provider(monkeypatch, durable):
    service, store, provider, client = make_service(monkeypatch, durable=durable)
    assert service.poll(NOW) is None
    assert service._channels == set()
    assert service._provider is provider
    store.cleaned = True
    assert service.poll(NOW + timedelta(seconds=1)) is None
    assert service._provider is None
    assert service.closed_cleaned_proof['status'] == 'CLOSED_CLEANED'
    assert store.heartbeats[-1]['available'] is True
    assert client.close_calls == (0 if durable else 1)


@pytest.mark.parametrize('arrival', ['before_close', 'during_close'])
def test_feed_late_buffer_is_preserved_and_never_written(monkeypatch, arrival):
    service, store, provider, client = make_service(monkeypatch)
    service._channels = set()
    store.cleaned = True
    message = {'late': 'original raw input'}
    if arrival == 'before_close':
        provider._buffer_message(message)
    else:
        client.on_close = lambda: provider._buffer_message(message)
    monkeypatch.setattr(service, 'ingest', lambda *a, **kw: pytest.fail('old-day write'))
    assert service.poll(NOW) is not None
    assert service._provider is provider
    assert len(provider._messages) == 1
    assert provider._messages[0][0] == message
    assert service.closed_cleaned_proof is None
    assert service._input_failure is not None
    assert service.poll(NOW + timedelta(days=1)) is not None
    assert len(provider._messages) == 1


def test_unknown_close_preserves_provider_and_blocks_next_day(monkeypatch):
    service, store, provider, client = make_service(monkeypatch)
    service._channels = set()
    store.cleaned = True
    def fail():
        raise RuntimeError('simulated close outcome unknown')
    client.on_close = fail
    assert service.poll(NOW) is not None
    assert service._provider is provider
    assert service._input_failure is not None
    assert service.poll(NOW + timedelta(days=1)) is not None


@pytest.mark.parametrize('defect', ['records', 'events', 'cursor'])
def test_durable_unsettled_input_never_retires_or_discards(monkeypatch, defect):
    service, store, provider, _ = make_service(monkeypatch, durable=True)
    service._channels = set()
    store.cleaned = True
    if defect == 'records':
        provider.records.append(('original', ('rb', NOW)))
    elif defect == 'events':
        provider.events[('rb', NOW)] = 'original'
    else:
        provider.stream.behind = True
    before = (tuple(provider.records), dict(provider.events))
    assert service.poll(NOW) is not None
    assert service._provider is provider
    assert (tuple(provider.records), provider.events) == before
    assert service.closed_cleaned_proof is None
    assert service._halted == 'OBSERVATION_CLEANUP_UNPROVEN'


def test_nonempty_pending_does_not_close_provider(monkeypatch):
    service, store, provider, client = make_service(monkeypatch)
    store.cleaned = True
    service._pending[('rb', NOW)] = 'original'
    assert service.poll(NOW) is not None
    assert client.close_calls == 0
    assert service._provider is provider


def test_retirement_failure_finally_does_not_drain_late_input(monkeypatch):
    service, store, provider, _ = make_service(monkeypatch)
    store.cleaned = True
    provider._buffer_message({'late': 'preserved'})
    assert service.poll(NOW) is not None
    monkeypatch.setattr(provider, 'poll_buffered', lambda: pytest.fail('buffer must not drain'))
    with pytest.raises(ValueError, match='LIVE_PROVIDER_CLOSE_UNKNOWN'):
        service._discard_provider()
    assert service._provider is provider
    assert len(provider._messages) == 1


def test_still_alive_listener_is_not_retired(monkeypatch):
    service, store, provider, _ = make_service(monkeypatch)
    store.cleaned = True
    provider._listener = SimpleNamespace(is_alive=lambda: True)
    real_close = provider.close_verified
    monkeypatch.setattr(provider, 'close_verified', lambda: real_close(timeout=0))
    assert service.poll(NOW) is not None
    assert service._provider is provider
    assert provider._listener.is_alive()
    assert service._input_failure == 'LIVE_PROVIDER_CLOSE_UNKNOWN'


def test_cleanup_authority_is_rechecked_after_close(monkeypatch):
    service, store, provider, client = make_service(monkeypatch)
    store.cleaned = True
    client.on_close = lambda: setattr(service, 'closed_cleanup_evidence', lambda *_: None)
    assert service.poll(NOW) is not None
    assert client.close_calls == 1
    assert service.closed_cleaned_proof is None
    assert store.heartbeats[-1]['available'] is False


def test_retirement_does_not_swallow_ownership_loss(monkeypatch):
    service, store, _, client = make_service(monkeypatch)
    store.cleaned = True
    def lost():
        raise RuntimeError('RUNTIME_OWNER_INVALID')
    service.assert_owned = lost
    with pytest.raises(RuntimeError, match='RUNTIME_OWNER_INVALID'):
        service.poll(NOW)
    assert client.close_calls == 0


def test_session_phase_is_rechecked_after_bounded_close(monkeypatch):
    service, store, _, client = make_service(monkeypatch)
    store.cleaned = True
    def session_started():
        service._phase_resolver = SimpleNamespace(resolve=lambda *_: ProductMarketPhase(
            'rb', MarketPhase.TRADING, DAY + timedelta(days=1), None, NOW + timedelta(days=1)))
    client.on_close = session_started
    assert service.poll(NOW) is not None
    assert service.closed_cleaned_proof is None


@pytest.mark.parametrize('late', [False, True])
def test_real_listener_thread_ends_before_empty_buffer_acceptance(monkeypatch, late):
    from threading import Event, Thread
    service, store, provider, client = make_service(monkeypatch)
    store.cleaned = True
    stop = Event()
    def listen():
        stop.wait()
        if late:
            provider._buffer_message({'late': 'listener final callback'})
    listener = Thread(target=listen)
    provider._listener = listener
    client.on_close = stop.set
    listener.start()
    try:
        result = service.poll(NOW)
        assert not listener.is_alive()
        if late:
            assert result is not None
            assert service._provider is provider
            assert len(provider._messages) == 1
        else:
            assert result is None
            assert service._provider is None
            assert service.closed_cleaned_proof['status'] == 'CLOSED_CLEANED'
    finally:
        stop.set()
        listener.join(timeout=1)


def test_unproven_cleanup_finally_cannot_drain_late_old_day_input(monkeypatch):
    service, store, provider, _ = make_service(monkeypatch)
    store.cleaned = True
    service.closed_cleanup_evidence = lambda *_: None
    provider._buffer_message({'late': 'unparsed original input'})
    assert service.poll(NOW) is not None
    with pytest.raises(ValueError, match='LIVE_PROVIDER_CLOSE_UNKNOWN'):
        service._discard_provider()
    assert service._provider is provider
    assert len(provider._messages) == 1


@pytest.mark.parametrize('drift', ['deleted', 'mapping', 'local_day', 'registered_day'])
def test_shutdown_rechecks_exact_snapshot_after_listener_close_before_drain(monkeypatch, drift):
    service, store, provider, client = make_service(monkeypatch)
    provider._buffer_message({'late': 'preserve on close race'})
    def changed():
        if drift == 'deleted':
            store.cleaned = True
        elif drift == 'mapping':
            monkeypatch.setattr(store, 'subscriptions', lambda *_: {'rb': 'RB2705'})
        elif drift == 'registered_day':
            monkeypatch.setattr(service.source_stream, 'registered_day', lambda *_: DAY + timedelta(days=1))
        else:
            service._trading_day = DAY + timedelta(days=1)
    client.on_close = changed
    monkeypatch.setattr(provider, 'poll_buffered', lambda: pytest.fail('must fence before drain'))
    with pytest.raises(ValueError, match='LIVE_PROVIDER_CLOSE_UNKNOWN'):
        service._discard_provider()
    assert service._provider is provider
    assert len(provider._messages) == 1
    assert service._input_failure is not None


def test_unproven_cleanup_raw_buffer_stays_fenced_across_next_session(monkeypatch):
    service, store, provider, client = make_service(monkeypatch)
    store.cleaned = True
    service.closed_cleanup_evidence = lambda *_: None
    provider._buffer_message({'late': 'retain original time and raw fields'})
    assert service.poll(NOW) is not None
    assert service._input_failure is not None
    service._phase_resolver = SimpleNamespace(resolve=lambda *_: ProductMarketPhase(
        'rb', MarketPhase.TRADING, DAY + timedelta(days=1), None, NOW + timedelta(days=1)))
    monkeypatch.setattr(provider, 'poll_buffered', lambda: pytest.fail('must not take old raw'))
    monkeypatch.setattr(service, 'ingest', lambda *a, **kw: pytest.fail('must not ingest old raw'))
    monkeypatch.setattr(client, 'subscribe', lambda *_: pytest.fail('must not subscribe'), raising=False)
    assert service.poll(NOW + timedelta(hours=3)) is not None
    assert service._provider is provider
    assert len(provider._messages) == 1


def test_unproven_cleanup_empty_provider_does_not_block_normal_next_session(monkeypatch):
    service, store, provider, _ = make_service(monkeypatch)
    store.cleaned = True
    service.closed_cleanup_evidence = lambda *_: None
    assert service.poll(NOW) is not None
    assert service._input_failure is None
    phase = ProductMarketPhase('rb', MarketPhase.TRADING, DAY + timedelta(days=1), None,
                               NOW + timedelta(days=1))
    service._phase_resolver = SimpleNamespace(resolve=lambda *_: phase)
    reached = []
    monkeypatch.setattr(feed.LiveMarketService, 'poll', lambda *_: reached.append(True))
    service.poll(NOW + timedelta(hours=3))
    assert reached == [True]


def test_shutdown_lock_busy_preserves_original_buffer(monkeypatch, tmp_path):
    from app.market_data.live_recovery_guard import after_market_recovery_guard
    service, _, provider, _ = make_service(monkeypatch)
    service._shutdown_guard_factory = lambda: after_market_recovery_guard(root=tmp_path, wait=False)
    provider._buffer_message({'late': 'original buffer'})
    with after_market_recovery_guard(root=tmp_path, wait=False):
        with pytest.raises(ValueError, match='LIVE_PROVIDER_CLOSE_UNKNOWN'):
            service._discard_provider()
    assert service._provider is provider
    assert len(provider._messages) == 1
    assert service._closed_retirement_failed


def test_shutdown_drain_excludes_cleanup_without_locking_listener_join(monkeypatch, tmp_path):
    from app.market_data.live_recovery_guard import after_market_recovery_guard
    service, store, provider, client = make_service(monkeypatch)
    def guard():
        return after_market_recovery_guard(root=tmp_path, wait=False)
    service._shutdown_guard_factory = guard
    closed_without_guard = []
    def close():
        # Actual flock can be acquired here: listener join is outside it.
        with guard():
            closed_without_guard.append(True)
    client.on_close = close
    drain_while_cleanup_excluded = []
    def drain():
        # Natural cleanup's same lock cannot enter while finite drain publishes.
        with pytest.raises(RuntimeError, match='LIVE_RECOVERY_BUSY'):
            with guard():
                store.cleaned = True
        drain_while_cleanup_excluded.append(True)
        return ()
    monkeypatch.setattr(provider, 'poll_buffered', drain)
    service._discard_provider()
    assert closed_without_guard == [True]
    assert drain_while_cleanup_excluded == [True]
    assert service._provider is None
    assert not store.cleaned


def test_shutdown_without_guard_cannot_take_buffer(monkeypatch):
    service, _, provider, _ = make_service(monkeypatch)
    service._shutdown_guard_factory = None
    provider._buffer_message({'late': 'original buffer'})
    with pytest.raises(ValueError, match='LIVE_PROVIDER_CLOSE_UNKNOWN'):
        service._discard_provider()
    assert service._provider is provider
    assert len(provider._messages) == 1


def test_first_new_session_without_closed_poll_fences_old_raw(monkeypatch):
    service, store, provider, client = make_service(monkeypatch)
    store.cleaned = True
    service.closed_cleanup_evidence = lambda *_: None
    provider._buffer_message({'late': 'arrived while process was suspended'})
    service._phase_resolver = SimpleNamespace(resolve=lambda *_: ProductMarketPhase(
        'rb', MarketPhase.TRADING, DAY + timedelta(days=1), None, NOW + timedelta(days=1)))
    monkeypatch.setattr(feed.LiveMarketService, 'poll', lambda *_: pytest.fail('old provider reused'))
    assert service.poll(NOW + timedelta(hours=3)) is not None
    assert service._provider is provider
    assert len(provider._messages) == 1
    assert service._input_failure is not None


def test_first_new_session_retires_empty_old_provider_before_normal_poll(monkeypatch):
    service, store, provider, client = make_service(monkeypatch)
    store.cleaned = True
    service.closed_cleanup_evidence = lambda *_: None
    service._phase_resolver = SimpleNamespace(resolve=lambda *_: ProductMarketPhase(
        'rb', MarketPhase.TRADING, DAY + timedelta(days=1), None, NOW + timedelta(days=1)))
    reached = []
    def normal(*_):
        assert service._provider is None
        assert client.close_calls == 1
        reached.append(True)
    monkeypatch.setattr(feed.LiveMarketService, 'poll', normal)
    service.poll(NOW + timedelta(hours=3))
    assert reached == [True]
    assert service.closed_cleaned_proof is None


def test_unproven_cleanup_retires_listener_even_before_next_session(monkeypatch):
    service, store, provider, client = make_service(monkeypatch)
    store.cleaned = True
    service.closed_cleanup_evidence = lambda *_: None
    assert service.poll(NOW) is not None
    assert client.close_calls == 1
    assert service._provider is None
    assert service.closed_cleaned_proof is None


def test_normal_closed_grace_detects_cleanup_after_identity_restore_before_take(monkeypatch):
    service, store, provider, _ = make_service(monkeypatch)
    provider._buffer_message({'late': 'must remain after cleanup'})
    restore = service._restore_break_identity
    def raced(phases):
        result = restore(phases)
        store.cleaned = True
        return result
    monkeypatch.setattr(service, '_restore_break_identity', raced)
    monkeypatch.setattr(provider, 'poll_buffered', lambda: pytest.fail('take after cleanup'))
    assert service.poll(NOW) is not None
    assert len(provider._messages) == 1
    assert service._provider is provider


def test_normal_break_grace_holds_cleanup_mutex_before_take(monkeypatch, tmp_path):
    from app.market_data.live_recovery_guard import after_market_recovery_guard
    service, store, provider, _ = make_service(monkeypatch)
    phase = ProductMarketPhase('rb', MarketPhase.BREAK, DAY, None, NOW + timedelta(hours=1))
    service._phase_resolver = SimpleNamespace(resolve=lambda *_: phase)
    service._shutdown_guard_factory = lambda: after_market_recovery_guard(root=tmp_path, wait=False)
    checked = []
    provider._buffer_message({'invalid': 'forces a finite raw-buffer take'})
    real_drain = provider.poll_buffered
    def drain():
        with pytest.raises(RuntimeError, match='LIVE_RECOVERY_BUSY'):
            with after_market_recovery_guard(root=tmp_path, wait=False):
                store.cleaned = True
        checked.append(True)
        return real_drain()
    monkeypatch.setattr(provider, 'poll_buffered', drain)
    assert service.poll(NOW) is None
    assert checked == [True]


def test_last_normal_closed_poll_then_cleanup_and_late_raw_before_new_session(monkeypatch):
    service, store, provider, _ = make_service(monkeypatch)
    assert service.poll(NOW) is None
    assert service._provider is provider
    assert provider.buffered_message_count() == 0
    store.cleaned = True
    service.closed_cleanup_evidence = lambda *_: None
    provider._buffer_message({'late': 'after last closed poll, before first new poll'})
    phase = ProductMarketPhase('rb', MarketPhase.TRADING, DAY + timedelta(days=1), None,
                               NOW + timedelta(days=1))
    service._phase_resolver = SimpleNamespace(resolve=lambda *_: phase)
    monkeypatch.setattr(feed.LiveMarketService, 'poll', lambda *_: pytest.fail('old raw reused'))
    assert service.poll(NOW + timedelta(hours=3)) is not None
    assert service._provider is provider
    assert len(provider._messages) == 1
    assert service._input_failure is not None


@pytest.mark.parametrize('defect', ['records', 'events', 'cursor'])
def test_durable_first_new_session_cannot_clear_old_unsettled_input(monkeypatch, defect):
    service, store, provider, _ = make_service(monkeypatch, durable=True)
    provider.select_day(DAY)
    store.cleaned = True
    if defect == 'records':
        provider.records.append(('original', ('rb', NOW)))
    elif defect == 'events':
        provider.events[('rb', NOW)] = 'original'
    else:
        provider.stream.behind = True
    before = (tuple(provider.records), dict(provider.events))
    service._phase_resolver = SimpleNamespace(resolve=lambda *_: ProductMarketPhase(
        'rb', MarketPhase.TRADING, DAY + timedelta(days=1), None, NOW + timedelta(days=1)))
    monkeypatch.setattr(provider, 'select_day', lambda *_: pytest.fail('must not clear old input'))
    assert service.poll(NOW + timedelta(hours=3)) is not None
    assert service._halted == 'OBSERVATION_CLEANUP_UNPROVEN'
    assert (tuple(provider.records), provider.events) == before


def test_ownership_lost_during_listener_close_propagates_and_retains_object(monkeypatch):
    service, store, provider, client = make_service(monkeypatch)
    store.cleaned = True
    valid = [True]
    def assert_owned():
        if not valid[0]:
            raise RuntimeError('RUNTIME_OWNER_INVALID')
    service.assert_owned = assert_owned
    client.on_close = lambda: valid.__setitem__(0, False)
    with pytest.raises(RuntimeError, match='RUNTIME_OWNER_INVALID'):
        service.poll(NOW)
    assert service._provider is provider
    assert service._input_failure is not None


@pytest.mark.parametrize('drift', ['day', 'registered', 'contracts', 'object', 'snapshot', 'cursor', 'pending'])
def test_cleanup_retirement_rechecks_frozen_identity_before_buffer_count(monkeypatch, drift):
    service, store, provider, client = make_service(monkeypatch)
    store.cleaned = True
    replacement = SimpleNamespace()
    def changed():
        if drift == 'day':
            service._trading_day = DAY + timedelta(days=1)
        elif drift == 'registered':
            monkeypatch.setattr(service.source_stream, 'registered_day', lambda *_: DAY + timedelta(days=1))
        elif drift == 'contracts':
            service._contracts = {'rb': 'RB2705'}
        elif drift == 'object':
            service._provider = replacement
        elif drift == 'snapshot':
            store.cleaned = False
        elif drift == 'cursor':
            service.source_stream.behind = True
        else:
            service._pending[('rb', NOW)] = 'original'
    client.on_close = changed
    monkeypatch.setattr(provider, 'buffered_message_count', lambda: pytest.fail('identity drift before count'))
    assert service.poll(NOW) is not None
    assert service._input_failure is not None
    assert service._provider is (replacement if drift == 'object' else provider)
    assert service._cleanup_isolation.provider is provider


def test_empty_grace_does_not_contend_with_natural_maintenance(monkeypatch, tmp_path):
    from app.market_data.live_recovery_guard import after_market_recovery_guard
    service, store, provider, _ = make_service(monkeypatch)
    service._shutdown_guard_factory = lambda: after_market_recovery_guard(root=tmp_path, wait=False)
    monkeypatch.setattr(provider, 'poll_buffered', lambda: pytest.fail('zero count must not take'))
    with after_market_recovery_guard(root=tmp_path, wait=False):
        assert service.poll(NOW) is None
    assert service._input_failure is None
    assert service._provider is provider
    assert provider.buffered_message_count() == 0


def test_raw_arriving_after_empty_count_is_left_for_next_isolation(monkeypatch):
    service, store, provider, _ = make_service(monkeypatch)
    count = provider.buffered_message_count
    def after_count():
        result = count()
        provider._buffer_message({'late': 'after empty count'})
        return result
    monkeypatch.setattr(provider, 'buffered_message_count', after_count)
    monkeypatch.setattr(provider, 'poll_buffered', lambda: pytest.fail('late raw must not be taken'))
    assert service.poll(NOW) is None
    assert len(provider._messages) == 1
    monkeypatch.setattr(provider, 'buffered_message_count', count)
    store.cleaned = True
    assert service.poll(NOW + timedelta(seconds=1)) is not None
    assert service._input_failure is not None
    assert service._provider is provider
    assert len(provider._messages) == 1
