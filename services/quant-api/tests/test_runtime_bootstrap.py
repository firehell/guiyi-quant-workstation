from contextlib import contextmanager

import pytest

from app.runtime_bootstrap import BootstrapError, apply_bootstrap_plan, build_bootstrap_plan
from app.runtime_bindings import CONTRACTS


class Backend:
    def __init__(self, root):
        self.root = root
        self.events = []
        self.revision = '20261009_0050'
        self.safe = True
        self.fail = None
        self.exists = False
    def registry_exists(self):
        return self.exists
    def verify_candidate(self, *args):
        assert args[0] == self.root
    def contracts(self, root):
        return {key: 'f' * 64 for key in CONTRACTS}
    def installed(self):
        return {service: {'root': str(self.root), 'tag': 'v1.14.5', 'commit': 'a' * 40,
                         'enabled': True, 'label': 'com.guiyi.quant-' + service,
                         'plist_sha256': 'b' * 64} for service in ('live', 'alert', 'reference-worker')}
    def schema_revision(self):
        return self.revision
    def prove_safe_boundary(self, _plan):
        if not self.safe:
            raise BootstrapError('BOOTSTRAP_REST_WINDOW_REQUIRED')
        return {'trading_day': '2026-10-09', 'legacy_last_bar_at': '2026-10-09T02:15:00+00:00'}
    def journal(self, value):
        self.events.append(('journal', value['phase'], tuple(value['completed_steps'])))
    @contextmanager
    def writer_guards(self, _plan):
        self.events.append('guards')
        yield
    def stop_legacy(self, _plan):
        self.events.append('stop')
    def prove_no_inflight_sends(self):
        self.events.append('send_idle')
    def migrate_schema(self, _plan):
        self.events.append('migrate')
        self.revision = '20261009_0051'
    def initialize_cutoffs(self, _plan, _proof):
        self.events.append('cutoffs')
        if self.fail == 'cutoffs':
            raise RuntimeError('unknown')
    def install(self, _plan):
        self.events.append('install')
    def commit_registry(self, _registry):
        self.events.append('commit')
        self.exists = True
    def start(self, _plan):
        self.events.append('start')
    def verify(self, _plan, _proof):
        self.events.append('verify')
        return True


def plan_for(backend):
    return build_bootstrap_plan(backend.root, 'v1.14.6', 'c' * 40, backend=backend)


def test_planner_is_readonly_and_binds_each_frozen_service(tmp_path):
    backend = Backend(tmp_path)
    plan = plan_for(backend)
    assert backend.events == []
    assert plan['bindings']['market-feed']['enabled'] is True
    assert plan['installed']['alert']['root'] == str(tmp_path)
    assert 'plist' not in plan['installed']['live']


def test_bootstrap_orders_migration_and_empty_cutoffs_before_publishers(tmp_path):
    backend = Backend(tmp_path)
    assert apply_bootstrap_plan(plan_for(backend), backend=backend)['natural_acceptance'] == 'pending'
    stages = [event for event in backend.events if isinstance(event, str)]
    assert stages == ['guards', 'stop', 'send_idle', 'migrate', 'cutoffs', 'install', 'commit', 'start', 'verify']


def test_rest_window_failure_does_not_stop_or_write(tmp_path):
    backend = Backend(tmp_path)
    plan = plan_for(backend)
    backend.safe = False
    with pytest.raises(BootstrapError, match='REST_WINDOW_REQUIRED'):
        apply_bootstrap_plan(plan, backend=backend)
    assert backend.events == []


def test_unknown_cutoff_mutation_never_starts_or_automatically_retries(tmp_path):
    backend = Backend(tmp_path)
    backend.fail = 'cutoffs'
    with pytest.raises(BootstrapError, match='OUTCOME_UNKNOWN'):
        apply_bootstrap_plan(plan_for(backend), backend=backend)
    assert 'start' not in backend.events
    assert 'commit' not in backend.events
    assert backend.events[-1][1] == 'outcome_unknown'


def test_schema_drift_rejects_before_mutation(tmp_path):
    backend = Backend(tmp_path)
    plan = plan_for(backend)
    backend.revision = '20261009_0051'
    with pytest.raises(BootstrapError, match='PLAN_DRIFT'):
        apply_bootstrap_plan(plan, backend=backend)
    assert backend.events == []


def test_real_redis_bootstrap_establishes_only_empty_cutoff(monkeypatch):
    import os
    from datetime import date
    from redis import Redis
    from app.runtime_bootstrap import BootstrapBackend
    from app.market_data.observation_stream import ObservationStream
    import app.redis_connections
    url = os.getenv('GUIYI_ISOLATED_REDIS_URL')
    if not url:
        pytest.skip('GUIYI_ISOLATED_REDIS_URL required')
    redis = Redis.from_url(url)
    prefixes = ('live:observations:*',)
    existing = set(redis.scan_iter(match=prefixes[0]))
    if existing:
        pytest.skip('bootstrap requires isolated empty observation namespace')
    # Backend closes this borrowed client, which reconnects on next operation.
    monkeypatch.setattr(app.redis_connections, 'get_redis_connection', lambda: redis)
    backend = BootstrapBackend()
    monkeypatch.setattr(backend, '_assert_rest_still_open', lambda: None)
    plan = {'bindings': {'alert': {'enabled': True}, 'reference-worker': {'enabled': True}}}
    proof = {'trading_day': '2026-10-09'}
    try:
        backend.initialize_cutoffs(plan, proof)
        assert ObservationStream(redis, kind='source').cursor('live', date(2026, 10, 9)) == '0-0'
        completed = ObservationStream(redis, kind='completed')
        assert completed.cursor('alert', date(2026, 10, 9)) == '0-0'
        assert completed.cursor('reference', date(2026, 10, 9)) == '0-0'
        with pytest.raises(BootstrapError, match='JOURNAL_NOT_EMPTY'):
            backend.initialize_cutoffs(plan, proof)
    finally:
        created = set(redis.scan_iter(match=prefixes[0])) - existing
        if created:
            redis.delete(*created)
        redis.close()


def test_cli_plan_writes_private_plan_and_apply_uses_exact_file(tmp_path, monkeypatch, capsys):
    from app.runtime_bootstrap import main
    import app.runtime_handover
    backend = Backend(tmp_path)
    destination = tmp_path / 'plan.json'
    assert main(['plan', '--candidate-root', str(tmp_path), '--tag', 'v1.14.6',
                 '--commit', 'c' * 40, '--output', str(destination)], backend=backend) == 0
    assert destination.stat().st_mode & 0o777 == 0o600
    assert 'plan_hash' in capsys.readouterr().out
    @contextmanager
    def isolated_lock():
        yield
    monkeypatch.setattr(app.runtime_handover, 'deployment_lock', isolated_lock)
    assert main(['apply', '--plan', str(destination)], backend=backend) == 0
    assert 'switched' in capsys.readouterr().out


def test_launchctl_permission_failure_is_never_missing(monkeypatch):
    from types import SimpleNamespace
    import app.runtime_bootstrap
    from app.runtime_bootstrap import BootstrapBackend
    monkeypatch.setattr(app.runtime_bootstrap.subprocess, 'run', lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=1, stdout=b'', stderr=b'private internal detail'))
    with pytest.raises(BootstrapError, match='LAUNCHD_OPERATION_FAILED'):
        BootstrapBackend()._pid('com.guiyi.quant-live')


def test_readback_failure_parks_new_generation_without_retry_or_old_resume(tmp_path):
    backend = Backend(tmp_path)
    backend.verify = lambda *_args: False
    stopped = []
    def halt(plan):
        if backend.exists:
            stopped.extend(name for name, binding in plan['bindings'].items() if binding['enabled'])
    backend.halt_unknown = halt
    with pytest.raises(BootstrapError, match='OUTCOME_UNKNOWN'):
        apply_bootstrap_plan(plan_for(backend), backend=backend)
    assert backend.events.count('start') == 1
    assert set(stopped) == {'live', 'alert', 'reference-worker', 'market-feed'}
    assert backend.events[-1][1] == 'outcome_unknown'


def test_unknown_before_registry_does_not_park_legacy(tmp_path):
    backend = Backend(tmp_path)
    backend.fail = 'cutoffs'
    stopped = []
    backend.halt_unknown = lambda _plan: stopped.append(True) if backend.exists else None
    with pytest.raises(BootstrapError, match='OUTCOME_UNKNOWN'):
        apply_bootstrap_plan(plan_for(backend), backend=backend)
    assert stopped == []


@pytest.mark.parametrize('phase', ['prepared', 'binding_committed', 'outcome_unknown', None])
def test_nonterminal_bootstrap_journal_requires_readback(tmp_path, monkeypatch, phase):
    from app.runtime_bootstrap import BootstrapBackend
    from app.runtime_handover import _write
    import app.runtime_bootstrap
    monkeypatch.setattr(app.runtime_bootstrap, 'runtime_directory', lambda: tmp_path)
    _write(tmp_path / 'topology-bootstrap.json', {'phase': phase})
    with pytest.raises(BootstrapError, match='RECOVERY_READBACK_REQUIRED'):
        BootstrapBackend().registry_exists()


def test_unknown_journal_write_failure_keeps_prepared_gate(tmp_path, monkeypatch):
    from app.runtime_bootstrap import BootstrapBackend
    from app.runtime_handover import _write
    import app.runtime_bootstrap
    monkeypatch.setattr(app.runtime_bootstrap, 'runtime_directory', lambda: tmp_path)
    backend = Backend(tmp_path)
    backend.fail = 'cutoffs'
    def journal(value):
        if value['phase'] == 'outcome_unknown':
            raise OSError('control write unknown')
        _write(tmp_path / 'topology-bootstrap.json', value)
    backend.journal = journal
    with pytest.raises(BootstrapError, match='OUTCOME_UNKNOWN'):
        apply_bootstrap_plan(plan_for(backend), backend=backend)
    with pytest.raises(BootstrapError, match='RECOVERY_READBACK_REQUIRED'):
        BootstrapBackend().registry_exists()
    assert backend.events.count('migrate') == 1
