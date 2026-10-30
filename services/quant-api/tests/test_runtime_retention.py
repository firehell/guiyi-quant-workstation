from pathlib import Path

import pytest

from app.runtime_retention import build_cleanup_plan


class Backend:
    def __init__(self):
        self.references = {}
        self.unknown = False
    def candidate_identity(self, root):
        return {"root": str(root), "commit": "a" * 40, "tag": "v1.2.3"}
    def references_by_root(self, roots):
        if self.unknown:
            raise ValueError("private environment must not escape")
        return {str(root): self.references.get(str(root), []) for root in roots}


def test_exact_cleanup_candidates_with_any_reference_are_retained(tmp_path):
    backend = Backend()
    one, two, three = (tmp_path / name for name in ("binding", "process", "unused"))
    for root in (one, two, three):
        root.mkdir()
    backend.references = {str(one): ["binding:live"], str(two): ["loaded:com.guiyi.quant-alert"]}
    plan = build_cleanup_plan((one, two, three), backend=backend)
    assert plan["dry_run"] is True
    assert [item["status"] for item in plan["targets"]] == ["retained", "retained", "eligible"]
    assert len(plan["plan_sha256"]) == 64


def test_unknown_probe_blocks_cleanup_without_leaking_output(tmp_path):
    backend = Backend()
    backend.unknown = True
    plan = build_cleanup_plan((tmp_path,), backend=backend)
    assert plan["targets"][0]["status"] == "blocked"
    assert "environment must not escape" not in str(plan)


def test_invalid_or_duplicate_target_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        build_cleanup_plan((Path("relative"),), backend=Backend())
    with pytest.raises(ValueError):
        build_cleanup_plan((tmp_path, tmp_path), backend=Backend())


def test_host_reader_keeps_registry_plist_and_loaded_references(tmp_path, monkeypatch):
    import plistlib
    from app.runtime_bindings import BindingRegistry, ServiceBinding, write_bindings
    from app.runtime_retention import RetentionBackend
    monkeypatch.setattr("app.core.env.PROJECT_ROOT", tmp_path)
    root = tmp_path / "release"
    root.mkdir()
    binding = ServiceBinding("live", str(root), "v1.2.3", "a" * 40, 1, False,
        {key: "c" * 64 for key in ("db", "live", "input", "formula", "reference", "launcher")})
    write_bindings(BindingRegistry(1, {"live": binding}), home=tmp_path, expected_sha256=None)
    directory = tmp_path / "Library/LaunchAgents"
    directory.mkdir(parents=True)
    label = binding.label
    (directory / f"{label}.plist").write_bytes(plistlib.dumps({"Label": label,
        "WorkingDirectory": str(root), "ProgramArguments": ["/bin/bash", "/stable/launcher", "live"],
        "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": str(root), "IGNORED_SECRET": "not-for-output"}}))
    backend = RetentionBackend(home=tmp_path)
    def command(args):
        if args[0] == "/bin/launchctl":
            return "PID\tStatus\tLabel\n42\t0\t" + label
        if args[0] == "/usr/sbin/lsof":
            return "p999\nfcwd\nn/unrelated"
        return "999 /usr/bin/python unrelated"
    monkeypatch.setattr(backend, "_command", command)
    observed = (f"{label} = {{\n working directory = {root}\n arguments = {{\n/bin/bash\n/stable/launcher\nlive\n}}\n"
                f"environment = {{\nGUIYI_PROJECT_ROOT => {root}\nIGNORED_SECRET => not-for-output\n}}\n}}")
    monkeypatch.setattr("app.runtime_identity.read_launchd_service", lambda *a, **k: observed)
    references = backend.references_by_root((root,))
    assert references[str(root)] == ["binding:live", f"plist:{label}", f"loaded:{label}"]
    assert "not-for-output" not in str(references)


def test_foreign_repository_worktree_is_never_eligible(tmp_path, monkeypatch):
    from app.runtime_retention import RetentionBackend, RetentionError
    root = tmp_path / "foreign-release"
    root.mkdir()
    (root / ".git").write_text("gitdir: fixture")
    foreign = tmp_path / "foreign-common"
    project = tmp_path / "project-common"
    foreign.mkdir()
    project.mkdir()
    monkeypatch.setattr("app.runtime_retention._git", lambda cwd, *args: str(foreign if cwd == root else project))
    with pytest.raises(RetentionError, match="REPOSITORY_IDENTITY_INVALID"):
        RetentionBackend().candidate_identity(root)


def test_simnow_arguments_are_checked_as_references_without_ignoring_its_label(tmp_path, monkeypatch):
    from app.runtime_retention import RetentionBackend
    monkeypatch.setattr("app.core.env.PROJECT_ROOT", tmp_path)
    root = tmp_path / "release"
    root.mkdir()
    backend = RetentionBackend(home=tmp_path)
    label = "com.guiyi.quant-simnow"
    def command(args):
        if args[0] == "/bin/launchctl":
            return "PID\tStatus\tLabel\n42\t0\t" + label
        if args[0] == "/usr/sbin/lsof":
            return "p99\nfcwd\nn/unrelated"
        return "99 /usr/bin/python unrelated"
    monkeypatch.setattr(backend, "_command", command)
    observed = f"{label} = {{\narguments = {{\n{root}/.sdk/bin/python\n-I\n{root}/scripts/broker/simnow_supervisor.py\n}}\nenvironment = {{\n}}\n}}"
    monkeypatch.setattr("app.runtime_identity.read_launchd_service", lambda *args, **kwargs: observed)
    with pytest.raises(ValueError, match="SIMNOW_CONFIG_UNPROVEN"):
        backend.references_by_root((root,))


def test_native_reader_allows_only_known_simnow_label_and_still_rejects_unknown(tmp_path, monkeypatch):
    import subprocess
    from app import runtime_identity as identity
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "com.guiyi.quant-simnow = {}", "")
    monkeypatch.setattr(identity, "command_result", command)
    assert identity.read_launchd_service("com.guiyi.quant-simnow", root=tmp_path)
    assert calls[-1][-1].endswith("/com.guiyi.quant-simnow")
    before = len(calls)
    with pytest.raises(identity.RuntimeIdentityError):
        identity.read_launchd_service("com.guiyi.quant-unrecognized", root=tmp_path)
    assert len(calls) == before


def _simnow_fixture(tmp_path, monkeypatch, *, installed=True, loaded=True):
    import json
    import plistlib
    from app.runtime_retention import RetentionBackend
    old = tmp_path / 'old'
    old.mkdir()
    current = tmp_path / 'current'
    current.mkdir()
    config = tmp_path / 'trade.private.json'
    config.write_text(json.dumps({'schema': 2, 'account_id': 'a' * 64, 'enabled': True, 'mode': 'trade',
        'project_root': str(current), 'api_env': str(old / '.venv'),
        'sdk_python': str(current / 'python'), 'state_root': str(current / 'state'),
        'state_project_root': str(current)}))
    config.chmod(0o600)
    label = 'com.guiyi.quant-simnow'
    args = ['/usr/bin/python3', '-I', str(current / 'supervisor.py'), '--config', str(config), '--trade']
    if installed:
        directory = tmp_path / 'Library/LaunchAgents'
        directory.mkdir(parents=True)
        (directory / (label + '.plist')).write_bytes(plistlib.dumps({'Label': label, 'ProgramArguments': args}))
    monitor = tmp_path / 'Library/Application Support/GuiyiQuant/simnow-monitor.private.json'
    monitor.parent.mkdir(parents=True)
    monitor_value = json.loads(config.read_text())
    monitor_value['api_env'] = str(current / '.venv')
    monitor.write_text(json.dumps(monitor_value))
    monitor.chmod(0o600)
    backend = RetentionBackend(home=tmp_path)
    monkeypatch.setattr('app.runtime_retention.read_bindings', lambda **kw: None)
    monkeypatch.setattr('app.runtime_retirement.recovery_references', lambda *a: {str(old): []})
    monkeypatch.setattr('app.core.env.PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(backend, 'candidate_identity', lambda root: {'root': str(root)})
    monkeypatch.setattr(backend, '_command', lambda argv: (
        'PID\tStatus\tLabel\n' + ('42\t0\t' + label if loaded else '') if argv[0] == '/bin/launchctl'
        else 'p99\nfcwd\nn/unrelated' if argv[0] == '/usr/sbin/lsof' else '99 python unrelated'))
    monkeypatch.setattr('app.runtime_identity.read_launchd_service', lambda *a, **k:
        label + ' = {\narguments = {\n' + '\n'.join(args) + '\n}\nenvironment = {\n}\n}' if loaded else None)
    return old, config, monitor, backend


@pytest.mark.parametrize('installed,loaded', [(True, False), (False, True), (True, True)])
def test_simnow_private_config_indirect_reference(tmp_path, monkeypatch, installed, loaded):
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch, installed=installed, loaded=loaded)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'retained'


def test_simnow_stable_monitor_indirect_reference(tmp_path, monkeypatch):
    import json
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch, installed=False, loaded=False)
    value = json.loads(monitor.read_text())
    value['api_env'] = str(old / '.venv')
    monitor.write_text(json.dumps(value))
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'retained'


@pytest.mark.parametrize('damage', ['missing', 'symlink', 'hardlink', 'public', 'duplicate', 'parent_symlink'])
def test_simnow_config_unproven_blocks_cleanup(tmp_path, monkeypatch, damage):
    import os
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch)
    if damage == 'missing':
        config.unlink()
    elif damage == 'symlink':
        config.unlink()
        config.symlink_to(monitor)
    elif damage == 'hardlink':
        os.link(config, tmp_path / 'link')
    elif damage == 'public':
        config.chmod(0o644)
    elif damage == 'duplicate':
        config.write_text('{"api_env":"/first","api_env":"/second"}')
    else:
        target = tmp_path / 'real'
        target.mkdir()
        config.rename(target / config.name)
        config.symlink_to(target / config.name)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'blocked'


@pytest.mark.parametrize('switches', [[], ['--config'], ['--config=/somewhere'], ['--config-extra', '/path'], ['--config', '/path', '--config', '/path']])
def test_simnow_unknown_or_duplicate_config_arguments_block(tmp_path, monkeypatch, switches):
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch, installed=False)
    observed = 'com.guiyi.quant-simnow = {\narguments = {\n/python\n' + '\n'.join(switches) + '\n}\nenvironment = {\n}\n}'
    monkeypatch.setattr('app.runtime_identity.read_launchd_service', lambda *a, **k: observed)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'blocked'


def test_simnow_config_read_drift_blocks_cleanup(tmp_path, monkeypatch):
    from app import runtime_identity
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch)
    original = runtime_identity.file_snapshot
    reads = 0
    def changing(path, **kwargs):
        nonlocal reads
        if path == config:
            reads += 1
            if reads == 2:
                config.write_text('{"project_root":"/unrelated"}')
        return original(path, **kwargs)
    monkeypatch.setattr(runtime_identity, 'file_snapshot', changing)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'blocked'


@pytest.mark.parametrize('damage', ['missing', 'symlink', 'unreadable'])
def test_simnow_monitor_missing_or_unproven_blocks(tmp_path, monkeypatch, damage):
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch)
    monitor.unlink()
    if damage == 'symlink':
        monitor.symlink_to(config)
    elif damage == 'unreadable':
        monitor.write_text('{}')
        monitor.chmod(0o000)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'blocked'


@pytest.mark.parametrize('stage', ['START_REQUESTED', 'COMPLETE', 'RECOVERED'])
def test_unproved_simnow_intents_never_release_dependencies(tmp_path, monkeypatch, stage):
    import json
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch, installed=False, loaded=False)
    intent = tmp_path / 'output/simnow-switch/switch-intent.private.json'
    intent.parent.mkdir(parents=True)
    intent.write_text(json.dumps({'stage': stage, 'snapshot': {'old_root': str(old)}}))
    intent.chmod(0o600)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] != 'eligible'


def _closed_simnow_intent(tmp_path, old, *, late=False):
    import hashlib
    import json
    from app.runtime_retention import _hash
    folder = tmp_path / 'output/simnow-switch'
    folder.mkdir(parents=True)
    def write(name, value):
        path = folder / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    candidate = dict(root=str(tmp_path / 'current'), tag='v1.2.3', commit='a' * 40,
        annotated_exact=True, clean=True, sdk_check=True, preflight_valid=True,
        identities={key: 'a' * 64 for key in ('code', 'sdk', 'config', 'plist', 'old_config', 'old_plist', 'monitor')})
    snapshot = {'candidate': candidate,
                'host': {'pid': 10, 'run_id': 'old'}, 'preimage': {'old_root': str(old)}}
    plan = {'schema': 'simnow_trade_switch_plan_v7', 'snapshot': snapshot,
            'created_at': 0, 'expires_at': 60, 'execution_permitted': False, 'broker_io': False}
    plan['plan_hash'] = _hash(plan)
    plan_path = write('switch-plan.private.json', plan)
    value = {'schema': plan['schema'], 'plan_hash': plan['plan_hash'], 'snapshot': snapshot,
             'stage': 'COMPLETE', 'result': 'HOST_SWITCH_VERIFIED',
             'pid': 20, 'run_id': 'new', 'native_recovery_complete': False}
    if late:
        value['result'] = 'HOST_SWITCH_LATE_VERIFIED'
        value['error'] = 'READBACK_UNPROVEN'
        before = dict(value, stage='VERIFYING', result='UNKNOWN')
        before_path = write('late-started-beforeimage.private.json', before)
        proof = dict(pid=20, run_id='new', mode='trade', opening_enabled=False,
                     **{key: True for key in ('verified', 'dual_locks_held_by_pid',
                        'config_bound', 'monitor_bound', 'account_takeover_pending')})
        receipt = {'schema': 'simnow_late_started_reconciliation_v1',
            'original_intent_sha256': digest(before_path), 'original_plan_sha256': digest(plan_path),
            'plan_hash': plan['plan_hash'], 'target': snapshot['candidate'],
            'proofs': [proof, proof], 'runtime_restart': False}
        receipt_path = write('late-started-receipt.private.json', receipt)
        write('late-started-reconciliation-claim.private.json',
              {'source_sha256': digest(before_path), 'receipt_hash': _hash(receipt)})
        value['initial_failure'] = {'path': str(before_path), 'sha256': digest(before_path)}
        value['reconciliation_receipt'] = {'path': str(receipt_path), 'sha256': digest(receipt_path)}
    return write('switch-intent.private.json', value)


@pytest.mark.parametrize('late', [False, True])
def test_proven_completed_simnow_intent_is_history_not_permanent_pin(tmp_path, monkeypatch, late):
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch, installed=False, loaded=False)
    _closed_simnow_intent(tmp_path, old, late=late)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'eligible'


@pytest.mark.parametrize('artifact', ['switch-plan.private.json', 'late-started-receipt.private.json',
    'late-started-beforeimage.private.json', 'late-started-reconciliation-claim.private.json'])
def test_tampered_completed_simnow_chain_blocks(tmp_path, monkeypatch, artifact):
    import json
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch, installed=False, loaded=False)
    intent = _closed_simnow_intent(tmp_path, old, late=True)
    path = intent.parent / artifact
    value = json.loads(path.read_bytes())
    value['changed'] = True
    path.write_text(json.dumps(value))
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'blocked'


@pytest.mark.parametrize('field', ['project_root', 'api_env', 'sdk_python', 'state_root',
    'state_project_root', 'ordinary_takeover_permit', 'deployment_connection_permit'])
def test_all_simnow_path_fields_pin_old_tree(tmp_path, monkeypatch, field):
    import json
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch)
    value = json.loads(config.read_text())
    value['api_env'] = str(tmp_path / 'current/.venv')
    value[field] = str(old / 'dependency')
    config.write_text(json.dumps(value))
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'retained'


def test_simnow_monitor_drift_during_probe_blocks(tmp_path, monkeypatch):
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch)
    original = backend._command
    def changing(argv):
        if argv[0] == '/bin/ps':
            monitor.write_text('{"project_root":"/changed"}')
        return original(argv)
    monkeypatch.setattr(backend, '_command', changing)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'blocked'


@pytest.mark.parametrize('damage', ['empty', 'schema', 'unknown', 'missing_path'])
def test_unknown_or_incomplete_simnow_structure_blocks(tmp_path, monkeypatch, damage):
    import json
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch)
    value = json.loads(config.read_text())
    if damage == 'empty':
        value = {}
    elif damage == 'schema':
        value['schema'] = 99
    elif damage == 'unknown':
        value['alternate_api_env'] = str(old)
    else:
        value.pop('sdk_python')
    config.write_text(json.dumps(value))
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'blocked'


def test_tampered_normal_terminal_cannot_close_simnow_intent(tmp_path, monkeypatch):
    import json
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch, installed=False, loaded=False)
    intent = _closed_simnow_intent(tmp_path, old)
    value = json.loads(intent.read_text())
    value['native_recovery_complete'] = True
    intent.write_text(json.dumps(value))
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'blocked'


def test_pending_simnow_intent_preserves_non_ascii_root(tmp_path, monkeypatch):
    import json
    home = tmp_path / '扩展盘'
    home.mkdir()
    old, config, monitor, backend = _simnow_fixture(home, monkeypatch, installed=False, loaded=False)
    intent = home / 'output/simnow-switch/switch-intent.private.json'
    intent.parent.mkdir(parents=True)
    intent.write_text(json.dumps({'stage': 'START_REQUESTED', 'snapshot': {'old_root': str(old)}}))
    intent.chmod(0o600)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'retained'


@pytest.mark.parametrize('intermediate', [False, True])
def test_simnow_api_env_alias_preserves_real_target(tmp_path, monkeypatch, intermediate):
    import json
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch)
    (old / '.venv').mkdir()
    alias = tmp_path / 'api-alias'
    alias.symlink_to(old if intermediate else old / '.venv', target_is_directory=True)
    value = json.loads(config.read_text())
    value['api_env'] = str(alias / '.venv' if intermediate else alias)
    config.write_text(json.dumps(value))
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'retained'


@pytest.mark.parametrize('intermediate', [False, True])
def test_simnow_api_env_alias_target_drift_blocks(tmp_path, monkeypatch, intermediate):
    import json
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch)
    (old / '.venv').mkdir()
    destination = tmp_path / 'current'
    (destination / '.venv').mkdir()
    alias = tmp_path / 'api-alias'
    alias.symlink_to(old if intermediate else old / '.venv', target_is_directory=True)
    value = json.loads(config.read_text())
    value['api_env'] = str(alias / '.venv' if intermediate else alias)
    config.write_text(json.dumps(value))
    original = backend._command
    def changing(argv):
        if argv[0] == '/bin/ps':
            alias.unlink()
            alias.symlink_to(destination if intermediate else destination / '.venv', target_is_directory=True)
        return original(argv)
    monkeypatch.setattr(backend, '_command', changing)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'blocked'


def test_simnow_state_directory_content_updates_are_not_path_drift(tmp_path, monkeypatch):
    import json
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch)
    state = tmp_path / 'current/state'
    state.mkdir()
    value = json.loads(config.read_text())
    value['state_root'] = str(state)
    config.write_text(json.dumps(value))
    original = backend._command
    def changing(argv):
        if argv[0] == '/bin/ps':
            (state / 'new-journal').write_text('new natural state')
        return original(argv)
    monkeypatch.setattr(backend, '_command', changing)
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'retained'


def test_simnow_alias_chain_keeps_intermediate_release_dependency(tmp_path, monkeypatch):
    import json
    old, config, monitor, backend = _simnow_fixture(tmp_path, monkeypatch)
    destination = tmp_path / 'current/.venv'
    destination.mkdir()
    (old / '.venv').symlink_to(destination, target_is_directory=True)
    alias = tmp_path / 'api-alias'
    alias.symlink_to(old / '.venv', target_is_directory=True)
    value = json.loads(config.read_text())
    value['api_env'] = str(alias)
    config.write_text(json.dumps(value))
    assert build_cleanup_plan((old,), backend=backend)['targets'][0]['status'] == 'retained'
