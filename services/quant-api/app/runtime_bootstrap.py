"""First observation topology migration, with independently frozen legacy identities.

The planner is read-only. Apply never invents old consumption progress or kills an
in-flight transport; any uncertain mutation leaves an exact recovery journal.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import subprocess
from time import monotonic, sleep

from app.runtime_bindings import (BindingRegistry, ServiceBinding, contract_fingerprints,
    read_bindings, verify_release, write_bindings, authorized_program_arguments)
from app.runtime_handover import _write, runtime_directory

_CONTINUOUS = ('api', 'web', 'live', 'alert', 'reference-worker')
_MARKERS = {'live': 'market-runtime-enabled', 'alert': 'alert-runtime-enabled',
            'reference-worker': 'reference-worker-enabled', 'weekly-audit': 'weekly-audit-enabled'}
_SCHEMA = '20261009_0051'


class BootstrapError(RuntimeError):
    pass


def parse_disabled_states(output: bytes) -> dict[str, bool]:
    """Parse launchctl's actual activation vocabulary; unknown is never enabled."""
    try:
        lines = [line.strip() for line in output.decode('utf-8').splitlines() if line.strip()]
        if not lines or lines[0] != 'disabled services = {' or lines[-1] != '}':
            raise ValueError
        result = {}
        for line in lines[1:-1]:
            match = re.fullmatch(r'"([^"\s]+)"\s*=>\s*(true|false|disabled|enabled)', line)
            if not match or match[1] in result:
                raise ValueError
            result[match[1]] = match[2] in ('true', 'disabled')
        return result
    except (UnicodeError, AttributeError, ValueError):
        raise BootstrapError('BOOTSTRAP_DISABLED_STATE_UNPROVEN') from None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def build_bootstrap_plan(candidate_root, tag, commit, *, backend=None):
    backend = backend or BootstrapBackend()
    if backend.registry_exists():
        raise BootstrapError('BOOTSTRAP_REGISTRY_ALREADY_EXISTS')
    candidate_root = Path(candidate_root)
    backend.verify_candidate(candidate_root, tag, commit)
    installed = backend.installed()
    if 'live' not in installed:
        raise BootstrapError('BOOTSTRAP_LIVE_IDENTITY_MISSING')
    bindings = {}
    contracts = backend.contracts(candidate_root)
    for service, old in installed.items():
        bindings[service] = asdict(ServiceBinding(service, str(candidate_root), tag, commit,
                                                  1, old['enabled'], contracts))
    bindings['market-feed'] = asdict(ServiceBinding('market-feed', str(candidate_root), tag, commit,
                                                    1, installed['live']['enabled'], contracts))
    plan = {'schema_version': 1, 'kind': 'first_observation_topology',
            'candidate_root': str(candidate_root), 'tag': tag, 'commit': commit,
            'installed': installed, 'bindings': bindings,
            'schema_before': backend.schema_revision(), 'schema_after': _SCHEMA,
            'steps': ['verify_rest_and_send_idle', 'hold_writer_guards', 'graceful_stop',
                      'migrate_and_verify_schema', 'prove_empty_journals', 'initialize_explicit_cutoffs',
                      'install_dispatch_and_exact_plists', 'commit_registry', 'start_consumers_then_feed',
                      'readback_identity_and_cursor']}
    if plan['schema_before'] not in ('20261009_0050', _SCHEMA):
        raise BootstrapError('BOOTSTRAP_SCHEMA_INCOMPATIBLE')
    plan['plan_hash'] = _hash(plan)
    return plan


def apply_bootstrap_plan(plan, *, backend=None):
    backend = backend or BootstrapBackend()
    if not isinstance(plan, dict) or plan.get('plan_hash') != _hash({k: v for k, v in plan.items() if k != 'plan_hash'}):
        raise BootstrapError('BOOTSTRAP_PLAN_INVALID')
    refreshed = build_bootstrap_plan(Path(plan['candidate_root']), plan['tag'], plan['commit'], backend=backend)
    if refreshed['plan_hash'] != plan['plan_hash']:
        raise BootstrapError('BOOTSTRAP_PLAN_DRIFT')
    proof = backend.prove_safe_boundary(plan)
    journal = {'schema_version': 1, 'plan_hash': plan['plan_hash'], 'phase': 'prepared',
               'plan': plan, 'boundary': proof, 'completed_steps': []}
    backend.journal(journal)
    mutated = False
    try:
        with backend.writer_guards(plan):
            backend.prove_safe_boundary(plan)
            # Stop only exact frozen legacy labels. SIGTERM must finish the process;
            # launchctl bootout/SIGKILL is never used as a graceful-stop substitute.
            mutated = True
            backend.stop_legacy(plan)
            journal['completed_steps'].append('legacy_stopped')
            backend.journal(journal)
            backend.prove_no_inflight_sends()
            backend.migrate_schema(plan)
            if backend.schema_revision() != _SCHEMA:
                raise BootstrapError('BOOTSTRAP_SCHEMA_OUTCOME_UNKNOWN')
            journal['completed_steps'].append('schema_verified')
            backend.journal(journal)
            backend.initialize_cutoffs(plan, proof)
            journal['completed_steps'].append('cutoffs_initialized')
            backend.journal(journal)
            backend.install(plan)
            journal['completed_steps'].append('plists_installed')
            backend.journal(journal)
            registry = BindingRegistry(1, {key: ServiceBinding(**value) for key, value in plan['bindings'].items()})
            backend.commit_registry(registry)
            journal['completed_steps'].append('registry_committed')
            backend.journal(journal)
        backend.start(plan)
        if not backend.verify(plan, proof):
            raise BootstrapError('BOOTSTRAP_READBACK_FAILED')
        journal['phase'] = 'switched'
        backend.journal(journal)
        return {'status': 'switched', 'plan_hash': plan['plan_hash'], 'natural_acceptance': 'pending'}
    except Exception:
        if mutated:
            journal['phase'] = 'outcome_unknown'
            try:
                backend.journal(journal)
            except Exception:
                pass  # Control-store failure cannot justify continued mutation.
            try:
                backend.halt_unknown(plan)
            except Exception:
                pass  # Remain unknown; never restore or retry either generation.
            raise BootstrapError('BOOTSTRAP_OUTCOME_UNKNOWN_READBACK_REQUIRED') from None
        journal['phase'] = 'precondition_blocked'
        try:
            backend.journal(journal)
        except Exception:
            pass
        raise BootstrapError('BOOTSTRAP_PRECONDITION_BLOCKED') from None


class BootstrapBackend:
    """Host implementation; tests inject a backend without production side effects."""
    def registry_exists(self):
        from app.runtime_handover import _read
        recovery = _read(runtime_directory() / 'topology-legacy-recovery.json')
        if recovery is not None and recovery.get('phase') != 'recovered_legacy':
            raise BootstrapError('BOOTSTRAP_RECOVERY_ATTEMPT_READBACK_REQUIRED')
        journal = _read(runtime_directory() / 'topology-bootstrap.json')
        if journal is not None and journal.get('phase') not in ('switched', 'precondition_blocked', 'recovered_legacy'):
            raise BootstrapError('BOOTSTRAP_RECOVERY_READBACK_REQUIRED')
        return read_bindings() is not None

    def verify_candidate(self, root, tag, commit):
        verify_release(root, tag, commit)
        self.candidate_root = Path(root)

    def contracts(self, root):
        return contract_fingerprints(root)

    def installed(self):
        from app.runtime_handover import SERVICES
        result = {}
        disabled = self._launchctl("print-disabled", f"gui/{os.getuid()}").stdout
        for service in sorted(SERVICES - {'market-feed'}):
            label = f'com.guiyi.quant-{service}'
            path = Path.home() / 'Library/LaunchAgents' / f'{label}.plist'
            if not path.exists():
                continue
            if path.is_symlink():
                raise BootstrapError('BOOTSTRAP_PLIST_UNSAFE')
            from app.market_data.closeout_binding import _snapshot
            content, _stamp = _snapshot(path)
            payload = plistlib.loads(content)
            if service == 'log-rotate':
                result[service] = self._legacy_log_rotate(path, payload, content, disabled)
                continue
            env = payload.get('EnvironmentVariables', {})
            root = Path(env.get('GUIYI_PROJECT_ROOT', payload.get('WorkingDirectory', '')))
            if payload.get('Label') != label or not root.is_absolute() or root != root.resolve(strict=True):
                raise BootstrapError('BOOTSTRAP_PLIST_IDENTITY_INVALID')
            from app.runtime_bindings import _git
            commit = _git(root, 'rev-parse', 'HEAD')
            tag = env.get('GUIYI_RUNTIME_TAG') or _git(root, 'describe', '--exact-match', '--tags', 'HEAD')
            verify_release(root, tag, commit)
            expected_directory = Path.home() if service in ('api', 'web') else root
            expected_arguments = ('/bin/bash', str(runtime_directory() / 'run-local-service.sh'), service)
            if service == 'weekly-audit':
                expected_arguments = ('/bin/bash', str(root / 'scripts/ops/macos/run-local-service.sh'), 'weekly-audit-scheduled')
            if (env.get('GUIYI_RUNTIME_COMMIT') != commit
                    or payload.get('WorkingDirectory') != str(expected_directory)
                    or tuple(payload.get('ProgramArguments', ())) != expected_arguments):
                raise BootstrapError('BOOTSTRAP_PLIST_IDENTITY_INVALID')
            explicitly_disabled = parse_disabled_states(disabled).get(label, False)
            enabled = not payload.get('Disabled', False) and not explicitly_disabled
            marker = _MARKERS.get(service)
            if marker:
                marker_path = root / '.run' / marker
                enabled = enabled and marker_path.is_file() and not marker_path.is_symlink() and marker_path.read_bytes() == b'enabled\n'
            from app.market_data.captured_recovery_runtime import _read_launchd_service, _verify_loaded_service
            from app.market_data.closeout_binding import _arguments
            observed = _read_launchd_service(label, root=root)
            if enabled and observed is None:
                raise BootstrapError('BOOTSTRAP_LOADED_SERVICE_MISSING')
            loaded_pid = None
            if observed is not None:
                identity = _verify_loaded_service(observed, root=root, commit=commit,
                    allow_idle=service not in _CONTINUOUS, require_idle=not enabled,
                    working_directory=Path(payload['WorkingDirectory']))
                if _arguments(observed) != tuple(payload.get('ProgramArguments', ())):
                    raise BootstrapError('BOOTSTRAP_LOADED_SERVICE_CONFLICT')
                loaded_pid = identity.get('pid')
            result[service] = {'loaded_pid': loaded_pid, 'root': str(root), 'tag': tag, 'commit': commit, 'label': label,
                               'enabled': bool(enabled), 'plist_sha256': hashlib.sha256(content).hexdigest()}
            if service == 'after-market':
                from app.market_data.after_market_history import _bytes
                status = root / '.run/after-market-status.json'
                result[service]['status_sha256'] = hashlib.sha256(_bytes(status)).hexdigest() if status.exists() else None
        return result

    def _legacy_log_rotate(self, path, payload, content, disabled):
        """The old standalone script has no release identity; freeze its actual bytes."""
        from app.market_data.closeout_binding import _arguments, _snapshot
        from app.market_data.captured_recovery_runtime import _read_launchd_service
        try:
            home = Path.home()
            directory = home / 'Library/Application Support/GuiyiQuant'
            script = directory / 'rotate-local-service-logs.sh'
            label = 'com.guiyi.quant-log-rotate'
            candidate_root = self.candidate_root
            template = (candidate_root / 'deploy/launchd/com.guiyi.quant-log-rotate.plist.template').read_text()
            expected = plistlib.loads(template.replace('__HOME__', str(home))
                .replace('__RUNTIME_DIR__', str(directory))
                .replace('__LOG_DIR__', str(home / 'Library/Logs/GuiyiQuant')).encode())
            if 'Disabled' in payload:
                if type(payload['Disabled']) is not bool:
                    raise ValueError
                expected['Disabled'] = payload['Disabled']
            if payload != expected or path != home / 'Library/LaunchAgents' / f'{label}.plist':
                raise ValueError
            script_content, _script_stamp = _snapshot(script)
            if script_content != (candidate_root / 'scripts/ops/macos/rotate-local-service-logs.sh').read_bytes():
                raise ValueError
            enabled = not payload.get('Disabled', False) and not parse_disabled_states(disabled).get(label, False)
            output = _read_launchd_service(label, root=home)
            if enabled and output is None:
                raise ValueError
            if output is not None:
                # Parse direct service fields only; an event descriptor cannot prove idle.
                scopes, fields, environment = [], {}, {}
                environment_seen = False
                for raw in output.splitlines():
                    line = raw.strip()
                    if line.endswith((' = {', ' => {')):
                        name, operator, _ = line.rsplit(' ', 2)
                        if not scopes and (operator != '=' or name != f'gui/{os.getuid()}/{label}'):
                            raise ValueError
                        if len(scopes) == 1 and name == 'environment':
                            if environment_seen or operator != '=':
                                raise ValueError
                            environment_seen = True
                        scopes.append((name, operator))
                    elif line == '}':
                        if not scopes:
                            raise ValueError
                        scopes.pop()
                    elif len(scopes) == 1:
                        match = re.fullmatch(r'(state|pid|working directory|program) = (.*)', line)
                        if match:
                            if match[1] in fields:
                                raise ValueError
                            fields[match[1]] = match[2]
                    elif len(scopes) == 2 and scopes[-1] == ('environment', '='):
                        match = re.fullmatch(r'([^\s]+) => (.*)', line)
                        if not match or match[1] in environment:
                            raise ValueError
                        environment[match[1]] = match[2]
                expected_environment = dict(payload['EnvironmentVariables'])
                if environment.get('XPC_SERVICE_NAME') == label:
                    expected_environment['XPC_SERVICE_NAME'] = label
                # These are launchd bookkeeping keys, not a release identity.
                if 'OSLogRateLimit' in environment and re.fullmatch(r'[0-9]{1,10}', environment['OSLogRateLimit']):
                    expected_environment['OSLogRateLimit'] = environment['OSLogRateLimit']
                if (scopes or fields.get('state') != 'not running' or 'pid' in fields
                        or fields.get('working directory') != str(home)
                        or fields.get('program') != '/bin/bash'
                        or _arguments(output) != tuple(payload['ProgramArguments'])
                        or environment != expected_environment):
                    raise ValueError
            if _snapshot(path)[0] != content or _snapshot(script)[0] != script_content:
                raise ValueError
            return {'identity_kind': 'legacy_unversioned_log_rotate', 'label': label,
                    'enabled': bool(enabled), 'loaded_pid': None,
                    'script_path': str(script), 'script_sha256': hashlib.sha256(script_content).hexdigest(),
                    'plist_sha256': hashlib.sha256(content).hexdigest()}
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise BootstrapError('BOOTSTRAP_LOG_ROTATE_IDENTITY_UNPROVEN') from None

    def schema_revision(self):
        from app.db.session import engine
        from sqlalchemy import text
        with engine.connect() as connection:
            rows = connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
        if len(rows) != 1:
            raise BootstrapError('BOOTSTRAP_SCHEMA_AMBIGUOUS')
        return rows[0]

    def prove_safe_boundary(self, plan):
        from app.db.session import SessionLocal
        from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
        from app.market_data.operational_universe import load_operational_products
        from app.market_data.live_market import RedisLiveStore
        from app.redis_connections import get_redis_connection
        now = datetime.now(UTC)
        products = load_operational_products()
        with SessionLocal() as session:
            phases = [MarketPhaseResolver(session).resolve(product, now) for product in products]
        if not products or any(phase.phase not in (MarketPhase.BREAK, MarketPhase.CLOSED) for phase in phases):
            raise BootstrapError('BOOTSTRAP_REST_WINDOW_REQUIRED')
        if any(phase.next_session_start and phase.next_session_start <= now + timedelta(minutes=3) for phase in phases):
            raise BootstrapError('BOOTSTRAP_REST_WINDOW_TOO_SHORT')
        redis = get_redis_connection()
        try:
            heartbeat = RedisLiveStore(redis).heartbeat()
            old_live = plan['installed']['live']
            if (not heartbeat or heartbeat.get('available') is not True
                    or heartbeat.get('runtime_root') != old_live['root']
                    or heartbeat.get('runtime_commit') != old_live['commit']):
                raise BootstrapError('BOOTSTRAP_COMPLETED_BOUNDARY_UNPROVEN')
            generated = datetime.fromisoformat(heartbeat['generated_at'])
            if not 0 <= (now - generated).total_seconds() <= 30:
                raise BootstrapError('BOOTSTRAP_HEARTBEAT_STALE')
            coverage = heartbeat.get('coverage', {})
            days = set()
            for product in products:
                item = coverage.get(product, {})
                if item.get('state') not in ('ok', 'not_due') or item.get('first_missing_bar_end') or item.get('previous_unresolved'):
                    raise BootstrapError('BOOTSTRAP_COMPLETED_BOUNDARY_UNPROVEN')
                if item.get('expected_bar_end') != item.get('last_observed_bar_end'):
                    raise BootstrapError('BOOTSTRAP_COMPLETED_BOUNDARY_UNPROVEN')
                days.add(item.get('trading_day'))
            if None in days or len(days) != 1:
                raise BootstrapError('BOOTSTRAP_TRADING_DAY_UNPROVEN')
            # This is an unlocked preflight, never proof that a transport is idle.
            send_boundary = self.read_send_boundary()
            return {'trading_day': next(iter(days)), 'checked_at': now.isoformat(), 'products': len(products),
                    'legacy_last_bar_at': heartbeat.get('last_bar_at'), 'send_boundary': send_boundary}
        finally:
            redis.close()

    def read_send_boundary(self):
        """Read historical diagnostics without changing or acknowledging any fact."""
        from app.db.session import engine
        from app.redis_connections import get_redis_connection
        from sqlalchemy import text
        with engine.connect() as connection:
            if connection.execute(text("SELECT 1 FROM newow_notification_deliveries WHERE status='ATTEMPTED_UNKNOWN' LIMIT 1")).first():
                raise BootstrapError('BOOTSTRAP_NEWOW_SEND_UNKNOWN')
        redis = get_redis_connection()
        try:
            raw = redis.get('alert:runtime-status')
            if raw:
                status = json.loads(raw)
                if not isinstance(status, dict):
                    raise BootstrapError('BOOTSTRAP_ALERT_SEND_UNKNOWN')
                attempted = status.get('last_transport_attempt_at')
                accepted = status.get('last_provider_accepted_at')
                failure = status.get('last_notification_failure_at')
                parsed = {}
                for name, value in (('attempted', attempted), ('accepted', accepted), ('failure', failure)):
                    if value is not None:
                        stamp = datetime.fromisoformat(value)
                        if stamp.tzinfo is None or stamp.utcoffset() is None or stamp > datetime.now(UTC):
                            raise BootstrapError('BOOTSTRAP_ALERT_SEND_UNKNOWN')
                        parsed[name] = stamp
                if attempted and (not accepted or parsed['accepted'] < parsed['attempted']):
                    raise BootstrapError('BOOTSTRAP_ALERT_SEND_UNKNOWN')
                if status.get('notification_error_type') and (
                        not failure or not attempted or not accepted
                        or not parsed['failure'] < parsed['attempted'] <= parsed['accepted']):
                    raise BootstrapError('BOOTSTRAP_ALERT_SEND_UNKNOWN')
                return {'historical_notification_error': bool(status.get('notification_error_type')),
                        'transport_idle_proven': False}
            return {'historical_notification_error': False, 'transport_idle_proven': False}
        except (TypeError, ValueError):
            raise BootstrapError('BOOTSTRAP_ALERT_SEND_UNKNOWN') from None
        finally:
            redis.close()

    def prove_no_inflight_sends(self):
        # Only writer_guards establishes this marker after taking every legacy
        # send lock and validating the unguarded Canonical path. Timestamps cannot
        # establish it, nor do equal batch timestamps imply individual acceptance.
        if getattr(self, '_transport_guards_held', False) is not True:
            raise BootstrapError('BOOTSTRAP_SEND_GUARDS_REQUIRED')
        self.read_send_boundary()

    @contextmanager
    def writer_guards(self, plan):
        from app.db.session import SessionLocal
        from app.market_data.catalog import MarketCatalog
        from app.market_data.composition import canonical_root
        from app.market_data.live_recovery_guard import after_market_recovery_guard
        if getattr(self, '_transport_guards_held', False):
            raise BootstrapError('BOOTSTRAP_SEND_GUARDS_REENTRANT')
        with ExitStack() as stack:
            from app.market_data.operational_universe import load_operational_products
            products = tuple(load_operational_products())
            if not products or len(set(products)) != len(products):
                raise BootstrapError('BOOTSTRAP_SEND_SCOPE_UNPROVEN')
            roots = {Path(plan['installed'][service]['root']) for service in ('live', 'after-market') if service in plan['installed']}
            for root in sorted(roots):
                stack.enter_context(after_market_recovery_guard(root=root / ".run/live-recovery-guards", wait=False, legacy_root=True))
            from app.market_data.live_recovery_guard import recovery_guard
            guard_roots = {Path(plan['installed'][service]['root']) for service in ('live', 'alert') if service in plan['installed']}
            for root in sorted(guard_roots):
                for product in products:
                    stack.enter_context(recovery_guard(product, root=root / ".run/live-recovery-guards", wait=False, legacy_root=True))
            session = stack.enter_context(SessionLocal())
            from sqlalchemy import text, select
            # The old dispatcher holds this exact session-level lock across claims and sends.
            send_connection = stack.enter_context(session.get_bind().connect())
            if not send_connection.execute(text('SELECT pg_try_advisory_lock(1852143479, 1)')).scalar():
                raise BootstrapError('BOOTSTRAP_NEWOW_SEND_BUSY')
            stack.callback(lambda: send_connection.execute(text('SELECT pg_advisory_unlock(1852143479, 1)')))
            # Legacy canonical Alert does not hold symbol guards. Do not pretend its
            # table/health snapshot proves a safe SIGTERM around transport.
            from app.alerts.models import AlertRule
            from app.alerts.registry import get_alert_rule_definition
            for rule in session.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))):
                if get_alert_rule_definition(rule.rule_code).notification_enabled and any(
                    frequency in ('1d', '1w') for values in rule.scope_product_frequencies.values() for frequency in values):
                    raise BootstrapError('BOOTSTRAP_LEGACY_CANONICAL_DRAIN_UNSUPPORTED')
            old_alert = plan['installed'].get('alert', {})
            if old_alert.get('enabled') or old_alert.get('loaded_pid') is not None:
                from app.redis_connections import get_redis_connection
                redis = get_redis_connection()
                try:
                    raw = redis.get('alert:heartbeat')
                    heartbeat = json.loads(raw) if raw else {}
                    if (old_alert.get('loaded_pid') is None
                            or str(self._pid(old_alert['label'])) != str(old_alert['loaded_pid'])):
                        raise BootstrapError('BOOTSTRAP_LEGACY_ALERT_DRAIN_UNSUPPORTED')
                    generated = datetime.fromisoformat(heartbeat.get('generated_at', ''))
                    if (heartbeat.get('recovery_guard_enabled') is not True
                            or heartbeat.get('runtime_root') != old_alert['root']
                            or heartbeat.get('runtime_commit') != old_alert['commit']
                            or not 0 <= (datetime.now(UTC) - generated).total_seconds() <= 30):
                        raise BootstrapError('BOOTSTRAP_LEGACY_ALERT_DRAIN_UNSUPPORTED')
                finally:
                    redis.close()
            lease = MarketCatalog(session, canonical_root()).acquire_maintenance_lock()
            if lease is None:
                raise BootstrapError('BOOTSTRAP_CATALOG_WRITER_BUSY')
            stack.callback(lease.release)
            for service in ('after-market', 'late-provider-recovery', 'weekly-audit', 'log-rotate'):
                old = plan['installed'].get(service)
                if old and self._pid(old['label']) is not None:
                    raise BootstrapError('BOOTSTRAP_SCHEDULED_WRITER_BUSY')
            self._transport_guards_held = True
            try:
                self.prove_no_inflight_sends()
                yield
            finally:
                # Reset before ExitStack releases the locks, including exceptions.
                self._transport_guards_held = False

    def _launchctl(self, *args, allow_missing=False):
        result = subprocess.run(['/bin/launchctl', *args], capture_output=True, timeout=15)
        if result.returncode and not (allow_missing and result.returncode == 113):
            raise BootstrapError('BOOTSTRAP_LAUNCHD_OPERATION_FAILED')
        return result

    def _pid(self, label):
        from app.market_data.captured_recovery_runtime import _read_launchd_service, CapturedRecoveryRuntimeError
        try:
            output = _read_launchd_service(label, root=Path.home())
            if output is None:
                return None
            scopes, fields = [], {}
            for raw in output.splitlines():
                line = raw.strip()
                if line.endswith((' = {', ' => {')):
                    name, operator, _ = line.rsplit(' ', 2)
                    if not scopes and (operator != '=' or name != f'gui/{os.getuid()}/{label}'):
                        raise ValueError
                    scopes.append((name, operator))
                elif line == '}':
                    if not scopes:
                        raise ValueError
                    scopes.pop()
                elif len(scopes) == 1:
                    match = re.fullmatch(r'(state|pid) = (.*)', line)
                    if match:
                        if match[1] in fields:
                            raise ValueError
                        fields[match[1]] = match[2]
            if scopes or fields.get('state') not in ('running', 'waiting', 'not running'):
                raise ValueError
            value = fields.get('pid')
            if value is None:
                if fields['state'] == 'running':
                    raise ValueError
                return None
            if fields['state'] != 'running' or not re.fullmatch(r'[1-9][0-9]{0,9}', value):
                raise ValueError
            return int(value)
        except CapturedRecoveryRuntimeError:
            raise BootstrapError('BOOTSTRAP_LAUNCHD_OPERATION_FAILED') from None
        except (OSError, ValueError, TypeError):
            raise BootstrapError('BOOTSTRAP_PROCESS_STATE_UNPROVEN') from None

    def _process_alive(self, pid):
        if type(pid) is not int or not 0 < pid <= 2147483647:
            raise BootstrapError('BOOTSTRAP_PROCESS_STATE_UNPROVEN')
        try:
            os.kill(pid, 0)  # Existence probe only; never sends a termination signal.
            return True
        except ProcessLookupError:
            return False
        except OSError:
            raise BootstrapError('BOOTSTRAP_PROCESS_STATE_UNPROVEN') from None

    def _wait_process_exit(self, pid):
        if pid is None:
            return
        deadline = monotonic() + 10
        while self._process_alive(pid) and monotonic() < deadline:
            sleep(0.1)
        if self._process_alive(pid):
            raise BootstrapError('BOOTSTRAP_LEGACY_DRAIN_UNPROVEN')

    def _legacy_loaded_identity(self, service, old):
        from app.market_data.closeout_binding import _arguments, _snapshot
        from app.market_data.captured_recovery_runtime import _read_launchd_service, _verify_loaded_service
        try:
            root = Path(old['root'])
            path = Path.home() / 'Library/LaunchAgents' / f"{old['label']}.plist"
            content = _snapshot(path)[0]
            if hashlib.sha256(content).hexdigest() != old['plist_sha256']:
                raise ValueError
            payload = plistlib.loads(content)
            cwd = Path.home() if service in ('api', 'web') else root
            arguments = ('/bin/bash', str(runtime_directory() / 'run-local-service.sh'), service)
            if service == 'weekly-audit':
                arguments = ('/bin/bash', str(root / 'scripts/ops/macos/run-local-service.sh'), 'weekly-audit-scheduled')
            env = payload.get('EnvironmentVariables', {})
            if (payload.get('Label') != old['label'] or payload.get('WorkingDirectory') != str(cwd)
                    or env.get('GUIYI_PROJECT_ROOT') != old['root']
                    or env.get('GUIYI_RUNTIME_COMMIT') != old['commit']
                    or tuple(payload.get('ProgramArguments', ())) != arguments):
                raise ValueError
            output = _read_launchd_service(old['label'], root=root)
            if output is None:
                return None
            identity = _verify_loaded_service(output, root=root, commit=old['commit'], allow_idle=True, working_directory=cwd)
            if _arguments(output) != arguments or _snapshot(path)[0] != content:
                raise ValueError
            return int(identity['pid']) if 'pid' in identity else None
        except (OSError, ValueError, TypeError, KeyError):
            raise BootstrapError('BOOTSTRAP_LEGACY_IDENTITY_UNPROVEN') from None

    def stop_legacy(self, plan):
        # disable does not stop loaded KeepAlive jobs; track each exact old PID.
        scheduled = ('after-market', 'late-provider-recovery', 'weekly-audit')
        order = [service for service in scheduled if service in plan['installed']]
        order += [service for service in reversed(tuple(plan['installed'])) if service not in scheduled]
        for service in order:
            old = plan['installed'][service]
            label = old['label']
            target = f'gui/{os.getuid()}/{label}'
            if service in ('live', 'alert', 'reference-worker'):
                if getattr(self, '_transport_guards_held', False) is not True:
                    raise BootstrapError('BOOTSTRAP_SEND_GUARDS_REQUIRED')
                self.prove_no_inflight_sends()
            original = None
            if service != 'log-rotate':
                original = self._legacy_loaded_identity(service, old)
                frozen_pid = old.get('loaded_pid')
                if (None if frozen_pid is None else int(frozen_pid)) != original:
                    raise BootstrapError('BOOTSTRAP_LEGACY_PID_DRIFT')
            self._launchctl('disable', target)
            if service in ('api', 'web'):
                self._launchctl('bootout', target, allow_missing=True)
                self._wait_process_exit(original)
                if self._pid(label) is not None:
                    raise BootstrapError('BOOTSTRAP_LEGACY_DRAIN_UNPROVEN')
                continue
            if service == 'log-rotate':
                if self._pid(label) is not None:
                    raise BootstrapError('BOOTSTRAP_LOG_ROTATE_BUSY')
                from app.market_data.closeout_binding import _snapshot
                try:
                    path = Path.home() / 'Library/LaunchAgents' / f'{label}.plist'
                    content = _snapshot(path)[0]
                    frozen = self._legacy_log_rotate(path, plistlib.loads(content), content,
                        b'disabled services = {\n"' + label.encode() + b'" => disabled\n}')
                    if any(frozen[key] != old[key] for key in ('script_path', 'script_sha256', 'plist_sha256')):
                        raise ValueError
                except (OSError, ValueError, TypeError, KeyError):
                    raise BootstrapError('BOOTSTRAP_LOG_ROTATE_DRIFT') from None
                if self._pid(label) is not None:
                    raise BootstrapError('BOOTSTRAP_LOG_ROTATE_BUSY')
                self._launchctl('bootout', target, allow_missing=True)
                continue  # Log rotation must never enter the generic SIGTERM path.
            if service in scheduled:
                if original is not None:
                    raise BootstrapError('BOOTSTRAP_SCHEDULED_WRITER_BUSY')
            elif original is not None:
                try:
                    os.kill(original, signal.SIGTERM)
                except ProcessLookupError:
                    pass  # Exact old PID already exited; never signal its successor.
                except OSError:
                    raise BootstrapError('BOOTSTRAP_LEGACY_SIGNAL_UNPROVEN') from None
                self._wait_process_exit(original)
            revived = self._legacy_loaded_identity(service, old)
            if service in scheduled and revived is not None:
                raise BootstrapError('BOOTSTRAP_SCHEDULED_WRITER_BUSY')
            if service in ('live', 'alert', 'reference-worker'):
                self.prove_no_inflight_sends()
            # Exact old identity is proven and transport guards are still held.
            self._launchctl('bootout', target, allow_missing=True)
            self._wait_process_exit(revived)
            if self._pid(label) is not None:
                raise BootstrapError('BOOTSTRAP_LEGACY_DRAIN_UNPROVEN')

    def migrate_schema(self, plan):
        if self.schema_revision() == _SCHEMA:
            return
        from alembic import command
        from alembic.config import Config
        root = Path(plan['candidate_root']) / 'services/quant-api'
        config = Config(str(root / 'alembic.ini'))
        config.set_main_option('script_location', str(root / 'alembic'))
        command.upgrade(config, _SCHEMA)

    def initialize_cutoffs(self, plan, proof):
        self._assert_rest_still_open()
        from app.market_data.observation_stream import ObservationStream
        from app.redis_connections import get_redis_connection
        day = date.fromisoformat(proof['trading_day'])
        redis = get_redis_connection()
        try:
            source = ObservationStream(redis, kind='source')
            completed = ObservationStream(redis, kind='completed')
            if source.days() or completed.days() or source.tail(day) != '0-0' or completed.tail(day) != '0-0':
                raise BootstrapError('BOOTSTRAP_JOURNAL_NOT_EMPTY')
            # Explicit first baseline, before any publisher; no historical tail is skipped.
            source.initialize('live', day, cursor='0-0')
            for service, consumer in (('alert', 'alert'), ('reference-worker', 'reference')):
                if plan['bindings'].get(service, {}).get('enabled'):
                    completed.initialize(consumer, day, cursor='0-0')
        finally:
            redis.close()

    def install(self, plan):
        directory = runtime_directory()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        root = Path(plan['candidate_root'])
        self._retain_after_market(plan)
        dispatch = (root / 'scripts/ops/macos/runtime-service-dispatch.sh').read_bytes()
        launcher = directory / 'run-local-service.sh'
        if launcher.is_symlink():
            raise BootstrapError('BOOTSTRAP_LAUNCHER_UNSAFE')
        if launcher.exists():
            backup = directory / 'bootstrap-preimage-run-local-service.sh'
            if backup.exists() or backup.is_symlink():
                raise BootstrapError('BOOTSTRAP_PREIMAGE_CONFLICT')
            backup.write_bytes(launcher.read_bytes())
            backup.chmod(0o600)
        launcher.write_bytes(dispatch)
        launcher.chmod(0o700)
        installed_dir = Path.home() / 'Library/LaunchAgents'
        preimages = {}
        for old in plan['installed'].values():
            path = installed_dir / f"{old['label']}.plist"
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != old['plist_sha256']:
                raise BootstrapError('BOOTSTRAP_PLIST_DRIFT')
            preimages[old['label']] = content
        for service, raw in plan['bindings'].items():
            binding = ServiceBinding(**raw)
            old = plan['installed'].get(service) or plan['installed']['live']
            content = preimages[old['label']]
            if hashlib.sha256(content).hexdigest() != old['plist_sha256']:
                raise BootstrapError('BOOTSTRAP_PLIST_DRIFT')
            backup = directory / f"bootstrap-preimage-{old['label']}.plist"
            if not backup.exists():
                backup.write_bytes(content)
                backup.chmod(0o600)
            payload = plistlib.loads(content)
            payload['Label'] = binding.label
            payload['WorkingDirectory'] = str(Path.home()) if service in ('api', 'web') else binding.root
            env = dict(payload.get('EnvironmentVariables', {}))
            env.update(GUIYI_PROJECT_ROOT=binding.root, GUIYI_RUNTIME_TAG=binding.tag,
                GUIYI_RUNTIME_COMMIT=binding.commit, GUIYI_RUNTIME_GENERATION=str(binding.generation),
                GUIYI_OBSERVATION_STREAM_ENABLED='1', GUIYI_RUNTIME_HANDOVER_ENABLED='1')
            payload['EnvironmentVariables'] = env
            payload['ProgramArguments'] = list(authorized_program_arguments(binding, Path.home()))
            payload['Disabled'] = not binding.enabled
            if service == 'market-feed':
                payload['KeepAlive'] = True
                payload['RunAtLoad'] = True
                payload.pop('StartCalendarInterval', None)
            path = installed_dir / f'{binding.label}.plist'
            if path.is_symlink():
                raise BootstrapError('BOOTSTRAP_PLIST_UNSAFE')
            path.write_bytes(plistlib.dumps(payload))
            path.chmod(0o600)
            marker = _MARKERS.get(service)
            if marker and binding.enabled:
                marker_path = root / '.run' / marker
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                if marker_path.is_symlink():
                    raise BootstrapError('BOOTSTRAP_MARKER_UNSAFE')
                marker_path.write_bytes(b'enabled\n')
                marker_path.chmod(0o600)

    def _retain_after_market(self, plan):
        from app.market_data.after_market_history import NAME, _bytes, make_history, read_history, publish_history
        from app.market_data.operational_universe import load_operational_products
        old = plan['installed'].get('after-market')
        if not old:
            return
        status = Path(old['root']) / '.run/after-market-status.json'
        now = datetime.now(UTC)
        products = load_operational_products()
        history = read_history(status.with_name(NAME), products=products, now=now)
        if old.get('status_sha256') is not None:
            content = _bytes(status)
            if hashlib.sha256(content).hexdigest() != old['status_sha256']:
                raise BootstrapError('BOOTSTRAP_AFTER_MARKET_STATUS_DRIFT')
            latest = make_history(content, commit=old['commit'], products=products, now=now)
            if latest:
                history = latest
        if history:
            publish_history(Path(plan['candidate_root']) / '.run' / NAME, history)

    def commit_registry(self, registry):
        write_bindings(registry, expected_sha256=None)

    def start(self, plan):
        self._assert_rest_still_open()
        ordered = ('api', 'web', 'live', 'alert', 'reference-worker', 'market-feed',
                   'after-market', 'late-provider-recovery', 'weekly-audit', 'log-rotate')
        for service in ordered:
            raw = plan['bindings'].get(service)
            if raw and raw['enabled']:
                label = ServiceBinding(**raw).label
                self._launchctl('enable', f'gui/{os.getuid()}/{label}')
                self._launchctl('bootstrap', f'gui/{os.getuid()}', str(Path.home() / 'Library/LaunchAgents' / f'{label}.plist'))

    def _assert_rest_still_open(self):
        from app.db.session import SessionLocal
        from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
        from app.market_data.operational_universe import load_operational_products
        now = datetime.now(UTC)
        with SessionLocal() as session:
            phases = [MarketPhaseResolver(session).resolve(product, now) for product in load_operational_products()]
        if not phases or any(phase.phase not in (MarketPhase.BREAK, MarketPhase.CLOSED)
                or phase.next_session_start and phase.next_session_start <= now + timedelta(seconds=30)
                for phase in phases):
            raise BootstrapError('BOOTSTRAP_REST_WINDOW_CLOSED')

    def verify(self, plan, proof):
        from app.runtime_handover import read_service_state
        deadline = monotonic() + 10
        expected = [service for service in (*_CONTINUOUS, 'market-feed') if plan['bindings'].get(service, {}).get('enabled')]
        while monotonic() < deadline:
            if read_bindings() != BindingRegistry(1, {key: ServiceBinding(**value) for key, value in plan['bindings'].items()}):
                raise BootstrapError('BOOTSTRAP_REGISTRY_DRIFT')
            if all((state := read_service_state(service)) and state.get('generation') == 1 and state.get('phase') == 'active' and state.get('ready') is True and state.get('pid') == self._pid(ServiceBinding(**plan['bindings'][service]).label) for service in expected):
                from app.market_data.observation_stream import ObservationStream
                from app.redis_connections import get_redis_connection
                redis = get_redis_connection()
                try:
                    day = date.fromisoformat(proof['trading_day'])
                    ObservationStream(redis, kind='source').cursor('live', day)
                    completed = ObservationStream(redis, kind='completed')
                    for service, consumer in (('alert', 'alert'), ('reference-worker', 'reference')):
                        if service in expected:
                            completed.cursor(consumer, day)
                    from app.services.deployment_identity import deployment_identity_health
                    identity = deployment_identity_health(root=Path(plan['candidate_root']), commit=plan['commit'])
                    rows = identity.get('services', {})
                    mapping = {'live': 'live_market', 'reference-worker': 'reference_worker', 'market-feed': 'market-feed'}
                    return all(rows.get(mapping.get(service, service), {}).get('status') == 'matched' for service in expected)
                finally:
                    redis.close()
            sleep(0.1)
        return False

    def halt_unknown(self, plan):
        """Park only the exact new generation; let its in-flight effects finish."""
        from app.runtime_handover import request_drain
        expected = BindingRegistry(1, {key: ServiceBinding(**value) for key, value in plan['bindings'].items()})
        if read_bindings() != expected:
            return False  # No authority was committed, or another generation now owns it.
        requested, failed = [], []
        for service in (*_CONTINUOUS, 'market-feed'):
            binding = expected.services.get(service)
            if binding is not None and binding.enabled:
                try:
                    request_drain(service, generation=binding.generation)
                    requested.append(service)
                except Exception:
                    failed.append(service)
        # Prevent subsequent scheduled writes; never kill an unknown running job.
        for service in ('after-market', 'late-provider-recovery', 'weekly-audit', 'log-rotate'):
            binding = expected.services.get(service)
            if binding is not None and binding.enabled:
                try:
                    self._launchctl('disable', f'gui/{os.getuid()}/{binding.label}')
                except Exception:
                    failed.append(service)
        if failed:
            raise BootstrapError('BOOTSTRAP_HALT_UNPROVEN')
        return requested

    def read_legacy_recovery(self):
        """Prove the narrow pre-schema/pre-install boundary; never infer rollback."""
        from app.runtime_bindings import _read as secure_read
        from app.runtime_handover import _read
        from app.market_data.closeout_binding import _snapshot, _arguments
        from app.market_data.captured_recovery_runtime import _read_launchd_service, _verify_loaded_service
        from app.redis_connections import get_redis_connection
        directory = runtime_directory()
        attempt = _read(directory / 'topology-legacy-recovery.json')
        if attempt is not None:
            raise BootstrapError('BOOTSTRAP_RECOVERY_ATTEMPT_READBACK_REQUIRED')
        raw = secure_read(directory / 'topology-bootstrap.json')
        journal = json.loads(raw) if raw else {}
        if (journal.get('phase') != 'outcome_unknown' or journal.get('completed_steps') != []
                or not isinstance(journal.get('plan'), dict)):
            raise BootstrapError('BOOTSTRAP_RECOVERY_BOUNDARY_UNPROVEN')
        plan = journal['plan']
        if plan.get('plan_hash') != _hash({key: value for key, value in plan.items() if key != 'plan_hash'}):
            raise BootstrapError('BOOTSTRAP_RECOVERY_ORIGINAL_PLAN_INVALID')
        if (self.schema_revision() != plan.get('schema_before') or plan.get('schema_before') != '20261009_0050'
                or read_bindings() is not None):
            raise BootstrapError('BOOTSTRAP_RECOVERY_SCHEMA_OR_BINDING_CHANGED')
        if list(directory.glob('bootstrap-preimage-*')) or list(directory.glob('*.owner.json')):
            raise BootstrapError('BOOTSTRAP_RECOVERY_INSTALL_OR_OWNER_PRESENT')
        redis = get_redis_connection()
        try:
            if next(iter(redis.scan_iter(match='live:observations:*')), None) is not None:
                raise BootstrapError('BOOTSTRAP_RECOVERY_STREAM_PRESENT')
        finally:
            redis.close()
        disabled = parse_disabled_states(self._launchctl('print-disabled', f'gui/{os.getuid()}').stdout)
        launcher = _snapshot(directory / 'run-local-service.sh')[0]
        observed, actions = {}, []
        self.candidate_root = Path(plan['candidate_root'])
        for service, old in plan['installed'].items():
            label = old['label']
            path = Path.home() / 'Library/LaunchAgents' / f'{label}.plist'
            content = _snapshot(path)[0]
            if hashlib.sha256(content).hexdigest() != old['plist_sha256']:
                raise BootstrapError('BOOTSTRAP_RECOVERY_PLIST_DRIFT')
            payload = plistlib.loads(content)
            is_disabled = disabled.get(label, False) or payload.get('Disabled', False)
            if service == 'log-rotate':
                current = self._legacy_log_rotate(path, payload, content,
                    self._launchctl('print-disabled', f'gui/{os.getuid()}').stdout)
                if current['enabled'] != old['enabled']:
                    raise BootstrapError('BOOTSTRAP_RECOVERY_UNSUPPORTED_CHANGE')
                observed[service] = current
                continue
            root = Path(old['root'])
            env = payload.get('EnvironmentVariables', {})
            if (env.get('GUIYI_PROJECT_ROOT') != str(root) or env.get('GUIYI_RUNTIME_COMMIT') != old['commit']
                    or (env.get('GUIYI_RUNTIME_TAG') is not None and env['GUIYI_RUNTIME_TAG'] != old['tag'])):
                raise BootstrapError('BOOTSTRAP_RECOVERY_PLIST_IDENTITY_DRIFT')
            verify_release(root, old['tag'], old['commit'])
            if launcher != _snapshot(root / 'scripts/ops/macos/run-local-service.sh')[0]:
                raise BootstrapError('BOOTSTRAP_RECOVERY_LAUNCHER_DRIFT')
            loaded = _read_launchd_service(label, root=root)
            current = dict(old)
            current['disabled'] = bool(is_disabled)
            current['loaded_pid'] = None
            if loaded is not None:
                identity = _verify_loaded_service(loaded, root=root, commit=old['commit'],
                    allow_idle=service not in _CONTINUOUS, require_idle=service not in _CONTINUOUS,
                    working_directory=Path(payload['WorkingDirectory']))
                if _arguments(loaded) != tuple(payload['ProgramArguments']):
                    raise BootstrapError('BOOTSTRAP_RECOVERY_LOADED_ARGV_DRIFT')
                current['loaded_pid'] = (str(identity['pid']) if identity.get('pid') is not None else None)
            if service in _CONTINUOUS:
                if old['enabled'] and current['loaded_pid'] is None:
                    raise BootstrapError('BOOTSTRAP_RECOVERY_BUSINESS_MISSING')
                if bool(is_disabled) == bool(old['enabled']):
                    if service != 'web' or not old['enabled'] or loaded is None:
                        raise BootstrapError('BOOTSTRAP_RECOVERY_UNSUPPORTED_CHANGE')
                    actions.append({'service': service, 'action': 'enable_loaded'})
            elif old['enabled'] and loaded is None:
                self._assert_recovery_calendar_safe(payload)
                actions.append({'service': service, 'action': 'enable_calendar'})
            elif bool(is_disabled) == bool(old['enabled']):
                raise BootstrapError('BOOTSTRAP_RECOVERY_UNSUPPORTED_CHANGE')
            observed[service] = current
        proof_plan = dict(plan, installed=observed)
        boundary = self.prove_safe_boundary(proof_plan)
        with self.writer_guards(proof_plan):
            self.prove_no_inflight_sends()
        result = {'schema_version': 1, 'kind': 'legacy_recovery',
            'original_journal_sha256': hashlib.sha256(raw).hexdigest(),
            'original_plan_hash': plan['plan_hash'], 'schema_before': plan['schema_before'],
            'launcher_sha256': hashlib.sha256(launcher).hexdigest(),
            'trading_day': boundary['trading_day'], 'installed': observed, 'actions': actions,
            'proof_plan': proof_plan}
        result['plan_hash'] = _hash(result)
        return result

    def _assert_recovery_calendar_safe(self, payload):
        if payload.get('RunAtLoad', False) or payload.get('KeepAlive', False):
            raise BootstrapError('BOOTSTRAP_RECOVERY_JOB_AUTOSTART')
        calendars = payload.get('StartCalendarInterval')
        if isinstance(calendars, dict):
            calendars = [calendars]
        if not isinstance(calendars, list) or not calendars:
            raise BootstrapError('BOOTSTRAP_RECOVERY_CALENDAR_UNPROVEN')
        now = datetime.now().astimezone()
        for entry in calendars:
            if (not isinstance(entry, dict) or set(entry) - {'Hour', 'Minute', 'Weekday', 'Day', 'Month'}
                    or any(type(value) is not int for value in entry.values())
                    or not 0 <= entry.get('Hour', -1) <= 23 or not 0 <= entry.get('Minute', -1) <= 59):
                raise BootstrapError('BOOTSTRAP_RECOVERY_CALENDAR_UNPROVEN')
            for delta in range(-3, 4):
                at = now + timedelta(minutes=delta)
                if (at.hour == entry['Hour'] and at.minute == entry['Minute']
                        and entry.get('Weekday', (at.weekday() + 1) % 7) in ((at.weekday() + 1) % 7, 7 if at.weekday() == 6 else -1)
                        and entry.get('Day', at.day) == at.day and entry.get('Month', at.month) == at.month):
                    raise BootstrapError('BOOTSTRAP_RECOVERY_CALENDAR_DUE')

    def recover_legacy(self, recovery):
        from app.runtime_bindings import _read as secure_read
        if not isinstance(recovery, dict) or recovery.get('plan_hash') != _hash({
                key: value for key, value in recovery.items() if key != 'plan_hash'}):
            raise BootstrapError('BOOTSTRAP_RECOVERY_PLAN_INVALID')
        fresh = self.read_legacy_recovery()
        if fresh['plan_hash'] != recovery['plan_hash']:
            raise BootstrapError('BOOTSTRAP_RECOVERY_PLAN_DRIFT')
        directory = runtime_directory()
        original = secure_read(directory / 'topology-bootstrap.json')
        archive = directory / f"topology-bootstrap-original-{recovery['original_journal_sha256']}.json"
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(original)
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            raise BootstrapError('BOOTSTRAP_RECOVERY_ARCHIVE_UNPROVEN') from None
        attempt = {'phase': 'prepared', 'plan': recovery, 'completed_actions': []}
        _write(directory / 'topology-legacy-recovery.json', attempt)
        try:
            with self.writer_guards(recovery['proof_plan']):
                self._assert_rest_still_open()
                self._assert_legacy_recovery_unchanged(recovery)
                for action in recovery['actions']:
                    old = recovery['installed'][action['service']]
                    target = f"gui/{os.getuid()}/{old['label']}"
                    if (str(pid) if (pid := self._pid(old['label'])) is not None else None) != old['loaded_pid']:
                        raise BootstrapError('BOOTSTRAP_RECOVERY_PID_DRIFT')
                    self._launchctl('enable', target)
                    if action['action'] == 'enable_calendar':
                        path = Path.home() / 'Library/LaunchAgents' / f"{old['label']}.plist"
                        self._assert_recovery_calendar_safe(plistlib.loads(path.read_bytes()))
                        self._launchctl('bootstrap', f'gui/{os.getuid()}', str(path))
                        if self._pid(old['label']) is not None:
                            raise BootstrapError('BOOTSTRAP_RECOVERY_JOB_STARTED')
                    attempt['completed_actions'].append(action)
                    _write(directory / 'topology-legacy-recovery.json', attempt)
                actual = self.installed()
                for service, old in recovery['proof_plan']['installed'].items():
                    current = actual.get(service)
                    if current is None or any(current.get(key) != old.get(key) for key in (
                            'root', 'commit', 'tag', 'label', 'enabled', 'plist_sha256')):
                        raise BootstrapError('BOOTSTRAP_RECOVERY_READBACK_FAILED')
                    if service in _CONTINUOUS and (str(current['loaded_pid']) if current['loaded_pid'] is not None else None) != old['loaded_pid']:
                        raise BootstrapError('BOOTSTRAP_RECOVERY_PID_DRIFT')
                self.prove_no_inflight_sends()
                journal = json.loads(original)
                journal.update(phase='recovered_legacy', recovery_plan_hash=recovery['plan_hash'],
                    original_journal_sha256=recovery['original_journal_sha256'], original_journal_archive=str(archive))
                self.journal(journal)
                attempt['phase'] = 'recovered_legacy'
                _write(directory / 'topology-legacy-recovery.json', attempt)
            return {'status': 'recovered_legacy', 'plan_hash': recovery['plan_hash']}
        except Exception:
            attempt['phase'] = 'outcome_unknown'
            try:
                _write(directory / 'topology-legacy-recovery.json', attempt)
            except Exception:
                pass
            raise BootstrapError('BOOTSTRAP_RECOVERY_OUTCOME_UNKNOWN') from None

    def _assert_legacy_recovery_unchanged(self, recovery):
        from app.runtime_bindings import _read as secure_read
        from app.market_data.closeout_binding import _snapshot
        from app.redis_connections import get_redis_connection
        directory = runtime_directory()
        raw = secure_read(directory / 'topology-bootstrap.json')
        if (raw is None or hashlib.sha256(raw).hexdigest() != recovery['original_journal_sha256']
                or self.schema_revision() != recovery['schema_before'] or read_bindings() is not None
                or list(directory.glob('bootstrap-preimage-*')) or list(directory.glob('*.owner.json'))):
            raise BootstrapError('BOOTSTRAP_RECOVERY_PLAN_DRIFT')
        if hashlib.sha256(_snapshot(directory / 'run-local-service.sh')[0]).hexdigest() != recovery['launcher_sha256']:
            raise BootstrapError('BOOTSTRAP_RECOVERY_LAUNCHER_DRIFT')
        redis = get_redis_connection()
        try:
            if next(iter(redis.scan_iter(match='live:observations:*')), None) is not None:
                raise BootstrapError('BOOTSTRAP_RECOVERY_STREAM_PRESENT')
        finally:
            redis.close()
        disabled = parse_disabled_states(self._launchctl('print-disabled', f'gui/{os.getuid()}').stdout)
        for service, old in recovery['installed'].items():
            path = Path.home() / 'Library/LaunchAgents' / f"{old['label']}.plist"
            content = _snapshot(path)[0]
            if hashlib.sha256(content).hexdigest() != old['plist_sha256']:
                raise BootstrapError('BOOTSTRAP_RECOVERY_PLIST_DRIFT')
            payload = plistlib.loads(content)
            if service != 'log-rotate' and (
                    bool(disabled.get(old['label'], False) or payload.get('Disabled', False)) != old['disabled']
                    or (str(pid) if (pid := self._pid(old['label'])) is not None else None) != old['loaded_pid']):
                raise BootstrapError('BOOTSTRAP_RECOVERY_PID_OR_ENABLE_DRIFT')

    def journal(self, payload):
        _write(runtime_directory() / 'topology-bootstrap.json', payload)


def main(argv=None, *, backend=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--candidate-root", type=Path, required=True)
    plan.add_argument("--tag", required=True)
    plan.add_argument("--commit", required=True)
    plan.add_argument("--output", type=Path)
    apply = commands.add_parser("apply")
    apply.add_argument("--plan", type=Path, required=True)
    recovery_readback = commands.add_parser('recover-readback')
    recovery_readback.add_argument('--output', type=Path)
    recovery_apply = commands.add_parser('recover-legacy')
    recovery_apply.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode in ('plan', 'recover-readback'):
            result = (build_bootstrap_plan(args.candidate_root, args.tag, args.commit, backend=backend)
                if args.mode == 'plan' else (backend or BootstrapBackend()).read_legacy_recovery())
            if args.output:
                if not args.output.is_absolute() or args.output.exists() or args.output.is_symlink():
                    raise BootstrapError("BOOTSTRAP_PLAN_OUTPUT_UNSAFE")
                _write(args.output, result)
        else:
            from app.runtime_bindings import _read as read_secure_plan
            from app.runtime_handover import deployment_lock
            with deployment_lock():
                raw = read_secure_plan(args.plan)
                if raw is None:
                    raise BootstrapError("BOOTSTRAP_PLAN_MISSING")
                result = (apply_bootstrap_plan(json.loads(raw), backend=backend) if args.mode == 'apply'
                    else (backend or BootstrapBackend()).recover_legacy(json.loads(raw)))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, BootstrapError) and re.fullmatch(r"[A-Z0-9_]{1,96}", str(error)) else "TOPOLOGY_BOOTSTRAP_BLOCKED"
        print(json.dumps({"status": "blocked", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
