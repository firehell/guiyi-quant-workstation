from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.reference_trading import worker_entry


def test_startup_failure_retains_stage_and_only_safe_enum(monkeypatch):
    reports = []
    owner = SimpleNamespace(mark_not_ready=reports.append)
    @contextmanager
    def failing(**kwargs):
        kwargs['publish_stage']('stream_subscribe')
        raise ValueError('private-password SQL details')
        yield
    monkeypatch.setattr(worker_entry, '_open_forward_worker', failing)
    with pytest.raises(ValueError):
        with worker_entry.open_forward_worker(ownership=owner):
            pass
    assert reports[-1] == {'reference_runtime': {'stage': 'stream_subscribe',
        'ready': False, 'failure_code': 'UNCLASSIFIED_FAILURE'}}
    assert 'password' not in str(reports)


def test_warmup_skips_idle_durable_minutes_but_validates_canonical_service(monkeypatch):
    calls = []
    repository = SimpleNamespace(
        enabled_forward_stream_ids=lambda **kwargs: () if kwargs['after'] else ('minute', 'daily'),
        read_pending_capture=lambda _: None,
        forward_source_context=lambda name: (SimpleNamespace(frequency='60m' if name == 'minute' else '1d'),),
        load_checkpoint=lambda name: calls.append(('checkpoint', name)) or (None, None))
    worker = SimpleNamespace(_repository=repository, scan_live=False,
        _work_key=lambda name: name, _work_routes=lambda name: (name,),
        _service_for=lambda name: calls.append(('service', name)) or object(),
        _read_input=lambda *_args: None)
    @contextmanager
    def opened(**kwargs):
        assert kwargs == {'warmup': True}
        yield worker, None, None
    monkeypatch.setattr(worker_entry, 'open_forward_worker', opened)
    monkeypatch.setattr(worker_entry, '_warmup_saved_capture', lambda _repository, name, _service:
        calls.append(('pure_compute', name)))
    assert worker_entry.warmup_reference_worker() == {'calculated': 1}
    assert calls == [('service', 'daily'), ('checkpoint', 'daily'), ('pure_compute', 'daily')]


def test_drain_diagnostic_preserves_last_blocked_counts(monkeypatch):
    reports = []
    owner = SimpleNamespace(mark_not_ready=reports.append)
    @contextmanager
    def opened(**kwargs):
        kwargs['report_health']({'stage': 'cycle', 'ready': False, 'blocked_counts': {'SOURCE_BUSY': 4}})
        yield None
        kwargs['publish_stage']('draining')
    monkeypatch.setattr(worker_entry, '_open_forward_worker', opened)
    with worker_entry.open_forward_worker(ownership=owner):
        pass
    assert reports[-1]['reference_runtime'] == {'stage': 'draining', 'ready': False,
        'blocked_counts': {'SOURCE_BUSY': 4}}


def test_failed_notification_stop_still_attempts_refresh_and_wake_close():
    calls = []
    def fail():
        calls.append('notifications')
        raise ValueError('stop failed')
    notifications = SimpleNamespace(is_alive=lambda: True, stop=fail)
    refresh = SimpleNamespace(stop=lambda **kwargs: calls.append(('refresh', kwargs)))
    wake = SimpleNamespace(close=lambda: calls.append('wake'))
    with pytest.raises(ValueError):
        worker_entry.close_worker_resources(notifications, refresh, wake, warmup=False)
    assert calls == ['notifications', ('refresh', {'timeout': None}), 'wake']


def test_warmup_validates_entire_live_group_when_one_route_pending(monkeypatch):
    calls = []
    repository = SimpleNamespace(
        enabled_forward_stream_ids=lambda **kwargs: () if kwargs['after'] else ('first', 'second'),
        read_pending_capture=lambda name: ('capture', {}) if name == 'second' else None,
        forward_source_context=lambda _: (SimpleNamespace(frequency='60m'),),
        load_checkpoint=lambda _: (None, None))
    service = SimpleNamespace(_evaluator=lambda *_args: None)
    worker = SimpleNamespace(_repository=repository, scan_live=False,
        _work_key=lambda _: 'group', _work_routes=lambda _: ('first', 'second'),
        _service_for=lambda name: calls.append(name) or service, _read_input=lambda *_args: None)
    @contextmanager
    def opened(**kwargs):
        yield worker, None, None
    monkeypatch.setattr(worker_entry, 'open_forward_worker', opened)
    monkeypatch.setattr(worker_entry, '_warmup_saved_capture', lambda *_args: None)
    assert worker_entry.warmup_reference_worker() == {'calculated': 2}
    assert calls == ['first', 'second']
