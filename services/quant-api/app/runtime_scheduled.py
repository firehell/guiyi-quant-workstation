"""Idle-only replacement of exact scheduled jobs; never kickstart a business run."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
from uuid import uuid4

from app.runtime_handover import _write, runtime_directory

SCHEDULED = frozenset({'after-market', 'late-provider-recovery', 'weekly-audit', 'log-rotate'})


class ScheduledUpdateError(RuntimeError):
    pass


def execute_scheduled_update(service, previous, candidate, *, backend=None, commit_binding):
    if service not in SCHEDULED or previous.service != service or candidate.service != service:
        raise ScheduledUpdateError('SCHEDULED_SERVICE_INVALID')
    backend = backend or ScheduledBackend()
    request = uuid4().hex
    preimage = backend.freeze(previous)
    journal = {'schema_version': 1, 'service': service, 'request_id': request,
               'previous': asdict(previous), 'candidate': asdict(candidate),
               'preimage': preimage, 'phase': 'prepared'}
    backend.journal(journal)
    mutated = False
    try:
        with backend.idle_guards(previous):
            if not backend.idle(previous):
                journal['phase'] = 'scheduled_busy'
                backend.journal(journal)
                return 'scheduled_busy'
            mutated = True
            backend.disable(previous)
            if not backend.idle(previous):
                raise ScheduledUpdateError('SCHEDULED_START_RACE')
            backend.unload(previous)
            backend.install(previous, candidate, preimage)
            commit_binding()
            journal['phase'] = 'binding_committed'
            backend.journal(journal)
        backend.load(candidate)  # Calendar registration only; no kickstart/RunAtLoad.
        if not backend.verify(candidate):
            raise ScheduledUpdateError('SCHEDULED_READBACK_FAILED')
        journal['phase'] = 'switched'
        backend.journal(journal)
        return 'switched'
    except Exception:
        if mutated:
            journal['phase'] = 'outcome_unknown'
            try:
                backend.journal(journal)
            except Exception:
                pass
            try:
                backend.halt_unknown(candidate)
            except Exception:
                pass
            raise ScheduledUpdateError('SCHEDULED_OUTCOME_UNKNOWN_READBACK_REQUIRED') from None
        journal['phase'] = 'precondition_blocked'
        try:
            backend.journal(journal)
        except Exception:
            pass
        raise ScheduledUpdateError('SCHEDULED_PRECONDITION_BLOCKED') from None


class ScheduledBackend:
    def _path(self, binding):
        return Path.home() / 'Library/LaunchAgents' / f'{binding.label}.plist'

    def _launchctl(self, *args, allow_missing=False):
        result = subprocess.run(['/bin/launchctl', *args], capture_output=True, timeout=15)
        if result.returncode and not (allow_missing and result.returncode == 113):
            raise ScheduledUpdateError('SCHEDULED_LAUNCHD_OPERATION_FAILED')
        return result

    def freeze(self, binding):
        from app.runtime_handover import _read
        prior = _read(runtime_directory() / f"{binding.service}.scheduled-update.json")
        if prior is not None and prior.get("phase") not in ("switched", "scheduled_busy", "precondition_blocked"):
            raise ScheduledUpdateError("SCHEDULED_RECOVERY_READBACK_REQUIRED")
        from app.market_data.closeout_binding import _snapshot
        from app.runtime_bindings import authorized_program_arguments
        path = self._path(binding)
        content, _stamp = _snapshot(path)
        payload = plistlib.loads(content)
        env = payload.get('EnvironmentVariables', {})
        if (payload.get('Label') != binding.label
                or payload.get('WorkingDirectory') != binding.root
                or env.get('GUIYI_PROJECT_ROOT') != binding.root
                or env.get('GUIYI_RUNTIME_COMMIT') != binding.commit
                or env.get('GUIYI_RUNTIME_TAG') != binding.tag
                or env.get('GUIYI_RUNTIME_GENERATION') != str(binding.generation)
                or tuple(payload.get('ProgramArguments', ())) != authorized_program_arguments(binding, Path.home())):
            raise ScheduledUpdateError('SCHEDULED_PLIST_IDENTITY_INVALID')
        return {'plist_sha256': hashlib.sha256(content).hexdigest()}

    def idle(self, binding):
        from app.market_data.captured_recovery_runtime import _read_launchd_service, _verify_loaded_service
        from app.market_data.closeout_binding import _arguments, _environments
        from app.runtime_bindings import authorized_program_arguments
        output = _read_launchd_service(binding.label, root=Path(binding.root))
        if output is None:  # Reader returns None only for an exact explicit absent label.
            return True
        fields = _verify_loaded_service(output, root=Path(binding.root), commit=binding.commit, allow_idle=True)
        environments = _environments(output)
        if (_arguments(output) != authorized_program_arguments(binding, Path.home())
                or not any(environment.get('GUIYI_RUNTIME_TAG') == binding.tag
                    and environment.get('GUIYI_RUNTIME_GENERATION') == str(binding.generation)
                    for environment in environments)):
            raise ScheduledUpdateError('SCHEDULED_LOADED_IDENTITY_INVALID')
        return fields.get('pid') is None and fields.get('state') in ('waiting', 'not running')

    @contextmanager
    def idle_guards(self, binding):
        with ExitStack() as stack:
            if binding.service != 'log-rotate':
                from app.market_data.live_recovery_guard import after_market_recovery_guard
                from app.db.session import SessionLocal
                from app.market_data.catalog import MarketCatalog
                from app.market_data.composition import canonical_root
                stack.enter_context(after_market_recovery_guard(wait=False))
                session = stack.enter_context(SessionLocal())
                lease = MarketCatalog(session, canonical_root()).acquire_maintenance_lock()
                if lease is None:
                    raise ScheduledUpdateError('SCHEDULED_MAINTENANCE_BUSY')
                stack.callback(lease.release)
            yield

    def disable(self, binding):
        self._launchctl('disable', f'gui/{os.getuid()}/{binding.label}')

    def unload(self, binding):
        if not self.idle(binding):
            raise ScheduledUpdateError('SCHEDULED_OWNER_BUSY')
        self._launchctl('bootout', f'gui/{os.getuid()}/{binding.label}', allow_missing=True)

    def install(self, previous, candidate, preimage):
        path = self._path(previous)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != preimage['plist_sha256']:
            raise ScheduledUpdateError('SCHEDULED_PLIST_DRIFT')
        backup = runtime_directory() / f'{previous.service}.scheduled-preimage-{previous.generation}.plist'
        if backup.exists() or backup.is_symlink():
            raise ScheduledUpdateError('SCHEDULED_PREIMAGE_EXISTS')
        backup.write_bytes(content)
        backup.chmod(0o600)
        payload = plistlib.loads(content)
        payload['Label'] = candidate.label
        payload['WorkingDirectory'] = candidate.root
        env = dict(payload.get('EnvironmentVariables', {}))
        env.update(GUIYI_PROJECT_ROOT=candidate.root, GUIYI_RUNTIME_TAG=candidate.tag,
                   GUIYI_RUNTIME_COMMIT=candidate.commit, GUIYI_RUNTIME_GENERATION=str(candidate.generation),
                   GUIYI_RUNTIME_HANDOVER_ENABLED='1', GUIYI_OBSERVATION_STREAM_ENABLED='1')
        payload['EnvironmentVariables'] = env
        payload['ProgramArguments'] = ['/bin/bash', str(runtime_directory() / 'run-local-service.sh'), candidate.service]
        payload['RunAtLoad'] = False
        payload['KeepAlive'] = False
        payload['Disabled'] = not candidate.enabled
        target = self._path(candidate)
        if target.is_symlink():
            raise ScheduledUpdateError('SCHEDULED_PLIST_UNSAFE')
        target.write_bytes(plistlib.dumps(payload))
        target.chmod(0o600)

    def load(self, binding):
        if binding.enabled:
            self._launchctl('enable', f'gui/{os.getuid()}/{binding.label}')
            self._launchctl('bootstrap', f'gui/{os.getuid()}', str(self._path(binding)))

    def verify(self, binding):
        from app.runtime_bindings import resolve_service_binding
        if resolve_service_binding(binding.service) != binding:
            return False
        payload = plistlib.loads(self._path(binding).read_bytes())
        env = payload.get('EnvironmentVariables', {})
        if (payload.get('RunAtLoad') is not False or payload.get('WorkingDirectory') != binding.root
                or env.get('GUIYI_RUNTIME_COMMIT') != binding.commit
                or env.get('GUIYI_RUNTIME_GENERATION') != str(binding.generation)):
            return False
        if not binding.enabled:
            from app.market_data.captured_recovery_runtime import _read_launchd_service
            return payload.get('Disabled') is True and _read_launchd_service(binding.label, root=Path(binding.root)) is None
        from app.services.deployment_identity import deployment_identity_health
        result = deployment_identity_health(root=Path(binding.root), commit=binding.commit)
        mapping = {'after-market': 'after_market', 'late-provider-recovery': 'late_provider_recovery',
                   'weekly-audit': 'weekly_audit', 'log-rotate': 'log-rotate'}
        return result.get('services', {}).get(mapping[binding.service], {}).get('status') == 'matched'

    def halt_unknown(self, candidate):
        """Block future calendar triggers without killing any possibly running job."""
        from app.runtime_bindings import resolve_service_binding
        if resolve_service_binding(candidate.service) != candidate:
            return False
        self._launchctl('disable', f'gui/{os.getuid()}/{candidate.label}')
        return True

    def journal(self, value):
        _write(runtime_directory() / f"{value['service']}.scheduled-update.json", value)
