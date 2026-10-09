"""Real PostgreSQL migration and one-shot delivery tests in guarded random schema."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import threading
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.alerts.notification import ProviderAcceptance
from app.notifications.newow import (NewowNotificationDispatcher, NewowNotificationDelivery,
    enable_newow_notifications)
from app.reference_trading.models import ReferenceStream, ReferenceRevision, ReferenceBatch
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401

pytestmark = pytest.mark.isolated_postgresql
NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


@pytest.fixture
def pg_factory(isolated_postgres_engine):  # noqa: F811
    schema = 'newow_delivery_' + uuid4().hex
    with isolated_postgres_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        ops = Operations(MigrationContext.configure(connection))
        root = Path(__file__).resolve().parents[1] / 'alembic' / 'versions'
        for name in ('20260919_0047_reference_trading.py', '20260923_0048_reference_forward.py',
                     '20261009_0050_newow_notifications.py'):
            spec = importlib.util.spec_from_file_location('newow_test_migration', root / name)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.op = ops
            module.upgrade()
    scoped = isolated_postgres_engine.execution_options(schema_translate_map={None: schema})
    try:
        yield sessionmaker(scoped, expire_on_commit=False)
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


def _enable(factory):
    with factory() as session:
        enable_newow_notifications(session, products=['j'], enabled_at=NOW, topic_hash='topic-hash')


def _batch(factory, batch_id='b1', signal='s1', processed=None):
    with factory() as session:
        stream = session.get(ReferenceStream, 's')
        if stream is None:
            stream = ReferenceStream(stream_id='s', identity_hash='h', strategy_code='newow_trend',
                formula_versions=['v1'], profile_id='p', reference_model_version='m',
                futures_adaptation_version='f', product='j', frequency='1d', series_kind='actual_dominant',
                recording_mode='forward_observation', observation_policy_version='v1', enabled=True,
                latest_seq=0, health='READY')
            session.add(stream)
            session.flush()
            session.add(ReferenceRevision(stream_id='s', revision_id='r', status='active', dependency_digest='h'))
            session.flush()
            stream.active_revision_id = 'r'
        stream.latest_seq += 1
        session.add(ReferenceBatch(batch_id=batch_id, stream_id='s', revision_id='r', batch_key=batch_id,
            payload_hash='h', kind='calculation', outcome='committed', seq=stream.latest_seq,
            expected_seq=stream.latest_seq-1, observed_at=NOW+timedelta(minutes=6), dependency_manifest={},
            source_evidence={'presentation_v1': {'version': 'presentation_v1', 'points': [{'kind': 'action',
                'value': {'kind': 'BUILD', 'signal_id': signal, 'physical_contract': 'J2701',
                    'reference_price': '100', 'bar_end': (NOW+timedelta(minutes=5)).isoformat(),
                    'observed_at': (NOW+timedelta(minutes=6)).isoformat()}}]}},
            projected_action_pks=[], diagnostics=[], processed_at=processed or NOW+timedelta(minutes=7)))
        session.commit()


def test_migration_default_off(pg_factory):
    assert NewowNotificationDispatcher(pg_factory).tick() == {'enabled': False, 'processed': 0, 'attempted': 0}


def test_claim_committed_before_provider_and_unknown_not_retried(pg_factory):
    _enable(pg_factory)
    _batch(pg_factory)
    class Transport:
        calls = 0
        def send(self, _delivery):
            with pg_factory() as session:
                row = session.scalar(select(NewowNotificationDelivery).where(NewowNotificationDelivery.status == 'ATTEMPTED_UNKNOWN'))
                assert row is not None
            self.calls += 1
            raise TimeoutError('outcome unknown')
    transport = Transport()
    dispatcher = NewowNotificationDispatcher(pg_factory, transport=transport, topic_hash='topic-hash')
    assert dispatcher.tick()['attempted'] == 1
    assert dispatcher.tick()['attempted'] == 0
    _batch(pg_factory, 'b2', 's1')
    assert dispatcher.tick()['attempted'] == 0
    assert transport.calls == 1


def test_concurrent_dispatchers_send_once(pg_factory):
    _enable(pg_factory)
    _batch(pg_factory)
    entered, release = threading.Event(), threading.Event()
    class Transport:
        calls = 0
        def send(self, _delivery):
            self.calls += 1
            entered.set()
            assert release.wait(timeout=10)
            return ProviderAcceptance(reference='private-receipt')
    transport = Transport()
    first = NewowNotificationDispatcher(pg_factory, transport=transport, topic_hash='topic-hash')
    second = NewowNotificationDispatcher(pg_factory, transport=transport, topic_hash='topic-hash')
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(first.tick)
        assert entered.wait(timeout=10)
        try:
            assert second.tick()['busy'] is True
        finally:
            release.set()
        assert future.result()['attempted'] == 1
    assert transport.calls == 1
    with pg_factory() as session:
        row = session.scalar(select(NewowNotificationDelivery).where(NewowNotificationDelivery.status == 'PROVIDER_ACCEPTED'))
        assert row.provider_reference == 'private-receipt'
        assert row.finished_at is not None


def test_late_commit_with_older_timestamp_discovered(pg_factory):
    _enable(pg_factory)
    _batch(pg_factory)
    class Transport:
        def send(self, _delivery):
            return ProviderAcceptance()
    dispatcher = NewowNotificationDispatcher(pg_factory, transport=Transport(), topic_hash='topic-hash')
    assert dispatcher.tick()['attempted'] == 1
    _batch(pg_factory, 'late', 'late-signal', processed=NOW+timedelta(minutes=6))
    assert dispatcher.tick()['attempted'] == 1
