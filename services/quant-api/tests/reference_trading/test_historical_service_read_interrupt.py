"""Only actual initial input boundaries may prove cancellation before mutation."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.market_data.newow.product_reader import NewowProductReadCancelled
from app.reference_trading.historical_refresh import BUDGET
from app.reference_trading.planning import HistoricalReferenceRequest, HistoricalStreamRequest
from app.reference_trading.service import HistoricalReferenceService
from app.reference_trading.service import ResumeToken
from tests.reference_trading.test_historical_refresh import Planner, END, route


def prepared(operation, *, cancel_stage=None, error_type=NewowProductReadCancelled):
    item = route()
    plan = Planner().plan(HistoricalReferenceRequest(operation, (HistoricalStreamRequest(
        item.identity, item.since, END.date(), END),), BUDGET))
    effects = []
    @contextmanager
    def pin(_request):
        effects.append('pin')
        if cancel_stage == 'pin':
            raise error_type('NEWOW_READ_CANCELLED')
        try:
            yield
        finally:
            effects.append('release')
    def load(*_args, **_kwargs):
        effects.append('load')
        if cancel_stage == 'load':
            raise error_type('NEWOW_READ_CANCELLED')
        return object()
    service = HistoricalReferenceService.__new__(HistoricalReferenceService)
    service._clock = lambda: 0
    service._reader = SimpleNamespace(pin_stream=pin, load_stream=load)
    service._repository = SimpleNamespace(
        read_state=lambda _: SimpleNamespace(revision_id='old', stream=SimpleNamespace(row_version=1)),
        invalidate_revision=lambda *_: effects.append('invalidate'))
    service._snapshot_matches = lambda *_: True
    def build(*_args, **_kwargs):
        effects.append('seed')
        raise NewowProductReadCancelled('NEWOW_READ_CANCELLED')
    if operation == 'rebuild':
        service._build_stream_from_input = build
    return service, plan, effects


@pytest.mark.parametrize('operation', ['build', 'rebuild'])
@pytest.mark.parametrize('stage', ['pin', 'load'])
def test_actual_initial_typed_cancel_proves_no_formal_mutation(operation, stage):
    service, plan, effects = prepared(operation, cancel_stage=stage)
    invoke = service.execute if operation == 'build' else service.rebuild
    report = invoke(plan, plan.plan_hash).streams[0]
    assert report.reason == 'INPUT_READ_INTERRUPTED'
    assert report.completed_bars == 0
    assert report.resume_token is None and report.candidate_revision_id is None
    assert 'invalidate' not in effects and 'seed' not in effects
    if stage == 'load':
        assert effects[-1] == 'release'


def test_post_invalidation_read_cancel_has_no_prewrite_proof():
    service, plan, effects = prepared('rebuild')
    report = service.rebuild(plan, plan.plan_hash).streams[0]
    assert effects == ['pin', 'load', 'invalidate', 'seed', 'release']
    assert report.reason == 'NEWOW_READ_CANCELLED'
    assert report.resume_token is None


def test_plain_error_text_does_not_prove_prewrite_cancel():
    service, plan, effects = prepared('rebuild', cancel_stage='load', error_type=ValueError)
    report = service.rebuild(plan, plan.plan_hash).streams[0]
    assert report.reason == 'NEWOW_READ_CANCELLED'
    assert 'invalidate' not in effects


def test_resume_revalidation_typed_cancel_retains_exact_original_token():
    service, plan, effects = prepared('build')
    token = ResumeToken(plan.plan_hash, plan.streams[0].request.identity.stream_id,
        'known-candidate', 8, plan.streams[0].source_token, 'known-batch')
    def revalidate(*_args, **_kwargs):
        raise NewowProductReadCancelled('NEWOW_READ_CANCELLED')
    service._reader.revalidate = revalidate
    report = service.resume(plan, token, plan.plan_hash).streams[0]
    assert report.reason == 'INPUT_READ_INTERRUPTED'
    assert report.resume_token is token
    assert report.candidate_revision_id == token.revision_id
    assert report.completed_bars == token.next_input_index
    assert effects == ['pin', 'release']


def test_advance_callback_follows_known_atomic_commit_without_resume_token():
    from tests.reference_trading.test_bootstrap import Reader, _plan, _repository
    from tests.reference_trading.test_historical_incremental import _append_plan
    reader, repository = Reader(), _repository()
    initial = _plan(reader)
    assert HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash).status == 'completed'
    plan = _append_plan(reader, initial, operation='advance')
    seen = []
    def committed(stage, context):
        state = repository.read_state(plan.streams[0].request.identity.stream_id)
        assert stage == 'committed'
        assert context['batch_key'] == state.checkpoint_batch_key
        assert context['stream_id'] == state.stream.stream_id
        assert context['revision_id'] == state.revision_id
        assert 'resume_token' not in context
        seen.append(context)
    assert HistoricalReferenceService(repository, reader, after_batch=committed).advance(
        plan, plan.plan_hash).status == 'completed'
    assert len(seen) == 1


def test_unknown_advance_commit_never_calls_committed_callback():
    from tests.reference_trading.test_bootstrap import Reader, _plan, _repository
    from tests.reference_trading.test_historical_incremental import _append_plan
    from app.reference_trading.service import CommitOutcomeUnknown
    reader, repository = Reader(), _repository()
    initial = _plan(reader)
    assert HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash).status == 'completed'
    plan = _append_plan(reader, initial, operation='advance')
    service = HistoricalReferenceService(repository, reader,
        after_batch=lambda *_: pytest.fail('unknown commit cannot trigger known callback'))
    service._commit_once = lambda *_: (_ for _ in ()).throw(CommitOutcomeUnknown())
    assert service.advance(plan, plan.plan_hash).streams[0].reason == 'COMMIT_OUTCOME_UNKNOWN'


def test_known_advance_commit_callback_storage_failure_is_not_completed():
    from tests.reference_trading.test_bootstrap import Reader, _plan, _repository
    from tests.reference_trading.test_historical_incremental import _append_plan
    from app.reference_trading.historical_refresh import RefreshStateError
    reader, repository = Reader(), _repository()
    initial = _plan(reader)
    assert HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash).status == 'completed'
    before = repository.read_state(initial.streams[0].request.identity.stream_id).checkpoint_batch_key
    plan = _append_plan(reader, initial, operation='advance')
    def storage_failed(_stage, _context):
        raise RefreshStateError('REFRESH_STATE_WRITE_UNKNOWN')
    report = HistoricalReferenceService(repository, reader, after_batch=storage_failed).advance(plan, plan.plan_hash)
    assert report.streams[0].status == 'failed'
    assert report.streams[0].reason == 'REFRESH_STATE_WRITE_UNKNOWN'
    assert repository.read_state(plan.streams[0].request.identity.stream_id).checkpoint_batch_key != before
