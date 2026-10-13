from dataclasses import replace
from datetime import timedelta

import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.live_market import RedisLiveStore, _bar_payload
from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
from app.market_data.market_phase import MarketPhase
from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _bar, _phase
from tests.data_foundation.test_observation_stream import isolated_redis as redis_fixture

isolated_redis = redis_fixture


def build(redis, *, phase, subscription=True):
    bar = _bar(1)
    day = bar.trading_day
    window = SessionWindow(bar.bar_end - timedelta(minutes=1), bar.bar_end + timedelta(minutes=74))
    source = ObservationStream(redis, kind='source')
    source.initialize('live', day, cursor='0-0')
    completed = ObservationStream(redis, kind='completed')
    completed.initialize('alert', day, cursor='0-0')
    store = RedisLiveStore(redis)
    if subscription:
        store.set_subscriptions(day, {'rb': 'RB2505'})
    phases = FakePhases({'rb': replace(_phase('rb', day, window), phase=phase,
                                      current_session=window if phase is MarketPhase.TRADING else None)})
    service = DurableLiveMarketService(source_provider=StreamLiveProvider(source),
        dominant_source=FakeDominants({('rb', day): 'RB2505'}), phase_resolver=phases, store=store,
        operational_products=('rb',), authoritative_dominants=True,
        coverage_sessions=lambda *_args: (window,))
    return service, source, completed, store, bar


@pytest.mark.parametrize('phase', [MarketPhase.CLOSED, MarketPhase.BREAK])
def test_empty_rest_restart_uses_existing_identity_without_observations(isolated_redis, phase):
    service, source, completed, store, bar = build(isolated_redis, phase=phase)
    now = bar.bar_end - timedelta(minutes=10)
    assert service.poll(now) is None
    assert service._trading_day == bar.trading_day
    assert service._contracts == {'rb': 'RB2505'}
    assert service._provider is None  # No RQ connection or subscription in rest.
    assert source.cursor('live', bar.trading_day) == '0-0'
    assert source.tail(bar.trading_day) == completed.tail(bar.trading_day) == '0-0'
    assert not isolated_redis.exists(source.key(bar.trading_day))
    assert not isolated_redis.exists(completed.key(bar.trading_day))
    assert store.heartbeat()['available'] is True
    assert store.heartbeat()['coverage']['rb']['state'] == 'not_due'
    assert service.poll(now + timedelta(seconds=5)) is None
    assert store.heartbeat()['generated_at'] == (now + timedelta(seconds=5)).isoformat()


def test_rest_without_frozen_subscription_is_not_ready(isolated_redis):
    service, _source, _completed, _store, bar = build(isolated_redis, phase=MarketPhase.CLOSED, subscription=False)
    assert service.poll(bar.bar_end - timedelta(minutes=10)) == 'OBSERVATION_CLEANUP_UNPROVEN'
    assert service._trading_day is None


def test_rest_missing_progress_is_not_initialized(isolated_redis):
    service, source, _completed, _store, bar = build(isolated_redis, phase=MarketPhase.CLOSED)
    isolated_redis.delete(source.cursor_key('live', bar.trading_day))
    assert service.poll(bar.bar_end - timedelta(minutes=10)) == 'OBSERVATION_CURSOR_MISSING'
    assert not isolated_redis.exists(source.cursor_key('live', bar.trading_day))


def test_pending_source_poll_refreshes_heartbeat_before_completion(isolated_redis):
    service, source, completed, store, bar = build(isolated_redis, phase=MarketPhase.TRADING)
    observed_at = bar.bar_end - timedelta(seconds=55)
    data = _bar_payload(bar, contract='RB2505')
    data['subscription_snapshot'] = {'rb': 'RB2505'}
    source.append(ObservationEnvelope('raw', bar.trading_day, observed_at, 'live:bar:rb:1m', data, True))
    assert service.poll(observed_at) is None
    assert store.heartbeat() is not None
    assert store.heartbeat()['generated_at'] == observed_at.isoformat()
    assert store.heartbeat()['available'] is False
    assert completed.tail(bar.trading_day) == '0-0'
    assert source.cursor('live', bar.trading_day) == '0-0'


def test_rest_catalog_contract_drift_remains_blocked(isolated_redis):
    service, source, completed, store, bar = build(isolated_redis, phase=MarketPhase.CLOSED)
    store.set_subscriptions(bar.trading_day, {'rb': 'RB2510'})
    assert service.poll(bar.bar_end - timedelta(minutes=10)) == 'LIVE_RANK1_CATALOG_CONFLICT'
    assert source.cursor('live', bar.trading_day) == completed.cursor('alert', bar.trading_day) == '0-0'
    assert completed.tail(bar.trading_day) == '0-0'


def test_new_session_day_waits_for_feed_without_creating_cursor(isolated_redis):
    service, source, completed, store, bar = build(isolated_redis, phase=MarketPhase.CLOSED)
    later = bar.trading_day + timedelta(days=1)
    prior = service._phase_resolver.phases['rb']
    service._phase_resolver.phases['rb'] = replace(prior, trading_day=later)
    assert service.poll(bar.bar_end - timedelta(minutes=10)) == 'OBSERVATION_DAY_AWAITING_FEED'
    assert service._halted is None
    assert not isolated_redis.exists(source.cursor_key('live', later))
    assert source.cursor('live', bar.trading_day) == '0-0'
    assert completed.tail(bar.trading_day) == '0-0'
    assert store.heartbeat()['available'] is False


@pytest.mark.parametrize('reference_lagging', [False, True])
def test_cleaned_closed_restart_requires_every_existing_consumer_drained(isolated_redis, reference_lagging):
    service, source, completed, store, bar = build(isolated_redis, phase=MarketPhase.CLOSED, subscription=False)
    day = bar.trading_day
    now = bar.bar_end + timedelta(hours=3)
    completed.initialize('reference', day, cursor='0-0')
    if reference_lagging:
        identity = completed.append(ObservationEnvelope('completed-reference-pending', day, bar.bar_end,
            'live:bar:rb:1m', _bar_payload(bar, contract='RB2505'), True))
        completed.ack('alert', day, expected_cursor='0-0', next_id=identity)
    service._phase_resolver.phases['rb'] = replace(service._phase_resolver.phases['rb'],
        next_session_start=now + timedelta(hours=1))
    service.closed_cleanup_evidence = lambda *_: dict(trading_day=day.isoformat(), cleanup_verified=True,
        cleanup_checked_at=now.isoformat(), evidence_kind='retained')
    before = (source.cursor('live', day), completed.cursor('alert', day), completed.cursor('reference', day))
    if reference_lagging:
        assert service.poll(now) == 'OBSERVATION_CLEANUP_UNPROVEN'
        assert service.closed_cleaned_proof is None
    else:
        assert service.poll(now) is None
        assert service.closed_cleaned_proof['status'] == 'CLOSED_CLEANED'
        assert store.heartbeat()['closed_cleaned']['natural_bar_verified'] is False
        assert store.heartbeat()['available'] is True
    assert store.subscriptions(day) is None
    assert service._provider is None
    assert before == (source.cursor('live', day), completed.cursor('alert', day), completed.cursor('reference', day))


@pytest.mark.parametrize('kind', ['feed', 'live'])
@pytest.mark.parametrize('revocation', ['current_failure', 'readback', 'reference_lag', 'already_restored', 'same_day_trading'])
def test_closed_cleanup_proof_is_revalidated_after_every_poll(isolated_redis, tmp_path, monkeypatch, kind, revocation):
    import json
    from types import SimpleNamespace
    from app.market_data.composition import build_closed_cleanup_evidence
    from app.market_data.market_feed import MarketFeedService, FeedLiveStore
    from app.market_data.market_phase import ProductMarketPhase
    from tests.data_foundation.test_closed_cleaned_idle import _passed_status
    day = _bar(1).trading_day
    now = _bar(1).bar_end.replace(hour=12)
    phase = ProductMarketPhase('rb', MarketPhase.CLOSED, day, None, now + timedelta(hours=1))
    if kind == 'live':
        service, source, completed, store, bar = build(isolated_redis, phase=MarketPhase.CLOSED, subscription=False)
        service._phase_resolver.phases['rb'] = phase
    else:
        bar = _bar(1)
        source = ObservationStream(isolated_redis, kind='source')
        source.initialize('live', day, cursor='0-0')
        completed = ObservationStream(isolated_redis, kind='completed')
        completed.initialize('alert', day, cursor='0-0')
        store = FeedLiveStore(isolated_redis)
        service = MarketFeedService(source_stream=source, store=store, operational_products=('rb',),
            phase_resolver=FakePhases({'rb': phase}), dominant_source=FakeDominants({('rb', day): 'RB2505'}),
            provider_factory=lambda: pytest.fail('closed cleanup cannot connect provider'),
            coverage_sessions=lambda *_args: (SessionWindow(now - timedelta(hours=4), now - timedelta(hours=3)),))
    completed.initialize('reference', day, cursor='0-0')
    commit = 'a' * 40
    directory = tmp_path / '.run'
    directory.mkdir()
    path = directory / 'after-market-status.json'
    status = _passed_status(day.isoformat(), commit)
    path.write_text(json.dumps(status))
    monkeypatch.setattr('app.runtime_bindings.resolve_service_binding', lambda _: SimpleNamespace(
        root=str(tmp_path), commit=commit, generation=19, enabled=True))
    callback = build_closed_cleanup_evidence(store, ('rb',))
    service.closed_cleanup_evidence = callback
    if revocation == 'already_restored':
        service._trading_day = day
        service._contracts = {'rb': 'RB2505'}
        service._available = True
        service.closed_cleanup_evidence = None
    else:
        assert service.poll(now) is None
        assert service.closed_cleaned_proof['status'] == 'CLOSED_CLEANED'
        if revocation == 'current_failure':
            status['last_run'].update(status='failed', error_code='TEST_FAILURE')
            path.write_text(json.dumps(status))
        elif revocation == 'readback':
            store.set_subscriptions(day, {'rb': 'RB2505'})
        elif revocation == 'same_day_trading':
            service._phase_resolver.phases['rb'] = replace(phase, phase=MarketPhase.TRADING,
                current_session=SessionWindow(now, now + timedelta(hours=1)))
        else:
            identity = completed.append(ObservationEnvelope('new-reference-pending', day, bar.bar_end,
                'live:bar:rb:1m', _bar_payload(bar, contract='RB2505'), True))
            completed.ack('alert', day, expected_cursor='0-0', next_id=identity)
    assert service.poll(now + timedelta(seconds=1)) is not None
    assert service.closed_cleaned_proof is None
    assert service._available is False
    assert service._provider is None
    assert source.cursor('live', day) == '0-0'
    assert completed.cursor('reference', day) == '0-0'
