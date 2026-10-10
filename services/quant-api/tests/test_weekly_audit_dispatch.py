from dataclasses import asdict, replace
import hashlib
import os
from pathlib import Path
import plistlib
import subprocess

import pytest

from app.runtime_bindings import CONTRACTS, ServiceBinding, authorized_program_arguments
from app.runtime_bootstrap import BootstrapBackend
from app.runtime_scheduled import ScheduledBackend

REPO = Path(__file__).resolve().parents[3]


def binding(root, service='weekly-audit'):
    return ServiceBinding(service, str(root), 'v1.14.16', 'a' * 40, 2, True, {key: 'b' * 64 for key in CONTRACTS})


@pytest.mark.parametrize('service,argument', [('weekly-audit', 'weekly-audit-scheduled'),
    ('after-market', 'after-market'), ('late-provider-recovery', 'late-provider-recovery'), ('log-rotate', 'log-rotate')])
def test_formal_scheduled_service_uses_unique_dispatch_mapping(tmp_path, service, argument):
    args = authorized_program_arguments(binding(tmp_path, service), tmp_path)
    assert args == ('/bin/bash', str(tmp_path / 'Library/Application Support/GuiyiQuant/run-local-service.sh'), argument)


def test_candidate_dispatch_identity_does_not_change(tmp_path):
    candidate = replace(binding(tmp_path), launchd_label='com.guiyi.quant-weekly-audit-candidate-' + 'c' * 32)
    assert authorized_program_arguments(candidate, tmp_path)[2:] == ('handover-candidate', 'weekly-audit', 'c' * 32, '2')


def host(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    root = tmp_path / 'release'
    agents = home / 'Library/LaunchAgents'
    runtime = home / 'Library/Application Support/GuiyiQuant'
    agents.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (root / 'scripts/ops/macos').mkdir(parents=True)
    (root / 'scripts/ops/macos/runtime-service-dispatch.sh').write_text('#!/bin/bash\nexit 0\n')
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.setattr('app.runtime_bootstrap.runtime_directory', lambda: runtime)
    monkeypatch.setattr('app.runtime_scheduled.runtime_directory', lambda: runtime)
    previous = replace(binding(root), generation=1)
    payload = {'Label': previous.label, 'WorkingDirectory': str(root), 'EnvironmentVariables': {'PATH': '/usr/bin:/bin'},
               'ProgramArguments': ['/bin/bash', str(runtime / 'run-local-service.sh'), 'weekly-audit'],
               'StartCalendarInterval': [{'Weekday': 6, 'Hour': 16, 'Minute': 0}]}
    content = plistlib.dumps(payload)
    path = agents / (previous.label + '.plist')
    path.write_bytes(content)
    path.chmod(0o600)
    return root, path, previous, {'plist_sha256': hashlib.sha256(content).hexdigest()}


def test_scheduled_writer_and_reader_share_formal_arguments(tmp_path, monkeypatch):
    root, path, previous, preimage = host(tmp_path, monkeypatch)
    candidate = binding(root)
    ScheduledBackend().install(previous, candidate, preimage)
    payload = plistlib.loads(path.read_bytes())
    assert tuple(payload['ProgramArguments']) == authorized_program_arguments(candidate, Path.home())
    assert payload['ProgramArguments'][-1] == 'weekly-audit-scheduled'
    assert payload.get('RunAtLoad', False) is False and payload.get('KeepAlive', False) is False


def test_first_topology_writer_uses_same_scheduled_arguments(tmp_path, monkeypatch):
    root, path, _previous, preimage = host(tmp_path, monkeypatch)
    candidate = binding(root)
    BootstrapBackend().install({'candidate_root': str(root), 'installed': {'weekly-audit':
        {'label': candidate.label, 'plist_sha256': preimage['plist_sha256']}},
        'bindings': {'weekly-audit': asdict(candidate)}})
    assert tuple(plistlib.loads(path.read_bytes())['ProgramArguments']) == authorized_program_arguments(candidate, Path.home())


def test_formal_weekly_launch_reaches_scheduled_runtime_entry(tmp_path):
    root = tmp_path / 'release'
    ops = root / 'scripts/ops/macos'
    python = root / 'services/quant-api/.venv/bin/python'
    ops.mkdir(parents=True)
    python.parent.mkdir(parents=True)
    launcher = ops / 'run-local-service.sh'
    launcher.write_bytes((REPO / 'scripts/ops/macos/run-local-service.sh').read_bytes())
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    python.chmod(0o700)
    arguments = authorized_program_arguments(binding(root), tmp_path)
    env = {'PATH': os.environ['PATH'], 'HOME': str(tmp_path), 'GUIYI_PROJECT_ROOT': str(root),
           'GUIYI_RUNTIME_ENV': str(tmp_path / 'absent.env'), 'POSTGRES_PASSWORD': 'isolated_test_only'}
    result = subprocess.run(['/bin/bash', str(launcher), arguments[-1]], env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.splitlines() == ['-m', 'app.runtime_entry', 'weekly-audit-scheduled']
