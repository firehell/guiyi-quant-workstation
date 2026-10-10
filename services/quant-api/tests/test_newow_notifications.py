"""Delivery boundary tests use persisted source facts, never provider network."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.notifications.newow import (NewowNotificationDispatcher, NewowNotificationPolicy,
    NewowNotificationDelivery, enable_newow_notifications, STRATEGIES, FREQUENCIES)
from app.reference_trading.models import ReferenceBatch, ReferenceStream, ReferenceActionRow, ReferenceRevision

NOW = datetime(2026, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def factory():
    engine = create_engine('sqlite://')
    for table in (NewowNotificationPolicy.__table__, NewowNotificationDelivery.__table__,
                  ReferenceStream.__table__, ReferenceBatch.__table__, ReferenceActionRow.__table__, ReferenceRevision.__table__):
        table.create(engine)
    return sessionmaker(engine, expire_on_commit=False)


def point(kind='BUILD', **values):
    return {'kind': 'action', 'value': {'kind': kind, 'signal_id': 'stable-signal',
        'bar_end': (NOW + timedelta(minutes=5)).isoformat(),
        'observed_at': (NOW + timedelta(minutes=6)).isoformat(),
        'physical_contract': 'J2701', 'reference_price': '100', **values}}


def insert_batch(factory, strategy='newow_trend', frequency='1d', points=None, batch_id='b', revision='r'):
    with factory() as session:
        stream_id = strategy + frequency
        if session.get(ReferenceStream, stream_id) is None:
            session.add(ReferenceStream(stream_id=stream_id, identity_hash=stream_id,
                strategy_code=strategy, formula_versions=['v1'], profile_id='p', reference_model_version='m',
                futures_adaptation_version='f', product='j', frequency=frequency, series_kind='actual_dominant',
                recording_mode='forward_observation', observation_policy_version='v1', enabled=True,
                active_revision_id=revision, latest_seq=1, health='READY'))
        stream = session.get(ReferenceStream, stream_id)
        if stream is None:
            session.flush()
            stream = session.get(ReferenceStream, stream_id)
        stream.active_revision_id = revision
        sequence = 1 + session.scalar(select(func.count()).select_from(ReferenceBatch).where(ReferenceBatch.stream_id == stream_id, ReferenceBatch.revision_id == revision))
        stream.latest_seq = sequence
        if session.get(ReferenceRevision, (stream_id, revision)) is None:
            session.add(ReferenceRevision(stream_id=stream_id, revision_id=revision, status='active', dependency_digest='h'))
        session.add(ReferenceBatch(batch_id=batch_id, stream_id=stream_id, revision_id=revision,
            batch_key=batch_id, payload_hash='h', kind='calculation', outcome='committed', seq=sequence,
            expected_seq=0, observed_at=NOW+timedelta(minutes=6), dependency_manifest={}, source_evidence={'presentation_v1': {'version': 'presentation_v1',
            'points': points or [point()]}}, projected_action_pks=[], diagnostics=[], processed_at=NOW+timedelta(minutes=7)))
        session.commit()


def enabled(factory):
    with factory() as session:
        return enable_newow_notifications(session, products=['j'], enabled_at=NOW, topic_hash='hash')


class Transport:
    def __init__(self, fail=False):
        self.deliveries = []
        self.fail = fail
    def send(self, delivery):
        self.deliveries.append(delivery)
        if self.fail:
            raise TimeoutError('private provider detail')


def test_default_off_never_loads_transport(factory):
    assert NewowNotificationDispatcher(factory).tick()['enabled'] is False


@pytest.mark.parametrize('strategy', STRATEGIES[:3])
@pytest.mark.parametrize('frequency', FREQUENCIES)
def test_each_source_strategy_frequency(factory, strategy, frequency):
    enabled(factory)
    insert_batch(factory, strategy, frequency)
    transport = Transport()
    assert NewowNotificationDispatcher(factory, transport=transport, topic_hash='hash', clock=lambda: NOW + timedelta(minutes=6)).tick()['attempted'] == 1
    assert transport.deliveries[0].audience == 'htdy_observers'
    assert '仅供研究观察' in transport.deliveries[0].content


@pytest.mark.parametrize('bad', [point('HOLD'), {'kind': 'hint', 'value': point()['value']},
    point(bar_end=(NOW-timedelta(minutes=1)).isoformat()), point(observed_at=NOW.isoformat()),
    point(trade_eligibility='WARMUP_ONLY')])
def test_no_history_state_or_hints(factory, bad):
    enabled(factory)
    insert_batch(factory, points=[bad])
    if bad.get('value', {}).get('observed_at') == NOW.isoformat():
        with factory() as session:
            session.get(ReferenceBatch, 'b').observed_at = NOW
            session.commit()
    assert NewowNotificationDispatcher(factory, transport=Transport(), topic_hash='hash', clock=lambda: NOW + timedelta(minutes=6)).tick()['attempted'] == 0


def test_failure_not_retried_and_claim_before_call(factory):
    enabled(factory)
    insert_batch(factory)
    class CheckedTransport(Transport):
        def send(self, delivery):
            with factory() as session:
                assert session.scalar(select(NewowNotificationDelivery)).status == 'ATTEMPTED_UNKNOWN'
            super().send(delivery)
    transport = CheckedTransport(fail=True)
    dispatcher = NewowNotificationDispatcher(factory, transport=transport, topic_hash='hash', clock=lambda: NOW + timedelta(minutes=6))
    dispatcher.tick()
    insert_batch(factory, batch_id='b2', revision='r2')
    assert dispatcher.tick()['attempted'] == 0
    assert len(transport.deliveries) == 1


def test_reduce_without_reference_trade_row(factory):
    enabled(factory)
    insert_batch(factory, strategy='newow_main_rise', points=[point('REDUCE')])
    assert NewowNotificationDispatcher(factory, transport=Transport(), topic_hash='hash', clock=lambda: NOW + timedelta(minutes=6)).tick()['attempted'] == 1


def test_topic_drift_fails_closed(factory):
    enabled(factory)
    with pytest.raises(ValueError, match='TOPIC_CHANGED'):
        NewowNotificationDispatcher(factory, transport=Transport(), topic_hash='other').tick()


def test_bounded_cursor_drains_without_starvation(factory):
    enabled(factory)
    for n in range(3):
        insert_batch(factory, batch_id=f'b{n}', points=[point(signal_id=f's{n}')])
    dispatcher = NewowNotificationDispatcher(factory, transport=Transport(), topic_hash='hash', clock=lambda: NOW + timedelta(minutes=6))
    assert [dispatcher.tick(limit=1)['attempted'] for _ in range(4)] == [1, 1, 1, 0]


@pytest.mark.parametrize('frequency', FREQUENCIES)
def test_fusion_action_uses_own_stream_reference_row(factory, frequency):
    enabled(factory)
    insert_batch(factory, strategy='newow_dual_fusion', frequency=frequency,
                 points=[point('OPEN_LONG', source_signal_id='stable-signal')])
    with factory() as session:
        session.add(ReferenceActionRow(action_pk='a', stream_id='newow_dual_fusion'+frequency,
            origin_revision_id='r', batch_revision_id='r', source_action_id='stable-signal',
            recording_mode='forward_observation', kind='OPEN_LONG', sequence=0, physical_contract='J2701',
            owner_segment_id='seg', calculation_segment_id='seg', bar_end=NOW+timedelta(minutes=5),
            trading_day=NOW.date(), observed_at=NOW+timedelta(minutes=6), reference_price=100,
            reference_price_type='reference', batch_id='b', batch_seq=1))
        session.commit()
    assert NewowNotificationDispatcher(factory, transport=Transport(), topic_hash='hash', clock=lambda: NOW + timedelta(minutes=6)).tick()['attempted'] == 1


def test_late_commit_older_timestamp_is_not_lost(factory):
    enabled(factory)
    insert_batch(factory, batch_id='z')
    dispatcher = NewowNotificationDispatcher(factory, transport=Transport(), topic_hash='hash', clock=lambda: NOW + timedelta(minutes=6))
    assert dispatcher.tick()['attempted'] == 1
    insert_batch(factory, batch_id='a', revision='r2', points=[point(signal_id='late-signal')])
    with factory() as session:
        row = session.get(ReferenceBatch, 'a')
        row.processed_at = NOW + timedelta(minutes=6)
        session.commit()
    assert dispatcher.tick()['attempted'] == 1


@pytest.mark.parametrize('strategy', ['trend', 'oscillation', 'main_rise'])
def test_product_action_actual_presentation_serialization(factory, strategy):
    import json
    from types import SimpleNamespace
    from newow.product_fixtures import ProductCases
    from app.reference_trading.presentation import presentation_point, envelope, require_envelope
    case = ProductCases().closed(strategy=strategy)
    action = case.entry
    observed = action.bar_end + timedelta(seconds=5)
    persisted = json.loads(json.dumps(envelope([presentation_point(kind='action', value=action,
        trading_day=action.trading_day, formula_versions=case.identity.formula_versions)])))
    saved_point = require_envelope(persisted)[0]
    saved_point['value']['observed_at'] = observed.isoformat()
    policy = SimpleNamespace(enabled_at=action.bar_end-timedelta(seconds=1))
    stream = SimpleNamespace(strategy_code='newow_'+strategy, product=case.identity.product, frequency='1d')
    candidate = NewowNotificationDispatcher._candidate(None, policy, SimpleNamespace(observed_at=observed, source_evidence={}), stream, saved_point)
    assert candidate[0] == action.signal_id
    assert str(action.reference_price) in candidate[1].content


@pytest.mark.parametrize('eligibility', ['INITIAL_CLEAR_NO_ENTRY', 'NO_ELIGIBLE_ENTRY'])
def test_formal_clear_observation_does_not_require_reference_entry(factory, eligibility):
    enabled(factory)
    insert_batch(factory, points=[point('CLEAR', trade_eligibility=eligibility)])
    assert NewowNotificationDispatcher(factory, transport=Transport(), topic_hash='hash', clock=lambda: NOW + timedelta(minutes=6)).tick()['attempted'] == 1

@pytest.mark.parametrize('age,expected', [(30, 1), (31, 0)])
def test_source_observation_deadline_keeps_expired_fact_without_attempt(factory, age, expected):
    enabled(factory)
    insert_batch(factory)
    transport = Transport()
    dispatcher = NewowNotificationDispatcher(factory, transport=transport, topic_hash='hash',
        clock=lambda: NOW + timedelta(minutes=6, seconds=age))
    assert dispatcher.tick()['attempted'] == expected
    assert len(transport.deliveries) == expected
    dispatcher.tick()
    assert len(transport.deliveries) == expected
    with factory() as session:
        row = session.scalar(select(NewowNotificationDelivery).where(NewowNotificationDelivery.signal_id == 'stable-signal'))
        if not expected:
            assert row.status == 'EXPIRED_NO_SEND'
            assert row.attempted_at is None



def test_drain_does_not_claim_or_receipt_unprocessed_batch(factory):
    enabled(factory)
    insert_batch(factory)
    transport = Transport()
    dispatcher = NewowNotificationDispatcher(factory, transport=transport, topic_hash='hash',
        clock=lambda: NOW + timedelta(minutes=6), should_stop=lambda: True)
    assert dispatcher.tick() == {'enabled': True, 'processed': 0, 'attempted': 0}
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(NewowNotificationDelivery)) == 0
    dispatcher.should_stop = lambda: False
    assert dispatcher.tick()['attempted'] == 1


def test_ownership_lost_after_claim_never_sends_or_rewrites_claim(factory):
    enabled(factory)
    insert_batch(factory)
    transport = Transport()
    calls = []
    def assert_owned():
        calls.append(True)
        if len(calls) > 1:
            raise RuntimeError('RUNTIME_GENERATION_CHANGED')
    dispatcher = NewowNotificationDispatcher(factory, transport=transport, topic_hash='hash',
        clock=lambda: NOW + timedelta(minutes=6), assert_owned=assert_owned)
    with pytest.raises(RuntimeError, match='GENERATION_CHANGED'):
        dispatcher.tick()
    assert transport.deliveries == []
    with factory() as session:
        row = session.scalar(select(NewowNotificationDelivery))
        assert row.status == 'ATTEMPTED_UNKNOWN'
        assert session.scalar(select(func.count()).select_from(NewowNotificationDelivery)) == 1


def test_completed_confirmation_never_extends_original_raw_deadline(factory):
    enabled(factory)
    insert_batch(factory)
    with factory() as session:
        batch = session.get(ReferenceBatch, 'b')
        batch.source_evidence = {**batch.source_evidence, 'observation_timing_v1': {
            'raw_received_at': (NOW + timedelta(minutes=5, seconds=20)).isoformat(),
            'confirmed_at': (NOW + timedelta(minutes=6)).isoformat()}}
        session.commit()
    transport = Transport()
    result = NewowNotificationDispatcher(factory, transport=transport, topic_hash='hash',
        clock=lambda: NOW + timedelta(minutes=6)).tick()
    assert result['attempted'] == 0
    assert transport.deliveries == []
