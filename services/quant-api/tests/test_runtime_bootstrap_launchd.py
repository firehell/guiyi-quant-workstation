from pathlib import Path
import hashlib
import os
import plistlib
from types import SimpleNamespace

import pytest

from app.runtime_bootstrap import BootstrapBackend, BootstrapError, parse_disabled_states


@pytest.mark.parametrize('value,disabled', [('disabled', True), ('enabled', False), ('true', True), ('false', False)])
def test_disabled_states_actual_and_legacy_values(value, disabled):
    assert parse_disabled_states(f'disabled services = {{\n "com.guiyi.quant-web" => {value}\n}}'.encode()) == {'com.guiyi.quant-web': disabled}


@pytest.mark.parametrize('output', [b'', b'garbage', b'disabled services = {\n"x" => unknown\n}',
    b'disabled services = {\n"x" => disabled\n"x" => enabled\n}'])
def test_disabled_states_unknown_or_duplicate_is_not_absence(output):
    with pytest.raises(BootstrapError, match='DISABLED_STATE_UNPROVEN'):
        parse_disabled_states(output)


def frozen_host(tmp_path, monkeypatch, service='live'):
    home = tmp_path / 'home'
    root = tmp_path / 'release'
    agents = home / 'Library/LaunchAgents'
    agents.mkdir(parents=True)
    root.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)
    directory = home / 'Library/Application Support/GuiyiQuant'
    monkeypatch.setattr('app.runtime_bootstrap.runtime_directory', lambda: directory)
    label = 'com.guiyi.quant-' + service
    cwd = home if service in ('api', 'web') else root
    args = ['/bin/bash', str(directory / 'run-local-service.sh'), service]
    payload = {'Label': label, 'WorkingDirectory': str(cwd), 'ProgramArguments': args,
               'EnvironmentVariables': {'GUIYI_PROJECT_ROOT': str(root), 'GUIYI_RUNTIME_COMMIT': 'a' * 40}}
    content = plistlib.dumps(payload)
    path = agents / (label + '.plist')
    path.write_bytes(content)
    path.chmod(0o600)
    old = {'root': str(root), 'commit': 'a' * 40, 'tag': 'v1.14.9', 'label': label,
           'loaded_pid': '101', 'plist_sha256': hashlib.sha256(content).hexdigest(), 'enabled': True}
    def output(pid):
        return f'''gui/{os.getuid()}/{label} = {{
 state = running
 pid = {pid}
 working directory = {cwd}
 arguments = {{
 {args[0]}
 {args[1]}
 {args[2]}
 }}
 environment = {{
 GUIYI_PROJECT_ROOT => {root}
 GUIYI_RUNTIME_COMMIT => {'a' * 40}
 }}
}}'''
    backend = BootstrapBackend()
    backend._transport_guards_held = True
    calls, proofs = [], []
    observed = [output(101), output(202)]
    def loaded(*_args, **_kwargs):
        return observed.pop(0) if observed else None
    monkeypatch.setattr('app.market_data.captured_recovery_runtime._read_launchd_service', loaded)
    monkeypatch.setattr(backend, '_launchctl', lambda *args, **_kwargs: calls.append(args) or SimpleNamespace(returncode=0,stdout=b''))
    monkeypatch.setattr(backend, 'prove_no_inflight_sends', lambda: proofs.append('idle'))
    monkeypatch.setattr(backend, '_process_alive', lambda _pid: False)
    monkeypatch.setattr('app.runtime_bootstrap.os.kill', lambda pid, sig: calls.append(('signal', pid, sig)))
    return backend, old, calls, proofs, observed, output, path


def test_keepalive_revival_does_not_wait_for_or_signal_new_pid(tmp_path, monkeypatch):
    backend, old, calls, proofs, *_ = frozen_host(tmp_path, monkeypatch)
    backend.stop_legacy({'installed': {'live': old}})
    assert [item[0] for item in calls] == ['disable', 'signal', 'bootout']
    assert calls[1][1] == 101
    assert calls[1][2] == 15
    assert len(proofs) >= 2


def test_revival_identity_drift_is_not_unloaded(tmp_path, monkeypatch):
    backend, old, calls, _proofs, observed, output, _path = frozen_host(tmp_path, monkeypatch)
    observed[-1] = output(202).replace('GUIYI_RUNTIME_COMMIT => ' + 'a' * 40, 'GUIYI_RUNTIME_COMMIT => ' + 'b' * 40)
    with pytest.raises(BootstrapError, match='LEGACY_IDENTITY_UNPROVEN'):
        backend.stop_legacy({'installed': {'live': old}})
    assert 'bootout' not in [item[0] for item in calls]


def test_business_stop_requires_full_transport_guards(tmp_path, monkeypatch):
    backend, old, calls, *_ = frozen_host(tmp_path, monkeypatch)
    backend._transport_guards_held = False
    with pytest.raises(BootstrapError, match='SEND_GUARDS_REQUIRED'):
        backend.stop_legacy({'installed': {'live': old}})
    assert calls == []


def test_page_stop_has_no_transport_signal_and_requires_pid_exit(tmp_path, monkeypatch):
    backend, old, calls, _proofs, observed, *_ = frozen_host(tmp_path, monkeypatch, 'web')
    observed[:] = observed[:1]
    backend.stop_legacy({'installed': {'web': old}})
    assert [item[0] for item in calls] == ['disable', 'bootout']



def test_original_process_not_exited_never_boots_out_successor(tmp_path, monkeypatch):
    backend, old, calls, *_ = frozen_host(tmp_path, monkeypatch)
    monkeypatch.setattr(backend, '_process_alive', lambda _pid: True)
    ticks = iter([0, 11])
    monkeypatch.setattr('app.runtime_bootstrap.monotonic', lambda: next(ticks))
    with pytest.raises(BootstrapError, match='LEGACY_DRAIN_UNPROVEN'):
        backend.stop_legacy({'installed': {'live': old}})
    assert [item[0] for item in calls] == ['disable', 'signal']


def test_readonly_pid_probe_failure_is_not_exited(monkeypatch):
    def denied(*_args):
        raise PermissionError('private')
    monkeypatch.setattr('app.runtime_bootstrap.os.kill', denied)
    with pytest.raises(BootstrapError, match='^BOOTSTRAP_PROCESS_STATE_UNPROVEN$'):
        BootstrapBackend()._process_alive(101)


@pytest.mark.parametrize('body', ['state = running', 'state = not running\n pid = 101', 'state = running\n pid = 101\n pid = 202', 'state = mystery'])
def test_pid_requires_exact_unambiguous_service_shape(monkeypatch, body):
    output = f'gui/{os.getuid()}/com.guiyi.quant-live = {{\n{body}\n}}'
    monkeypatch.setattr('app.market_data.captured_recovery_runtime._read_launchd_service', lambda *_args, **_kwargs: output)
    with pytest.raises(BootstrapError, match='^BOOTSTRAP_PROCESS_STATE_UNPROVEN$'):
        BootstrapBackend()._pid('com.guiyi.quant-live')
