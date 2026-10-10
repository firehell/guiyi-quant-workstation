from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.market_data.live_market import RedisLiveStore
from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
from app.market_data.observation_stream import ObservationStream
from app.market_data.session_clock import session_windows_for_trading_day
from tests.data_foundation.test_live_market import FakeDominants
from tests.data_foundation.test_market_phase import session as session_fixture, _now
from tests.data_foundation.test_observation_stream import isolated_redis as redis_fixture

session = session_fixture
isolated_redis = redis_fixture


def make_service(redis, session, *, registered_day=date(2025, 1, 6)):
    products = ('jm', 'ap')
    contracts = {'jm': 'JM2505', 'ap': 'AP2505'}
    source = ObservationStream(redis, kind='source')
    source.initialize('live', registered_day, cursor='0-0')
    completed = ObservationStream(redis, kind='completed')
    completed.initialize('alert', registered_day, cursor='0-0')
    store = RedisLiveStore(redis)
    store.set_subscriptions(registered_day, contracts)
    resolver = MarketPhaseResolver(session)
    service = DurableLiveMarketService(source_provider=StreamLiveProvider(source),
        dominant_source=FakeDominants({(symbol, registered_day): contract for symbol, contract in contracts.items()}),
        phase_resolver=resolver, store=store, operational_products=products, authoritative_dominants=True,
        coverage_sessions=lambda symbol, day: session_windows_for_trading_day(session,
            exchange='DCE' if symbol == 'jm' else 'CZCE', symbol=symbol, trading_day=day))
    return service, source, completed, store, resolver


def test_real_weekend_closed_has_no_day_but_next_session_proves_registered_day(isolated_redis, session):
    service, source, completed, store, resolver = make_service(isolated_redis, session)
    now = _now(4, 12)
    next_starts = set()
    for symbol in ('jm', 'ap'):
        phase = resolver.resolve(symbol, now)
        assert phase.phase is MarketPhase.CLOSED and phase.trading_day is None
        assert phase.next_session_start is not None
        next_starts.add(phase.next_session_start)
        upcoming = resolver.resolve(symbol, phase.next_session_start)
        assert upcoming.phase is MarketPhase.TRADING and upcoming.trading_day == date(2025, 1, 6)
    assert next_starts  # Both products derive ownership from their own Session facts.
    assert service.poll(now) is None
    assert service._trading_day == date(2025, 1, 6)
    assert service._provider is None
    assert store.heartbeat()['phase_counts'] == {'CLOSED': 2}
    assert store.heartbeat()['available'] is True
    assert source.cursor('live', date(2025, 1, 6)) == '0-0'
    assert source.tail(date(2025, 1, 6)) == completed.tail(date(2025, 1, 6)) == '0-0'


def test_real_next_session_later_than_registration_waits_for_feed(isolated_redis, session):
    service, source, completed, store, _resolver = make_service(isolated_redis, session, registered_day=date(2025, 1, 3))
    assert service.poll(_now(4, 12)) == 'OBSERVATION_DAY_AWAITING_FEED'
    assert service._halted is None
    assert not isolated_redis.exists(source.cursor_key('live', date(2025, 1, 6)))
    assert completed.tail(date(2025, 1, 3)) == '0-0'
    assert store.heartbeat()['available'] is False


@pytest.mark.parametrize('failure', ['unknown', 'missing_next', 'misaligned_window'])
def test_unproven_next_session_does_not_restore_day(isolated_redis, session, monkeypatch, failure):
    service, source, _completed, _store, resolver = make_service(isolated_redis, session)
    real_resolve = resolver.resolve
    now = _now(4, 12)
    def unknown_next(symbol, timestamp):
        result = real_resolve(symbol, timestamp)
        if timestamp == now:
            return replace(result, next_session_start=None) if failure == 'missing_next' else result
        if failure == 'misaligned_window':
            return replace(result, current_session=replace(result.current_session,
                start=result.current_session.start + timedelta(minutes=1)))
        return replace(result, phase=MarketPhase.UNKNOWN, trading_day=None)
    monkeypatch.setattr(resolver, 'resolve', unknown_next)
    assert service.poll(now) == 'OBSERVATION_DAY_MISSING'
    assert service._trading_day is None
    assert source.cursor('live', date(2025, 1, 6)) == '0-0'



def test_product_next_session_day_conflict_is_not_feed_wait(isolated_redis, session, monkeypatch):
    service, source, _completed, _store, resolver = make_service(isolated_redis, session)
    real_resolve = resolver.resolve
    now = _now(4, 12)
    def conflict(symbol, timestamp):
        result = real_resolve(symbol, timestamp)
        return replace(result, trading_day=date(2025, 1, 7)) if symbol == 'ap' and timestamp != now else result
    monkeypatch.setattr(resolver, 'resolve', conflict)
    assert service.poll(now) == 'LIVE_TRADING_DAY_INCONSISTENT'
    assert service._halted == 'LIVE_TRADING_DAY_INCONSISTENT'
    assert service._trading_day is None
    assert source.cursor('live', date(2025, 1, 6)) == '0-0'
