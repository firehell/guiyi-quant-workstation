"""Current v3 pending work may roll to a later verified dependency target."""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.reference_trading.historical_refresh import RefreshStateError
from app.reference_trading.planning import plan_from_dict
from app.reference_trading.refresh_recovery import recover_pending_source
from tests.reference_trading.test_historical_refresh import END
from tests.reference_trading.test_refresh_fusion_proof_upgrade import prepared


def current_v3(tmp_path, *, resume=True, old_cutoff=None, advance_reason='INTERRUPTED'):
    runner, dual, planner, service, repository = prepared(
        tmp_path, resume=resume,
        old_reader='newow_fusion_saved_sources_v3',
        source_reader='newow_product_reader_prefix_v5',
        **({'old_cutoff': old_cutoff} if old_cutoff is not None else {}),
    )
    if not resume:
        dual = replace(dual, reason=None)
        original_routes = runner._routes()
        runner._routes = lambda: (dual, *original_routes[1:])
        state = runner.state.read()
        prior = state['routes'][dual.identity.stream_id]
        prior.pop('rebuild_required')
        prior['reason'] = advance_reason
        runner.state.write(state)
    return runner, dual, planner, service, repository


@pytest.mark.parametrize('resume,operation', ((True, 'rebuild'), (False, 'advance')))
def test_current_v3_old_target_rolls_forward_without_old_request_replan(
    tmp_path, resume, operation,
):
    runner, dual, planner, service, repository = current_v3(tmp_path, resume=resume)
    original = runner.state.path.read_bytes()
    active, candidate = repository.active, repository.candidate
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert dry['status'] == 'ready'
    assert len(planner.requests) == 1
    assert planner.requests[0].streams[0].as_of == END
    assert planner.requests[0].operation == operation
    assert runner.state.path.read_bytes() == original
    assert repository.active == active and repository.candidate == candidate
    record = dry['recovery']
    assert record['version'] == 'reference_refresh_fusion_dependency_target_rollforward_v1'
    assert 'source_change' not in record and 'proof_upgrade' not in record
    policy = record['dependency_target_rollforward']
    assert policy['policy'] == 'newow_fusion_dependency_target_rollforward_v1'
    assert policy['old_target_completed_through'] < policy['new_target_completed_through']
    assert policy['new_operation'] == operation
    recover_pending_source(
        runner, dual.identity.stream_id, now=END, apply=True,
        expected_recovery_sha256=dry['recovery_sha256'],
    )
    current = runner.state.read()['routes'][dual.identity.stream_id]
    assert current['status'] == 'pending' and 'resume' not in current
    assert plan_from_dict(runner.state.read_plan(current['plan'])).operation == operation
    assert len(list(tmp_path.glob('refresh.json.recovery-*.json'))) == 1
    assert not service.calls
    runner.tick(now=END)
    assert service.calls and service.calls[0][0] == operation


def test_current_v3_same_target_retains_old_source_revalidation(tmp_path):
    runner, dual, planner, _, _ = current_v3(tmp_path, old_cutoff=END)
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert dry['recovery']['version'] == 'reference_refresh_source_recovery_v2'
    assert planner.requests[0].streams[0].as_of == END
    assert 'source_change' in dry['recovery']


def test_current_v3_preexecution_pending_without_resume_is_known_advance(tmp_path):
    runner, dual, planner, _, repository = current_v3(
        tmp_path, resume=False, advance_reason=None)
    old_candidate = repository.candidate
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert dry['recovery']['dependency_target_rollforward']['new_operation'] == 'advance'
    assert dry['recovery']['readback']['active_progress']['max_committed_seq'] == 1
    assert len(planner.requests) == 1
    assert repository.candidate == old_candidate


def test_native_worker_preexecution_yield_keeps_known_pending_for_target_rollforward(tmp_path):
    runner, dual, planner, service, _ = current_v3(
        tmp_path, resume=False, advance_reason=None)
    state = runner.state.read()
    old = plan_from_dict(runner.state.read_plan(state['routes'][dual.identity.stream_id]['plan']))
    state['routes'].clear()
    runner.state.write(state)
    base_routes = runner._routes()[1:]
    runner._routes = lambda: (
        replace(dual, computed_through=dual.computed_through - timedelta(seconds=1)),
        *base_routes,
    )
    runner._endpoint = lambda *_args: (dual.computed_through, dual.computed_through.date())
    original_plan = planner.plan

    def plan_old(request):
        planner.requests.append(request)
        return old

    planner.plan = plan_old
    runner.tick(now=END, cancelled=lambda: bool(planner.requests))
    planner.plan = original_plan
    pending = runner.state.read()['routes'][dual.identity.stream_id]
    assert pending['status'] == 'pending' and pending['reason'] is None
    assert 'resume' not in pending and not service.calls
    runner._routes = lambda: (dual, *base_routes)
    runner._endpoint = lambda *_args: (END, END.date())
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert dry['recovery']['dependency_target_rollforward']['new_operation'] == 'advance'


@pytest.mark.parametrize('drift', ('route', 'active', 'candidate', 'source', 'db_after'))
def test_current_v3_rollforward_fails_closed_on_drift(tmp_path, drift):
    runner, dual, planner, service, repository = current_v3(tmp_path)
    original = runner.state.path.read_bytes()
    if drift == 'route':
        calls = [0]

        def changed_route():
            calls[0] += 1
            return (dual,) if calls[0] == 1 else (replace(dual, reason='HISTORY_NOT_PUBLISHED'),)

        runner._routes = changed_route
    elif drift == 'active':
        repository.active = replace(repository.active, revision_status='active')
    elif drift == 'candidate':
        repository.candidate = replace(repository.candidate, revision_status='invalid')
    else:
        original_load = service._reader.load_stream

        def changed(*args, **kwargs):
            snapshot = original_load(*args, **kwargs)
            if drift == 'source':
                snapshot.source_token = 'changed'
            else:
                repository.maximum = 2
            return snapshot

        service._reader.load_stream = changed
    with pytest.raises(ValueError, match='ROUTE_CHANGED|READBACK_REQUIRED|SOURCE_CHANGED'):
        recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert runner.state.path.read_bytes() == original
    assert not list(tmp_path.glob('refresh.json.recovery-*.json'))
    assert not service.calls
    assert len(planner.requests) == (0 if drift in {'route', 'active', 'candidate'} else 1)


def test_current_v3_rollforward_rechecks_hash_and_keeps_old_pending(tmp_path):
    runner, dual, planner, _, _ = current_v3(tmp_path)
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    original = runner.state.path.read_bytes()
    planner.manifest = {**planner.manifest, 'changed': True}
    with pytest.raises(ValueError, match='HASH_CONFLICT'):
        recover_pending_source(
            runner, dual.identity.stream_id, now=END, apply=True,
            expected_recovery_sha256=dry['recovery_sha256'],
        )
    assert runner.state.path.read_bytes() == original
    assert not list(tmp_path.glob('refresh.json.recovery-*.json'))


def test_current_v3_rollforward_rejects_unknown_pending(tmp_path):
    runner, dual, _, _, _ = current_v3(tmp_path)
    state = runner.state.read()
    state['routes'][dual.identity.stream_id].update(
        status='blocked', reason='REFRESH_READBACK_REQUIRED')
    runner.state.write(state)
    original = runner.state.path.read_bytes()
    with pytest.raises(ValueError, match='NOT_ELIGIBLE'):
        recover_pending_source(runner, dual.identity.stream_id, now=END)
    assert runner.state.path.read_bytes() == original


def test_current_v3_rollforward_archive_conflict_preserves_pending(tmp_path):
    runner, dual, _, service, _ = current_v3(tmp_path)
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    original = runner.state.path.read_bytes()
    archive = tmp_path / ('refresh.json.recovery-' + dry['recovery_sha256'] + '.json')
    archive.write_text('{}')
    with pytest.raises(ValueError, match='ARCHIVE_CONFLICT'):
        recover_pending_source(
            runner, dual.identity.stream_id, now=END, apply=True,
            expected_recovery_sha256=dry['recovery_sha256'],
        )
    assert runner.state.path.read_bytes() == original
    assert not service.calls


def test_current_v3_rollforward_unknown_state_write_keeps_archive(tmp_path):
    runner, dual, _, service, _ = current_v3(tmp_path)
    dry = recover_pending_source(runner, dual.identity.stream_id, now=END)
    original = runner.state.path.read_bytes()
    write = runner.state.write

    def unknown(_state):
        raise RefreshStateError('REFRESH_STATE_WRITE_UNKNOWN')

    runner.state.write = unknown
    try:
        with pytest.raises(RefreshStateError, match='WRITE_UNKNOWN'):
            recover_pending_source(
                runner, dual.identity.stream_id, now=END, apply=True,
                expected_recovery_sha256=dry['recovery_sha256'],
            )
    finally:
        runner.state.write = write
    assert runner.state.path.read_bytes() == original
    assert len(list(tmp_path.glob('refresh.json.recovery-*.json'))) == 1
    assert not service.calls
