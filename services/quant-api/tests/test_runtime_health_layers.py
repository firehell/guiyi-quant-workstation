from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services import runtime_health as health


def _build(monkeypatch, *, alert=None, reference=None, live=None):
    monkeypatch.delenv('GUIYI_RUNTIME_COMMIT', raising=False)
    monkeypatch.setattr(health, 'resolve_service_binding', lambda _: None)
    monkeypatch.setattr(health, '_collect_db_health', lambda _: {'status': 'ok'})
    monkeypatch.setattr(health, '_collect_redis_health', lambda _: (None, {'status': 'ok'}))
    monkeypatch.setattr(health, '_collect_live_market_health', lambda *a, **k: live or {'status': 'ok'})
    monkeypatch.setattr(health, '_collect_after_market_health', lambda *a, **k: {'status': 'ok'})
    monkeypatch.setattr(health, '_collect_alert_health', lambda *a, **k: alert or {
        'status': 'ok', 'notification': {'transport': 'pushplus'}, 'coverage': {}})
    monkeypatch.setattr(health, '_collect_reference_owner_health', lambda *a: reference or {'status': 'disabled'})
    monkeypatch.setattr(health, 'weekly_audit_health', lambda *a, **k: {'status': 'disabled'})
    monkeypatch.setattr(health, 'load_operational_products', lambda: ())
    return health.build_runtime_health(None, now=datetime(2026, 10, 30, 13, 6, tzinfo=UTC),
        live_runtime_enabled=True, after_market_automation_enabled=True, alert_runtime_enabled=True,
        weekly_audit_enabled=False, notification_transport_configured=True)


def test_strategy_wait_does_not_report_basic_service_failure(monkeypatch):
    result = _build(monkeypatch, alert={'status': 'ok', 'notification': {'transport': 'pushplus'},
        'processing_state': 'ok', 'coverage': {'subing:rs:1w': {
            'state': 'warming_up', 'error_type': 'evaluation_warming_up'}}})
    assert result['status'] == 'ok'
    assert result['components']['alert']['coverage']['subing:rs:1w']['state'] == 'warming_up'


@pytest.mark.parametrize('code', ['SUBING_REFERENCE_DATA_UNAVAILABLE', 'SOURCE_BUSY', 'REFERENCE_CANONICAL_MISMATCH'])
def test_reference_business_diagnostic_is_separate_and_strict(monkeypatch, code):
    result = _build(monkeypatch, reference={'status': 'degraded', 'error_type': 'reference_routes_blocked',
        'blocked_count': 1, 'blocked_counts': {code: 1}})
    assert result['status'] == 'ok'
    assert result['components']['reference_worker']['status'] == 'degraded'
    assert result['components']['reference_worker']['blocked_counts'] == {code: 1}


@pytest.mark.parametrize('error', ['alert_heartbeat_stale', 'alert_heartbeat_missing',
                                  'alert_heartbeat_invalid', 'alert_unavailable',
                                  'alert_runtime_status_invalid', 'runtime_identity_unavailable'])
def test_actual_alert_service_fault_remains_unhealthy(monkeypatch, error):
    result = _build(monkeypatch, alert={'status': 'degraded', 'error_type': error,
        'notification': {'transport': 'pushplus'}, 'coverage': {}})
    assert result['status'] == 'degraded'


@pytest.mark.parametrize('status,expected', [('unknown', 'degraded'), ('disabled', 'ok'),
                                            ('invalid', 'degraded')])
def test_reference_unknown_identity_is_not_disabled(monkeypatch, status, expected):
    result = _build(monkeypatch, reference={'status': status})
    assert result['status'] == expected


def test_actual_processing_failure_is_not_strategy_wait(monkeypatch):
    result = _build(monkeypatch, alert={'status': 'degraded', 'processing_state': 'failed',
        'notification': {'transport': 'pushplus'}, 'processing_error_type': 'evaluation_failed'})
    assert result['status'] == 'degraded'


def test_live_data_lag_remains_operational_failure(monkeypatch):
    result = _build(monkeypatch, live={'status': 'degraded', 'coverage_state': 'lagging'})
    assert result['status'] == 'degraded'


def test_actual_strategy_error_is_retained_without_claiming_readiness(monkeypatch):
    result = _build(monkeypatch, alert={'status': 'degraded', 'processing_state': 'ok',
        'notification': {'transport': 'pushplus'}, 'coverage': {'subing:rb:1w': {
            'state': 'evaluation_failed', 'input_error_code': 'MARKET_READ_WINDOW_INCOMPLETE',
            'previous_unresolved': '2026-10-29'}}})
    assert result['status'] == 'ok'
    assert result['components']['alert']['status'] == 'degraded'
    assert result['components']['alert']['coverage']['subing:rb:1w']['previous_unresolved'] == '2026-10-29'


def test_reference_owner_freshness_and_failure_are_not_relaxed():
    now = datetime(2026, 10, 30, 13, 6, tzinfo=UTC)
    state = {'generation': 43, 'pid': 17, 'phase': 'active', 'at': now.isoformat(), 'ready': False,
             'proof': {'reference_runtime': {'blocked_count': 1,
                 'blocked_counts': {'SOURCE_BUSY': 1}, 'stage': 'cycle'}}}
    binding = SimpleNamespace(generation=43)
    identity = {'status': 'matched', 'loaded_pid': 17}
    result = health._reference_owner_health(binding, identity, state, now)
    assert result['status'] == 'degraded'
    assert health._service_health_status('reference_worker', result) == 'ok'
    state['proof']['reference_runtime']['failure_code'] = 'REFERENCE_WORKER_FAILED'
    failed = health._reference_owner_health(binding, identity, state, now)
    assert failed['error_type'] == 'reference_worker_failed'
    assert health._service_health_status('reference_worker', failed) == 'degraded'
    state['pid'] = 18
    assert health._reference_owner_health(binding, identity, state, now)['status'] == 'degraded'



@pytest.mark.parametrize('background,receiving,expected', [
    ({'historical_refresh_alive': False, 'historical_refresh_error': None}, None, 'ok'),
    ({'historical_refresh_alive': False, 'historical_refresh_error': 'REFRESH_FAILED'}, None, 'degraded'),
    ({'historical_refresh_alive': True}, {'protocol_version': 2, 'intake_error': 'REFERENCE_INBOX_FAILED'}, 'degraded'),
    ({'notifications_alive': False}, None, 'degraded'),
])
def test_reference_deferred_refresh_and_real_intake_failure_are_distinct(background, receiving, expected):
    now = datetime(2026, 10, 30, 13, 6, tzinfo=UTC)
    proof = {'reference_runtime': {'stage': 'receiving_cycle', 'blocked_count': 1,
        'blocked_counts': {'SOURCE_BUSY': 1}, **background}}
    if receiving is not None:
        proof['receiving'] = receiving
    state = {'generation': 43, 'pid': 17, 'phase': 'active', 'at': now.isoformat(),
             'ready': False, 'proof': proof}
    component = health._reference_owner_health(SimpleNamespace(generation=43),
        {'status': 'matched', 'loaded_pid': 17}, state, now)
    assert health._service_health_status('reference_worker', component) == expected
    assert component['status'] == 'degraded'  # strict route/input gate remains closed
    assert component['blocked_counts'] == {'SOURCE_BUSY': 1}
