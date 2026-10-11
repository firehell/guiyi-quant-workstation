"""Cooperative foreground priority preserves frozen history and unknown facts."""
from threading import Event
from types import SimpleNamespace

from app.reference_trading.historical_refresh import RefreshThread
from app.market_data.newow.product_reader import NewowProductReadCancelled
from app.reference_trading.refresh_plan_codec import decode_plan
from tests.reference_trading.test_historical_refresh import setup, route, END


def test_background_requires_new_healthy_grant_and_yields_without_stop():
    permitted, active, yielded, finished, ticked = Event(), Event(), Event(), Event(), Event()
    calls = []
    def begin():
        if not permitted.is_set():
            return False
        permitted.clear()
        active.set()
        return True
    def finish():
        active.clear()
        finished.set()
    class Runner:
        def tick(self, *, now, cancelled):
            calls.append(now)
            ticked.set()
            while not cancelled():
                yielded.wait(.01)
    thread = RefreshThread(Runner(), interval=.01, can_run=permitted.is_set,
        yield_requested=yielded.is_set, on_tick_started=begin, on_tick_finished=finish)
    thread.start()
    try:
        assert not ticked.wait(.05)
        permitted.set()
        assert ticked.wait(1) and active.is_set()
        yielded.set()
        assert finished.wait(1)
        ticked.clear()
        assert not ticked.wait(.15) and len(calls) == 1
        assert thread.is_alive() and thread.last_error is None
    finally:
        thread.stop(timeout=1)
    assert not thread.is_alive()


def test_claim_race_does_not_start_tick_or_fake_finish():
    observed = Event()
    def begin():
        observed.set()
        return False
    thread = RefreshThread(SimpleNamespace(tick=lambda **_: (_ for _ in ()).throw(AssertionError())),
        can_run=lambda: True, on_tick_started=begin,
        on_tick_finished=lambda: (_ for _ in ()).throw(AssertionError()))
    thread.start()
    try:
        assert observed.wait(1) and thread.last_error is None
    finally:
        thread.stop(timeout=1)


def test_planning_cancel_keeps_pending_plan_and_cursor(tmp_path):
    runner, planner, service = setup(tmp_path, [('blocked', 'REBUILD_REQUIRED', False)])
    runner.tick(now=END)
    before = runner.state.read()
    cancelled = Event()
    def interrupted(_request):
        cancelled.set()
        raise NewowProductReadCancelled('NEWOW_READ_CANCELLED')
    planner.plan = interrupted
    runner.tick(now=END, cancelled=cancelled.is_set)
    assert runner.state.read() == before and len(service.calls) == 1


def test_initial_service_read_cancel_keeps_complete_rebuild_plan(tmp_path):
    runner, planner, service = setup(tmp_path, [
        ('blocked', 'REBUILD_REQUIRED', False), ('partial', 'INPUT_READ_INTERRUPTED', False)])
    runner.tick(now=END)
    cancelled = Event()
    original = service.rebuild
    def cancel_read(plan, expected):
        cancelled.set()
        return original(plan, expected)
    service.rebuild = cancel_read
    runner.tick(now=END, cancelled=cancelled.is_set)
    row = runner.state.read()['routes'][route().identity.stream_id]
    assert row['status'] == 'pending' and row['reason'] == 'INTERRUPTED'
    assert decode_plan(row['plan'])['operation'] == 'rebuild' and 'resume' not in row


def test_storage_unknown_wins_over_yield(tmp_path, monkeypatch):
    from app.reference_trading.historical_refresh import RefreshStateError
    import pytest
    runner, _planner, _service = setup(tmp_path, [])
    entered = Event()
    original = runner.state.write
    def write(value):
        if any(item['status'] == 'inflight' for item in value['routes'].values()):
            entered.set()
            raise RefreshStateError('REFRESH_STATE_WRITE_UNKNOWN')
        original(value)
    monkeypatch.setattr(runner.state, 'write', write)
    with pytest.raises(RefreshStateError, match='REFRESH_STATE_WRITE_UNKNOWN'):
        runner.tick(now=END, cancelled=entered.is_set)


def test_finish_runs_after_fatal_failure_and_never_regrants():
    finished = Event()
    def fail(**_kwargs):
        raise ValueError('COMMIT_OUTCOME_UNKNOWN')
    thread = RefreshThread(SimpleNamespace(tick=fail), on_tick_finished=finished.set)
    thread.start()
    assert finished.wait(1)
    thread.stop(timeout=1)
    assert finished.is_set() and thread.last_error == 'COMMIT_OUTCOME_UNKNOWN'


def test_real_service_read_cancel_before_rebuild_mutation_is_pending(tmp_path):
    from contextlib import contextmanager, nullcontext
    from app.reference_trading.service import HistoricalReferenceService
    runner, planner, _service = setup(tmp_path, [('blocked', 'REBUILD_REQUIRED', False)])
    runner.tick(now=END)
    cancelled = Event()
    def read(*_args, **_kwargs):
        cancelled.set()
        raise NewowProductReadCancelled('NEWOW_READ_CANCELLED')
    @contextmanager
    def components(**_kwargs):
        service = HistoricalReferenceService.__new__(HistoricalReferenceService)
        service._clock = lambda: 0
        service._reader = SimpleNamespace(pin_stream=lambda _: nullcontext(), load_stream=read)
        # The actual rebuild path must fail during pure load, never get here.
        service._repository = SimpleNamespace(read_state=lambda _: (_ for _ in ()).throw(AssertionError('formal path reached')))
        yield planner, service
    runner._components = components
    runner.tick(now=END, cancelled=cancelled.is_set)
    row = runner.state.read()['routes'][route().identity.stream_id]
    assert row['status'] == 'pending' and row['reason'] == 'INTERRUPTED'
    assert decode_plan(row['plan'])['operation'] == 'rebuild'


def test_read_cancel_without_actual_cancel_request_stays_blocked(tmp_path):
    runner, _planner, _service = setup(tmp_path, [('failed', 'NEWOW_READ_CANCELLED', False)])
    runner.tick(now=END)
    assert runner.state.read()['routes'][route().identity.stream_id]['status'] == 'blocked'


def test_unknown_commit_is_never_made_pending_by_yield(tmp_path):
    runner, _planner, service = setup(tmp_path, [('partial', 'COMMIT_OUTCOME_UNKNOWN', False)])
    cancelled = Event()
    original = service.advance
    def advance(plan, expected):
        cancelled.set()
        return original(plan, expected)
    service.advance = advance
    runner.tick(now=END, cancelled=cancelled.is_set)
    row = runner.state.read()['routes'][route().identity.stream_id]
    assert row['status'] == 'blocked' and row['reason'] == 'COMMIT_OUTCOME_UNKNOWN'


def test_rebuild_interrupted_without_resume_cannot_repeat_invalidation(tmp_path):
    runner, _planner, _service = setup(tmp_path, [
        ('blocked', 'REBUILD_REQUIRED', False), ('partial', 'INTERRUPTED', None)])
    runner.tick(now=END)
    runner.tick(now=END)
    row = runner.state.read()['routes'][route().identity.stream_id]
    assert row['status'] == 'blocked' and row['reason'] == 'INTERRUPTED'


def test_post_invalidation_read_cancel_without_resume_never_repeats(tmp_path):
    from contextlib import contextmanager, nullcontext
    from app.reference_trading.service import HistoricalReferenceService
    runner, planner, _ = setup(tmp_path, [('blocked', 'REBUILD_REQUIRED', False)])
    runner.tick(now=END)
    cancelled = Event()
    mutations = []
    @contextmanager
    def components(**_kwargs):
        service = HistoricalReferenceService.__new__(HistoricalReferenceService)
        service._clock = lambda: 0
        service._reader = SimpleNamespace(pin_stream=lambda _: nullcontext(), load_stream=lambda *_args, **_kwargs: object())
        service._snapshot_matches = lambda *_: True
        service._repository = SimpleNamespace(
            read_state=lambda _: SimpleNamespace(revision_id='old', stream=SimpleNamespace(row_version=1)),
            invalidate_revision=lambda *_: mutations.append('invalidate'))
        def after_invalidation(*_args, **_kwargs):
            mutations.append('seed-stage')
            cancelled.set()
            raise NewowProductReadCancelled('NEWOW_READ_CANCELLED')
        service._build_stream_from_input = after_invalidation
        yield planner, service
    runner._components = components
    runner.tick(now=END, cancelled=cancelled.is_set)
    cancelled.clear()
    runner.tick(now=END, cancelled=cancelled.is_set)
    row = runner.state.read()['routes'][route().identity.stream_id]
    assert mutations == ['invalidate', 'seed-stage']
    assert row['status'] == 'blocked' and decode_plan(row['plan'])['operation'] == 'rebuild'


def test_batch_quantum_counts_only_durable_committed_callbacks(tmp_path):
    from contextlib import contextmanager
    runner, planner, _ = setup(tmp_path, [])
    counts = []
    @contextmanager
    def components(*, cancelled, after_batch, **_kwargs):
        def advance(plan, _expected):
            for index in range(3):
                if cancelled():
                    break
                after_batch('committed', {'batch_key': str(index)})
                # The cutoff must become visible only after persisted inflight.
                assert runner.state.read()['routes'][route().identity.stream_id]['status'] == 'inflight'
                counts.append(index)
            return SimpleNamespace(streams=(SimpleNamespace(status='partial', reason='INTERRUPTED', resume_token=None),))
        yield planner, SimpleNamespace(advance=advance)
    runner._components = components
    runner.tick(now=END, batch_limit=1)
    row = runner.state.read()['routes'][route().identity.stream_id]
    assert counts == [0] and row['status'] == 'pending' and 'resume' not in row
    counts.clear()
    runner.tick(now=END)  # Default callers retain the existing unrestricted tick.
    assert counts == [0, 1, 2]


def test_committed_callback_storage_unknown_cannot_be_quantum_pending(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import pytest
    from app.reference_trading.historical_refresh import RefreshStateError
    runner, planner, _ = setup(tmp_path, [])
    original = runner.state.write
    committed = Event()
    def write(state):
        if committed.is_set():
            raise RefreshStateError('REFRESH_STATE_WRITE_UNKNOWN')
        original(state)
    monkeypatch.setattr(runner.state, 'write', write)
    @contextmanager
    def components(*, after_batch, **_kwargs):
        def advance(_plan, _expected):
            committed.set()
            try:
                after_batch('committed', {'batch_key': 'known'})
            except RefreshStateError:
                pass  # Actual service isolates callback exceptions into a report.
            return SimpleNamespace(streams=(SimpleNamespace(status='partial', reason='INTERRUPTED', resume_token=None),))
        yield planner, SimpleNamespace(advance=advance)
    runner._components = components
    with pytest.raises(RefreshStateError, match='REFRESH_STATE_WRITE_UNKNOWN'):
        runner.tick(now=END, batch_limit=1)
    assert runner.state.read()['routes'][route().identity.stream_id]['status'] == 'inflight'


def test_thread_forwards_runtime_quantum_without_changing_default_callers():
    received, finished = [], Event()
    def tick(**kwargs):
        received.append(kwargs['batch_limit'])
    thread = RefreshThread(SimpleNamespace(tick=tick), batch_limit=1, interval=30,
        on_tick_finished=finished.set)
    thread.start()
    assert finished.wait(1)
    thread.stop(timeout=1)
    assert received == [1]


def test_old_durable_resume_does_not_prove_later_bare_cancel_safe(tmp_path):
    from contextlib import contextmanager
    from dataclasses import asdict
    from app.reference_trading.service import ResumeToken
    runner, planner, _ = setup(tmp_path, [('blocked', 'REBUILD_REQUIRED', False)])
    runner.tick(now=END)
    cancelled = Event()
    tokens = []
    @contextmanager
    def components(*, after_batch, **_kwargs):
        def rebuild(plan, _expected):
            token = ResumeToken(plan.plan_hash, route().identity.stream_id, 'revision',
                256, plan.streams[0].source_token, 'batch')
            after_batch('committed', {'resume_token': token})
            tokens.append(token)
            cancelled.set()
            return SimpleNamespace(streams=(SimpleNamespace(status='failed', reason='NEWOW_READ_CANCELLED', resume_token=None),))
        yield planner, SimpleNamespace(rebuild=rebuild)
    runner._components = components
    runner.tick(now=END, cancelled=cancelled.is_set)
    row = runner.state.read()['routes'][route().identity.stream_id]
    assert row['status'] == 'blocked' and row['reason'] == 'NEWOW_READ_CANCELLED'
    assert row['resume'] == asdict(tokens[0])
    assert decode_plan(row['plan'])['plan_hash'] == tokens[0].plan_hash
