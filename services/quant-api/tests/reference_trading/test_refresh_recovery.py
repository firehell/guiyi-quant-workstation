from contextlib import contextmanager
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from app.reference_trading.contracts import CheckpointToken, CommitResult, StoredRevisionState, StoredStream
from app.reference_trading.historical_refresh import BUDGET, HistoricalRefresh, RefreshStateStore
from app.reference_trading.planning import HistoricalReferenceRequest, HistoricalStreamRequest, plan_to_dict
from app.reference_trading.refresh_recovery import recover_pending_source, install_source_recovery
from app.reference_trading.service import HistoricalReferenceService, ResumeToken
from tests.reference_trading.test_historical_refresh import Planner, Service, route, END


def prepared(tmp_path, *, resume=True):
    item = route()
    planner = Planner()
    old = planner.plan(HistoricalReferenceRequest('rebuild' if resume else 'advance', (
        HistoricalStreamRequest(item.identity, item.since, END.date(), END),), BUDGET))
    seed = __import__('hashlib').sha256(__import__('json').dumps(
        {'plan_hash': old.plan_hash, 'stream_id': item.identity.stream_id},
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    batch_key = 'seed:' + seed
    token = CheckpointToken(item.identity.stream_id, 'candidate', 1, 2, 'c' * 64)
    stream = StoredStream(item.identity.stream_id, False, 'old-active', 1, 2, 'STALE_INVALID')
    candidate = StoredRevisionState(stream, 'candidate', 'candidate', old.streams[0].input_manifest,
        old.streams[0].dependency_digest, token, batch_key, {})
    active = replace(candidate, revision_id='old-active', revision_status='invalid')
    receipt = CommitResult('committed', 'candidate', 1, 'c' * 64)
    class ReadSession:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def scalar(self, _query): return 1
    repository = SimpleNamespace(_session_factory=ReadSession, read_state=lambda _sid, rid=None: active if rid is None else candidate,
        load_checkpoint=lambda *_: (token, SimpleNamespace(stream=item.identity)),
        read_batch=lambda *_: receipt)
    guarded = []
    @contextmanager
    def guard(*_args, **_kwargs):
        guarded.append(True)
        try:
            yield
        finally:
            guarded.pop()
    def load(request, *, expected_source_token):
        assert guarded
        current = planner.plan(HistoricalReferenceRequest('rebuild', (request,), BUDGET)).streams[0]
        return SimpleNamespace(stream=item.identity, source_token=expected_source_token,
            completed_through=current.target_completed_through, bars=(None,) * current.input_count,
            input_bytes=current.input_bytes, dependency_manifest=current.input_manifest)
    service = Service([('completed', None, False)])
    service._reader = SimpleNamespace(source_guard=guard, load_stream=load)
    service._repository = repository
    service._snapshot_matches = HistoricalReferenceService._snapshot_matches
    @contextmanager
    def components(**_):
        yield planner, service
    store = RefreshStateStore(tmp_path / 'refresh.json')
    prior = {'status': 'pending', 'reason': 'INTERRUPTED', 'plan': store.store_plan(plan_to_dict(old))}
    if resume:
        prior['resume'] = asdict(ResumeToken(old.plan_hash, item.identity.stream_id, 'candidate',
                                             0, old.streams[0].source_token, batch_key))
    else:
        prior['rebuild_required'] = True
    store.write({'version': 'newow_historical_refresh_v1', 'cursor': '',
                 'routes': {item.identity.stream_id: prior}})
    runner = HistoricalRefresh(routes=lambda: (item,), endpoint=lambda *_: (END, END.date()),
                               components=components, state=store)
    planner.source = 'changed-source'
    return runner, item, planner, service


@pytest.mark.parametrize('resume', [True, False])
def test_exact_dryrun_and_apply_preserve_original_intent_and_candidate(tmp_path, resume):
    runner, item, _, service = prepared(tmp_path, resume=resume)
    original = runner.state.path.read_bytes()
    result = recover_pending_source(runner, item.identity.stream_id, now=END)
    assert result['status'] == 'ready' and runner.state.path.read_bytes() == original
    assert not service.calls
    saved = result['recovery']
    recover_pending_source(runner, item.identity.stream_id, now=END, apply=True,
                           expected_recovery_sha256=result['recovery_sha256'])
    restored = runner.state.read()['routes'][item.identity.stream_id]
    assert 'resume' not in restored
    assert runner.state.read_plan(restored['plan'])['operation'] == 'rebuild'
    archive = next(tmp_path.glob('refresh.json.recovery-*.json'))
    from app.reference_trading.plan_bundle import read_plan
    assert read_plan(archive, trusted_root=tmp_path) == saved
    assert not service.calls  # Installing is NOT execution or candidate deletion.


def test_unchanged_source_retains_pending_exactly(tmp_path):
    runner, item, planner, _ = prepared(tmp_path)
    planner.source = 'same-source'
    original = runner.state.path.read_bytes()
    assert recover_pending_source(runner, item.identity.stream_id, now=END)['status'] == 'source_unchanged'
    assert runner.state.path.read_bytes() == original


@pytest.mark.parametrize('status,reason', [('inflight', 'INTERRUPTED'), ('pending', 'COMMIT_OUTCOME_UNKNOWN'),
                                         ('blocked', 'REFRESH_READBACK_REQUIRED')])
def test_unknown_or_inflight_intent_never_replans(tmp_path, status, reason):
    runner, item, _, _ = prepared(tmp_path)
    state = runner.state.read()
    state['routes'][item.identity.stream_id].update(status=status, reason=reason)
    runner.state.write(state)
    original = runner.state.path.read_bytes()
    with pytest.raises(ValueError, match='NOT_ELIGIBLE'):
        recover_pending_source(runner, item.identity.stream_id, now=END)
    assert runner.state.path.read_bytes() == original


def test_ahead_checkpoint_requires_readback_not_replan(tmp_path):
    runner, item, _, service = prepared(tmp_path)
    original = service._repository.load_checkpoint
    service._repository.load_checkpoint = lambda *a: (replace(original(*a)[0], seq=2), original(*a)[1])
    with pytest.raises(ValueError, match='READBACK_REQUIRED'):
        recover_pending_source(runner, item.identity.stream_id, now=END)
    assert not list(tmp_path.glob('*.recovery-*'))


def test_changed_control_state_or_wrong_plan_hash_never_installs(tmp_path):
    runner, item, _, _ = prepared(tmp_path)
    result = recover_pending_source(runner, item.identity.stream_id, now=END)
    with pytest.raises(ValueError, match='HASH_CONFLICT'):
        recover_pending_source(runner, item.identity.stream_id, now=END, apply=True,
                               expected_recovery_sha256='a' * 64)
    state = runner.state.read()
    changed = runner.state.read()
    changed['routes'][item.identity.stream_id]['reason'] = 'SOURCE_BUSY'
    runner.state.write(changed)
    with pytest.raises(ValueError, match='STATE_CHANGED'):
        install_source_recovery(runner.state, state, result['recovery'])


def test_existing_worker_uses_same_archived_path_then_native_rebuild(tmp_path):
    runner, _, _, service = prepared(tmp_path)
    runner.tick(now=END)
    assert len(service.calls) == 1 and service.calls[0][0] == 'rebuild'
    assert service.calls[0][1].streams[0].input_manifest['proof'] == 'changed-source'
    assert service.calls[0][2] is None
    assert not runner.state.read()['routes']
    assert len(list(tmp_path.glob('refresh.json.recovery-*.json'))) == 1


@pytest.mark.parametrize('stage', ['old_plan', 'new_plan', 'full_input'])
def test_foreground_cancel_during_recovery_retains_original_pending_and_cursor(tmp_path, stage):
    from app.market_data.newow.product_reader import NewowProductReadCancelled
    runner, _, planner, service = prepared(tmp_path)
    original = runner.state.read()
    cancelled = []
    old_plan = planner.plan
    calls = []
    def plan(request):
        calls.append(request)
        if (stage == 'old_plan' and len(calls) == 1) or (stage == 'new_plan' and len(calls) == 2):
            cancelled.append(True)
            raise NewowProductReadCancelled('NEWOW_READ_CANCELLED')
        return old_plan(request)
    planner.plan = plan
    if stage == 'full_input':
        def load(*_args, **_kwargs):
            cancelled.append(True)
            raise NewowProductReadCancelled('NEWOW_READ_CANCELLED')
        service._reader.load_stream = load
    runner.tick(now=END, cancelled=lambda: bool(cancelled))
    assert runner.state.read() == original
    assert not service.calls
    assert runner.last_progress['reason'] == 'FOREGROUND_YIELD'


def test_advance_interrupted_without_resume_preserves_known_progress_before_rebuild(tmp_path):
    runner, item, _, _ = prepared(tmp_path, resume=False)
    state = runner.state.read()
    del state['routes'][item.identity.stream_id]['rebuild_required']
    runner.state.write(state)
    result = recover_pending_source(runner, item.identity.stream_id, now=END)
    assert result['status'] == 'ready'
    assert result['recovery']['readback']['active_progress']['max_committed_seq'] == 1


def test_unreferenced_later_committed_batch_prevents_source_recovery(tmp_path):
    runner, item, _, service = prepared(tmp_path)
    original = service._repository._session_factory
    class Ahead(original):
        def scalar(self, _query): return 2
    service._repository._session_factory = Ahead
    with pytest.raises(ValueError, match='READBACK_REQUIRED'):
        recover_pending_source(runner, item.identity.stream_id, now=END)
    assert not list(tmp_path.glob('*.recovery-*'))
