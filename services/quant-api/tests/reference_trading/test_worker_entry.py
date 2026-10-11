import pytest

from app.reference_trading import worker_entry


@pytest.mark.parametrize('release_after', [0.2, None])
def test_warmup_lease_wait_is_bounded_by_shared_deadline(monkeypatch, release_after):
    from types import SimpleNamespace
    clock, attempts = [0.0], []
    lease = object()
    monkeypatch.setattr(worker_entry, 'monotonic', lambda: clock[0], raising=False)
    def sleep(seconds):
        clock[0] += seconds
    monkeypatch.setattr(worker_entry, 'sleep', sleep, raising=False)
    def acquire():
        attempts.append(clock[0])
        return lease if release_after is not None and clock[0] >= release_after else None
    catalog = SimpleNamespace(acquire_maintenance_lock=acquire)
    if release_after is None:
        with pytest.raises(RuntimeError, match='REFERENCE_WARMUP_TIMEOUT'):
            worker_entry._acquire_canonical_lease(catalog, deadline=120.0)
        assert clock[0] == pytest.approx(120.0)
        assert max(attempts) < 120.0
    else:
        assert worker_entry._acquire_canonical_lease(catalog, deadline=120.0) is lease
        assert clock[0] == pytest.approx(release_after)


def test_formal_canonical_lease_does_not_wait(monkeypatch):
    from types import SimpleNamespace
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    monkeypatch.setattr(worker_entry, 'sleep', lambda _: pytest.fail('formal mode waited'), raising=False)
    calls = []
    catalog = SimpleNamespace(acquire_maintenance_lock=lambda: calls.append(1))
    with pytest.raises(ForwardInputUnavailable, match='SOURCE_BUSY'):
        worker_entry._acquire_canonical_lease(catalog, deadline=None)
    assert calls == [1]


def test_warmup_lease_acquired_after_deadline_is_released(monkeypatch):
    from types import SimpleNamespace
    clock, released = [0.0], []
    monkeypatch.setattr(worker_entry, 'monotonic', lambda: clock[0])
    lease = SimpleNamespace(release=lambda: released.append(True))
    def acquire():
        clock[0] = 120.0
        return lease
    with pytest.raises(RuntimeError, match='REFERENCE_WARMUP_TIMEOUT'):
        worker_entry._acquire_canonical_lease(SimpleNamespace(acquire_maintenance_lock=acquire), deadline=120.0)
    assert released == [True]


def test_entire_warmup_shares_one_deadline(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    clock, checked = [10.0], []
    monkeypatch.setattr(worker_entry, 'monotonic', lambda: clock[0])
    repository = SimpleNamespace(
        enabled_forward_stream_ids=lambda **_: ('first', 'second'),
        read_pending_capture=lambda _: None,
        forward_source_context=lambda _: (SimpleNamespace(frequency='1d'),),
        load_checkpoint=lambda _: (None, None))
    worker = SimpleNamespace(_repository=repository, scan_live=False,
        _service_for=lambda name: checked.append(name), _read_input=lambda *_: None)
    @contextmanager
    def opened(**kwargs):
        assert kwargs == {'warmup': True, 'warmup_deadline': 130.0}
        yield worker, None, None
    monkeypatch.setattr(worker_entry, 'open_forward_worker', opened)
    def compute(*_):
        clock[0] = 130.0
    monkeypatch.setattr(worker_entry, '_warmup_saved_capture', compute)
    with pytest.raises(RuntimeError, match='REFERENCE_WARMUP_TIMEOUT'):
        worker_entry.warmup_reference_worker()
    assert checked == ['first']


def test_worker_stays_off_without_exact_marker(tmp_path, monkeypatch):
    marker = tmp_path / "reference-worker-enabled"
    monkeypatch.setattr(worker_entry, "ACTIVATION_MARKER", marker)
    with pytest.raises(RuntimeError, match="REFERENCE_WORKER_NOT_ENABLED"):
        with worker_entry.open_forward_worker():
            raise AssertionError("disabled worker must not open resources")
    marker.write_text("enabled", encoding="utf-8")
    with pytest.raises(RuntimeError, match="REFERENCE_WORKER_NOT_ENABLED"):
        worker_entry.require_worker_enabled()


def test_unknown_historical_attempt_survives_release_root_change(tmp_path, monkeypatch):
    from pathlib import Path
    from app.reference_trading import worker_entry
    from app.reference_trading.historical_refresh import RefreshStateStore, VERSION
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(worker_entry, "PROJECT_ROOT", tmp_path / "release-one")
    old_path = worker_entry.historical_refresh_state_path()
    unknown = {"version": VERSION, "cursor": "", "routes": {"stream": {"status": "inflight"}}}
    RefreshStateStore(old_path).write(unknown)
    monkeypatch.setattr(worker_entry, "PROJECT_ROOT", tmp_path / "release-two")
    assert worker_entry.historical_refresh_state_path() == old_path
    assert RefreshStateStore(worker_entry.historical_refresh_state_path()).read() == unknown


def test_main_signal_stops_batch_after_current_observation(monkeypatch):
    from contextlib import contextmanager
    from copy import deepcopy
    import signal
    from types import SimpleNamespace
    from app import runtime_bindings, runtime_handover
    from tests.reference_trading.test_live_wake import _durable_wake_with_backlog
    wake, worker, _, acknowledgements = _durable_wake_with_backlog()
    first = wake._stream.read()[0]
    second = deepcopy(first)
    second.stream_id = '2-0'
    wake._stream.read = lambda *_, **__: (first, second)
    handlers, reads = {}, []
    monkeypatch.setattr(worker_entry.signal, 'signal', lambda name, handler: handlers.setdefault(name, handler))
    def read(*_):
        reads.append('read')
        handlers[signal.SIGTERM](signal.SIGTERM, None)
    worker._read_input = read
    def serve(*, should_stop, wait):
        assert not should_stop()
        wake.poll()
        assert should_stop()
    worker.serve = serve
    @contextmanager
    def opened(**_):
        yield worker, wake, SimpleNamespace()
    monkeypatch.setattr(worker_entry, 'open_forward_worker', opened)
    monkeypatch.setattr(runtime_bindings, 'read_bindings', lambda: object())
    monkeypatch.setattr(runtime_handover, 'run_supervised', lambda _name, run, **_: run(
        SimpleNamespace(should_drain=lambda: False)))
    monkeypatch.setenv('GUIYI_RUNTIME_LEGACY_MODE', '0')
    assert worker_entry.main() == 0
    assert reads == ['read'] and len(acknowledgements) == 1
