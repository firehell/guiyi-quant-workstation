from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from app.runtime_bootstrap import BootstrapBackend, BootstrapError


@pytest.fixture
def boundary(monkeypatch, tmp_path):
    now = datetime.now(UTC)
    status = {
        'last_transport_attempt_at': (now - timedelta(minutes=1)).isoformat(),
        'last_provider_accepted_at': (now - timedelta(minutes=1)).isoformat(),
        'last_notification_failure_at': (now - timedelta(hours=1)).isoformat(),
        'notification_error_type': 'notification_transport_failed',
        'notification_acknowledged_at': None,
    }
    raw = json.dumps(status).encode()
    products = tuple(chr(97 + i // 26) + chr(97 + i % 26) for i in range(60))
    plan = {'installed': {'alert': {'root': str(tmp_path), 'commit': 'a' * 40,
        'label': 'com.guiyi.quant-alert', 'enabled': True, 'loaded_pid': 123}}}
    calls = []
    database = {'advisory_available': True, 'unknown_delivery': False}
    heartbeat = {'generated_at': now.isoformat(), 'recovery_guard_enabled': True,
        'runtime_root': str(tmp_path), 'runtime_commit': 'a' * 40}
    class Redis:
        def get(self, key):
            calls.append(('read', key))
            return json.dumps(status).encode() if key == 'alert:runtime-status' else json.dumps(heartbeat).encode()
        def close(self):
            pass
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def execute(self, query):
            sql = str(query)
            assert sql.startswith('SELECT ')
            calls.append(('sql', sql))
            return SimpleNamespace(first=lambda: object() if database['unknown_delivery'] else None,
                scalar=lambda: database['advisory_available'])
    engine = SimpleNamespace(connect=lambda: Connection())
    class Session:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def get_bind(self):
            return engine
        def scalars(self, _query):
            return rules
    rules = []
    @contextmanager
    def symbol_guard(product, **options):
        assert options['legacy_root'] is True
        calls.append(('locked', product))
        yield
        calls.append(('released', product))
    monkeypatch.setattr('app.redis_connections.get_redis_connection', Redis)
    monkeypatch.setattr('app.db.session.engine', engine)
    monkeypatch.setattr('app.db.session.SessionLocal', Session)
    monkeypatch.setattr('app.market_data.operational_universe.load_operational_products', lambda: products)
    monkeypatch.setattr('app.market_data.live_recovery_guard.recovery_guard', symbol_guard)
    monkeypatch.setattr('app.market_data.catalog.MarketCatalog', lambda *_args:
        SimpleNamespace(acquire_maintenance_lock=lambda: SimpleNamespace(release=lambda: None)))
    backend = BootstrapBackend()
    monkeypatch.setattr(backend, '_pid', lambda _label: 123)
    return SimpleNamespace(backend=backend, plan=plan, calls=calls, raw=raw, status=status,
        rules=rules, heartbeat=heartbeat, Redis=Redis, products=products, database=database)


def test_retained_failure_readback_is_not_unlocked_idle_proof(boundary):
    assert boundary.backend.read_send_boundary() == {
        'historical_notification_error': True, 'transport_idle_proven': False}
    with pytest.raises(BootstrapError, match='SEND_GUARDS_REQUIRED'):
        boundary.backend.prove_no_inflight_sends()


def test_all_legacy_locks_allow_terminal_history_without_mutating_facts(boundary):
    original = boundary.raw
    with boundary.backend.writer_guards(boundary.plan):
        assert len([call for call in boundary.calls if call[0] == 'locked']) == 60
        assert not [call for call in boundary.calls if call[0] == 'released']
        boundary.backend.prove_no_inflight_sends()  # Also valid after stop_legacy.
    assert boundary.Redis().get('alert:runtime-status') == original
    assert boundary.status['notification_acknowledged_at'] is None
    with pytest.raises(BootstrapError, match='SEND_GUARDS_REQUIRED'):
        boundary.backend.prove_no_inflight_sends()


@pytest.mark.parametrize('kind', ['busy', 'active_call'])
def test_busy_legacy_send_lock_blocks_before_any_stop(boundary, monkeypatch, kind):
    @contextmanager
    def blocked_guard(*_args, **_kwargs):
        raise RuntimeError('LIVE_RECOVERY_BUSY')
        yield
    monkeypatch.setattr('app.market_data.live_recovery_guard.recovery_guard', blocked_guard)
    with pytest.raises(RuntimeError, match='LIVE_RECOVERY_BUSY'):
        with boundary.backend.writer_guards(boundary.plan):
            pytest.fail('cannot stop the active transport')
    assert not getattr(boundary.backend, '_transport_guards_held', False)


def test_notifying_canonical_scope_cannot_claim_symbol_lock_proof(boundary):
    from app.alerts.registry import HTDY_ALERT_RULE_CODE
    boundary.rules.append(SimpleNamespace(rule_code=HTDY_ALERT_RULE_CODE,
        scope_product_frequencies={'aa': ['1d']}))
    with pytest.raises(BootstrapError, match='CANONICAL_DRAIN_UNSUPPORTED'):
        with boundary.backend.writer_guards(boundary.plan):
            pytest.fail('unguarded canonical transport')


def test_non_notifying_canonical_rule_preserves_send_guard_proof(boundary):
    from app.alerts.registry import SUBING_THS_ALERT_RULE_CODE
    boundary.rules.append(SimpleNamespace(rule_code=SUBING_THS_ALERT_RULE_CODE,
        scope_product_frequencies={'aa': ['1d', '1w']}))
    with boundary.backend.writer_guards(boundary.plan):
        boundary.backend.prove_no_inflight_sends()


def test_newow_advisory_busy_prevents_proof_and_stop(boundary):
    boundary.database['advisory_available'] = False
    with pytest.raises(BootstrapError, match='NEWOW_SEND_BUSY'):
        with boundary.backend.writer_guards(boundary.plan):
            pytest.fail('active notification thread must finish its call')
    assert not getattr(boundary.backend, '_transport_guards_held', False)


def test_existing_unknown_claim_blocks_even_with_all_send_locks(boundary):
    boundary.database['unknown_delivery'] = True
    with pytest.raises(BootstrapError, match='NEWOW_SEND_UNKNOWN'):
        with boundary.backend.writer_guards(boundary.plan):
            pytest.fail('unknown one-shot outcome cannot be recovered by retry')


@pytest.mark.parametrize('field,value', [
    ('last_notification_failure_at', None),
    ('last_notification_failure_at', '2026-10-09T03:00:00'),
    ('last_notification_failure_at', '2099-10-09T03:00:00+00:00'),
    ('last_transport_attempt_at', None),
    ('last_provider_accepted_at', None),
])
def test_incomplete_or_future_diagnostic_still_blocks_under_locks(boundary, field, value):
    boundary.status[field] = value
    with pytest.raises(BootstrapError, match='ALERT_SEND_UNKNOWN'):
        with boundary.backend.writer_guards(boundary.plan):
            pytest.fail('missing terminal history evidence')


def test_equal_batch_failure_is_not_proven_by_equal_acceptance(boundary):
    boundary.status['last_notification_failure_at'] = boundary.status['last_provider_accepted_at']
    with pytest.raises(BootstrapError, match='ALERT_SEND_UNKNOWN'):
        with boundary.backend.writer_guards(boundary.plan):
            pytest.fail('timestamps are not per-delivery facts')


@pytest.mark.parametrize('field,value', [
    ('recovery_guard_enabled', False), ('runtime_commit', 'b' * 40),
    ('generated_at', (datetime.now(UTC) - timedelta(minutes=2)).isoformat()),
])
def test_missing_fresh_exact_guard_identity_blocks(boundary, field, value):
    boundary.heartbeat[field] = value
    with pytest.raises(BootstrapError, match='ALERT_DRAIN_UNSUPPORTED'):
        with boundary.backend.writer_guards(boundary.plan):
            pytest.fail('identity proof absent')
