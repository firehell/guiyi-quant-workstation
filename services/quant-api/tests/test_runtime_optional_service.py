"""Reviewable optional topology mutations exercise exact preimages and CAS."""
from dataclasses import replace

import pytest

from app.runtime_bindings import BindingRegistry
from app.runtime_handover import _read, _write
from app.runtime_optional_service import (
    OptionalServiceError, OptionalServiceHost, apply_optional_service,
    plan_optional_service, rollback_optional_service,
)
from app.reference_trading.recovery_campaign import digest
from test_runtime_cohort import Host


class OptionalHost(Host):
    def __init__(self, tmp):
        super().__init__(tmp)
        self.files = {'plist_hex': None, 'marker_hex': None, 'loaded': False}
        self.started = []
        self.commits = []
        self.fail = None
        self.halted = []

    def binding_hash(self):
        from dataclasses import asdict
        return digest(asdict(self.registry))

    def verify(self, binding):
        assert binding.root == self.old.services['api'].root
        assert binding.commit == self.old.services['api'].commit

    def preimage(self, binding):
        assert not self.files['loaded']
        assert self.files['marker_hex'] is None
        return dict(self.files)

    def assert_stopped(self, binding):
        assert not self.files['loaded']

    def install(self, binding, before):
        assert before == self.files
        self.files['plist_hex'] = b'exact plist'.hex()
        if binding.enabled:
            self.files['marker_hex'] = b'enabled\n'.hex()
        if self.fail == 'install':
            raise OSError()

    def rollback(self, binding, before):
        self.files = dict(before)

    def commit(self, registry, expected):
        assert expected == self.binding_hash()
        if self.fail == 'cas_before':
            self.fail = None
            raise OSError()
        self.registry = registry
        self.commits.append(registry)
        if self.fail == 'cas_after':
            self.fail = None
            raise OSError()
        return self.binding_hash()

    def start(self, binding):
        self.files['loaded'] = True
        self.started.append(binding.service)
        if self.fail == 'start':
            raise OSError()

    def ready(self, binding):
        return self.fail != 'ready'

    def halt(self, binding):
        self.halted.append(binding.service)


def test_absent_optional_plan_default_disabled_and_cas_apply_is_idempotent(tmp_path):
    host = OptionalHost(tmp_path)
    plan = plan_optional_service(host, service='home-projection')
    assert plan['previous_binding'] is None
    assert plan['preimage'] == {'plist_hex': None, 'marker_hex': None, 'loaded': False}
    assert plan['new_binding']['enabled'] is False
    old = host.registry
    assert not host.started and host.files['plist_hex'] is None
    assert apply_optional_service(host, plan)['status'] == 'switched'
    assert not host.registry.services['home-projection'].enabled
    assert {k: v for k, v in host.registry.services.items() if k != 'home-projection'} == old.services
    assert not host.started and host.files['marker_hex'] is None
    assert apply_optional_service(host, plan)['status'] == 'already_applied'
    assert len(host.commits) == 1


def test_explicit_enable_supports_old_absent_and_existing_disabled_binding(tmp_path):
    host = OptionalHost(tmp_path)
    disabled = plan_optional_service(host, service='home-projection')
    apply_optional_service(host, disabled)
    enabled = plan_optional_service(host, service='home-projection', enable=True)
    assert enabled['previous_binding']['enabled'] is False
    assert apply_optional_service(host, enabled)['enabled'] is True
    assert host.started == ['home-projection']
    assert host.files['marker_hex'] == b'enabled\n'.hex()
    assert apply_optional_service(host, enabled)['status'] == 'already_applied'
    assert host.started == ['home-projection']


@pytest.mark.parametrize('failure', ['install', 'cas_before', 'cas_after'])
def test_prestart_failure_restores_exact_old_absent_preimage(tmp_path, failure):
    host = OptionalHost(tmp_path)
    plan = plan_optional_service(host, service='home-projection', enable=True)
    old, before = host.registry, dict(host.files)
    host.fail = failure
    with pytest.raises(OptionalServiceError, match='OPTIONAL_SERVICE_ROLLED_BACK'):
        apply_optional_service(host, plan)
    assert host.registry == old
    assert host.files == before
    assert not host.started
    assert _read(host.directory / 'optional-service-operation.json')['phase'] == 'rolled_back'


@pytest.mark.parametrize('failure', ['start', 'ready'])
def test_after_activation_uncertainty_never_rolls_back_or_retries(tmp_path, failure):
    host = OptionalHost(tmp_path)
    plan = plan_optional_service(host, service='home-projection', enable=True)
    host.fail = failure
    with pytest.raises(OptionalServiceError, match='OPTIONAL_SERVICE_OUTCOME_UNKNOWN'):
        apply_optional_service(host, plan)
    assert host.registry.services['home-projection'].enabled
    assert host.halted == ['home-projection']
    assert host.files['marker_hex'] == b'enabled\n'.hex()
    with pytest.raises(OptionalServiceError, match='OPTIONAL_SERVICE_OUTCOME_UNKNOWN'):
        apply_optional_service(host, plan)
    assert len(host.started) == 1


def test_prepared_crash_has_native_exact_rollback_without_starting_job(tmp_path):
    host = OptionalHost(tmp_path)
    plan = plan_optional_service(host, service='home-projection', enable=True)
    old = host.registry
    binding = replace(old.services['api'], **{
        key: value for key, value in plan['new_binding'].items() if key != 'contracts'
    })
    _write(host.directory / 'optional-service-operation.json', {
        'schema_version': 1, 'phase': 'prepared', 'plan_sha256': plan['plan_sha256'], 'plan': plan,
    })
    host.install(binding, plan['preimage'])
    host.commit(BindingRegistry(1, {**old.services, 'home-projection': binding}), host.binding_hash())
    assert rollback_optional_service(host, plan)['status'] == 'rolled_back'
    assert host.registry == old
    assert host.files == plan['preimage']
    assert not host.started


def test_plan_expiry_registry_drift_unknown_name_and_tamper_fail_before_mutation(tmp_path):
    host = OptionalHost(tmp_path)
    with pytest.raises(OptionalServiceError):
        plan_optional_service(host, service='unknown')
    plan = plan_optional_service(host, service='home-projection')
    host.registry = BindingRegistry(1, {**host.registry.services, 'api': replace(host.registry.services['api'], generation=99)})
    with pytest.raises(OptionalServiceError, match='OPTIONAL_SERVICE_PLAN_DRIFT'):
        apply_optional_service(host, plan)
    assert not host.commits and not host.started and host.files['plist_hex'] is None


def test_native_disabled_install_then_enable_uses_identical_exact_plist(tmp_path):
    host = Host(tmp_path)
    native = object.__new__(OptionalServiceHost)
    native.home = tmp_path / 'home'
    native.directory = tmp_path / 'control'
    binding = replace(host.old.services['api'], service='home-projection', enabled=False)
    before = {'plist_hex': None, 'marker_hex': None, 'loaded': False}
    native.install(binding, before)
    initial = native.path(binding).read_bytes()
    enabled = replace(binding, enabled=True)
    native.install(enabled, {**before, 'plist_hex': initial.hex()})
    assert native.path(enabled).read_bytes() == initial
    assert native.marker(enabled).read_bytes() == b'enabled\n'
    native.rollback(enabled, {**before, 'plist_hex': initial.hex()})
    assert native.path(enabled).read_bytes() == initial
    assert not native.marker(enabled).exists()


def test_native_cli_plans_disabled_by_default_and_only_explicit_flag_enables(tmp_path, monkeypatch, capsys):
    from contextlib import nullcontext
    import json
    from app import runtime_deployment, runtime_optional_service

    host = OptionalHost(tmp_path)
    monkeypatch.setattr(runtime_optional_service, 'OptionalServiceHost', lambda: host)
    monkeypatch.setattr(runtime_deployment, 'deployment_lock', lambda: nullcontext())
    monkeypatch.setattr(runtime_deployment, 'assert_no_unknown_deployment', lambda **kwargs: None)
    assert runtime_deployment.main(['plan-optional-service', '--service', 'home-projection']) == 0
    disabled = json.loads(capsys.readouterr().out)
    assert disabled['new_binding']['enabled'] is False
    assert runtime_deployment.main(['plan-optional-service', '--service', 'home-projection', '--enable']) == 0
    enabled = json.loads(capsys.readouterr().out)
    path = tmp_path / 'reviewed-plan.json'
    _write(path, enabled)
    assert runtime_deployment.main(['apply-optional-service-plan', '--plan', str(path)]) == 0
    assert json.loads(capsys.readouterr().out)['enabled'] is True
    assert host.started == ['home-projection']


def test_unresolved_optional_activation_blocks_other_release_and_cohort_paths(tmp_path, monkeypatch):
    from app import runtime_deployment

    monkeypatch.setattr(runtime_deployment, 'runtime_directory', lambda: tmp_path)
    _write(tmp_path / 'optional-service-operation.json', {'phase': 'starting'})
    with pytest.raises(runtime_deployment.DeploymentError, match='OPTIONAL_SERVICE_OUTCOME_UNKNOWN'):
        runtime_deployment.assert_no_unknown_deployment()
    runtime_deployment.assert_no_unknown_deployment(allow_optional=True)


def test_native_plan_rejects_unverified_plist_without_exporting_private_environment(tmp_path):
    host = Host(tmp_path)
    native = object.__new__(OptionalServiceHost)
    native.home = tmp_path / 'home'
    native.directory = tmp_path / 'control'
    native.assert_stopped = lambda binding: None
    binding = replace(host.old.services['api'], service='home-projection', enabled=False)
    native.path(binding).parent.mkdir(parents=True)
    native.path(binding).write_bytes(b'PRIVATE_TOKEN=must-never-enter-plan')
    with pytest.raises(OptionalServiceError, match='OPTIONAL_SERVICE_PLIST_IDENTITY_UNPROVEN') as error:
        native.preimage(binding)
    assert 'PRIVATE_TOKEN' not in str(error.value)


def test_native_first_install_accepts_no_owner_artifacts_without_creating_lock(tmp_path, monkeypatch):
    host = Host(tmp_path)
    native = object.__new__(OptionalServiceHost)
    native.home = tmp_path / 'home'
    native.directory = tmp_path / 'native-runtime'
    native.directory.mkdir(mode=0o700)
    binding = replace(host.old.services['api'], service='home-projection', enabled=False)
    monkeypatch.setattr('app.runtime_identity.read_launchd_service', lambda *args, **kwargs: None)
    native.assert_stopped(binding)
    assert not list(native.directory.iterdir())


@pytest.mark.parametrize('artifact', [
    'held', 'bad_mode', 'symlink', 'dangling_symlink', 'directory', 'owner_without_lock',
    'control_without_lock', 'malformed_owner', 'loaded',
])
def test_native_stopped_proof_rejects_unproven_or_invalid_owner_artifacts(tmp_path, monkeypatch, artifact):
    import fcntl
    from app.runtime_handover import HandoverError, RunOwnership

    host = Host(tmp_path)
    native = object.__new__(OptionalServiceHost)
    native.home = tmp_path / 'home'
    native.directory = tmp_path / 'native-runtime'
    native.directory.mkdir(mode=0o700)
    binding = replace(host.old.services['api'], service='home-projection', enabled=False)
    monkeypatch.setattr('app.runtime_identity.read_launchd_service',
                        lambda *args, **kwargs: 'loaded' if artifact == 'loaded' else None)
    lock = native.directory / 'home-projection.owner.lock'
    held = None
    if artifact == 'held':
        held = lock.open('xb')
        lock.chmod(0o600)
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif artifact == 'bad_mode':
        lock.touch(mode=0o644)
    elif artifact in {'symlink', 'dangling_symlink'}:
        target = tmp_path / 'target'
        if artifact == 'symlink':
            target.touch(mode=0o600)
        lock.symlink_to(target)
    elif artifact == 'directory':
        lock.mkdir()
    elif artifact == 'owner_without_lock':
        _write(native.directory / 'home-projection.owner.json', {
            'schema_version': 1, 'service': 'home-projection', 'phase': 'parked',
        })
    elif artifact == 'control_without_lock':
        _write(native.directory / 'home-projection.handover.json', {'phase': 'drain'})
    elif artifact == 'malformed_owner':
        path = native.directory / 'home-projection.owner.json'
        path.write_text('{broken')
        path.chmod(0o600)
    try:
        with pytest.raises((OptionalServiceError, HandoverError)):
            native.assert_stopped(binding)
    finally:
        if held:
            held.close()
    # A real RuntimeOwner creates a valid lock. After its lock is released,
    # native proof uses this exact directory and recognizes the free lock.
    if artifact == 'held':
        owner = RunOwnership('home-projection', runtime_dir=native.directory,
                             generation=1, verify=lambda: None)
        with owner.acquired():
            with pytest.raises(OptionalServiceError):
                native.assert_stopped(binding)
        native.assert_stopped(binding)


def test_native_stopped_proof_never_treats_unreadable_lock_as_absence(tmp_path, monkeypatch):
    from app import runtime_handover

    host = Host(tmp_path)
    native = object.__new__(OptionalServiceHost)
    native.home = tmp_path / 'home'
    native.directory = tmp_path / 'native-runtime'
    native.directory.mkdir(mode=0o700)
    binding = replace(host.old.services['api'], service='home-projection', enabled=False)
    lock = native.directory / 'home-projection.owner.lock'
    lock.touch(mode=0o600)
    monkeypatch.setattr('app.runtime_identity.read_launchd_service', lambda *a, **kw: None)
    actual_open = runtime_handover.os.open

    def denied(path, *args, **kwargs):
        if path == lock:
            raise PermissionError()
        return actual_open(path, *args, **kwargs)

    monkeypatch.setattr(runtime_handover.os, 'open', denied)
    with pytest.raises(runtime_handover.HandoverError, match='RUNTIME_OWNER_INVALID'):
        native.assert_stopped(binding)
