"""Legacy Fusion pending plans move only through a verified v3 source upgrade."""

from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import timedelta
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from app.reference_trading.contracts import (
    CheckpointToken, CommitResult, StoredRevisionState, StoredStream,
)
from app.reference_trading.historical_refresh import (
    BUDGET, HistoricalRefresh, RefreshRoute, RefreshStateError, RefreshStateStore,
)
from app.reference_trading.plan_bundle import read_plan
from app.reference_trading.planning import (
    HistoricalReferencePlan, HistoricalReferenceRequest, HistoricalStreamPlan,
    HistoricalStreamRequest, canonical_sha256, plan_to_dict,
)
from app.reference_trading.refresh_recovery import recover_pending_source
from app.reference_trading.service import HistoricalReferenceService, ResumeToken
from tests.reference_trading.test_historical_refresh import END, Service, route
from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
from guiyi_quant.newow.product_identity import InputQualityPolicy


def _plan(request, manifest, target):
    digest = canonical_sha256(manifest)
    item = HistoricalStreamPlan(request.streams[0], request.streams[0].since,
                                target, 1, 10, manifest, digest, digest, digest)
    draft = HistoricalReferencePlan('historical_reference_plan_v1', request.operation,
                                    (item,), request.budget, request.batch_size, '')
    return replace(draft, plan_hash=canonical_sha256(draft))


def prepared(tmp_path, *, old_cutoff=END - timedelta(days=3), resume=True,
             old_reader='newow_fusion_saved_sources_v2',
             source_reader='newow_product_reader_v2'):
    dual = RefreshRoute(
        build_fusion_stream_identity('rb', '1d', input_quality_policy=InputQualityPolicy.DAILY_V2),
        route().since, old_cutoff,
        'CANONICAL_SOURCE_REVISION_CHANGED' if resume else 'INPUT_PROOF_UPGRADE_REQUIRED',
    )
    old_manifest = {
        'reader': old_reader, 'source_reader': source_reader,
        'query_since': dual.since.isoformat(),
        'source_input_fingerprints': ['a' * 64],
        'input_fingerprints': ['b' * 64],
    }
    new_manifest = {
        'reader': 'newow_fusion_saved_sources_v3',
        'source_reader': 'newow_product_reader_prefix_v5',
        'query_since': dual.since.isoformat(),
        'source_dependencies': [{'strategy': 'trend'}, {'strategy': 'oscillation'}],
    }
    old_request = HistoricalReferenceRequest(
        'rebuild' if resume else 'advance',
        (HistoricalStreamRequest(dual.identity, dual.since, old_cutoff.date(), old_cutoff),),
        BUDGET,
    )
    old = _plan(old_request, old_manifest, old_cutoff)
    store = RefreshStateStore(tmp_path / 'refresh.json')
    prior = {'status': 'pending', 'reason': 'INTERRUPTED' if resume else 'REBUILD_REQUIRED',
             'plan': store.store_plan(plan_to_dict(old))}
    seed_root = sha256(json.dumps({
        'plan_hash': old.plan_hash, 'stream_id': dual.identity.stream_id,
    }, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    candidate_token = CheckpointToken(dual.identity.stream_id, 'candidate', 1, 2, 'c' * 64)
    if resume:
        prior['resume'] = asdict(ResumeToken(
            old.plan_hash, dual.identity.stream_id, 'candidate', 0,
            old.streams[0].source_token, 'seed:' + seed_root,
        ))
    else:
        prior['rebuild_required'] = True
    osc = replace(route(strategy='oscillation', watermark=END), reason=None)
    trend = replace(route(strategy='trend', watermark=END), reason=None)
    store.write({'version': 'newow_historical_refresh_v1',
                 'cursor': osc.identity.stream_id,
                 'routes': {dual.identity.stream_id: prior}})
    stream = StoredStream(dual.identity.stream_id, False, 'old-active', 1, 2, 'STALE_INVALID')
    active_token = CheckpointToken(dual.identity.stream_id, 'old-active', 1, 2, 'c' * 64)
    active = StoredRevisionState(stream, 'old-active', 'invalid' if resume else 'active', old_manifest,
                                 old.streams[0].dependency_digest, active_token,
                                 'old-active-batch', {})
    candidate = StoredRevisionState(stream, 'candidate', 'candidate', old_manifest,
                                    old.streams[0].dependency_digest, candidate_token,
                                    'seed-seal:' + 'c' * 64, {'seed_root_hash': seed_root})
    repository = SimpleNamespace(active=active, candidate=candidate, maximum=1)

    class ReadSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _query):
            return repository.maximum

    repository._session_factory = ReadSession
    repository.read_state = lambda _sid, revision_id=None: (
        repository.active if revision_id is None else repository.candidate
    )
    repository.load_checkpoint = lambda *_args: (
        candidate_token, SimpleNamespace(stream=dual.identity),
    )
    repository.read_batch = lambda _sid, _revision_id, key: (
        CommitResult('committed', 'old-active', 1, 'c' * 64)
        if key == 'old-active-batch' else
        CommitResult('committed', 'candidate', 1, 'c' * 64)
        if key == 'seed-seal:' + 'c' * 64 else None
    )

    class Planner:
        def __init__(self):
            self.requests = []
            self.old_request_fails = old_cutoff != END
            self.manifest = new_manifest

        def plan(self, request):
            self.requests.append(request)
            if request.streams[0].as_of == old_cutoff and self.old_request_fails:
                raise ValueError('REFERENCE_FUSION_SOURCE_NOT_READY')
            return _plan(request, self.manifest, END)

    planner = Planner()
    guard_depth = []

    @contextmanager
    def guard(*_args, **_kwargs):
        guard_depth.append(True)
        try:
            yield
        finally:
            guard_depth.pop()

    def load(request, *, expected_source_token):
        assert guard_depth
        plan = planner.requests[-1]
        item = _plan(plan, planner.manifest, END).streams[0]
        return SimpleNamespace(
            stream=request.identity, source_token=expected_source_token,
            completed_through=item.target_completed_through,
            bars=(None,), input_bytes=item.input_bytes,
            dependency_manifest=item.input_manifest,
        )

    service = Service([('completed', None, False)])
    service._repository = repository
    service._reader = SimpleNamespace(source_guard=guard, load_stream=load)
    service._snapshot_matches = HistoricalReferenceService._snapshot_matches

    @contextmanager
    def components(**_kwargs):
        yield planner, service

    runner = HistoricalRefresh(
        routes=lambda: (dual, trend, osc),
        endpoint=lambda *_args: (END, END.date()),
        components=components, state=store,
    )
    return runner, dual, planner, service, repository


@pytest.mark.parametrize('resume', (True, False))
def test_old_daily_cutoff_migrates_without_replanning_unavailable_old_request(tmp_path, resume):
    runner, dual, planner, service, repository = prepared(tmp_path, resume=resume)
    original_state = runner.state.path.read_bytes()
    original_active, original_candidate = repository.active, repository.candidate
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert dry['status'] == 'ready'
    assert len(planner.requests) == 1
    assert planner.requests[0].streams[0].as_of == END
    assert runner.state.path.read_bytes() == original_state
    assert not service.calls
    record = dry['recovery']
    assert record['version'] == 'reference_refresh_fusion_proof_upgrade_v1'
    assert 'source_change' not in record
    assert record['proof_upgrade']['policy'] == 'newow_fusion_saved_source_proof_upgrade_v1'
    assert record['proof_upgrade']['old_target_completed_through'] < record['proof_upgrade']['new_target_completed_through']
    assert record['proof_upgrade']['old_frozen_source_token'] != record['proof_upgrade']['new_rebuild_source_token']
    assert repository.active == original_active and repository.candidate == original_candidate
    recover_pending_source(runner, dual.identity.stream_id, now=END, apply=True,
                           expected_recovery_sha256=dry['recovery_sha256'])
    current = runner.state.read()['routes'][dual.identity.stream_id]
    assert current['status'] == 'pending' and 'resume' not in current
    assert runner.state.read_plan(current['plan'])['operation'] == 'rebuild'
    archive = next(tmp_path.glob('refresh.json.recovery-*.json'))
    assert read_plan(archive, trusted_root=tmp_path) == record
    assert not service.calls
    runner.tick(now=END)
    assert service.calls and service.calls[0][0] == 'rebuild'


@pytest.mark.parametrize('reader,source_reader', (
    ('newow_fusion_saved_sources_v2', 'newow_product_reader_v2'),
    ('newow_fusion_saved_sources_v1', 'newow_product_reader_intraday_v3'),
))
def test_same_cutoff_old_proof_migrates_in_one_current_replan(tmp_path, reader, source_reader):
    runner, dual, planner, _, _ = prepared(
        tmp_path, old_cutoff=END, old_reader=reader, source_reader=source_reader,
    )
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert dry['status'] == 'ready' and len(planner.requests) == 1
    upgrade = dry['recovery']['proof_upgrade']
    assert upgrade['old_target_completed_through'] == upgrade['new_target_completed_through']


@pytest.mark.parametrize('kind', ('current_v3', 'no_upgrade_reason'))
def test_current_v3_or_non_upgrade_route_never_uses_legacy_migration(tmp_path, kind):
    runner, dual, planner, _, _ = prepared(tmp_path)
    if kind == 'current_v3':
        state = runner.state.read()
        old_wire = runner.state.read_plan(state['routes'][dual.identity.stream_id]['plan'])
        old_manifest = old_wire['streams'][0]['input_manifest']
        old_manifest.update(reader='newow_fusion_saved_sources_v3',
                            source_reader='newow_product_reader_prefix_v5')
        old_manifest['source_input_fingerprints'] = {'encoding': 'sha256-leaves-b64-v1'}
        old_wire['streams'][0]['input_manifest_sha256'] = canonical_sha256(old_manifest)
        old_wire['streams'][0]['dependency_digest'] = canonical_sha256(old_manifest)
        old_wire['streams'][0]['source_token'] = canonical_sha256(old_manifest)
        old_wire['plan_hash'] = canonical_sha256({
            key: value for key, value in old_wire.items() if key != 'plan_hash'
        })
        state['routes'][dual.identity.stream_id]['plan'] = runner.state.store_plan(old_wire)
        runner.state.write(state)
    else:
        runner._routes = lambda: (replace(dual, reason=None),)
    with pytest.raises(ValueError, match='REFERENCE_FUSION_SOURCE_NOT_READY'):
        recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert planner.requests[0].streams[0].as_of != END
    assert not list(tmp_path.glob('*.recovery-*.json'))


def test_upgrade_rechecks_source_and_candidate_after_dryrun(tmp_path):
    runner, dual, planner, _, repository = prepared(tmp_path)
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    original = runner.state.path.read_bytes()
    planner.manifest = {**planner.manifest, 'changed_source_proof': True}
    with pytest.raises(ValueError, match='HASH_CONFLICT'):
        recover_pending_source(runner, dual.identity.stream_id, now=END, apply=True,
                               expected_recovery_sha256=dry['recovery_sha256'])
    assert runner.state.path.read_bytes() == original
    planner.manifest = {key: value for key, value in planner.manifest.items()
                        if key != 'changed_source_proof'}
    repository.candidate = replace(repository.candidate, revision_status='invalid')
    with pytest.raises(ValueError, match='READBACK_REQUIRED'):
        recover_pending_source(runner, dual.identity.stream_id, now=END, apply=True,
                               expected_recovery_sha256=dry['recovery_sha256'])
    assert runner.state.path.read_bytes() == original
    assert not list(tmp_path.glob('*.recovery-*.json'))


def test_upgrade_rechecks_current_route_inside_canonical_scope(tmp_path):
    runner, dual, planner, _, _ = prepared(tmp_path)
    original = runner.state.path.read_bytes()
    calls = 0

    def changed_route():
        nonlocal calls
        calls += 1
        return (dual,) if calls == 1 else (replace(dual, reason='HISTORY_NOT_PUBLISHED'),)

    runner._routes = changed_route
    with pytest.raises(ValueError, match='ROUTE_CHANGED'):
        recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert len(planner.requests) == 0
    assert runner.state.path.read_bytes() == original
    assert not list(tmp_path.glob('*.recovery-*.json'))


@pytest.mark.parametrize('drift', ('candidate', 'active', 'active_status', 'source', 'db_after'))
def test_upgrade_rejects_candidate_active_source_and_db_drift(tmp_path, drift):
    runner, dual, planner, service, repository = prepared(tmp_path)
    original = runner.state.path.read_bytes()
    if drift == 'candidate':
        repository.candidate = replace(repository.candidate, revision_status='invalid')
    elif drift == 'active':
        repository.maximum = 2
    elif drift == 'active_status':
        repository.active = replace(repository.active, revision_status='active')
    elif drift == 'source':
        original_load = service._reader.load_stream

        def changed(*args, **kwargs):
            snapshot = original_load(*args, **kwargs)
            snapshot.source_token = 'drift'
            return snapshot

        service._reader.load_stream = changed
    else:
        original_load = service._reader.load_stream

        def changed_after(*args, **kwargs):
            snapshot = original_load(*args, **kwargs)
            repository.maximum = 2
            return snapshot

        service._reader.load_stream = changed_after
    with pytest.raises(ValueError, match='READBACK_REQUIRED|SOURCE_CHANGED'):
        recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert runner.state.path.read_bytes() == original
    assert not list(tmp_path.glob('*.recovery-*.json'))
    assert len(planner.requests) == (0 if drift in {'candidate', 'active', 'active_status'} else 1)


def test_upgrade_archive_conflict_prevents_pending_install(tmp_path):
    runner, dual, _, service, _ = prepared(tmp_path)
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    original = runner.state.path.read_bytes()
    archive = tmp_path / ('refresh.json.recovery-' + dry['recovery_sha256'] + '.json')
    archive.write_text('{}')
    with pytest.raises(ValueError, match='ARCHIVE_CONFLICT'):
        recover_pending_source(runner, dual.identity.stream_id, now=END, apply=True,
                               expected_recovery_sha256=dry['recovery_sha256'])
    assert runner.state.path.read_bytes() == original
    assert not service.calls


def test_upgrade_archive_survives_unknown_state_write_without_worker_execution(tmp_path):
    runner, dual, _, service, _ = prepared(tmp_path)
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    original = runner.state.path.read_bytes()
    write = runner.state.write

    def unknown(_state):
        raise RefreshStateError('REFRESH_STATE_WRITE_UNKNOWN')

    runner.state.write = unknown
    try:
        with pytest.raises(RefreshStateError, match='WRITE_UNKNOWN'):
            recover_pending_source(runner, dual.identity.stream_id, now=END, apply=True,
                                   expected_recovery_sha256=dry['recovery_sha256'])
    finally:
        runner.state.write = write
    assert runner.state.path.read_bytes() == original
    assert len(list(tmp_path.glob('refresh.json.recovery-*.json'))) == 1
    assert not service.calls
