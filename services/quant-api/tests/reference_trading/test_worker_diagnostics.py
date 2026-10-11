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
        assert kwargs['warmup'] is True
        assert kwargs['warmup_deadline'] > worker_entry.monotonic()
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


def saved_capture_fixture():
    from datetime import UTC, datetime
    from app.reference_trading.capture import ForwardCapture
    capture = ForwardCapture('stream', 'revision', 1, 'source', datetime(2026, 10, 9, tzinfo=UTC),
        datetime(2026, 10, 10, tzinfo=UTC), 'canonical_completed', {'bar': {}}, {'proof': 'original'},
        'completed_observation')
    stream = SimpleNamespace(stream_id='stream', active_revision_id='revision', activation_generation=1)
    row = SimpleNamespace(kind='capture', outcome='consumed', stream_id='stream', revision_id='revision',
        consumed_by_batch_id='calculation', expected_seq=1, payload_hash=capture.capture_hash,
        batch_id='capture', batch_key=capture.batch_key, source_evidence=capture.evidence())
    latest = SimpleNamespace(kind='calculation', batch_id='calculation', expected_seq=1,
        source_evidence={'forward_capture_v1': {'capture_id': 'capture', 'hash': capture.capture_hash,
            'generation': 1}})
    previous = SimpleNamespace(seq=1)
    session = SimpleNamespace(get=lambda model, identifier: row if identifier == 'capture' else None)
    return session, stream, latest, previous, row


def test_saved_calculation_resolves_original_full_capture_without_modification():
    session, stream, latest, previous, row = saved_capture_fixture()
    original = repr(row.source_evidence)
    evidence = worker_entry._saved_capture_evidence(session, stream, latest, previous)
    assert evidence == {**row.source_evidence, 'capture_id': 'capture'}
    assert evidence['forward_capture_v1']['eligibility'] == 'completed_observation'
    assert repr(row.source_evidence) == original
    assert 'eligibility' not in latest.source_evidence['forward_capture_v1']


@pytest.mark.parametrize('field,bad', [('revision_id', 'other'), ('stream_id', 'other'),
    ('consumed_by_batch_id', 'other'), ('expected_seq', 0), ('kind', 'calculation'),
    ('payload_hash', 'changed'), ('outcome', 'pending')])
def test_saved_capture_linkage_drift_blocks_warmup(field, bad):
    session, stream, latest, previous, row = saved_capture_fixture()
    setattr(row, field, bad)
    with pytest.raises(RuntimeError, match='REFERENCE_WARMUP_CAPTURE_CONFLICT'):
        worker_entry._saved_capture_evidence(session, stream, latest, previous)


def test_saved_capture_full_content_tamper_rejected_even_when_declared_hash_unchanged():
    session, stream, latest, previous, row = saved_capture_fixture()
    row.source_evidence['forward_capture_v1']['source_proof']['proof'] = 'changed'
    with pytest.raises(RuntimeError, match='REFERENCE_WARMUP_CAPTURE_CONFLICT'):
        worker_entry._saved_capture_evidence(session, stream, latest, previous)


@pytest.mark.parametrize('field,bad', [('capture_id', 'missing'), ('generation', 2)])
def test_saved_capture_summary_identity_drift_rejected(field, bad):
    session, stream, latest, previous, _row = saved_capture_fixture()
    latest.source_evidence['forward_capture_v1'][field] = bad
    with pytest.raises(RuntimeError, match='REFERENCE_WARMUP_CAPTURE_CONFLICT'):
        worker_entry._saved_capture_evidence(session, stream, latest, previous)


def test_refresh_deferred_until_committed_healthy_round_then_started_once():
    from app.reference_trading.runtime import ForwardReferenceWorker
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    events, rounds, blocked = [], [0], [True]
    repository = SimpleNamespace(enabled_forward_stream_ids=lambda **kwargs: ('route',)
        if kwargs.get('after') is None else (), read_pending_capture=lambda _: None)
    def service(_name):
        if blocked[0]:
            raise ForwardInputUnavailable('SOURCE_BUSY')
        return object()
    worker = ForwardReferenceWorker(repository, service, lambda *_args: None, enabled=True)
    worker.report_health = lambda proof: events.append(('proof', proof['ready']))
    refresh = SimpleNamespace(start=lambda: events.append(('refresh', True)))
    worker_entry.defer_historical_refresh(worker, refresh, should_stop=lambda: False)
    assert events == []
    def wait(_seconds):
        rounds[0] += 1
        blocked[0] = False
    worker.serve(should_stop=lambda: rounds[0] >= 2, wait=wait)
    assert events.index(('proof', True)) < events.index(('refresh', True))
    assert ('proof', False) in events and events.count(('refresh', True)) == 1
    worker.after_healthy_round()
    assert events.count(('refresh', True)) == 1


def test_drain_prevents_deferred_refresh_start_and_unstarted_close_is_safe():
    from app.reference_trading.historical_refresh import RefreshThread
    refresh = RefreshThread(SimpleNamespace(tick=lambda **kwargs: pytest.fail('unexpected refresh')))
    worker = SimpleNamespace()
    worker_entry.defer_historical_refresh(worker, refresh, should_stop=lambda: True)
    worker.after_healthy_round()
    assert not refresh.is_alive() and not refresh._started
    worker_entry.close_worker_resources(SimpleNamespace(is_alive=lambda: False), refresh,
        SimpleNamespace(close=lambda: None), warmup=False)


def test_failed_healthy_proof_does_not_start_background():
    from app.reference_trading.runtime import ForwardReferenceWorker
    repository = SimpleNamespace(enabled_forward_stream_ids=lambda **kwargs: ('route',),
        read_pending_capture=lambda _: None)
    worker = ForwardReferenceWorker(repository, lambda _: object(), lambda *_args: None, enabled=True)
    def failed_proof(proof):
        if proof['ready']:
            raise ValueError('proof commit unknown')
    worker.report_health = failed_proof
    starts = []
    worker_entry.defer_historical_refresh(worker, SimpleNamespace(start=lambda: starts.append(True)),
        should_stop=lambda: False)
    with pytest.raises(ValueError, match='proof commit unknown'):
        worker.serve(should_stop=lambda: False)
    assert not starts


def test_unknown_refresh_start_is_not_retried():
    calls = []
    def start():
        calls.append(True)
        raise ValueError('start unknown')
    worker = SimpleNamespace()
    worker_entry.defer_historical_refresh(worker, SimpleNamespace(start=start), should_stop=lambda: False)
    with pytest.raises(ValueError):
        worker.after_healthy_round()
    worker.after_healthy_round()
    assert calls == [True]


def test_drained_reports_actual_closed_threads_preserving_last_counts(monkeypatch):
    reports = []
    @contextmanager
    def opened(**kwargs):
        kwargs['report_health']({'stage': 'cycle', 'ready': False, 'blocked_counts': {'SOURCE_BUSY': 4},
            'notifications_alive': True})
        yield None
        kwargs['publish_stage']('drained', historical_refresh_alive=False, notifications_alive=False)
    monkeypatch.setattr(worker_entry, '_open_forward_worker', opened)
    with worker_entry.open_forward_worker(ownership=SimpleNamespace(mark_not_ready=reports.append)):
        pass
    proof = reports[-1]['reference_runtime']
    assert proof['stage'] == 'drained' and proof['blocked_counts'] == {'SOURCE_BUSY': 4}
    assert proof['historical_refresh_alive'] is False and proof['notifications_alive'] is False
