"""Independent state-machine acceptance; all persistence is confined to pytest tmp_path."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from app.market_data.newow.home_projection import ProjectionError
from app.market_data.newow.home_recovery_state import (
    RecoveryPolicy, WorkStore, eligible, failure_detail, finish, hour_budget,
    probe, reconcile, reserve, settle,
)


def fixture(tmp_path, **limits):
    store = WorkStore(tmp_path / 'summary.json')
    state = store.state()
    policy = RecoveryPolicy(period_seconds=2, product_seconds=24, initial_seconds=100, retry_seconds=100, **limits)
    job = reconcile(state, 'rb', {'1d': 'd1', '1w': 'w1'}, 'impl1', False, 100)
    return store, state, job, policy


def restart(store, state):
    store.save(state)
    other = WorkStore(store.path.with_name('summary.json'))
    return other, other.state()


def detail(category):
    return {'category': category, 'code': 'HOME_PROJECTION_BUILD_FAILED', 'stage': 'compute'}


def fail_attempt(state, job, policy, now, category='transient'):
    assert eligible(job, state, now, policy)
    assert reserve(state, 'rb', job, now, 2, policy)
    settle(state, 'rb', job, 1)
    finish(job, detail(category), now + 1, policy)


def test_real_store_roundtrip_hash_permissions_and_atomic_failure_keeps_last_good(tmp_path):
    store, state, job, policy = fixture(tmp_path)
    fail_attempt(state, job, policy, 100)
    store.save(state)
    before = store.path.read_bytes()
    envelope = json.loads(before)
    canonical = json.dumps(envelope['payload'], sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    assert envelope['sha256'] == sha256(canonical).hexdigest()
    assert store.path.stat().st_mode & 0o777 == 0o600
    other, loaded = restart(store, state)
    assert loaded == state
    assert other.public(['rb'])['rb'] == {
        'status': 'retry_wait', 'attempt': 1, 'category': 'transient',
        'code': 'HOME_PROJECTION_BUILD_FAILED',
        'last_attempt_at': '1970-01-01T00:01:40+00:00',
        'next_attempt_at': '1970-01-01T00:02:11+00:00',
    }
    oversized = deepcopy(state)
    oversized['items']['rb']['history'] = ['x' * (256 * 1024)]
    with pytest.raises(ProjectionError):
        store.save(oversized)
    assert store.path.read_bytes() == before
    assert not list(tmp_path.glob('.*.tmp'))


@pytest.mark.parametrize('corruption', ['json', 'hash', 'size', 'schema'])
def test_corrupt_state_never_silently_resets_or_overwrites(tmp_path, corruption):
    store, state, _, _ = fixture(tmp_path)
    store.save(state)
    if corruption == 'json':
        store.path.write_bytes(b'{broken')
    elif corruption == 'size':
        store.path.write_bytes(b' ' * (256 * 1024 + 1))
    else:
        packet = json.loads(store.path.read_bytes())
        if corruption == 'hash':
            packet['payload']['items']['rb']['attempt'] = 999
        else:
            packet['payload']['schema_version'] = 'foreign'
            encoded = json.dumps(packet['payload'], sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
            packet['sha256'] = sha256(encoded).hexdigest()
        store.path.write_text(json.dumps(packet))
    damaged = store.path.read_bytes()
    with pytest.raises(ProjectionError):
        store.state()
    assert store.public(['rb'])['rb']['code'] == 'HOME_RECOVERY_STATE_INVALID'
    assert store.path.read_bytes() == damaged


@pytest.mark.parametrize('dangling', [False, True])
def test_state_symlink_is_rejected_for_reads_and_writes_without_touching_target(tmp_path, dangling):
    store, state, _, _ = fixture(tmp_path)
    target = tmp_path / 'unrelated.json'
    if not dangling:
        target.write_text('user content')
    store.path.symlink_to(target)
    with pytest.raises(ProjectionError):
        store.state()
    with pytest.raises(ProjectionError):
        store.save(state)
    assert store.path.is_symlink()
    if dangling:
        assert not target.exists()
    else:
        assert target.read_text() == 'user content'


@pytest.mark.parametrize('mutation', [
    lambda s: s['items']['rb'].pop('id'),
    lambda s: s['items']['rb'].update(attempt=True),
    lambda s: s.update(probe=[]),
    lambda s: s.update(budgets={'0': {'initial': -1, 'retry': 0, 'products': {}}}),
    lambda s: s.update(budgets={'not-an-hour': {'initial': 0, 'retry': 0, 'products': {}}}),
], ids=['missing-job-id', 'boolean-attempt', 'invalid-probe', 'negative-budget', 'invalid-hour-key'])
def test_valid_hash_does_not_authorize_invalid_scheduler_schema(tmp_path, mutation):
    store, state, _, _ = fixture(tmp_path)
    mutation(state)
    store.save(state)
    with pytest.raises(ProjectionError):
        store.state()
    assert store.public(['rb'])['rb']['code'] == 'HOME_RECOVERY_STATE_INVALID'


def test_starts_budget_cannot_be_reset_by_new_job_or_process_restart(tmp_path):
    store, state, job, policy = fixture(tmp_path, product_starts=2)
    fail_attempt(state, job, policy, 100, 'source_changed')
    store, state = restart(store, state)
    job = reconcile(state, 'rb', {'1d': 'revised', '1w': 'w1'}, 'impl1', False, 200)
    assert not eligible(job, state, 200, policy)
    fail_attempt(state, job, policy, 231, 'source_changed')
    store, state = restart(store, state)
    job = reconcile(state, 'rb', {'1d': 'again', '1w': 'w1'}, 'impl1', False, 300)
    assert not reserve(state, 'rb', job, 300, 2, policy)
    assert job['detail']['category'] == 'budget'
    assert job['next_at'] == 3600
    assert state['budgets']['0']['products']['rb']['starts'] == 2
    assert job['attempt'] == 0


def test_initial_and_retry_global_pools_are_separate_and_fair(tmp_path):
    _, state, job, policy = fixture(tmp_path)
    policy = RecoveryPolicy(period_seconds=2, product_seconds=24, initial_seconds=4, retry_seconds=2)
    fail_attempt(state, job, policy, 100)
    fail_attempt(state, job, policy, 131)
    # Retry pool has one occupied second; a two-second reservation exceeds its cap.
    assert not reserve(state, 'rb', job, 252, 2, policy)
    other = reconcile(state, 'cu', {}, 'impl1', False, 252)
    assert reserve(state, 'cu', other, 252, 2, policy)
    assert other['reservation']['pool'] == 'initial'


def test_elapsed_budget_splits_at_utc_hour_boundary_and_survives_restart(tmp_path):
    store, state, job, policy = fixture(tmp_path)
    assert reserve(state, 'rb', job, 3599, 4, policy)
    store, state = restart(store, state)
    job = state['items']['rb']
    settle(state, 'rb', job, 3)
    assert state['budgets']['0']['initial'] == 1
    assert state['budgets']['1']['initial'] == 2
    assert state['budgets']['0']['products']['rb'] == {'starts': 1, 'seconds': 1}
    assert state['budgets']['1']['products']['rb']['seconds'] == 2
    # A duplicate settlement cannot refund or charge a second time.
    snapshot = deepcopy(state)
    settle(state, 'rb', job, 3)
    assert state == snapshot


def test_clock_rollback_never_refunds_latest_hour_budget(tmp_path):
    _, state, job, policy = fixture(tmp_path)
    hour_budget(state, 4000)
    assert reserve(state, 'rb', job, 3500, 2, policy)
    settle(state, 'rb', job, 2)
    assert state['budgets']['1']['products']['rb']['seconds'] == 2
    assert state['budgets']['1']['initial'] == 2
    assert len(state['budgets']) == 1


def test_transient_round_requires_cooldown_and_two_distinct_health_checks(tmp_path):
    store, state, job, policy = fixture(tmp_path)
    for now in [100, 131, 252]:
        fail_attempt(state, job, policy, now)
    assert job['status'] == 'dependency_wait'
    assert job['round_attempt'] == 3
    assert job['attempt'] == 3
    assert job['next_at'] == 1153
    store, state = restart(store, state)
    job = state['items']['rb']
    assert not eligible(job, state, 1152, policy)
    probe(state, True, 1153)
    assert not eligible(job, state, 1153, policy)
    probe(state, True, 1212)
    assert state['probe']['successes'] == 1
    assert not eligible(job, state, 1212, policy)
    probe(state, True, 1213)
    assert eligible(job, state, 1213, policy)
    assert job['round_attempt'] == 0
    assert reserve(state, 'rb', job, 1213, 2, policy)
    assert job['attempt'] == 4
    assert job['round_attempt'] == 1


def test_failed_or_repeated_probe_does_not_create_recovery_eligibility(tmp_path):
    _, state, job, policy = fixture(tmp_path)
    for now in [100, 131, 252]:
        fail_attempt(state, job, policy, now)
    probe(state, True, 1153)
    probe(state, False, 1213)
    assert state['probe']['successes'] == 0
    assert not eligible(job, state, 1213, policy)
    probe(state, True, 1273)
    probe(state, True, 1200)  # A backwards clock cannot count as another check.
    assert state['probe']['successes'] == 1
    assert not eligible(job, state, 1273, policy)


@pytest.mark.parametrize('category', ['unknown', 'timeout', 'interrupted'])
def test_repeat_unknown_failures_block_despite_restart_health_and_new_hour(tmp_path, category):
    store, state, job, policy = fixture(tmp_path)
    fail_attempt(state, job, policy, 100, category)
    assert job['status'] == 'retry_wait'
    store, state = restart(store, state)
    job = state['items']['rb']
    fail_attempt(state, job, policy, 131, category)
    assert job['status'] == 'blocked'
    assert len(job['history']) == 2
    probe(state, True, 4000)
    probe(state, True, 4060)
    hour_budget(state, 4060)
    assert not eligible(job, state, 4060, policy)


def test_revised_source_or_implementation_can_resume_without_resetting_resource_usage(tmp_path):
    _, state, job, policy = fixture(tmp_path)
    fail_attempt(state, job, policy, 100, 'data')
    assert job['status'] == 'blocked'
    identity = job['id']
    same = reconcile(state, 'rb', {'1d': 'd1', '1w': 'w1'}, 'impl1', False, 200)
    assert same['id'] == identity and not eligible(same, state, 200, policy)
    latest = reconcile(state, 'rb', {'1d': 'd2', '1w': 'w1'}, 'impl1', False, 200)
    assert latest['id'] != identity and not eligible(latest, state, 200, policy)
    assert eligible(latest, state, 230, policy)
    assert state['budgets']['0']['products']['rb']['starts'] == 1
    implementation = reconcile(state, 'rb', {'1d': 'd2', '1w': 'w1'}, 'impl2', False, 201)
    assert implementation['id'] != latest['id']
    assert state['budgets']['0']['products']['rb']['starts'] == 1


def test_ready_clears_current_failure_only_and_preserves_real_attempts_history(tmp_path):
    _, state, job, policy = fixture(tmp_path)
    fail_attempt(state, job, policy, 100)
    attempts = deepcopy(job['history'])
    ready = reconcile(state, 'rb', {'1d': 'd1', '1w': 'w1'}, 'impl1', True, 200)
    assert ready['status'] == 'succeeded'
    assert ready['attempt'] == 1 and ready['history'] == attempts
    assert 'detail' not in ready and ready['next_at'] is None
    assert not eligible(ready, state, 200, policy)


def test_source_change_waits_instead_of_unknown_block_and_diagnostics_stay_bounded(tmp_path):
    _, state, job, policy = fixture(tmp_path)
    for now in [100, 161, 222, 283]:
        fail_attempt(state, job, policy, now, 'source_changed')
    assert job['status'] == 'retry_wait'
    assert job['next_at'] == 344
    assert len(job['history']) == 3
    assert job['attempt'] == 4
    assert not eligible(job, state, 343, policy)
    assert eligible(job, state, 344, policy)


@pytest.mark.parametrize('sqlstate,expected', [('08006', 'transient'), ('40001', 'transient'), ('23505', 'unknown')])
def test_failure_classifier_allowlist_redacts_exception_text_and_paths(sqlstate, expected):
    class DatabaseError(Exception):
        pass
    try:
        error = DatabaseError('secret-token /Users/private/data password=secret')
        error.sqlstate = sqlstate
        raise error
    except DatabaseError as error:
        result = failure_detail(error)
    assert result['category'] == expected
    assert result['exception_type'] == 'DatabaseError'
    assert result['file'] == 'test_home_recovery_state.py'
    encoded = json.dumps(result)
    assert 'secret' not in encoded and '/Users/' not in encoded


def test_precommit_failure_preserves_previous_bytes_and_removes_temporary_file(tmp_path):
    store, state, job, policy = fixture(tmp_path)
    store.save(state)
    before = store.path.read_bytes()
    fail_attempt(state, job, policy, 100)
    calls = 0

    def guard():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('simulated owner lost before replace')

    store.write_guard = guard
    with pytest.raises(RuntimeError, match='owner lost'):
        store.save(state)
    assert store.path.read_bytes() == before
    assert not list(tmp_path.glob('.*.tmp'))


def test_bounded_work_items_and_fifo_fail_closed(tmp_path):
    store, state, _, _ = fixture(tmp_path)
    state['items'] = {f'bad{i}': {} for i in range(62)}
    store.save(state)
    with pytest.raises(ProjectionError):
        store.state()
    store.path.unlink()
    import os
    os.mkfifo(store.path)
    with pytest.raises(ProjectionError):
        store.state()


def test_product_seconds_limit_survives_job_replacement(tmp_path):
    _, state, job, policy = fixture(tmp_path)
    policy = RecoveryPolicy(period_seconds=2, product_seconds=2, initial_seconds=100, retry_seconds=100)
    fail_attempt(state, job, policy, 100)
    new = reconcile(state, 'rb', {'1d': 'new', '1w': 'new'}, 'impl1', False, 200)
    assert not reserve(state, 'rb', new, 200, 2, policy)
    assert new['detail']['category'] == 'budget'
    assert state['budgets']['0']['products']['rb']['seconds'] == 1


def test_connection_failure_is_transient_but_unclassified_exception_is_not():
    assert failure_detail(ConnectionError('private network address'))['category'] == 'transient'
    assert failure_detail(RuntimeError('database failed: private text'))['category'] == 'unknown'


def test_dependency_recovery_requires_two_fresh_probes_after_cooldown(tmp_path):
    _, state, job, policy = fixture(tmp_path)
    probe(state, True, 100)
    probe(state, True, 160)
    for now in [200, 231, 352]:
        fail_attempt(state, job, policy, now)
    cooldown = job['next_at']
    assert state['probe']['successes'] == 2
    assert not eligible(job, state, cooldown, policy)
    probe(state, True, cooldown)
    assert not eligible(job, state, cooldown, policy)
    probe(state, True, cooldown + 59)
    assert not eligible(job, state, cooldown + 59, policy)
    probe(state, True, cooldown + 60)
    assert eligible(job, state, cooldown + 60, policy)


def test_unowned_running_is_read_as_interrupted_without_journal_mutation(tmp_path):
    store, state, job, policy = fixture(tmp_path)
    reserve(state, 'rb', job, 100, 2, policy)
    store.save(state)
    before = store.path.read_bytes()
    assert not store.building()
    assert store.public(['rb'])['rb']['status'] == 'retry_wait'
    assert store.public(['rb'])['rb']['code'] == 'HOME_COMPUTE_INTERRUPTED'
    assert store.path.read_bytes() == before
    with store.lock():
        assert store.public(['rb'])['rb']['status'] == 'running'
