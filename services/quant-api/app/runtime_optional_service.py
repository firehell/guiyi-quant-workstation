"""Explicit additive optional-service topology plans, preserving registry CAS."""
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import plistlib
import stat
import time

from app.runtime_bindings import (
    BindingRegistry, ServiceBinding, authorized_program_arguments,
    bindings_sha256, contract_fingerprints, read_bindings, verify_release, write_bindings,
)
from app.runtime_contracts import OPTIONAL_CONTINUOUS
from app.runtime_handover import _read, _write, runtime_directory
from app.reference_trading.recovery_campaign import digest


class OptionalServiceError(ValueError):
    pass


def require(condition, code='OPTIONAL_SERVICE_PRECONDITION_BLOCKED'):
    if not condition:
        raise OptionalServiceError(code)


class OptionalServiceHost:
    """Native host; tests replace this entire adapter with isolated state."""
    def __init__(self):
        self.directory = runtime_directory()
        self.home = Path.home()

    def now(self):
        return datetime.now(UTC)

    def bindings(self):
        return read_bindings()

    def binding_hash(self):
        return bindings_sha256()

    def verify(self, binding):
        from app.runtime_identity import file_snapshot
        verify_release(Path(binding.root), binding.tag, binding.commit)
        require(binding.contracts == contract_fingerprints(Path(binding.root)))
        root = Path(binding.root)
        require((root / 'services/quant-api/app/market_data/newow/home_recovery.py').is_file())
        expected, _ = file_snapshot(root / 'scripts/ops/macos/runtime-service-dispatch.sh')
        actual, _ = file_snapshot(self.directory / 'run-local-service.sh')
        require(actual == expected)

    def path(self, binding):
        return self.home / 'Library/LaunchAgents' / f'{binding.label}.plist'

    def marker(self, binding):
        return Path(binding.root) / '.run/home-projection-enabled'

    @staticmethod
    def contents(path):
        from app.runtime_identity import file_snapshot
        if not os.path.lexists(path):
            return None
        content, _ = file_snapshot(path)
        return content

    def preimage(self, binding):
        self.assert_stopped(binding)
        marker = self.contents(self.marker(binding))
        require(marker is None, 'OPTIONAL_SERVICE_MARKER_ALREADY_PRESENT')
        content = self.contents(self.path(binding))
        # Do not export arbitrary installed environments into a review plan.
        require(content is None or content == self.plist(binding), 'OPTIONAL_SERVICE_PLIST_IDENTITY_UNPROVEN')
        return {'plist_hex': content.hex() if content is not None else None,
                'marker_hex': None, 'loaded': False}

    def assert_stopped(self, binding):
        from app.runtime_identity import read_launchd_service
        from app.runtime_handover import owner_lock_available, read_service_state
        require(self.directory.is_absolute() and self.directory == self.directory.resolve())
        if self.directory.exists():
            info = self.directory.lstat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                    and not info.st_mode & 0o077)
        require(read_launchd_service(binding.label, root=Path(binding.root)) is None)
        lock = self.directory / f'{binding.service}.owner.lock'
        try:
            info = lock.lstat()
        except FileNotFoundError:
            # Before the first RuntimeOwner, no lock exists. Absence is safe
            # only with no owner/control evidence and explicit launchd absence.
            require(read_service_state(binding.service, runtime_dir=self.directory) is None)
            require(not os.path.lexists(self.directory / f'{binding.service}.owner.json'))
            require(not os.path.lexists(self.directory / f'{binding.service}.handover.json'))
            return
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077)
        require(owner_lock_available(binding.service, runtime_dir=self.directory))

    @staticmethod
    def exclusive(path, content):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent = path.parent.stat()
        require(path.parent == path.parent.resolve(strict=True) and stat.S_ISDIR(parent.st_mode)
                and parent.st_uid == os.getuid() and not parent.st_mode & 0o022)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def install(self, binding, preimage):
        path = self.path(binding)
        # A disabled registration created by this operation is already exact.
        if preimage['plist_hex'] is not None:
            require(bytes.fromhex(preimage['plist_hex']) == self.plist(binding))
        else:
            self.exclusive(path, self.plist(binding))
        if binding.enabled:
            self.exclusive(self.marker(binding), b'enabled\n')

    def plist(self, binding):
        return plistlib.dumps({
            'Label': binding.label, 'WorkingDirectory': binding.root,
            'ProgramArguments': list(authorized_program_arguments(binding, self.home)),
            # Explicit launchctl enable overrides this only for an approved activation.
            'Disabled': True, 'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
            'EnvironmentVariables': {
                'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                'GUIYI_PROJECT_ROOT': binding.root, 'GUIYI_RUNTIME_COMMIT': binding.commit,
                'GUIYI_RUNTIME_TAG': binding.tag, 'GUIYI_RUNTIME_GENERATION': str(binding.generation),
                'GUIYI_RUNTIME_HANDOVER_ENABLED': '1', 'GUIYI_OBSERVATION_STREAM_ENABLED': '1',
            },
            'StandardOutPath': str(self.home / 'Library/Logs/GuiyiQuant/home-projection.log'),
            'StandardErrorPath': str(self.home / 'Library/Logs/GuiyiQuant/home-projection.log'),
        })

    def rollback(self, binding, preimage):
        # Only delete bytes this operation installed, after an exact comparison.
        for path, before, expected in (
            (self.marker(binding), preimage['marker_hex'], b'enabled\n'),
            (self.path(binding), preimage['plist_hex'], self.plist(binding)),
        ):
            current = self.contents(path)
            if before is not None:
                require(current == bytes.fromhex(before))
            elif current is not None:
                require(current == expected)
                path.unlink()

    def commit(self, registry, expected):
        return write_bindings(registry, expected_sha256=expected)

    def start(self, binding):
        from app.runtime_deployment import _launchctl
        (self.home / 'Library/Logs/GuiyiQuant').mkdir(parents=True, mode=0o700, exist_ok=True)
        _launchctl('enable', f'gui/{os.getuid()}/{binding.label}')
        _launchctl('bootstrap', f'gui/{os.getuid()}', str(self.path(binding)))

    def ready(self, binding):
        from app.runtime_deployment import owner_process_matches
        from app.runtime_handover import read_service_state
        end = time.monotonic() + 10
        while time.monotonic() < end:
            state = read_service_state(binding.service)
            if (state and state.get('phase') == 'active' and state.get('ready') is True
                    and state.get('generation') == binding.generation
                    and owner_process_matches(state, binding)):
                return True
            time.sleep(0.1)
        return False

    def halt(self, binding):
        from app.runtime_handover import request_drain
        request_drain(binding.service, generation=binding.generation)


def plan_optional_service(host, *, service, enable=False):
    require(service in OPTIONAL_CONTINUOUS and type(enable) is bool)
    old = host.bindings()
    require(old is not None and 'api' in old.services)
    previous = old.services.get(service)
    require(previous is None or not previous.enabled, 'OPTIONAL_SERVICE_ALREADY_ENABLED')
    require(previous is None or previous.launchd_label is None)
    base = old.services['api']
    require(all(value.contracts == base.contracts for value in old.services.values() if value.enabled),
            'OPTIONAL_SERVICE_CONTRACT_MIX_UNPROVEN')
    require(previous is None or (
        previous.root, previous.commit, previous.tag, previous.contracts
    ) == (base.root, base.commit, base.tag, base.contracts))
    binding = replace(base, service=service, enabled=enable, launchd_label=None,
                      generation=(previous.generation if previous else max(v.generation for v in old.services.values()) + 1))
    host.verify(binding)
    before = host.preimage(binding)
    require(previous is not None or before['plist_hex'] is None, 'OPTIONAL_SERVICE_ORPHAN_PLIST')
    now = host.now()
    plan = {'schema_version': 1, 'kind': 'optional_service_topology_v1',
            'old': asdict(old), 'new_binding': asdict(binding), 'previous_binding': asdict(previous) if previous else None,
            'registry_sha256': host.binding_hash(), 'preimage': before,
            'created_at': now.isoformat(), 'expires_at': (now + timedelta(minutes=15)).isoformat()}
    plan['plan_sha256'] = digest(plan)
    return plan


def apply_optional_service(host, plan):
    require(plan.get('plan_sha256') == digest({k: v for k, v in plan.items() if k != 'plan_sha256'}))
    require(plan.get('schema_version') == 1 and plan.get('kind') == 'optional_service_topology_v1')
    require(datetime.fromisoformat(plan['expires_at']) - datetime.fromisoformat(plan['created_at']) == timedelta(minutes=15))
    require(datetime.fromisoformat(plan['created_at']) <= host.now() < datetime.fromisoformat(plan['expires_at']))
    binding = ServiceBinding(**plan['new_binding'])
    require(binding.service in OPTIONAL_CONTINUOUS)
    old = BindingRegistry(1, {k: ServiceBinding(**v) for k, v in plan['old']['services'].items()})
    new = BindingRegistry(1, {**old.services, binding.service: binding})
    journal_path = host.directory / 'optional-service-operation.json'
    journal = _read(journal_path)
    if journal and journal.get('phase') == 'switched' and journal.get('plan_sha256') == plan['plan_sha256']:
        require(host.bindings() == new, 'OPTIONAL_SERVICE_READBACK_DRIFT')
        return {'status': 'already_applied', 'service': binding.service, 'enabled': binding.enabled}
    require(journal is None or journal.get('phase') in {'switched', 'rolled_back'}, 'OPTIONAL_SERVICE_OUTCOME_UNKNOWN')
    fresh = plan_optional_service(host, service=binding.service, enable=binding.enabled)
    require(all(plan[key] == fresh[key] for key in ('old', 'new_binding', 'previous_binding', 'registry_sha256', 'preimage')),
            'OPTIONAL_SERVICE_PLAN_DRIFT')
    record = {'schema_version': 1, 'phase': 'prepared', 'plan_sha256': plan['plan_sha256'], 'plan': plan}
    _write(journal_path, record)
    started = False
    try:
        host.install(binding, plan['preimage'])
        host.commit(new, plan['registry_sha256'])
        require(host.bindings() == new, 'OPTIONAL_SERVICE_REGISTRY_READBACK_FAILED')
        if binding.enabled:
            # Persist before requesting bootstrap: uncertainty never permits a
            # second activation or rollback around a possibly running writer.
            record['phase'] = 'starting'
            _write(journal_path, record)
            started = True
            host.start(binding)
            require(host.ready(binding), 'OPTIONAL_SERVICE_READY_UNPROVEN')
        record['phase'] = 'switched'
        _write(journal_path, record)
        return {'status': 'switched', 'service': binding.service, 'enabled': binding.enabled}
    except Exception:
        if started:
            record['phase'] = 'outcome_unknown'
            _write(journal_path, record)
            try:
                host.halt(binding)
            except Exception:
                pass
            raise OptionalServiceError('OPTIONAL_SERVICE_OUTCOME_UNKNOWN') from None
        try:
            current = host.bindings()
            require(current in (old, new), 'OPTIONAL_SERVICE_REGISTRY_DRIFT')
            if current == new:
                host.commit(old, host.binding_hash())
            host.rollback(binding, plan['preimage'])
            require(host.bindings() == old)
            record['phase'] = 'rolled_back'
            _write(journal_path, record)
        except Exception:
            record['phase'] = 'outcome_unknown'
            _write(journal_path, record)
            raise OptionalServiceError('OPTIONAL_SERVICE_OUTCOME_UNKNOWN') from None
        raise OptionalServiceError('OPTIONAL_SERVICE_ROLLED_BACK') from None


def rollback_optional_service(host, plan):
    """Recover a crashed pre-start installation; never roll back a started writer."""
    require(plan.get('plan_sha256') == digest({k: v for k, v in plan.items() if k != 'plan_sha256'}))
    journal_path = host.directory / 'optional-service-operation.json'
    journal = _read(journal_path)
    require(journal and journal.get('phase') == 'prepared'
            and journal.get('plan_sha256') == plan['plan_sha256']
            and journal.get('plan') == plan, 'OPTIONAL_SERVICE_OUTCOME_UNKNOWN')
    binding = ServiceBinding(**plan['new_binding'])
    require(binding.service in OPTIONAL_CONTINUOUS)
    host.verify(binding)
    host.assert_stopped(binding)
    old = BindingRegistry(1, {k: ServiceBinding(**v) for k, v in plan['old']['services'].items()})
    new = BindingRegistry(1, {**old.services, binding.service: binding})
    current = host.bindings()
    require(current in (old, new), 'OPTIONAL_SERVICE_REGISTRY_DRIFT')
    if current == new:
        host.commit(old, host.binding_hash())
    host.rollback(binding, plan['preimage'])
    require(host.bindings() == old)
    journal['phase'] = 'rolled_back'
    _write(journal_path, journal)
    return {'status': 'rolled_back', 'service': binding.service}
