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
    assert service.poll(bar.bar_end - timedelta(minutes=10)) == 'OBSERVATION_SUBSCRIPTION_MISSING'
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
