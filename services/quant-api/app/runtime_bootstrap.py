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
import subprocess
from time import monotonic, sleep

from app.runtime_bindings import (BindingRegistry, ServiceBinding, contract_fingerprints,
    read_bindings, verify_release, write_bindings)
from app.runtime_handover import _write, runtime_directory

_CONTINUOUS = ('api', 'web', 'live', 'alert', 'reference-worker')
_MARKERS = {'live': 'market-runtime-enabled', 'alert': 'alert-runtime-enabled',
            'reference-worker': 'reference-worker-enabled', 'weekly-audit': 'weekly-audit-enabled'}
_SCHEMA = '20261009_0051'


class BootstrapError(RuntimeError):
    pass


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
        journal = _read(runtime_directory() / 'topology-bootstrap.json')
        if journal and journal.get('phase') not in ('switched', 'precondition_blocked'):
            raise BootstrapError('BOOTSTRAP_RECOVERY_READBACK_REQUIRED')
        return read_bindings() is not None

    def verify_candidate(self, root, tag, commit):
        verify_release(root, tag, commit)

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
            content = path.read_bytes()
            payload = plistlib.loads(content)
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
            explicitly_disabled = re.search(rb'"' + label.encode() + rb'"\s*=>\s*true', disabled) is not None
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
            self.prove_no_inflight_sends()
            return {'trading_day': next(iter(days)), 'checked_at': now.isoformat(), 'products': len(products),
                    'legacy_last_bar_at': heartbeat.get('last_bar_at')}
        finally:
            redis.close()

    def prove_no_inflight_sends(self):
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
                attempted = status.get('last_transport_attempt_at')
                accepted = status.get('last_provider_accepted_at')
                if attempted and (not accepted or datetime.fromisoformat(accepted) < datetime.fromisoformat(attempted)):
                    raise BootstrapError('BOOTSTRAP_ALERT_SEND_UNKNOWN')
                if status.get('notification_error_type'):
                    raise BootstrapError('BOOTSTRAP_ALERT_SEND_UNKNOWN')
        finally:
            redis.close()

    @contextmanager
    def writer_guards(self, plan):
        from app.db.session import SessionLocal
        from app.market_data.catalog import MarketCatalog
        from app.market_data.composition import canonical_root
        from app.market_data.live_recovery_guard import after_market_recovery_guard
        with ExitStack() as stack:
            roots = {Path(plan['installed'][service]['root']) for service in ('live', 'after-market') if service in plan['installed']}
            for root in sorted(roots):
                stack.enter_context(after_market_recovery_guard(root=root / ".run/live-recovery-guards", wait=False, legacy_root=True))
            from app.market_data.live_recovery_guard import recovery_guard
            from app.market_data.operational_universe import load_operational_products
            guard_roots = {Path(plan['installed'][service]['root']) for service in ('live', 'alert') if service in plan['installed']}
            for root in sorted(guard_roots):
                for product in load_operational_products():
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
            if plan['installed'].get('alert', {}).get('enabled'):
                from app.redis_connections import get_redis_connection
                redis = get_redis_connection()
                try:
                    raw = redis.get('alert:heartbeat')
                    heartbeat = json.loads(raw) if raw else {}
                    old_alert = plan['installed']['alert']
                    generated = datetime.fromisoformat(heartbeat.get('generated_at', ''))
                    if (heartbeat.get('recovery_guard_enabled') is not True
                            or heartbeat.get('runtime_root') != old_alert['root']
                            or heartbeat.get('runtime_commit') != old_alert['commit']
                            or not 0 <= (datetime.now(UTC) - generated).total_seconds() <= 30):
                        raise BootstrapError('BOOTSTRAP_LEGACY_ALERT_DRAIN_UNSUPPORTED')
                finally:
                    redis.close()
            self.prove_no_inflight_sends()
            lease = MarketCatalog(session, canonical_root()).acquire_maintenance_lock()
            if lease is None:
                raise BootstrapError('BOOTSTRAP_CATALOG_WRITER_BUSY')
            stack.callback(lease.release)
            for service in ('after-market', 'late-provider-recovery', 'weekly-audit'):
                old = plan['installed'].get(service)
                if old and self._pid(old['label']) is not None:
                    raise BootstrapError('BOOTSTRAP_SCHEDULED_WRITER_BUSY')
            yield

    def _launchctl(self, *args, allow_missing=False):
        result = subprocess.run(['/bin/launchctl', *args], capture_output=True, timeout=15)
        if result.returncode and not (allow_missing and result.returncode == 113):
            raise BootstrapError('BOOTSTRAP_LAUNCHD_OPERATION_FAILED')
        return result

    def _pid(self, label):
        result = self._launchctl('print', f'gui/{os.getuid()}/{label}', allow_missing=True)
        if result.returncode:
            return None
        match = re.search(rb'^\s*pid = ([0-9]+)\s*$', result.stdout, re.M)
        return int(match[1]) if match else None

    def stop_legacy(self, plan):
        # Disable launchd restart before SIGTERM. Never call bootout on a live pid.
        scheduled = ('after-market', 'late-provider-recovery', 'weekly-audit')
        order = [service for service in scheduled if service in plan['installed']]
        order += [service for service in reversed(tuple(plan['installed'])) if service not in scheduled]
        for service in order:
            old = plan['installed'][service]
            label = old['label']
            target = f'gui/{os.getuid()}/{label}'
            self._launchctl('disable', target)
            if self._pid(label) is not None:
                self._launchctl('kill', 'SIGTERM', target)
                deadline = monotonic() + 10
                while self._pid(label) is not None and monotonic() < deadline:
                    sleep(0.1)
                if self._pid(label) is not None:
                    raise BootstrapError('BOOTSTRAP_LEGACY_DRAIN_UNPROVEN')
            self._launchctl('bootout', target, allow_missing=True)

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
            payload['ProgramArguments'] = ['/bin/bash', str(launcher), service]
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
    args = parser.parse_args(argv)
    try:
        if args.mode == "plan":
            result = build_bootstrap_plan(args.candidate_root, args.tag, args.commit, backend=backend)
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
                result = apply_bootstrap_plan(json.loads(raw), backend=backend)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, BootstrapError) and re.fullmatch(r"[A-Z0-9_]{1,96}", str(error)) else "TOPOLOGY_BOOTSTRAP_BLOCKED"
        print(json.dumps({"status": "blocked", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
