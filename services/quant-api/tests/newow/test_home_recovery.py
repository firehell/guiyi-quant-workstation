"""Real temporary stores with deterministic compute/clock seams; no database or sleeps."""
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.market_data.newow.home_projection import HomeProjection, ProjectionError, ProjectionStore
from app.market_data.newow.home_recovery import HomeComputeError, HomeRecovery, configure_delivery
from app.market_data.newow.home_recovery_state import RecoveryPolicy, WorkStore, reconcile, reserve


class FakeClock:
    def __init__(self, now=100):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeExecutor:
    def __init__(self, versions, clock):
        self.versions = versions
        self.clock = clock
        self.calls = []
        self.failures = {}
        self.hook = None

    def __call__(self, product, period):
        self.calls.append((product, period))
        self.clock.advance(.1)
        if self.hook is not None:
            self.hook(product, period)
        if (product, period) in self.failures:
            raise self.failures[(product, period)]
        if product == 'overview':
            return {'status': 'ready', 'source': dict(self.versions)}
        return {strategy: {'status': 'ready', 'state': 'HOLD',
                           'input_sha256': self.versions[f'{product}:{period}'],
                           'page_parity': True, 'executable': False}
                for strategy in ('trend', 'oscillation')}


def fixture(tmp_path, products=('rb', 'cu'), *, overview=False, dependency=None):
    clock = FakeClock()
    versions = {f'{product}:{period}': f'{product}-{period}-v1'
                for product in products for period in ('1d', '1w')}
    executor = FakeExecutor(versions, clock)
    home = configure_delivery(HomeProjection(
        ProjectionStore(tmp_path / 'home.json'), products, lambda: dict(versions), executor,
        now=lambda: datetime.fromtimestamp(clock(), UTC),
        overview=(lambda: {'unused': True}) if overview else None,
    ))
    policy = RecoveryPolicy(period_seconds=2, product_seconds=24, initial_seconds=100, retry_seconds=100)
    recovery = HomeRecovery(home, clock=clock, monotonic=clock, executor=executor,
                            implementation='test-implementation', policy=policy,
                            dependency_probe=dependency or (lambda: True))
    return recovery, home, executor, clock, versions


def transient():
    return HomeComputeError({'category': 'transient', 'code': 'HOME_DATABASE_UNAVAILABLE', 'stage': '1w'})


def test_failed_product_does_not_block_others_or_claim_success(tmp_path):
    worker, home, executor, _, _ = fixture(tmp_path)
    executor.failures[('rb', '1d')] = transient()
    result = worker.tick()
    assert result == {'status': 'partial', 'computed': 2}
    states = {item['product']: item for item in home.read()['items']}
    assert states['cu']['projection_status'] == 'ready'
    assert states['rb']['projection_status'] != 'ready'
    assert states['rb']['recovery']['status'] == 'retry_wait'
    assert states['rb']['recovery']['category'] == 'transient'
    assert ('cu', '1d') in executor.calls and ('cu', '1w') in executor.calls


def test_week_failure_retains_both_old_periods_as_one_complete_generation(tmp_path):
    worker, home, executor, clock, versions = fixture(tmp_path, ('rb',))
    assert worker.tick()['status'] == 'passed'
    before = deepcopy(home.store.load()['items']['rb'])
    versions.update({'rb:1d': 'daily-v2', 'rb:1w': 'weekly-v2'})
    executor.failures[('rb', '1w')] = transient()
    assert worker.tick()['computed'] == 0
    clock.advance(31)
    assert worker.tick()['status'] == 'partial'
    after = home.store.load()['items']['rb']
    assert after['periods'] == before['periods']
    assert after['computed_at'] == before['computed_at']
    assert after['building'] is False
    assert home.read()['items'][0]['projection_status'] != 'ready'


def test_cold_week_failure_never_publishes_a_partial_daily_generation(tmp_path):
    worker, home, executor, _, _ = fixture(tmp_path, ('rb',))
    executor.failures[('rb', '1w')] = transient()
    assert worker.tick()['status'] == 'partial'
    item = home.store.load()['items']['rb']
    assert item.get('periods', {}) == {}
    assert item.get('computed_at') is None
    assert home.read()['items'][0]['computed_at'] is None


def test_changed_source_during_compute_never_publishes_current_or_clears_failure(tmp_path):
    worker, home, executor, clock, versions = fixture(tmp_path, ('rb',))
    worker.tick()
    previous = deepcopy(home.store.load()['items']['rb']['periods'])
    versions.update({'rb:1d': 'daily-v2', 'rb:1w': 'weekly-v2'})
    executor.hook = lambda product, period: versions.update({f'{product}:{period}': 'changed-mid-compute'})
    assert worker.tick()['computed'] == 0
    clock.advance(31)
    assert worker.tick()['status'] == 'partial'
    item = home.store.load()['items']['rb']
    assert item['periods'] == previous
    assert 'HOME_PROJECTION_SOURCE_CHANGED' in item['failures'].values()
    work = worker.work.state()['items']['rb']
    assert work['status'] == 'retry_wait' and work['detail']['category'] == 'source_changed'
    assert home.read()['items'][0]['projection_status'] != 'ready'


def test_restart_recovers_running_without_refunding_reserved_budget_or_recomputing_early(tmp_path):
    worker, _, executor, clock, versions = fixture(tmp_path, ('rb',))
    state = worker.work.state()
    target = {period: versions[f'rb:{period}'] for period in ('1d', '1w')}
    job = reconcile(state, 'rb', target, worker.implementation, False, clock())
    assert reserve(state, 'rb', job, clock(), 4, worker.policy)
    worker.work.save(state)
    before = deepcopy(state['budgets'])
    assert worker.tick() == {'status': 'partial', 'computed': 0}
    restarted = WorkStore(worker.home.store.path).state()
    assert restarted['budgets'] == before
    assert restarted['items']['rb']['status'] == 'retry_wait'
    assert restarted['items']['rb']['attempt'] == 1
    assert 'reservation' not in restarted['items']['rb']
    assert executor.calls == []
    clock.advance(31)
    assert worker.tick()['status'] == 'passed'
    assert worker.work.state()['items']['rb']['attempt'] == 2


def test_actual_ready_readback_after_unknown_exit_avoids_duplicate_compute(tmp_path):
    worker, home, executor, clock, versions = fixture(tmp_path, ('rb',))
    assert worker.tick()['status'] == 'passed'
    count = len(executor.calls)
    state = worker.work.state()
    job = state['items']['rb']
    assert reserve(state, 'rb', job, clock(), 4, worker.policy)
    worker.work.save(state)
    assert worker.tick() == {'status': 'passed', 'computed': 0}
    assert len(executor.calls) == count
    assert worker.work.state()['items']['rb']['status'] == 'succeeded'
    assert worker.work.state()['items']['rb']['attempt'] == 2
    assert home.read()['items'][0]['projection_status'] == 'ready'
    clock.advance(60)
    assert worker.tick() == {'status': 'passed', 'computed': 0}
    assert len(executor.calls) == count
    assert versions['rb:1d'].endswith('v1')


def test_second_writer_cannot_compute_while_work_lock_is_held(tmp_path):
    worker, home, executor, _, _ = fixture(tmp_path)
    with worker.work.lock():
        with pytest.raises(ProjectionError):
            worker.tick()
    assert executor.calls == []
    assert not home.store.path.exists()


def test_corrupt_work_never_resets_budget_or_touches_last_good_projection(tmp_path):
    worker, home, executor, _, _ = fixture(tmp_path)
    worker.tick()
    previous = home.store.path.read_bytes()
    executor.calls.clear()
    worker.work.path.write_text('{invalid')
    damaged = worker.work.path.read_bytes()
    with pytest.raises(ProjectionError):
        worker.tick()
    assert executor.calls == []
    assert worker.work.path.read_bytes() == damaged
    assert home.store.path.read_bytes() == previous
    assert home.read()['items'][0]['recovery']['code'] == 'HOME_RECOVERY_STATE_INVALID'


def test_failed_dependency_probe_prevents_compute_and_budget_consumption(tmp_path):
    worker, _, executor, _, _ = fixture(tmp_path, dependency=lambda: False)
    result = worker.tick()
    assert result['computed'] == 0
    assert executor.calls == []
    state = worker.work.state()
    assert state['budgets'] == {}
    assert all(job['attempt'] == 0 for job in state['items'].values())


def test_overview_failure_does_not_undo_successful_product_publication(tmp_path):
    worker, home, executor, _, _ = fixture(tmp_path, overview=True)
    executor.failures[('overview', 'overview')] = transient()
    result = worker.tick()
    assert result['status'] == 'partial' and result['computed'] == 3
    assert all(item['projection_status'] == 'ready' for item in home.read()['items'])
    assert home.store.load()['overview_failed'] is True
    assert worker.work.state()['items']['overview']['status'] == 'retry_wait'


def test_product_failure_does_not_prevent_overview_publication(tmp_path):
    worker, home, executor, _, _ = fixture(tmp_path, overview=True)
    executor.failures[('rb', '1d')] = transient()
    assert worker.tick()['status'] == 'partial'
    payload = home.store.load()
    assert payload['overview']['status'] == 'ready'
    assert not payload.get('overview_failed')
    assert worker.work.state()['items']['overview']['status'] == 'succeeded'
    assert next(item for item in home.read()['items'] if item['product'] == 'cu')['projection_status'] == 'ready'


def test_unchanged_source_recovers_after_exhausted_transient_round_with_fresh_health_checks(tmp_path):
    worker, home, executor, clock, _ = fixture(tmp_path, ('rb',))
    executor.failures[('rb', '1d')] = transient()
    assert worker.tick()['computed'] == 1
    clock.advance(31)
    assert worker.tick()['computed'] == 1
    clock.advance(121)
    assert worker.tick()['computed'] == 1
    blocked = worker.work.state()['items']['rb']
    assert blocked['status'] == 'dependency_wait'
    assert blocked['attempt'] == 3
    executor.failures.clear()
    clock.now = blocked['next_at'] - 1
    assert worker.tick()['computed'] == 0
    clock.now = blocked['next_at']
    assert worker.tick()['computed'] == 0  # Pre-cooldown probe cannot count as fresh.
    clock.advance(60)
    assert worker.tick()['computed'] == 0  # First fresh health probe.
    clock.advance(60)
    assert worker.tick()['computed'] == 1
    current = worker.work.state()['items']['rb']
    assert current['status'] == 'succeeded' and current['attempt'] == 4
    assert 'detail' not in current
    assert home.read()['items'][0]['projection_status'] == 'ready'


def test_budget_counts_each_period_process_start(tmp_path):
    worker, _, executor, _, _ = fixture(tmp_path, ('rb',))
    worker.tick()
    assert len(executor.calls) == 2
    budget = next(iter(worker.work.state()['budgets'].values()))
    assert budget['products']['rb']['starts'] == 2
