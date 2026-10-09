from datetime import UTC, date, datetime

import pytest

from app.market_data.observation_stream import ObservationEnvelope, ObservationStream


def test_envelope_rejects_naive_source_time():
    with pytest.raises(ValueError, match='OBSERVATION_TIME_INVALID'):
        ObservationEnvelope('x', date(2026, 10, 9), datetime(2026, 10, 9), 'live:bar:rb:1m', {}, True)


def test_missing_cursor_does_not_silently_start_at_latest():
    class Redis:
        def get(self, key):
            return None
    stream = ObservationStream(Redis(), kind='completed')
    with pytest.raises(ValueError, match='OBSERVATION_CURSOR_MISSING'):
        stream.read('alert', date(2026, 10, 9))


def test_roundtrip_keeps_original_source_time():
    event = ObservationEnvelope('x', date(2026, 10, 9), datetime(2026, 10, 9, tzinfo=UTC),
                                'live:bar:rb:1m', {'close': '10'}, True)
    assert ObservationEnvelope.from_json(event.to_json(), stream_id='1-0').source_observed_at == event.source_observed_at

@pytest.fixture
def isolated_redis():
    import os
    from redis import Redis
    port = os.environ.get('GUIYI_TEST_REDIS_PORT')
    if not port:
        pytest.skip('requires disposable Redis on explicit nonproduction port')
    assert 1024 <= int(port) <= 65535 and int(port) != 6379
    client = Redis(host='127.0.0.1', port=int(port), db=11, decode_responses=True)
    client.flushdb()
    yield client
    client.flushdb()
    client.close()


def test_real_stream_idempotency_conflict_cursor_and_capacity(isolated_redis, monkeypatch):
    import app.market_data.observation_stream as module
    from dataclasses import replace
    day = date(2026, 10, 9)
    stream = ObservationStream(isolated_redis, kind='completed')
    stream.initialize('alert', day, cursor='0-0')
    event = ObservationEnvelope('x', day, datetime(2026, 10, 9, tzinfo=UTC),
                                'live:bar:rb:1m', {'close': '10'}, True)
    identifier = stream.append(event)
    assert stream.append(event) == identifier
    assert stream.days() == (day,)
    assert stream.read('alert', day)[0].source_observed_at == event.source_observed_at
    with pytest.raises(ValueError, match='CONTENT_CONFLICT'):
        stream.append(replace(event, data={'close': '11'}))
    monkeypatch.setattr(module, 'DAILY_LIMIT', 1)
    with pytest.raises(ValueError, match='CAPACITY_EXCEEDED'):
        stream.append(replace(event, observation_id='y'))
    stream.ack('alert', day, expected_cursor='0-0', next_id=identifier)
    assert stream.read('alert', day) == ()
    isolated_redis.delete(stream.key(day))
    with pytest.raises(ValueError, match='CURSOR_EXPIRED'):
        stream.read('alert', day)


def test_durable_live_atomic_completion_and_restart(isolated_redis):
    from datetime import timedelta
    from dataclasses import replace
    from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
    from app.market_data.live_market import RedisLiveStore, _bar_payload
    from app.market_data.aggregation import SessionWindow
    from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _bar, _phase
    base = _bar(1)
    day = base.trading_day
    window = SessionWindow(base.bar_end - timedelta(minutes=1), base.bar_end + timedelta(minutes=74))
    source = ObservationStream(isolated_redis, kind='source')
    source.initialize('live', day, cursor='0-0')
    completed = ObservationStream(isolated_redis, kind='completed')
    completed.initialize('alert', day, cursor='0-0')
    store = RedisLiveStore(isolated_redis)
    store.set_subscriptions(day, {'rb': 'RB2505'})
    def build():
        return DurableLiveMarketService(source_provider=StreamLiveProvider(source),
            dominant_source=FakeDominants({('rb', day): 'RB2505'}),
            phase_resolver=FakePhases({'rb': _phase('rb', day, window)}), store=store,
            operational_products=('rb',))
    service = build()
    for minute in range(1, 6):
        bar = replace(base, bar_end=base.bar_end + timedelta(minutes=minute - 1))
        data = _bar_payload(bar, contract='RB2505')
        data['subscription_snapshot'] = {'rb': 'RB2505'}
        source.append(ObservationEnvelope(str(minute), day, bar.bar_end + timedelta(seconds=1),
                                         'live:bar:rb:1m', data, True))
    now = base.bar_end + timedelta(minutes=4, seconds=3)
    assert service.poll(now) is None
    events = completed.read('alert', day)
    assert len(events) == 6  # five M1 plus the completed M5
    assert len(store.bars_after(day, 'rb', '1m', None)) == 5
    assert len(store.bars_after(day, 'rb', '5m', None)) == 1
    assert source.cursor('live', day) == source.tail(day)
    assert build().poll(now + timedelta(seconds=1)) is None
    assert len(completed.read('alert', day)) == 6


def test_conflict_rolls_back_all_completed_writes_and_cursor(isolated_redis):
    from app.market_data.live_recovery_scripts import COMMIT_OBSERVATIONS
    import json
    day = date(2026, 10, 9)
    source = ObservationStream(isolated_redis, kind='source')
    source.initialize('live', day, cursor='0-0')
    completed = ObservationStream(isolated_redis, kind='completed')
    event = ObservationEnvelope('x', day, datetime(2026, 10, 9, tzinfo=UTC), 'live:bar:rb:1m', {}, True)
    identifier = source.append(event)
    keys = [source.cursor_key('live', day), source.key(day), completed.key(day),
            completed.identity_key(day), 'test:bar:a', 'test:bar:b']
    isolated_redis.zadd(keys[-1], {'conflict': 2})
    plan = [{'key_index': i, 'score': score, 'payload': 'new', 'identity': str(i),
             'envelope': event.to_json(), 'channel': event.channel}
            for i, score in ((5, 1), (6, 2))]
    assert isolated_redis.eval(COMMIT_OBSERVATIONS, len(keys), *keys,
                               '0-0', identifier, json.dumps(plan), 259200, 120000) == -1
    assert source.cursor('live', day) == '0-0'
    assert isolated_redis.exists(keys[-2]) == 0
    assert completed.tail(day) == '0-0'


def test_source_duplicate_preserves_first_arrival_and_new_day_is_proven(isolated_redis):
    from datetime import timedelta
    from dataclasses import replace
    stream = ObservationStream(isolated_redis, kind='source')
    day = date(2026, 10, 9)
    stream.initialize('live', day, cursor='0-0')
    event = ObservationEnvelope('x', day, datetime(2026, 10, 9, tzinfo=UTC),
                                'live:bar:rb:1m', {'close': '10'}, True)
    identifier = stream.append(event)
    assert stream.append(replace(event, source_observed_at=event.source_observed_at + timedelta(seconds=5))) == identifier
    assert stream.read('live', day)[0].source_observed_at == event.source_observed_at
    tomorrow = day + timedelta(days=1)
    with pytest.raises(ValueError, match='DAY_BASELINE_UNPROVEN'):
        stream.initialize_new_day('live', tomorrow)
    stream.ack('live', day, expected_cursor='0-0', next_id=identifier)
    stream.initialize_new_day('live', tomorrow)
    assert stream.cursor('live', tomorrow) == '0-0'
    isolated_redis.delete(stream.cursor_key('live', tomorrow))
    with pytest.raises(ValueError, match='CURSOR_MISSING'):
        stream.prepare_registered_day(tomorrow)


def test_live_uncompleted_input_is_replayed_after_restart(isolated_redis):
    from datetime import timedelta
    from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
    from app.market_data.live_market import RedisLiveStore, _bar_payload
    from app.market_data.aggregation import SessionWindow
    from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _bar, _phase
    bar = _bar(1)
    day = bar.trading_day
    window = SessionWindow(bar.bar_end - timedelta(minutes=1), bar.bar_end + timedelta(minutes=74))
    source = ObservationStream(isolated_redis, kind='source')
    source.initialize('live', day, cursor='0-0')
    data = _bar_payload(bar, contract='RB2505')
    data['subscription_snapshot'] = {'rb': 'RB2505'}
    source.append(ObservationEnvelope('one', day, bar.bar_end - timedelta(seconds=1), 'live:bar:rb:1m', data, True))
    store = RedisLiveStore(isolated_redis)
    store.set_subscriptions(day, {'rb': 'RB2505'})
    def build():
        return DurableLiveMarketService(source_provider=StreamLiveProvider(source),
            dominant_source=FakeDominants({('rb', day): 'RB2505'}),
            phase_resolver=FakePhases({'rb': _phase('rb', day, window)}), store=store,
            operational_products=('rb',))
    assert build().poll(bar.bar_end + timedelta(seconds=1)) is None
    assert source.cursor('live', day) == '0-0'
    assert store.bars_after(day, 'rb', '1m', None) == ()
    assert build().poll(bar.bar_end + timedelta(seconds=3)) is None
    assert source.cursor('live', day) == source.tail(day)
    assert store.bars_after(day, 'rb', '1m', None) == (bar,)


def test_feed_captures_raw_without_publishing_completed_and_obeys_owner(isolated_redis):
    from datetime import timedelta
    from app.market_data.market_feed import FeedLiveStore, MarketFeedService
    from app.market_data.aggregation import SessionWindow
    from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _bar, _phase
    bar = _bar(1)
    window = SessionWindow(bar.bar_end - timedelta(minutes=1), bar.bar_end + timedelta(minutes=74))
    stream = ObservationStream(isolated_redis, kind='source')
    stream.initialize('live', bar.trading_day, cursor='0-0')
    feed = MarketFeedService(source_stream=stream, provider_factory=lambda: None,
        dominant_source=FakeDominants({('rb', bar.trading_day): 'RB2505'}),
        phase_resolver=FakePhases({'rb': _phase('rb', bar.trading_day, window)}),
        store=FeedLiveStore(isolated_redis), operational_products=('rb',))
    feed._contracts = {'rb': 'RB2505'}
    now = bar.bar_end - timedelta(seconds=1)
    assert feed.ingest('RB2505', bar, now=now) is None
    assert stream.read('live', bar.trading_day)[0].source_observed_at == now
    assert feed.flush_due(bar.bar_end + timedelta(seconds=3)) == ()
    assert not isolated_redis.exists('live:bars:' + bar.trading_day.isoformat() + ':rb:1m')
    def reject_owner():
        raise ValueError('RUN_OWNERSHIP_LOST')
    feed.assert_owned = reject_owner
    with pytest.raises(ValueError, match='RUN_OWNERSHIP_LOST'):
        feed.ingest('RB2505', bar, now=now)
    assert len(stream.read('live', bar.trading_day)) == 1


def test_live_coalesces_all_buffered_revisions_before_finalization(isolated_redis):
    from datetime import timedelta
    from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
    from app.market_data.live_market import RedisLiveStore, _bar_payload
    from app.market_data.aggregation import SessionWindow
    from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _bar, _phase
    bar = _bar(1)
    day = bar.trading_day
    window = SessionWindow(bar.bar_end - timedelta(minutes=1), bar.bar_end + timedelta(minutes=74))
    source = ObservationStream(isolated_redis, kind='source')
    source.initialize('live', day, cursor='0-0')
    store = RedisLiveStore(isolated_redis)
    store.set_subscriptions(day, {'rb': 'RB2505'})
    for revision in range(130):
        from dataclasses import replace
        from decimal import Decimal
        data = _bar_payload(replace(bar, volume=Decimal(100 + revision)), contract='RB2505')
        data['subscription_snapshot'] = {'rb': 'RB2505'}
        source.append(ObservationEnvelope(str(revision), day, bar.bar_end + timedelta(seconds=1),
                                         'live:bar:rb:1m', data, True))
    service = DurableLiveMarketService(source_provider=StreamLiveProvider(source),
        dominant_source=FakeDominants({('rb', day): 'RB2505'}),
        phase_resolver=FakePhases({'rb': _phase('rb', day, window)}), store=store,
        operational_products=('rb',))
    assert service.poll(bar.bar_end + timedelta(seconds=3)) is None
    assert source.cursor('live', day) == source.tail(day)
    assert store.bars_after(day, 'rb', '1m', None) == (replace(bar, volume=Decimal(229)),)


def test_lua_validates_entire_plan_before_first_mutation(isolated_redis):
    from app.market_data.live_recovery_scripts import COMMIT_OBSERVATIONS
    import json
    day = date(2026, 10, 9)
    source = ObservationStream(isolated_redis, kind='source')
    source.initialize('live', day, cursor='0-0')
    completed = ObservationStream(isolated_redis, kind='completed')
    event = ObservationEnvelope('x', day, datetime(2026, 10, 9, tzinfo=UTC), 'live:bar:rb:1m', {}, True)
    identifier = source.append(event)
    keys = [source.cursor_key('live', day), source.key(day), completed.key(day),
            completed.identity_key(day), 'test:bar:a', 'test:bar:b']
    plan = [{'key_index': 5, 'score': 1, 'payload': 'new', 'identity': 'a',
             'envelope': event.to_json(), 'channel': event.channel},
            {'key_index': 6, 'score': 2, 'payload': 'new', 'identity': 'b',
             'envelope': event.to_json(), 'channel': False}]
    assert isolated_redis.eval(COMMIT_OBSERVATIONS, len(keys), *keys,
                               '0-0', identifier, json.dumps(plan), 259200, 120000) == -4
    assert source.cursor('live', day) == '0-0'
    assert isolated_redis.exists(keys[-2]) == 0
    assert completed.tail(day) == '0-0'


def test_continuous_source_advances_completed_frontier_with_next_bar_pending(isolated_redis):
    from dataclasses import replace
    from datetime import timedelta
    from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
    from app.market_data.live_market import RedisLiveStore, _bar_payload
    from app.market_data.aggregation import SessionWindow
    from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _bar, _phase
    bar = _bar(1)
    day = bar.trading_day
    window = SessionWindow(bar.bar_end - timedelta(minutes=1), bar.bar_end + timedelta(minutes=74))
    source = ObservationStream(isolated_redis, kind='source')
    source.initialize('live', day, cursor='0-0')
    store = RedisLiveStore(isolated_redis)
    store.set_subscriptions(day, {'rb': 'RB2505'})
    def build():
        return DurableLiveMarketService(source_provider=StreamLiveProvider(source),
            dominant_source=FakeDominants({('rb', day): 'RB2505'}),
            phase_resolver=FakePhases({'rb': _phase('rb', day, window)}), store=store,
            operational_products=('rb',))
    service = build()
    identifiers = []
    for minute in range(1, 6):
        current = replace(bar, bar_end=bar.bar_end + timedelta(minutes=minute - 1))
        data = _bar_payload(current, contract='RB2505')
        data['subscription_snapshot'] = {'rb': 'RB2505'}
        identifiers.append(source.append(ObservationEnvelope(str(minute), day,
            current.bar_end - timedelta(seconds=55), 'live:bar:rb:1m', data, True)))
        if minute > 1:
            assert service.poll(current.bar_end - timedelta(seconds=55)) is None
            assert source.cursor('live', day) == identifiers[minute - 2]
            assert len(store.bars_after(day, 'rb', '1m', None)) == minute - 1
            service = build()  # repeated restart while next-minute preview is pending
    assert service.poll(current.bar_end + timedelta(seconds=3)) is None
    assert source.cursor('live', day) == source.tail(day)
    assert len(store.bars_after(day, 'rb', '1m', None)) == 5


def test_cross_day_old_backlog_drains_before_feed_initializes_new_day(isolated_redis):
    from dataclasses import replace
    from datetime import timedelta
    from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
    from app.market_data.live_market import RedisLiveStore, _bar_payload
    from app.market_data.aggregation import SessionWindow
    from tests.data_foundation.test_live_market import FakeDominants, _bar, _phase
    bar = _bar(1)
    old_day = bar.trading_day
    new_day = old_day + timedelta(days=1)
    old_window = SessionWindow(bar.bar_end - timedelta(minutes=1), bar.bar_end + timedelta(minutes=74))
    new_window = SessionWindow(old_window.start + timedelta(days=1), old_window.end + timedelta(days=1))
    class Phases:
        def resolve(self, symbol, now):
            return _phase(symbol, old_day if now < new_window.start else new_day,
                          old_window if now < new_window.start else new_window)
    source = ObservationStream(isolated_redis, kind='source')
    source.initialize('live', old_day, cursor='0-0')
    store = RedisLiveStore(isolated_redis)
    store.set_subscriptions(old_day, {'rb': 'RB2505'})
    store.set_subscriptions(new_day, {'rb': 'RB2505'})
    data = _bar_payload(bar, contract='RB2505')
    data['subscription_snapshot'] = {'rb': 'RB2505'}
    source.append(ObservationEnvelope('old', old_day, bar.bar_end + timedelta(seconds=1),
                                     'live:bar:rb:1m', data, True))
    service = DurableLiveMarketService(source_provider=StreamLiveProvider(source),
        dominant_source=FakeDominants({('rb', old_day): 'RB2505', ('rb', new_day): 'RB2505'}),
        phase_resolver=Phases(), store=store, operational_products=('rb',))
    now = new_window.start + timedelta(seconds=3)
    assert service.poll(now) is None
    assert source.cursor('live', old_day) == source.tail(old_day)
    assert service.poll(now) == 'OBSERVATION_DAY_AWAITING_FEED'
    assert service._halted is None
    source.prepare_registered_day(new_day)
    next_bar = replace(bar, bar_end=bar.bar_end + timedelta(days=1), trading_day=new_day)
    data = _bar_payload(next_bar, contract='RB2505')
    data['subscription_snapshot'] = {'rb': 'RB2505'}
    source.append(ObservationEnvelope('new', new_day, next_bar.bar_end + timedelta(seconds=1),
                                     'live:bar:rb:1m', data, True))
    assert service.poll(next_bar.bar_end + timedelta(seconds=3)) is None
    assert source.cursor('live', new_day) == source.tail(new_day)
    assert store.bars_after(new_day, 'rb', '1m', None) == (next_bar,)


def test_raw_budget_and_first_confirmation_survive_unacked_prefix_restart(isolated_redis):
    from dataclasses import replace
    from datetime import timedelta
    from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
    from app.market_data.live_market import RedisLiveStore, _bar_payload
    from app.market_data.aggregation import SessionWindow
    from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _bar, _phase
    bar = _bar(1)
    day = bar.trading_day
    window = SessionWindow(bar.bar_end - timedelta(minutes=1), bar.bar_end + timedelta(minutes=74))
    source = ObservationStream(isolated_redis, kind='source')
    source.initialize('live', day, cursor='0-0')
    completed = ObservationStream(isolated_redis, kind='completed')
    completed.initialize('alert', day, cursor='0-0')
    store = RedisLiveStore(isolated_redis)
    store.set_subscriptions(day, {'rb': 'RB2505'})
    future = replace(bar, bar_end=bar.bar_end + timedelta(minutes=1))
    raw_time = bar.bar_end - timedelta(seconds=5)
    for identity, item in (('future', future), ('old', bar)):
        data = _bar_payload(item, contract='RB2505')
        data['subscription_snapshot'] = {'rb': 'RB2505'}
        source.append(ObservationEnvelope(identity, day, raw_time, 'live:bar:rb:1m', data, True))
    def build():
        return DurableLiveMarketService(source_provider=StreamLiveProvider(source),
            dominant_source=FakeDominants({('rb', day): 'RB2505'}),
            phase_resolver=FakePhases({'rb': _phase('rb', day, window)}), store=store,
            operational_products=('rb',))
    confirmed = bar.bar_end + timedelta(seconds=3)
    assert build().poll(confirmed) is None
    first = completed.read('alert', day)[0]
    assert first.source_observed_at == first.raw_received_at == raw_time
    assert first.confirmed_at == confirmed
    assert first.confirmed_at >= bar.bar_end
    assert source.cursor('live', day) == '0-0'  # earlier future record must remain unacknowledged
    assert build().poll(confirmed + timedelta(seconds=5)) is None
    assert completed.read('alert', day) == (first,)


def test_feed_close_failure_never_reports_parked_owner(tmp_path):
    from app.market_data.market_feed import MarketFeedService
    from app.runtime_handover import RunOwnership, read_service_state
    from tests.data_foundation.test_live_market import FakeDominants, FakePhases, FakeRedis
    from app.market_data.market_feed import FeedLiveStore
    class Provider:
        def close(self):
            raise RuntimeError('close failed')
        def close_verified(self):
            raise ValueError('LIVE_PROVIDER_CLOSE_UNKNOWN')
    feed = MarketFeedService(source_stream=ObservationStream(FakeRedis(), kind='source'),
        provider_factory=lambda: Provider(), dominant_source=FakeDominants({}),
        phase_resolver=FakePhases({}), store=FeedLiveStore(FakeRedis()), operational_products=())
    provider = feed._provider = Provider()
    owner = RunOwnership('market-feed', generation=1, runtime_dir=tmp_path, verify=lambda: None)
    with pytest.raises(ValueError, match='LIVE_PROVIDER_CLOSE_UNKNOWN'):
        with owner.acquired():
            feed.run_forever(should_stop=lambda: True)
    assert feed._provider is provider
    assert read_service_state('market-feed', runtime_dir=tmp_path)['phase'] == 'active'


def test_rqdata_verified_close_waits_for_listener_and_timeout_is_explicit():
    from app.market_data.live_market import RQDataLiveProvider
    from tests.data_foundation.test_live_market import FakeLiveClient
    client = FakeLiveClient()
    provider = RQDataLiveProvider(client)
    provider.poll()
    with pytest.raises(ValueError, match='LIVE_PROVIDER_CLOSE_UNKNOWN'):
        provider.close_verified(timeout=0)
    assert client.closed
    assert provider._listener is client.listener  # unknown listener is not forgotten
    assert not provider._closed

    client = FakeLiveClient()
    provider = RQDataLiveProvider(client)
    provider.poll()
    ticks = [0.0]
    def sleep(_seconds):
        ticks[0] += 0.01
        if ticks[0] >= 0.03:
            client.listener.alive = False
    provider.close_verified(timeout=1, clock=lambda: ticks[0], sleep=sleep)
    assert ticks[0] >= 0.03
    assert provider._closed and provider._listener is None


def test_rqdata_client_close_exception_retains_listener_and_rejects_verified_close():
    from app.market_data.live_market import RQDataLiveProvider
    from tests.data_foundation.test_live_market import FakeLiveClient
    class Client(FakeLiveClient):
        def close(self):
            raise ConnectionError('close unavailable')
    client = Client()
    provider = RQDataLiveProvider(client)
    provider.poll()
    with pytest.raises(ValueError, match='LIVE_PROVIDER_CLOSE_UNKNOWN'):
        provider.close_verified()
    assert provider._listener is client.listener
    assert not provider._closed
