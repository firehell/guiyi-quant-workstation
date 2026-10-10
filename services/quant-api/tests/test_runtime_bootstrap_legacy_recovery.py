from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.runtime_bootstrap import BootstrapBackend, BootstrapError
from app.runtime_handover import _write


@pytest.fixture
def recovery_host(tmp_path, monkeypatch):
    import app.runtime_bootstrap as module
    directory = tmp_path / 'runtime'
    directory.mkdir(mode=0o700)
    home = tmp_path / 'home'
    plists = home / 'Library/LaunchAgents'
    plists.mkdir(parents=True)
    root = tmp_path / 'release'
    scripts = root / 'scripts/ops/macos'
    scripts.mkdir(parents=True)
    launcher = b'old-launcher\n'
    (scripts / 'run-local-service.sh').write_bytes(launcher)
    (directory / 'run-local-service.sh').write_bytes(launcher)
    installed, loaded, disabled, pids = {}, {}, {}, {}
    services = ('api', 'web', 'live', 'alert', 'reference-worker', 'after-market', 'late-provider-recovery', 'weekly-audit')
    for number, service in enumerate(services):
        label = 'com.guiyi.quant-' + service
        payload = {'Label': label, 'WorkingDirectory': str(root),
            'ProgramArguments': ['/bin/bash', str(directory / 'run-local-service.sh'), service],
            'EnvironmentVariables': {'GUIYI_PROJECT_ROOT': str(root), 'GUIYI_RUNTIME_COMMIT': 'a' * 40,
                'GUIYI_RUNTIME_TAG': 'v1.14.9'}, 'Disabled': False}
        if service not in module._CONTINUOUS:
            payload['StartCalendarInterval'] = {'Hour': (datetime.now() + timedelta(hours=1)).hour, 'Minute': 0}
        import plistlib
        content = plistlib.dumps(payload)
        (plists / (label + '.plist')).write_bytes(content)
        running = service in module._CONTINUOUS
        loaded[label] = running
        disabled[label] = not running or service == 'web'
        pids[label] = 100 + number if running else None
        installed[service] = {'root': str(root), 'tag': 'v1.14.9', 'commit': 'a' * 40,
            'enabled': True, 'label': label, 'loaded_pid': pids[label],
            'plist_sha256': hashlib.sha256(content).hexdigest()}
    original_plan = {'candidate_root': str(root), 'plan_hash': 'original-plan',
        'schema_before': '20261009_0050', 'installed': installed}
    original_plan['plan_hash'] = module._hash({key: value for key, value in original_plan.items() if key != 'plan_hash'})
    journal = {'phase': 'outcome_unknown', 'completed_steps': [], 'plan': original_plan}
    _write(directory / 'topology-bootstrap.json', journal)
    raw = (directory / 'topology-bootstrap.json').read_bytes()
    monkeypatch.setattr(module, 'runtime_directory', lambda: directory)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setattr(module, 'read_bindings', lambda: None)
    monkeypatch.setattr(module, 'verify_release', lambda *_args: None)
    monkeypatch.setattr('app.market_data.captured_recovery_runtime._read_launchd_service',
        lambda label, **_kw: label if loaded[label] else None)
    monkeypatch.setattr('app.market_data.captured_recovery_runtime._verify_loaded_service',
        lambda label, **_kw: {'pid': str(pids[label]) if pids[label] is not None else None})
    monkeypatch.setattr('app.market_data.closeout_binding._arguments',
        lambda label: tuple(__import__('plistlib').loads((plists / (label + '.plist')).read_bytes())['ProgramArguments']))
    keys = []
    class Redis:
        def scan_iter(self, **_kw):
            return iter(keys)
        def close(self):
            pass
    monkeypatch.setattr('app.redis_connections.get_redis_connection', Redis)
    backend = BootstrapBackend()
    state = {'schema': '20261009_0050', 'locked': False, 'fail': None}
    monkeypatch.setattr(backend, 'schema_revision', lambda: state['schema'])
    monkeypatch.setattr(backend, 'prove_safe_boundary', lambda _plan: {'trading_day': '2026-10-09'})
    monkeypatch.setattr(backend, '_assert_rest_still_open', lambda: None)
    monkeypatch.setattr(backend, '_pid', lambda label: pids[label])
    @contextmanager
    def guards(_plan):
        if state['fail'] == 'inflight':
            raise BootstrapError('BOOTSTRAP_NEWOW_SEND_BUSY')
        state['locked'] = True
        try:
            yield
        finally:
            state['locked'] = False
    monkeypatch.setattr(backend, 'writer_guards', guards)
    monkeypatch.setattr(backend, 'prove_no_inflight_sends', lambda: None if state['locked'] else pytest.fail('unlocked'))
    calls = []
    def launchctl(*args, **_kw):
        if args[0] == 'print-disabled':
            body = '\n'.join(f'"{label}" => {"disabled" if value else "enabled"}' for label, value in disabled.items())
            return SimpleNamespace(stdout=('disabled services = {\n' + body + '\n}').encode())
        assert state['locked']
        calls.append(args)
        if state['fail'] == 'enable':
            raise BootstrapError('BOOTSTRAP_LAUNCHD_OPERATION_FAILED')
        if args[0] == 'enable':
            disabled[args[1].split('/')[-1]] = False
        elif args[0] == 'bootstrap':
            loaded[Path(args[2]).stem] = True
        else:
            pytest.fail('no kill, disable, unload or kickstart in recovery')
        return SimpleNamespace(stdout=b'')
    monkeypatch.setattr(backend, '_launchctl', launchctl)
    monkeypatch.setattr(backend, 'installed', lambda: {service: dict(old, enabled=not disabled[old['label']],
        loaded_pid=pids[old['label']]) for service, old in installed.items()})
    return SimpleNamespace(backend=backend, directory=directory, installed=installed, state=state,
        calls=calls, raw=raw, keys=keys, plists=plists, pids=pids)


def test_exact_partial_recovery_restores_only_web_and_three_calendars(recovery_host):
    host = recovery_host
    plan = host.backend.read_legacy_recovery()
    assert isinstance(plan['installed']['web']['loaded_pid'], str)
    assert isinstance(host.pids['com.guiyi.quant-web'], int)
    assert plan['installed']['after-market']['loaded_pid'] is None
    assert len(plan['actions']) == 4
    assert host.calls == []
    assert host.backend.recover_legacy(plan)['status'] == 'recovered_legacy'
    assert len([call for call in host.calls if call[0] == 'enable']) == 4
    assert len([call for call in host.calls if call[0] == 'bootstrap']) == 3
    archives = list(host.directory.glob('topology-bootstrap-original-*'))
    assert archives[0].read_bytes() == host.raw
    assert archives[0].stat().st_mode & 0o777 == 0o600
    assert host.backend.registry_exists() is False


@pytest.mark.parametrize('kind', ['schema', 'stream', 'preimage', 'owner', 'inflight'])
def test_recovery_unproven_boundary_does_not_mutate(recovery_host, kind):
    host = recovery_host
    if kind == 'schema':
        host.state['schema'] = '20261009_0051'
    elif kind == 'stream':
        host.keys.append(b'live:observations:registered:source:live')
    elif kind == 'inflight':
        host.state['fail'] = 'inflight'
    else:
        (host.directory / ('bootstrap-preimage-any' if kind == 'preimage' else 'alert.owner.json')).write_text('{}')
    with pytest.raises(BootstrapError):
        host.backend.read_legacy_recovery()
    assert host.calls == []


def test_pid_drift_invalidates_frozen_recovery(recovery_host):
    host = recovery_host
    plan = host.backend.read_legacy_recovery()
    host.pids['com.guiyi.quant-web'] += 1
    with pytest.raises(BootstrapError, match='PLAN_DRIFT'):
        host.backend.recover_legacy(plan)
    assert host.calls == []


def test_plist_drift_invalidates_recovery(recovery_host):
    host = recovery_host
    plan = host.backend.read_legacy_recovery()
    (host.plists / 'com.guiyi.quant-after-market.plist').write_text('changed')
    with pytest.raises(BootstrapError, match='PLIST_DRIFT'):
        host.backend.recover_legacy(plan)
    assert host.calls == []


def test_calendar_autostart_or_current_due_is_blocked(recovery_host):
    host = recovery_host
    with pytest.raises(BootstrapError, match='AUTOSTART'):
        host.backend._assert_recovery_calendar_safe({'RunAtLoad': True})
    with pytest.raises(BootstrapError, match='CALENDAR_DUE'):
        host.backend._assert_recovery_calendar_safe({'StartCalendarInterval':
            {'Hour': datetime.now().hour, 'Minute': datetime.now().minute}})


def test_failed_recovery_preserves_unknown_and_cannot_retry(recovery_host):
    host = recovery_host
    plan = host.backend.read_legacy_recovery()
    host.state['fail'] = 'enable'
    with pytest.raises(BootstrapError, match='OUTCOME_UNKNOWN'):
        host.backend.recover_legacy(plan)
    assert (host.directory / 'topology-bootstrap.json').read_bytes() == host.raw
    with pytest.raises(BootstrapError, match='ATTEMPT_READBACK_REQUIRED'):
        host.backend.recover_legacy(plan)
    with pytest.raises(BootstrapError, match='ATTEMPT_READBACK_REQUIRED'):
        host.backend.registry_exists()
    assert len(host.calls) == 1
