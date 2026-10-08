from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event

import pytest

from app.reference_trading.planning import HistoricalReferenceRequest, HistoricalStreamRequest, WorkBudget
from scripts import newow_recording_history as script
from tests.reference_trading.test_historical_refresh import Planner, route, END


def plan():
    return Planner().plan(HistoricalReferenceRequest('rebuild', (
        HistoricalStreamRequest(route().identity, date(2023, 1, 1), END.date(), END),),
        WorkBudget(1, 500_000, 1800, 512_000_000)))


class Service:
    count = 0
    def rebuild(self, plan, expected):
        self.count += 1
        assert expected == plan.plan_hash
        from app.reference_trading.service import BatchReport, StreamBatchReport
        return BatchReport('completed', (StreamBatchReport(
            plan.streams[0].request.identity.stream_id, 'completed', None, 1,
            'new-revision', 'new-revision', 'batch', None),))


def test_after_commit_before_receipt_restart_has_zero_mutation(tmp_path, monkeypatch):
    frozen, service = plan(), Service()
    intent, receipt = tmp_path / 'intent.json', tmp_path / 'receipt.json'
    original = script._atomic_json
    def fail_receipt(path, value, **kwargs):
        if path == receipt:
            raise OSError('simulated disk failure after successful commit')
        return original(path, value, **kwargs)
    monkeypatch.setattr(script, '_atomic_json', fail_receipt)
    with pytest.raises(OSError):
        script.apply_exact_plan(service, frozen, intent=intent, receipt=receipt)
    assert service.count == 1 and intent.exists() and not receipt.exists()
    monkeypatch.setattr(script, '_atomic_json', original)
    with pytest.raises(ValueError, match='HISTORY_PRIOR_RESULT_REQUIRES_READBACK'):
        script.apply_exact_plan(service, frozen, intent=intent, receipt=receipt)
    assert service.count == 1


def test_concurrent_apply_reservation_allows_only_one_mutation(tmp_path):
    frozen, service = plan(), Service()
    entered, release = Event(), Event()
    original = service.rebuild
    def slow(plan, expected):
        entered.set()
        assert release.wait(2)
        return original(plan, expected)
    service.rebuild = slow
    def apply():
        try:
            with script.product_apply_lock(tmp_path):
                script.apply_exact_plan(service, frozen, intent=tmp_path / 'intent.json', receipt=tmp_path / 'receipt.json')
            return 'completed'
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(apply)
        assert entered.wait(1)
        second = pool.submit(apply)
        assert second.result() == 'HISTORY_EXECUTION_BUSY'
        release.set()
        assert first.result() == 'completed'
    assert service.count == 1


def test_intent_binding_is_durable_before_service_mutates(tmp_path):
    frozen = plan()
    intent, receipt = tmp_path / 'intent.json', tmp_path / 'receipt.json'
    class Inspect(Service):
        def rebuild(self, plan, expected):
            saved = script._read_json(intent)
            assert saved['plan_hash'] == plan.plan_hash
            assert saved['stream_id'] == plan.streams[0].request.identity.stream_id
            assert saved['operation'] == 'rebuild'
            assert saved['source_token'] == plan.streams[0].source_token
            assert saved['dependency_digest'] == plan.streams[0].dependency_digest
            assert not receipt.exists()
            return super().rebuild(plan, expected)
    script.apply_exact_plan(Inspect(), frozen, intent=intent, receipt=receipt)
    assert script._read_json(receipt)['plan_hash'] == frozen.plan_hash


def test_receipt_without_matching_intent_requires_readback(tmp_path):
    frozen, service = plan(), Service()
    script._atomic_json(tmp_path / 'receipt.json', {'status': 'completed', 'plan_hash': frozen.plan_hash})
    with pytest.raises(ValueError, match='HISTORY_PRIOR_RESULT_REQUIRES_READBACK'):
        script.apply_exact_plan(service, frozen, intent=tmp_path / 'intent.json', receipt=tmp_path / 'receipt.json')
    assert service.count == 0


def test_real_sqlite_commit_without_receipt_cannot_rebuild_on_restart(tmp_path, monkeypatch):
    from tests.reference_trading.test_bootstrap import Reader, _plan, _repository
    from app.reference_trading.service import HistoricalReferenceService
    reader, repository = Reader(), _repository()
    frozen = _plan(reader)
    delegate = HistoricalReferenceService(repository, reader)
    class Count:
        calls = 0
        def execute(self, plan, expected):
            self.calls += 1
            return delegate.execute(plan, expected)
    service = Count()
    intent, receipt = tmp_path / 'intent.json', tmp_path / 'receipt.json'
    original = script._atomic_json
    def fail_receipt(path, value, **kwargs):
        if path == receipt:
            raise OSError('disk fault after real repository publish')
        original(path, value, **kwargs)
    monkeypatch.setattr(script, '_atomic_json', fail_receipt)
    with pytest.raises(OSError):
        script.apply_exact_plan(service, frozen, intent=intent, receipt=receipt)
    before = repository.read_state(frozen.streams[0].request.identity.stream_id)
    assert before.revision_status == 'active'
    monkeypatch.setattr(script, '_atomic_json', original)
    with pytest.raises(ValueError, match='HISTORY_PRIOR_RESULT_REQUIRES_READBACK'):
        script.apply_exact_plan(service, frozen, intent=intent, receipt=receipt)
    assert repository.read_state(frozen.streams[0].request.identity.stream_id) == before
    assert service.calls == 1


def test_real_terminal_receipt_reentry_validates_snapshot_then_zero_mutation(tmp_path):
    from tests.reference_trading.test_bootstrap import Reader, _plan, _repository
    from app.reference_trading.service import HistoricalReferenceService
    reader, repository = Reader(), _repository()
    frozen = _plan(reader)
    service = HistoricalReferenceService(repository, reader)
    paths = {'intent': tmp_path / 'intent.json', 'receipt': tmp_path / 'receipt.json',
             'read_state': repository.read_state}
    original = script.apply_exact_plan(service, frozen, **paths)
    state = repository.read_state(frozen.streams[0].request.identity.stream_id)
    class NoMutation:
        def execute(self, *args):
            raise AssertionError('verified receipt must not call execution')
    assert script.apply_exact_plan(NoMutation(), frozen, **paths) == original
    assert repository.read_state(frozen.streams[0].request.identity.stream_id) == state


def test_fsync_reservation_failure_never_calls_service(tmp_path, monkeypatch):
    frozen, service = plan(), Service()
    def fail_fsync(fd):
        raise OSError('fsync fault')
    monkeypatch.setattr(script.os, 'fsync', fail_fsync)
    with pytest.raises(OSError):
        script.apply_exact_plan(service, frozen, intent=tmp_path / 'intent.json', receipt=tmp_path / 'receipt.json')
    assert service.count == 0


def test_apply_cli_unknown_prior_intent_stops_before_opening_any_service(tmp_path, monkeypatch):
    from scripts.reference_trading_p9_manifest import _newow
    from guiyi_quant.newow.product_contracts import ProductStrategy
    frozen = Planner().plan(HistoricalReferenceRequest('build', (HistoricalStreamRequest(
        _newow('rb', ProductStrategy.TREND, '1w', forward=False), date(2023, 1, 1), END.date(), END),),
        WorkBudget(1, 500_000, 1800, 512_000_000)))
    out = tmp_path / 'rb'
    out.mkdir()
    script._atomic_json(out / 'trend-1w-plan.json', script.plan_to_dict(frozen))
    script._atomic_json(out / 'trend-1w-intent.json', script._intent(frozen))
    monkeypatch.setattr(script, 'validate_product_scope', lambda *args: ('rb',))
    monkeypatch.setattr(script, 'load_active_products', lambda: ('rb',))
    monkeypatch.setattr(script, 'load_operational_products', lambda: ('rb',))
    def forbidden(**kwargs):
        raise AssertionError('unknown intent must stop before any service is opened')
    monkeypatch.setattr(script, 'open_historical_reference_components', forbidden)
    with pytest.raises(ValueError, match='HISTORY_PRIOR_RESULT_REQUIRES_READBACK'):
        script.main(['--product', 'rb', '--output-root', str(tmp_path), '--as-of', END.isoformat(),
                     '--strategy', 'trend', '--apply'])


def test_plan_cli_has_no_intent_receipt_or_mutating_service(tmp_path, monkeypatch):
    from contextlib import contextmanager, nullcontext
    import app.db.readonly
    calls = []
    class NoMutation:
        def execute(self, *args):
            calls.append('mutation')
            raise AssertionError('plan must be read only')
        rebuild = execute
    @contextmanager
    def components(**kwargs):
        from types import SimpleNamespace
        planner = Planner()
        planner._reader = SimpleNamespace(_newow_for=lambda identity: SimpleNamespace(
            historical_storage_start=lambda product: date(2000, 1, 1)))
        yield planner, NoMutation()
    class Session:
        def scalar(self, statement):
            return None
    monkeypatch.setattr(script, 'SessionLocal', lambda: nullcontext(Session()))
    monkeypatch.setattr(app.db.readonly, 'readonly_transaction', lambda session, **kwargs: nullcontext(session))
    monkeypatch.setattr(script, 'validate_product_scope', lambda *args: ('rb',))
    monkeypatch.setattr(script, 'load_active_products', lambda: ('rb',))
    monkeypatch.setattr(script, 'load_operational_products', lambda: ('rb',))
    monkeypatch.setattr(script, 'open_historical_reference_components', components)
    assert script.main(['--product', 'rb', '--output-root', str(tmp_path), '--as-of', END.isoformat(),
                        '--strategy', 'trend']) == 0
    assert len(list((tmp_path / 'rb').glob('*-plan.json'))) == 3
    assert not list((tmp_path / 'rb').glob('*-intent.json'))
    assert not list((tmp_path / 'rb').glob('*-receipt.json'))
    assert calls == []


def _process_apply(output, entered, release, count, results):
    from pathlib import Path
    frozen = plan()
    class ProcessService(Service):
        def rebuild(self, frozen, expected):
            with count.get_lock():
                count.value += 1
            entered.set()
            if not release.wait(10):
                raise RuntimeError('TEST_TIMEOUT')
            return super().rebuild(frozen, expected)
    try:
        with script.product_apply_lock(Path(output)):
            script.apply_exact_plan(ProcessService(), frozen, intent=Path(output) / 'intent.json',
                                    receipt=Path(output) / 'receipt.json')
        results.put('completed')
    except ValueError as error:
        results.put(str(error))


def test_distinct_processes_cannot_apply_same_product_twice(tmp_path):
    import multiprocessing
    context = multiprocessing.get_context('spawn')
    entered, release = context.Event(), context.Event()
    count, results = context.Value('i', 0), context.Queue()
    first = context.Process(target=_process_apply, args=(str(tmp_path), entered, release, count, results))
    second = context.Process(target=_process_apply, args=(str(tmp_path), entered, release, count, results))
    first.start()
    try:
        assert entered.wait(10)
        second.start()
        assert results.get(timeout=10) == 'HISTORY_EXECUTION_BUSY'
        release.set()
        assert results.get(timeout=10) == 'completed'
    finally:
        release.set()
        first.join(10)
        if second.pid:
            second.join(10)
        for process in (first, second):
            if process.is_alive():
                process.terminate()
                process.join(5)
        results.close()
    assert first.exitcode == 0 and second.exitcode == 0
    assert count.value == 1
