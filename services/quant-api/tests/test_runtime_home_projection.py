"""Optional home recovery lifecycle; no installed services or production state."""
from dataclasses import replace
import io
import json
from pathlib import Path
import plistlib
import sys
from types import ModuleType

import pytest

from app.runtime_bindings import (
    BindingRegistry, RuntimeBindingError, authorized_program_arguments,
    pinned_release_roots, read_bindings, write_bindings,
)
from app.runtime_cohort import continuous_services, freeze_cohort, validate
from app.runtime_contracts import OPTIONAL_CONTINUOUS, REQUIRED_SERVICES, SERVICES
from test_runtime_cohort import Host


def test_old_registry_remains_valid_without_optional_service(tmp_path):
    host = Host(tmp_path)
    assert set(host.old.services) == REQUIRED_SERVICES
    plan = freeze_cohort(host, candidate_root=host.root, tag='v1.16.5', commit='e' * 40)
    old, new = validate(plan, host.now())
    assert 'home-projection' not in old.services
    assert 'home-projection' not in new.services
    assert 'home-projection' not in continuous_services(new)
    write_bindings(old, home=tmp_path, expected_sha256=None)
    assert read_bindings(home=tmp_path) == old


@pytest.mark.parametrize('enabled', [False, True])
def test_explicit_optional_binding_keeps_activation_and_release_identity(tmp_path, enabled):
    host = Host(tmp_path)
    home = replace(host.old.services['api'], service='home-projection', enabled=enabled)
    host.old = host.registry = BindingRegistry(1, {**host.old.services, 'home-projection': home})
    plan = freeze_cohort(host, candidate_root=host.root, tag='v1.16.5', commit='e' * 40)
    old, new = validate(plan, host.now())
    assert new.services['home-projection'].enabled is enabled
    assert new.services['home-projection'].generation == home.generation + 1
    assert new.services['home-projection'].commit == 'e' * 40
    assert ('home-projection' in continuous_services(new)) is enabled
    write_bindings(old, home=tmp_path, expected_sha256=None)
    assert pinned_release_roots(home=tmp_path) == frozenset({Path(home.root)})
    assert authorized_program_arguments(home, tmp_path)[-1] == 'home-projection'


def test_unknown_service_is_still_rejected(tmp_path):
    assert SERVICES == REQUIRED_SERVICES | OPTIONAL_CONTINUOUS
    host = Host(tmp_path)
    with pytest.raises(RuntimeBindingError):
        replace(host.old.services['api'], service='home-projection-unknown')


@pytest.mark.parametrize('supervised', [False, True])
def test_runtime_entry_passes_owner_and_cooperative_stop_without_running_worker(monkeypatch, supervised):
    from app import runtime_entry

    module = ModuleType('app.market_data.newow.home_recovery')
    calls = []
    module.run_home_recovery_forever = lambda **kwargs: calls.append(kwargs)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    owner = type('Owner', (), {
        'assert_owned': lambda self: None,
        'mark_ready': lambda self: None,
    })()
    def should_stop():
        return True
    monkeypatch.setattr(runtime_entry, '_owned_runner', lambda name, run: (
        calls.append(name), run(owner, should_stop)
    ))
    monkeypatch.setenv('GUIYI_RUNTIME_HANDOVER_ENABLED', '1' if supervised else '0')
    output = io.StringIO()
    assert runtime_entry.main(['home-projection'], stdout=output, stderr=io.StringIO()) == 0
    assert json.loads(output.getvalue())['command'] == 'runtime.home-projection'
    if supervised:
        assert calls == ['home-projection', {
            'assert_owned': owner.assert_owned, 'stop_requested': should_stop,
            'mark_ready': owner.mark_ready,
        }]
    else:
        assert calls == [{}]


def test_candidate_warmup_only_checks_runner_contract(monkeypatch):
    from app.runtime_deployment import warmup_service

    module = ModuleType('app.market_data.newow.home_recovery')
    module.run_home_recovery_forever = lambda **kwargs: pytest.fail('warmup must not run worker')
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert warmup_service('home-projection') == {'runner_available': True}


def test_template_and_launcher_are_optional_and_use_exact_service_identity():
    root = Path(__file__).resolve().parents[3]
    template = root / 'deploy/launchd/com.guiyi.quant-home-projection.plist.template'
    payload = plistlib.loads(template.read_bytes())
    assert payload['Label'] == 'com.guiyi.quant-home-projection'
    assert payload['ProgramArguments'][-1] == 'home-projection'
    assert payload['KeepAlive'] is True
    assert payload['RunAtLoad'] is True
    assert payload['EnvironmentVariables']['GUIYI_PROJECT_ROOT'] == '__PROJECT_ROOT__'
    assert payload['EnvironmentVariables']['GUIYI_RUNTIME_COMMIT'] == '__RUNTIME_COMMIT__'
    installer = (root / 'scripts/ops/macos/install-local-services.sh').read_text()
    base = installer.split('base_labels=(', 1)[1].split(')', 1)[0]
    assert 'home-projection' not in base
    assert '--confirm-home-projection' in installer
    launcher = (root / 'scripts/ops/macos/run-local-service.sh').read_text()
    home_branch = launcher.split('  home-projection)', 1)[1].split(';;', 1)[0]
    assert '-m app.runtime_entry home-projection' in home_branch


def test_cohort_start_and_readiness_include_only_explicit_enabled_home(tmp_path, monkeypatch):
    from app.runtime_cohort_host import CohortHost

    host = Host(tmp_path)
    home = replace(host.old.services['api'], service='home-projection', enabled=True)
    host.old = host.registry = BindingRegistry(1, {**host.old.services, 'home-projection': home})
    plan = freeze_cohort(host, candidate_root=host.root, tag='v1.16.5', commit='e' * 40)
    actual = object.__new__(CohortHost)
    started = []
    actual.start = lambda binding: started.append(binding.service)
    actual.start_consumers(plan)
    assert 'home-projection' in started
    assert 'market-feed' not in started
    actual._await_names = lambda _plan, names, _proof, _seconds: tuple(names)
    assert 'home-projection' in actual.consumers_ready(plan, {})


def test_home_retention_pins_registry_plist_and_loaded_root(tmp_path, monkeypatch):
    from app.runtime_retention import RetentionBackend

    monkeypatch.setattr('app.core.env.PROJECT_ROOT', tmp_path)
    host = Host(tmp_path)
    home = replace(host.old.services['api'], service='home-projection', enabled=True)
    root = Path(home.root)
    write_bindings(BindingRegistry(1, {'home-projection': home}), home=tmp_path, expected_sha256=None)
    directory = tmp_path / 'Library/LaunchAgents'
    directory.mkdir(parents=True)
    (directory / f'{home.label}.plist').write_bytes(plistlib.dumps({
        'Label': home.label, 'WorkingDirectory': str(root),
        'ProgramArguments': ['/bin/bash', '/stable/launcher', home.service],
        'EnvironmentVariables': {'GUIYI_PROJECT_ROOT': str(root)},
    }))
    backend = RetentionBackend(home=tmp_path)

    def command(args):
        if args[0] == '/bin/launchctl':
            return 'PID\tStatus\tLabel\n42\t0\t' + home.label
        if args[0] == '/usr/sbin/lsof':
            return 'p999\nfcwd\nn/unrelated'
        return '999 /usr/bin/python unrelated'

    monkeypatch.setattr(backend, '_command', command)
    observed = (
        f'{home.label} = {{\n working directory = {root}\n arguments = {{\n'
        f'/bin/bash\n/stable/launcher\n{home.service}\n}}\n'
        f'environment = {{\nGUIYI_PROJECT_ROOT => {root}\n}}\n}}'
    )
    monkeypatch.setattr('app.runtime_identity.read_launchd_service', lambda *a, **k: observed)
    assert backend.references_by_root((root,))[str(root)] == [
        'binding:home-projection', f'plist:{home.label}', f'loaded:{home.label}',
    ]


def test_home_health_disabled_absence_and_unverified_marker_are_distinct(tmp_path):
    from app.services.deployment_identity import deployment_identity_health

    (tmp_path / 'Library/LaunchAgents').mkdir(parents=True)
    kwargs = dict(root=tmp_path, commit='a' * 40, home=tmp_path, service_reader=lambda *a, **k: None)
    assert deployment_identity_health(**kwargs)['services']['home-projection']['status'] == 'disabled'
    (tmp_path / '.run').mkdir()
    (tmp_path / '.run/home-projection-enabled').write_text('enabled\n')
    assert deployment_identity_health(**kwargs)['services']['home-projection']['status'] == 'unknown'


def test_home_diagnostics_use_bounded_rotated_service_log(tmp_path, monkeypatch):
    from app import runtime_logging

    paths = []
    import logging
    handler = logging.NullHandler()
    monkeypatch.setenv('GUIYI_LOG_DIR', str(tmp_path))
    monkeypatch.setattr(runtime_logging, 'runtime_diagnostic_handler', lambda path: paths.append(path) or handler)
    try:
        assert runtime_logging.install_runtime_diagnostics('home-projection') is handler
        assert paths == [tmp_path / 'home-projection.log']
    finally:
        logging.getLogger('app').removeHandler(handler)


def test_home_selective_release_plan_requires_cohort_and_apply_has_no_side_effects(tmp_path, monkeypatch):
    from app import runtime_bindings, runtime_deployment

    host = Host(tmp_path)
    home = replace(host.old.services['api'], service='home-projection', enabled=True)
    current = BindingRegistry(1, {**host.old.services, 'home-projection': home})
    monkeypatch.setattr(runtime_bindings, 'verify_release', lambda *args: None)
    monkeypatch.setattr(runtime_bindings, 'contract_fingerprints', lambda root: dict(home.contracts))
    monkeypatch.setattr(runtime_bindings, '_tracked', lambda root: {
        'services/quant-api/app/market_data/newow/home_recovery.py':
            'old' if root == Path(home.root) else 'new',
    })
    plan = runtime_bindings.build_release_plan(
        current, candidate_root=host.root, tag='v1.16.5', commit='e' * 40,
        registry_sha256='c' * 64,
    )
    assert plan['status'] == 'blocked'
    assert {'service': 'home-projection', 'code': 'COHORT_REQUIRED'} in plan['blocked']
    monkeypatch.setattr(runtime_deployment, 'assert_no_unknown_deployment', lambda: None)
    monkeypatch.setattr(runtime_deployment, 'read_bindings', lambda: current)
    monkeypatch.setattr(runtime_deployment, 'bindings_sha256', lambda: 'c' * 64)
    monkeypatch.setattr(runtime_deployment, 'LaunchdBackend', lambda: pytest.fail('blocked plan must not prepare jobs'))
    with pytest.raises(runtime_deployment.DeploymentError, match='RELEASE_PLAN_DRIFT_OR_BLOCKED'):
        runtime_deployment.apply_plan(plan)


def test_native_home_selective_candidate_rejects_before_any_launch_or_state_write(tmp_path, monkeypatch):
    from app import runtime_deployment

    host = Host(tmp_path)
    binding = replace(host.old.services['api'], service='home-projection', enabled=True)
    monkeypatch.setattr(runtime_deployment, '_launchctl', lambda *args: pytest.fail('no launchctl'))
    monkeypatch.setattr(runtime_deployment, '_write', lambda *args: pytest.fail('no state write'))
    monkeypatch.setattr(runtime_deployment, 'resolve_service_binding', lambda *args: pytest.fail('no candidate resolution'))
    with pytest.raises(runtime_deployment.DeploymentError, match='SERVICE_HANDOVER_UNSUPPORTED'):
        runtime_deployment.LaunchdBackend().prepare('home-projection', binding, 'a' * 32)
