"""Real host backend parsing with frozen legacy files and launchctl output."""
from pathlib import Path
import hashlib
import os
import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from app.runtime_bootstrap import BootstrapBackend, BootstrapError

REPO = Path(__file__).resolve().parents[3]


def host(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    directory = home / 'Library/Application Support/GuiyiQuant'
    agents = home / 'Library/LaunchAgents'
    directory.mkdir(parents=True)
    agents.mkdir(parents=True)
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.setattr('app.runtime_bootstrap.runtime_directory', lambda: directory)
    script = directory / 'rotate-local-service-logs.sh'
    script.write_bytes((REPO / 'scripts/ops/macos/rotate-local-service-logs.sh').read_bytes())
    script.chmod(0o700)
    template = (REPO / 'deploy/launchd/com.guiyi.quant-log-rotate.plist.template').read_text()
    payload = plistlib.loads(template.replace('__HOME__', str(home)).replace('__RUNTIME_DIR__', str(directory))
                           .replace('__LOG_DIR__', str(home / 'Library/Logs/GuiyiQuant')).encode())
    path = agents / 'com.guiyi.quant-log-rotate.plist'
    path.write_bytes(plistlib.dumps(payload))
    path.chmod(0o600)
    label = payload['Label']
    output = f'''gui/{os.getuid()}/{label} = {{
    program = /bin/bash
    state = not running
    working directory = {home}
    arguments = {{
        /bin/bash
        {script}
    }}
    inherited environment = {{
        SSH_AUTH_SOCK => /private/tmp/isolated-agent
    }}
    default environment = {{
        PATH => /usr/bin:/bin:/usr/sbin:/sbin
    }}
    environment = {{
        OSLogRateLimit => 64
        XPC_SERVICE_NAME => {label}
        PATH => {payload['EnvironmentVariables']['PATH']}
    }}
}}'''
    backend = BootstrapBackend()
    backend.candidate_root = REPO
    monkeypatch.setattr(backend, '_launchctl', lambda *_args, **_kwargs: SimpleNamespace(stdout=b'disabled services = {\n}', returncode=0))
    monkeypatch.setattr('app.market_data.captured_recovery_runtime._read_launchd_service', lambda *_args, **_kwargs: output)
    return backend, path, script, output


def test_installed_legacy_log_rotate_freezes_true_unversioned_identity(tmp_path, monkeypatch):
    backend, path, script, _output = host(tmp_path, monkeypatch)
    old = backend.installed()['log-rotate']
    assert old['identity_kind'] == 'legacy_unversioned_log_rotate'
    assert not {'root', 'commit', 'tag'} & old.keys()
    assert old['script_path'] == str(script)
    assert old['script_sha256'] == hashlib.sha256(script.read_bytes()).hexdigest()
    assert old['plist_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert old['loaded_pid'] is None and old['enabled'] is True


@pytest.mark.parametrize('change', ['script', 'argv', 'cwd', 'calendar', 'env', 'running'])
def test_legacy_log_rotate_drift_blocks(tmp_path, monkeypatch, change):
    backend, path, script, output = host(tmp_path, monkeypatch)
    if change == 'script':
        script.write_bytes(b'#!/bin/bash\nexit 0\n')
    elif change == 'running':
        output = output.replace('state = not running', 'state = running\n    pid = 1234')
        monkeypatch.setattr('app.market_data.captured_recovery_runtime._read_launchd_service', lambda *_args, **_kwargs: output)
    else:
        payload = plistlib.loads(path.read_bytes())
        if change == 'argv':
            payload['ProgramArguments'].append('extra')
        elif change == 'cwd':
            payload['WorkingDirectory'] = str(tmp_path)
        elif change == 'calendar':
            payload['StartCalendarInterval']['Hour'] = 4
        else:
            payload['EnvironmentVariables']['GUIYI_PROJECT_ROOT'] = str(REPO)
        path.write_bytes(plistlib.dumps(payload))
    with pytest.raises(BootstrapError, match='BOOTSTRAP_LOG_ROTATE_'):
        backend.installed()


def test_log_rotate_launcher_uses_release_script_without_loading_credentials(tmp_path):
    root = tmp_path / 'release'
    ops = root / 'scripts/ops/macos'
    ops.mkdir(parents=True)
    launcher = ops / 'run-local-service.sh'
    launcher.write_bytes((REPO / 'scripts/ops/macos/run-local-service.sh').read_bytes())
    (ops / 'rotate-local-service-logs.sh').write_text('#!/bin/bash\nprintf exact-release-rotation\n')
    environment = {'PATH': os.environ['PATH'], 'HOME': str(tmp_path), 'GUIYI_PROJECT_ROOT': str(root),
                   'GUIYI_RUNTIME_ENV': str(tmp_path / 'must-not-source.env')}
    Path(environment['GUIYI_RUNTIME_ENV']).write_text('exit 71\n')
    result = subprocess.run(['/bin/bash', str(launcher), 'log-rotate'], env=environment, capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout == 'exact-release-rotation'


@pytest.mark.parametrize('change', ['argv', 'cwd', 'identity', 'missing', 'unknown'])
def test_loaded_legacy_identity_must_match_and_be_observable(tmp_path, monkeypatch, change):
    backend, _path, script, output = host(tmp_path, monkeypatch)
    if change == 'argv':
        output = output.replace(str(script), str(script) + '-other')
    elif change == 'cwd':
        output = output.replace('working directory = ' + str(Path.home()), 'working directory = /private/tmp')
    elif change == 'identity':
        output = output.replace('OSLogRateLimit => 64', 'GUIYI_PROJECT_ROOT => /fake-root')
    elif change == 'missing':
        output = None
    if change == 'unknown':
        def unreadable(*_args, **_kwargs):
            raise ValueError('do not expose host output')
        monkeypatch.setattr('app.market_data.captured_recovery_runtime._read_launchd_service', unreadable)
    else:
        monkeypatch.setattr('app.market_data.captured_recovery_runtime._read_launchd_service', lambda *_args, **_kwargs: output)
    with pytest.raises(BootstrapError, match='^BOOTSTRAP_LOG_ROTATE_IDENTITY_UNPROVEN$'):
        backend.installed()


def test_scheduled_race_after_disable_never_terminates_rotation(tmp_path, monkeypatch):
    backend, _path, _script, _output = host(tmp_path, monkeypatch)
    old = backend.installed()['log-rotate']
    calls = []
    monkeypatch.setattr(backend, '_launchctl', lambda *args, **_kwargs: calls.append(args))
    monkeypatch.setattr(backend, '_pid', lambda _label: 1234)
    with pytest.raises(BootstrapError, match='^BOOTSTRAP_LOG_ROTATE_BUSY$'):
        backend.stop_legacy({'installed': {'log-rotate': old}})
    assert [call[0] for call in calls] == ['disable']


def test_install_promotes_log_rotation_to_exact_candidate_identity(tmp_path, monkeypatch):
    from dataclasses import asdict
    from app.runtime_bindings import CONTRACTS, ServiceBinding, authorized_program_arguments
    backend, path, _script, _output = host(tmp_path, monkeypatch)
    old = backend.installed()['log-rotate']
    binding = ServiceBinding('log-rotate', str(REPO), 'v1.14.11', 'c' * 40, 1, True,
                             {key: 'f' * 64 for key in CONTRACTS})
    backend.install({'candidate_root': str(REPO), 'installed': {'log-rotate': old},
                     'bindings': {'log-rotate': asdict(binding)}})
    payload = plistlib.loads(path.read_bytes())
    assert tuple(payload['ProgramArguments']) == authorized_program_arguments(binding, Path.home())
    assert payload['WorkingDirectory'] == binding.root
    assert payload['EnvironmentVariables']['GUIYI_RUNTIME_COMMIT'] == binding.commit
    assert payload['EnvironmentVariables']['GUIYI_RUNTIME_TAG'] == binding.tag
    assert payload['StartCalendarInterval'] == {'Hour': 3, 'Minute': 15}
    assert 'RunAtLoad' not in payload and 'KeepAlive' not in payload



def test_stop_rotation_requires_strict_loaded_idle_readback(tmp_path, monkeypatch):
    backend, _path, _script, _output = host(tmp_path, monkeypatch)
    old = backend.installed()['log-rotate']
    calls = []
    monkeypatch.setattr(backend, '_launchctl', lambda *args, **_kwargs: calls.append(args))
    monkeypatch.setattr(backend, '_pid', lambda _label: None)
    monkeypatch.setattr('app.market_data.captured_recovery_runtime._read_launchd_service', lambda *_args, **_kwargs: 'unknown')
    with pytest.raises(BootstrapError, match='^BOOTSTRAP_LOG_ROTATE_IDENTITY_UNPROVEN$'):
        backend.stop_legacy({'installed': {'log-rotate': old}})
    assert [call[0] for call in calls] == ['disable']


def test_rotation_starting_after_strict_readback_is_never_killed(tmp_path, monkeypatch):
    backend, _path, _script, _output = host(tmp_path, monkeypatch)
    old = backend.installed()['log-rotate']
    calls = []
    monkeypatch.setattr(backend, '_launchctl', lambda *args, **_kwargs: calls.append(args))
    pids = iter([None, 1234])
    monkeypatch.setattr(backend, '_pid', lambda _label: next(pids))
    with pytest.raises(BootstrapError, match='^BOOTSTRAP_LOG_ROTATE_BUSY$'):
        backend.stop_legacy({'installed': {'log-rotate': old}})
    assert [call[0] for call in calls] == ['disable']
