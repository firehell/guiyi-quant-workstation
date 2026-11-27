from dataclasses import replace
from datetime import date, timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import update
from sqlalchemy.engine import make_url

from app.market_data.live_market import RedisLiveStore
from app.market_data.market_feed import DurableLiveMarketService, FeedLiveStore, MarketFeedService, StreamLiveProvider
from app.market_data.market_foundation_scope import stage_empty_formal_tick_namespace
from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
from app.market_data.observation_stream import ObservationStream
from app.market_data.session_clock import session_windows_for_trading_day
from app.market_data.tick_feed import TickMarketDataProvider, TickPreviewStore
from app.models import TradingCalendar
from tests.data_foundation.test_live_market import FakeDominants
from tests.data_foundation.test_market_phase import session as session_fixture, _now
from tests.data_foundation.test_observation_stream import isolated_redis as redis_fixture
from tests.test_runtime_market_source_handover import redis_pair as redis_pair_fixture

session = session_fixture
isolated_redis = redis_fixture
redis_pair = redis_pair_fixture


@pytest.mark.parametrize('fault,error', [
    (None, None),
    ('no_formal_binding', None),
    ('cursor', 'OBSERVATION_DAY_BASELINE_UNPROVEN'),
    ('alert_key_type', 'OBSERVATION_DAY_BASELINE_UNPROVEN'),
    ('rank1', 'LIVE_RANK1_CATALOG_CONFLICT'),
    ('source_index', 'OBSERVATION_DAY_BASELINE_UNPROVEN'),
    ('next_session', 'OBSERVATION_DAY_MISSING'),
    ('weekend', None),
    ('opening_day', None),
    ('opening_rank1_drift', None),
    ('first_completed', None),
])
def test_market_owners_start_from_staged_next_day_after_close(redis_pair, session, tmp_path, monkeypatch, fault, error):
    old, target = redis_pair
    old_day, next_day = date(2025, 1, 3), date(2025, 1, 6)
    now = _now(4, 12) if fault == 'weekend' else _now(6, 8) if fault == 'opening_day' else _now(3, 17)
    if fault in {'weekend', 'opening_day'}:
        session.execute(update(TradingCalendar).where(
            TradingCalendar.trade_date == next_day,
        ).values(has_night_session=False))
        session.commit()
    contracts = {'jm': 'JM2505', 'ap': 'AP2505'}
    products = tuple(contracts)
    monkeypatch.setattr('app.market_data.operational_universe.load_operational_products', lambda: products)
    binding = stage_empty_formal_tick_namespace(
        target, make_url('postgresql://operator@127.0.0.1/guiyi_quant'), tmp_path,
        day=next_day, subscriptions=contracts, alert_enabled=True,
    )
    old.set('retained', old_day.isoformat())
    source = ObservationStream(target, kind='source')
    completed = ObservationStream(target, kind='completed')
    resolver = MarketPhaseResolver(session)
    for symbol in products:
        phase = resolver.resolve(symbol, now)
        assert phase.phase is MarketPhase.CLOSED
        assert resolver.completed_observation_trading_day(symbol, now) == old_day
        assert resolver.resolve(symbol, phase.next_session_start).trading_day == next_day

    ranks = {(symbol, next_day): contract for symbol, contract in contracts.items()}
    if fault == 'cursor':
        target.delete(completed.cursor_key('alert', next_day))
    if fault == 'alert_key_type':
        for key in (completed.registration_key('alert'), completed.cursor_key('alert', next_day)):
            target.delete(key)
            target.hset(key, 'bad_type', 'true')
    if fault == 'rank1':
        ranks['jm', next_day] = 'JM2509'
    if fault == 'source_index':
        target.hset(source.identity_key(next_day), 'orphan', '{}')
    if fault == 'next_session':
        resolve = resolver.resolve

        def wrong_next(symbol, at):
            phase = resolve(symbol, at)
            if symbol == 'ap' and at > now:
                return replace(phase, trading_day=date(2025, 1, 7))
            return phase

        monkeypatch.setattr(resolver, 'resolve', wrong_next)

    common = dict(
        dominant_source=FakeDominants(ranks), phase_resolver=resolver,
        operational_products=products, authoritative_dominants=True,
        coverage_sessions=lambda symbol, day: session_windows_for_trading_day(
            session, exchange='DCE' if symbol == 'jm' else 'CZCE', symbol=symbol, trading_day=day,
        ),
        prepare_trading_day=lambda _: pytest.fail('Staged receive must not run metadata preparation'),
        **({'formal_tick_binding': binding} if fault != 'no_formal_binding' else {}),
    )
    if fault == 'no_formal_binding':
        common.pop('prepare_trading_day')

    def owners():
        history = SimpleNamespace(
            start=lambda: pytest.fail('Staged Live must not start history preparation'),
            stop=lambda: None, snapshot=lambda: {},
        )
        return (
            DurableLiveMarketService(source_provider=StreamLiveProvider(source, require_tick=True),
                                     store=RedisLiveStore(target), history_preparation=history,
                                     clock=lambda: now, sleep=lambda _: None, **common),
            MarketFeedService(source_stream=source, store=FeedLiveStore(target), tick_source=True,
                              provider_factory=lambda: pytest.fail('CLOSED must not open the Tick provider'), **common),
        )

    before = {key: target.dump(key) for key in target.scan_iter()}
    live, feed = owners()
    if error is not None or fault == 'no_formal_binding':
        assert live.poll(now) == (error or 'OBSERVATION_DAY_MISSING')
        assert feed.poll(now) == (error or 'OBSERVATION_DAY_REGRESSION')
        assert live._trading_day is None and feed._trading_day is None
        if error is not None:
            assert RedisLiveStore(target).heartbeat()['available'] is False
            assert json.loads(target.get('live:feed:heartbeat'))['available'] is False
    else:
        stop_flags = iter((False, True))
        live.run_forever(should_stop=lambda: next(stop_flags))
        assert not live._can_start_history_preparation()
        for live, feed in ((live, feed), owners()):
            # Live starts before Feed. The latter must still verify the baseline
            # after the former has already published an owner heartbeat.
            for at in (now, now + timedelta(seconds=3)):
                assert live.poll(at) is None and feed.poll(at) is None
                assert live._trading_day == feed._trading_day == next_day
                assert live._contracts == feed._contracts == contracts
                assert live.source_provider.day == next_day and live.source_provider.after == '0-0'
                assert live._provider is None and feed._provider is None
                live_pulse = RedisLiveStore(target).heartbeat()
                assert live_pulse['available'] is True
                assert live_pulse['phase_counts'] == {'CLOSED': 2}
                assert all(row['trading_day'] == str(next_day) for row in live_pulse['coverage'].values())
                pulse = json.loads(target.get('live:feed:heartbeat'))
                assert pulse['available'] is True and pulse['registered_day'] == str(next_day)
                assert pulse['subscribed_count'] == pulse['input_pending_count'] == 0
        if fault == 'opening_rank1_drift':
            ranks['jm', next_day] = 'JM2509'
            start = _now(3, 21)
            assert live.poll(start) == feed.poll(start) == 'LIVE_RANK1_CATALOG_CONFLICT'
            assert RedisLiveStore(target).heartbeat()['available'] is False
            assert json.loads(target.get('live:feed:heartbeat'))['available'] is False

    assert old.get('retained') == old_day.isoformat()
    assert {key: target.dump(key) for key in before} == before
    assert set(target.scan_iter()) - before.keys() <= {'live:heartbeat', 'live:feed:heartbeat'}
    assert source.tail(next_day) == completed.tail(next_day) == '0-0'
    if fault == 'first_completed':
        start = _now(3, 21)
        clock = [start]

        class Client:
            def subscribe(self, channels):
                assert channels == ['tick_JM2505']

            def listen(self, *, handler):
                self.handler = handler

        client = Client()
        feed._provider_factory = lambda: TickMarketDataProvider(
            client, connection_identity=lambda: client, preview=TickPreviewStore(), clock=lambda: clock[0],
        )
        feed._prepare_trading_day = live._prepare_trading_day = None
        assert feed.poll(start) is None
        for minute in (0, 1):
            seen = start + timedelta(minutes=minute)
            clock[0] = seen + timedelta(milliseconds=10)
            client.handler({
                'channel': 'tick_JM2505', 'action': 'feed', 'order_book_id': 'JM2505',
                'datetime': seen, 'last': 100 + minute, 'volume': minute,
                'total_turnover': 100 * minute, 'open_interest': 51,
            })
            clock[0] = seen + timedelta(seconds=3)
            assert feed.poll(clock[0]) is None
            assert live.poll(clock[0]) is None
        reading, = completed.read('alert', next_day)
        assert reading.channel == 'live:bar:jm:1m'
        assert reading.data['contract'] == 'JM2505' and reading.trading_day == next_day
        assert source.cursor('live', next_day) == source.tail(next_day) != '0-0'
        assert completed.cursor('alert', next_day) == '0-0'
        assert live._can_start_history_preparation()


def make_service(redis, session, *, registered_day=date(2025, 1, 6), formal_tick_binding=None):
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
        formal_tick_binding=formal_tick_binding,
        coverage_sessions=lambda symbol, day: session_windows_for_trading_day(session,
            exchange='DCE' if symbol == 'jm' else 'CZCE', symbol=symbol, trading_day=day))
    return service, source, completed, store, resolver


def test_formal_live_resumes_history_preparation_on_proved_cleaned_day(isolated_redis, session):
    service, source, completed, store, _ = make_service(isolated_redis, session, formal_tick_binding='a' * 64)
    day = date(2025, 1, 6)
    isolated_redis.delete(store._subscription_key(day))
    service.closed_cleanup_evidence = lambda *_: {'trading_day': day.isoformat(), 'cleanup_verified': True}
    assert not service._can_start_history_preparation()
    assert service.poll(_now(6, 17)) is None
    assert service.closed_cleaned_proof['status'] == 'CLOSED_CLEANED'
    assert service._can_start_history_preparation()
    assert source.cursor('live', day) == completed.tail(day) == '0-0'


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
