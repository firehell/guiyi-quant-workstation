"""Equivalent Decimal text must not rewrite recovery facts or refresh observation age."""
from collections import deque
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency
from app.market_data.live_market import RedisLiveStore, _bar_payload, _compact_json, _epoch_millis
from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
from tests.data_foundation.test_live_market import _bar
from tests.data_foundation import test_observation_stream as stream_tests


@pytest.fixture
def isolated_redis():
    yield from stream_tests.isolated_redis.__wrapped__()


def setup(redis, frequency=BarFrequency.M1):
    bar = _bar(1)
    day = bar.trading_day
    source = ObservationStream(redis, kind='source')
    source.initialize('live', day, cursor='0-0')
    completed = ObservationStream(redis, kind='completed')
    completed.initialize('alert', day, cursor='0-0')
    provider = StreamLiveProvider(source)
    provider.day = day
    observed = bar.bar_end + timedelta(seconds=1)
    event = ObservationEnvelope('raw', day, observed, 'live:bar:rb:1m', {}, True)
    identifier = source.append(event)
    provider.records = deque([(identifier, ('RB2505', bar.bar_end))])
    service = object.__new__(DurableLiveMarketService)
    service.source_provider = provider
    service.completed_stream = completed
    service._store = RedisLiveStore(redis)
    service._contracts = {'rb': 'RB2505'}
    service._finalized = set()
    observations = [('rb', frequency, bar, 'RB2505', observed)]
    return service, observations, source, completed, identifier


def snapshot(redis):
    return {key: redis.dump(key) for key in redis.scan_iter()}


@pytest.mark.parametrize('frequency', (BarFrequency.M1, BarFrequency.M5))
def test_equal_recovery_keeps_payload_and_completed_is_idempotent(isolated_redis, frequency):
    service, observations, source, completed, identifier = setup(isolated_redis, frequency)
    _, _, bar, contract, observed = observations[0]
    payload = _bar_payload(bar, contract=contract)
    for field in ('open', 'high', 'low', 'close', 'volume', 'turnover', 'open_interest'):
        if payload[field] is not None:
            payload[field] = str(Decimal(payload[field]).quantize(Decimal('0.000')))
    old = _compact_json(payload)
    key = service._store._bars_key(bar.trading_day, 'rb', frequency)
    isolated_redis.zadd(key, {old: _epoch_millis(bar.bar_end)})
    confirmed = observed + timedelta(seconds=2)
    service._commit(observations, completed_keys={(contract, bar.bar_end)}, confirmed_at=confirmed)
    assert source.cursor('live', bar.trading_day) == identifier
    assert isolated_redis.zrange(key, 0, -1) == [old]
    first = completed.read('alert', bar.trading_day)[0]
    assert first.source_observed_at == first.raw_received_at == observed
    assert first.confirmed_at == confirmed
    changed_bar = replace(bar, close=bar.close.quantize(Decimal('0.000')))
    service._commit([('rb', frequency, changed_bar, contract, observed)],
                    completed_keys={(contract, bar.bar_end)}, confirmed_at=confirmed + timedelta(hours=1))
    events = completed.read('alert', bar.trading_day)
    assert len(events) == 1 and events[0].to_json() == first.to_json()
    assert isolated_redis.zrange(key, 0, -1) == [old]


@pytest.mark.parametrize('field', ('open', 'high', 'low', 'close', 'volume', 'turnover', 'open_interest',
                                  'contract', 'bar_end', 'trading_day', 'extra'))
def test_recovery_real_difference_is_atomic_conflict(isolated_redis, field):
    service, observations, source, completed, identifier = setup(isolated_redis)
    bar = observations[0][2]
    payload = _bar_payload(bar, contract='RB2505')
    if field == 'contract':
        payload[field] = 'RB2510'
    elif field == 'bar_end':
        payload[field] = (bar.bar_end + timedelta(minutes=1)).isoformat()
    elif field == 'trading_day':
        payload[field] = (bar.trading_day + timedelta(days=1)).isoformat()
    elif field == 'extra':
        payload[field] = 'unproven'
    else:
        payload[field] = str(Decimal(payload[field] or '0') + 1)
    key = service._store._bars_key(bar.trading_day, 'rb', BarFrequency.M1)
    isolated_redis.zadd(key, {_compact_json(payload): _epoch_millis(bar.bar_end)})
    before = snapshot(isolated_redis)
    with pytest.raises(ValueError, match='OBSERVATION_CONTENT_CONFLICT'):
        service._commit(observations, completed_keys={('RB2505', bar.bar_end)},
                        confirmed_at=bar.bar_end + timedelta(seconds=3))
    assert snapshot(isolated_redis) == before


@pytest.mark.parametrize('field', ('source_observed_at', 'raw_received_at', 'channel', 'notification_eligible'))
def test_prior_completed_metadata_cannot_be_rewritten(isolated_redis, field):
    import json
    service, observations, _, completed, _ = setup(isolated_redis)
    bar = observations[0][2]
    confirmed = bar.bar_end + timedelta(seconds=3)
    service._commit(observations, completed_keys={('RB2505', bar.bar_end)}, confirmed_at=confirmed)
    event = completed.read('alert', bar.trading_day)[0]
    value = {'source_observed_at': event.source_observed_at + timedelta(seconds=1),
             'raw_received_at': event.raw_received_at + timedelta(seconds=1),
             'channel': 'live:bar:jm:1m', 'notification_eligible': False}[field]
    rewritten = replace(event, **{field: value})
    record_key = completed.identity_key(bar.trading_day)
    record = json.loads(isolated_redis.hget(record_key, event.observation_id))
    record['payload'] = rewritten.to_json()
    isolated_redis.hset(record_key, event.observation_id, json.dumps(record))
    before = snapshot(isolated_redis)
    with pytest.raises(ValueError, match='OBSERVATION_CONTENT_CONFLICT'):
        service._commit(observations, completed_keys={('RB2505', bar.bar_end)}, confirmed_at=confirmed)
    assert snapshot(isolated_redis) == before


@pytest.mark.parametrize('mutation', ('removed', 'rewritten'))
def test_read_then_commit_drift_remains_atomic(isolated_redis, monkeypatch, mutation):
    service, observations, source, completed, _ = setup(isolated_redis)
    bar = observations[0][2]
    key = service._store._bars_key(bar.trading_day, 'rb', BarFrequency.M1)
    old = _compact_json(_bar_payload(bar, contract='RB2505'))
    isolated_redis.zadd(key, {old: _epoch_millis(bar.bar_end)})
    real_eval = isolated_redis.eval
    captured = {}

    def mutate_then_commit(*args):
        isolated_redis.zrem(key, old)
        if mutation == 'rewritten':
            changed = _compact_json(_bar_payload(replace(bar, volume=bar.volume + 1), contract='RB2505'))
            isolated_redis.zadd(key, {changed: _epoch_millis(bar.bar_end)})
        captured['before'] = snapshot(isolated_redis)
        return real_eval(*args)

    monkeypatch.setattr(isolated_redis, 'eval', mutate_then_commit)
    with pytest.raises(ValueError, match='OBSERVATION_CONTENT_CONFLICT'):
        service._commit(observations, completed_keys={('RB2505', bar.bar_end)},
                        confirmed_at=bar.bar_end + timedelta(seconds=3))
    assert snapshot(isolated_redis) == captured['before']
    assert source.cursor('live', bar.trading_day) == '0-0'
    assert completed.tail(bar.trading_day) == '0-0'


@pytest.mark.parametrize('value', ('NaN', 'Infinity', '-Infinity', 'invalid', 1.0))
def test_unproven_decimal_is_rejected(value):
    from app.market_data.market_feed import _equivalent_bar_payload
    assert not _equivalent_bar_payload({'close': value}, {'close': '1'})


def test_decimal_equivalence_never_uses_binary_float():
    from app.market_data.market_feed import _equivalent_bar_payload
    assert _equivalent_bar_payload({'close': '9007199254740993.000'}, {'close': '9007199254740993'})
    assert not _equivalent_bar_payload({'close': '9007199254740993'}, {'close': '9007199254740992'})
