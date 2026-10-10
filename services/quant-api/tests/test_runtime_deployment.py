import pytest


class Backend:
    def __init__(self, ready=True, drain=True, verified=True):
        self.calls = []
        self.ready, self.drain, self.verified = ready, drain, verified
    def prepare(self, service, binding, request):
        self.calls.append(('prepare', service))
        return self.ready
    def drain_owner(self, service, binding, request):
        self.calls.append(('drain', service))
        return self.drain
    def activate(self, service, binding, request):
        self.calls.append(('activate', service))
    def verify(self, service, binding, request):
        self.calls.append(('verify', service))
        return self.verified
    def retire(self, service, binding, request):
        self.calls.append(('retire', service))
    def cancel(self, service, binding, request):
        self.calls.append(('cancel', service))


def test_failed_warmup_keeps_old_owner_and_bindings():
    from app.runtime_deployment import execute_handover
    backend = Backend(ready=False)
    writes = []
    result = execute_handover('alert', {}, {}, backend=backend, commit_binding=lambda: writes.append(1))
    assert result == 'candidate_not_ready'
    assert not writes
    assert backend.calls == [('prepare', 'alert'), ('cancel', 'alert')]


def test_drain_timeout_cancels_before_binding_write():
    from app.runtime_deployment import execute_handover
    backend = Backend(drain=False)
    writes = []
    assert execute_handover('live', {}, {}, backend=backend, commit_binding=lambda: writes.append(1)) == 'drain_cancelled'
    assert not writes
    assert backend.calls[-1] == ('cancel', 'live')


def test_readback_unknown_never_restores_or_retries():
    from app.runtime_deployment import execute_handover, DeploymentError
    backend = Backend(verified=False)
    writes = []
    with pytest.raises(DeploymentError, match='RUNTIME_HANDOVER_OUTCOME_UNKNOWN'):
        execute_handover('alert', {}, {}, backend=backend, commit_binding=lambda: writes.append(1))
    assert writes == [1]
    assert backend.calls == [('prepare', 'alert'), ('drain', 'alert'), ('activate', 'alert'), ('verify', 'alert')]


def test_success_only_retires_after_readback():
    from app.runtime_deployment import execute_handover
    backend = Backend()
    assert execute_handover('alert', {}, {}, backend=backend, commit_binding=lambda: None) == 'switched'
    assert backend.calls[-2:] == [('verify', 'alert'), ('retire', 'alert')]


def test_continuity_requires_frozen_tail_and_old_committed_frontier():
    from app.runtime_deployment import progress_reached, merge_progress
    before = {'2026-10-09': {'cursor': '100-0', 'tail': '110-0'}}
    drained = {'2026-10-09': {'cursor': '105-0', 'tail': '120-0'}}
    boundary = merge_progress(before, drained)
    assert boundary == {'2026-10-09': {'cursor': '105-0', 'tail': '110-0'}}
    assert not progress_reached(drained, boundary)
    assert progress_reached({'2026-10-09': {'cursor': '111-0', 'tail': '120-0'}}, boundary)


def test_progress_regression_or_expiry_is_not_readiness():
    from app.runtime_deployment import DeploymentError, progress_reached, merge_progress
    old = {'2026-10-09': {'cursor': '105-0', 'tail': '110-0'}}
    with pytest.raises(DeploymentError, match='REGRESSED'):
        merge_progress(old, {'2026-10-09': {'cursor': '100-0', 'tail': '110-0'}})
    with pytest.raises(DeploymentError, match='EXPIRED'):
        progress_reached({}, old)


def test_api_shutdown_waits_for_child_before_releasing_owner(monkeypatch):
    from app import runtime_deployment as d, runtime_handover
    calls = []
    class Child:
        def poll(self): return None
        def terminate(self): calls.append('terminate')
        def wait(self): calls.append('wait')
    class Owner:
        def assert_owned(self): calls.append('owned')
        def should_drain(self): return True
    def supervise(service, run, **kwargs):
        run(Owner())
        calls.append('unlock')
    monkeypatch.setattr(d.subprocess, 'Popen', lambda *a, **kw: Child())
    monkeypatch.setattr(runtime_handover, 'run_supervised', supervise)
    d._run_port_service('api')
    assert calls == ['owned', 'terminate', 'wait', 'unlock']


def test_live_future_raw_frontier_is_read_without_premature_finalization():
    from app.runtime_deployment import progress_reached
    boundary = {'2026-10-09': {'cursor': '105-0', 'tail': '110-0'}}
    current = {'2026-10-09': {'cursor': '105-0', 'tail': '120-0'}}
    proof = {'trading_day': '2026-10-09', 'input_read_frontier': '111-0'}
    assert progress_reached(current, boundary, service='live', proof=proof)
    assert not progress_reached(current, boundary, service='alert', proof=proof)
    assert not progress_reached(current, boundary, service='live', proof={**proof, 'input_read_frontier': '109-0'})
    assert not progress_reached(current, boundary, service='live', proof={**proof, 'trading_day': '2026-10-08'})
    assert not progress_reached({'2026-10-09': {'cursor': '100-0', 'tail': '120-0'}}, boundary, service='live', proof=proof)


@pytest.mark.parametrize('phase', ['prepared', 'binding_committed', 'outcome_unknown', 'invalid'])
def test_interrupted_handover_journal_cannot_be_overwritten(monkeypatch, phase):
    from app import runtime_deployment as d
    monkeypatch.setattr(d, '_read', lambda path: {'phase': phase})
    with pytest.raises(d.DeploymentError, match='RECOVERY_READBACK_REQUIRED'):
        d.assert_no_unknown_deployment()


def test_failed_unknown_journal_still_requests_exact_candidate_drain(monkeypatch):
    from types import SimpleNamespace
    from app import runtime_deployment as d
    candidate = SimpleNamespace(root='/candidate', commit='a'*40, generation=2)
    backend = d.LaunchdBackend()
    backend.candidates['alert'] = candidate
    monkeypatch.setattr(d, 'resolve_service_binding', lambda service: candidate)
    def fail(*args): raise OSError('private control failure')
    monkeypatch.setattr(d, '_write', fail)
    drains = []
    monkeypatch.setattr(d, 'request_drain', lambda service, **kw: drains.append((service, kw['generation'])))
    with pytest.raises(OSError):
        backend.halt_unknown('alert', candidate, 'request')
    assert drains == [('alert', 2)]


def test_unknown_before_binding_commit_does_not_drain_legacy(monkeypatch):
    from app import runtime_deployment as d
    backend = d.LaunchdBackend()
    backend.candidates['alert'] = object()
    monkeypatch.setattr(d, 'resolve_service_binding', lambda service: object())
    monkeypatch.setattr(d, 'request_drain', lambda *a, **kw: pytest.fail('legacy must remain untouched'))
    backend.halt_unknown('alert', None, 'request')


def test_empty_interrupted_journal_is_not_absent(monkeypatch):
    from app import runtime_deployment as d
    monkeypatch.setattr(d, '_read', lambda path: {})
    with pytest.raises(d.DeploymentError, match='RECOVERY_READBACK_REQUIRED'):
        d.assert_no_unknown_deployment()
