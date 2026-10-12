"""Recovery proof uses immutable journals and disposable Redis only."""
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.live_market import RedisLiveStore, _bar_payload, _compact_json
from app.market_data.market_feed import DurableLiveMarketService, StreamLiveProvider
from app.market_data.observation_restore import build_projection_restore_plan, restore_missing_projections, _hash
from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
from tests.data_foundation import test_observation_stream as stream_tests
from tests.data_foundation.test_live_market import _bar, _phase, FakeDominants, FakePhases


@pytest.fixture
def isolated_redis():
    yield from stream_tests.isolated_redis.__wrapped__()


def fixture(redis):
    base = _bar(1)
    day = base.trading_day
    mapping = {'rb': 'RB2505', 'jm': 'JM2505'}
    window = SessionWindow(base.bar_end-timedelta(minutes=1), base.bar_end+timedelta(minutes=74))
    source = ObservationStream(redis, kind='source')
    completed = ObservationStream(redis, kind='completed')
    source.initialize('live', day, cursor='0-0')
    completed.initialize('alert', day, cursor='0-0')
    completed.initialize('reference', day, cursor='0-0')
    old_cursor = '0-0'
    for minute in range(1, 6):
        bar = replace(base, bar_end=base.bar_end+timedelta(minutes=minute-1))
        for symbol, contract in mapping.items():
            payload = _bar_payload(bar, contract=contract)
            data = {**payload, 'subscription_snapshot': mapping}
            observed = bar.bar_end+timedelta(seconds=1)
            raw = ObservationEnvelope(sha256(_compact_json(data).encode()).hexdigest(), day, observed,
                                      f'live:bar:{symbol}:1m', data, True, raw_received_at=observed)
            identifier = source.append(raw)
            if minute <= 2:
                identity = f'{day}:{contract}:1m:{bar.bar_end.isoformat()}'
                completed.append(ObservationEnvelope(identity, day, observed, raw.channel, payload, True,
                    raw_received_at=observed, confirmed_at=observed+timedelta(seconds=2)))
                source.ack('live', day, expected_cursor=old_cursor, next_id=identifier)
                old_cursor = identifier
    # Preserve the evidence that recovery was attempted, without deleting/ignoring it.
    redis.set(f'live:recovery:{day}:rb:RB2505', json.dumps({'revision': 1, 'recovered_through': base.bar_end.isoformat()}), ex=259200)
    redis.set(f'live:recovery:{day}:rb:RB2505:attempt:1', 'original attempt', ex=259200)
    evidence = {'trading_day': str(day), 'rank1_matches_snapshot': True, 'cleanup_verified': True,
                'scope_sha256': _hash(list(mapping)), 'snapshot_sha256': _hash(mapping),
                'formal_rank1_sha256': _hash(mapping)}
    arguments = {'day': day, 'products': tuple(mapping), 'formal_rank1': mapping,
                 'natural_live_evidence': evidence, 'session_for_bar': lambda *_: window}
    return base, mapping, window, source, completed, arguments


def test_missing_projection_restore_then_original_source_drain(isolated_redis):
    base, mapping, window, source, completed, args = fixture(isolated_redis)
    source_dump = isolated_redis.dump(source.key(base.trading_day))
    prefix = isolated_redis.xrange(completed.key(base.trading_day))
    recovery = {key: isolated_redis.dump(key) for key in isolated_redis.scan_iter(match='live:recovery:*')}
    plan = build_projection_restore_plan(isolated_redis, **args)
    assert plan.source_count == 10 and plan.completed_count == 4
    assert len(json.loads(plan.changes_json)['bars']) == 4
    restore_missing_projections(isolated_redis, plan, expected_sha256=plan.sha256, assert_owned=lambda: None)
    assert isolated_redis.xrange(completed.key(base.trading_day)) == prefix
    assert isolated_redis.dump(source.key(base.trading_day)) == source_dump
    assert RedisLiveStore(isolated_redis).subscriptions(base.trading_day) == mapping
    service = DurableLiveMarketService(source_provider=StreamLiveProvider(source),
        dominant_source=FakeDominants({(symbol, base.trading_day): contract for symbol, contract in mapping.items()}),
        phase_resolver=FakePhases({symbol: _phase(symbol, base.trading_day, window) for symbol in mapping}),
        store=RedisLiveStore(isolated_redis), operational_products=tuple(mapping))
    assert service.poll(base.bar_end+timedelta(minutes=5)) is None
    assert source.cursor('live', base.trading_day) == plan.source_tail
    after = isolated_redis.xrange(completed.key(base.trading_day))
    assert after[:len(prefix)] == prefix and len(after) == 12
    assert isolated_redis.dump(source.key(base.trading_day)) == source_dump
    assert {key: isolated_redis.dump(key) for key in isolated_redis.scan_iter(match='live:recovery:*')} == recovery
    restored = build_projection_restore_plan(isolated_redis, **args)
    assert json.loads(restored.changes_json)['bars'] == []
    assert json.loads(restored.changes_json)['snapshot'] is None


@pytest.mark.parametrize('mutation', ('source', 'completed', 'snapshot', 'recovery', 'new_recovery'))
def test_exact_preimage_drift_rejects_atomic_apply(isolated_redis, mutation):
    base, mapping, _, source, completed, args = fixture(isolated_redis)
    plan = build_projection_restore_plan(isolated_redis, **args)
    if mutation == 'source':
        isolated_redis.xadd(source.key(base.trading_day), {'envelope': '{}'})
    elif mutation == 'completed':
        isolated_redis.xadd(completed.key(base.trading_day), {'envelope': '{}'})
    elif mutation == 'snapshot':
        RedisLiveStore(isolated_redis).set_subscriptions(base.trading_day, mapping)
    elif mutation == 'recovery':
        isolated_redis.set(f'live:recovery:{base.trading_day}:rb:RB2505', 'changed recovery')
    else:
        isolated_redis.set(f'live:recovery:{base.trading_day}:rb:RB2505:attempt:2', 'new attempt')
    before = {key: isolated_redis.dump(key) for key in isolated_redis.scan_iter()}
    with pytest.raises(ValueError, match='RESTORE_PREIMAGE_DRIFT'):
        restore_missing_projections(isolated_redis, plan, expected_sha256=plan.sha256, assert_owned=lambda: None)
    assert {key: isolated_redis.dump(key) for key in isolated_redis.scan_iter()} == before


@pytest.mark.parametrize('field', ('snapshot_sha256', 'formal_rank1_sha256', 'scope_sha256', 'cleanup_verified'))
def test_false_natural_evidence_blocks_readonly_plan(isolated_redis, field):
    *_, args = fixture(isolated_redis)
    args['natural_live_evidence'][field] = False if field == 'cleanup_verified' else '0'*64
    with pytest.raises(ValueError, match='RESTORE_NATURAL_EVIDENCE_CONFLICT'):
        build_projection_restore_plan(isolated_redis, **args)



def test_owner_rejection_precedes_all_mutation(isolated_redis):
    *_, args = fixture(isolated_redis)
    plan = build_projection_restore_plan(isolated_redis, **args)
    before = {key: isolated_redis.dump(key) for key in isolated_redis.scan_iter()}

    def reject():
        raise ValueError('RUN_OWNERSHIP_LOST')

    with pytest.raises(ValueError, match='RUN_OWNERSHIP_LOST'):
        restore_missing_projections(isolated_redis, plan, expected_sha256=plan.sha256, assert_owned=reject)
    assert {key: isolated_redis.dump(key) for key in isolated_redis.scan_iter()} == before



def test_acknowledged_source_requires_original_completion_fact(isolated_redis):
    base, _, _, _, completed, args = fixture(isolated_redis)
    first_id, first_fields = isolated_redis.xrange(completed.key(base.trading_day), count=1)[0]
    event = ObservationEnvelope.from_json(first_fields['envelope'])
    isolated_redis.xdel(completed.key(base.trading_day), first_id)
    isolated_redis.hdel(completed.identity_key(base.trading_day), event.observation_id)
    with pytest.raises(ValueError, match='RESTORE_ACKNOWLEDGED_PREFIX_UNPROVEN'):
        build_projection_restore_plan(isolated_redis, **args)
