"""Exact, local Runtime planning and cooperative launchd handover.

No download, notification, migration or historical replay is performed here.
Uncertain post-activation results are terminal and are never automatically retried.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import signal
from time import monotonic, sleep
from uuid import uuid4

from app.runtime_bindings import (BindingRegistry, ServiceBinding,
    bindings_sha256, build_release_plan, read_bindings, resolve_service_binding, write_bindings)
from app.runtime_handover import (_read, _write, runtime_directory,
    request_drain, cancel_drain, read_service_state, owner_lock_available, deployment_lock)

CONTINUOUS = frozenset({'api', 'web', 'market-feed', 'live', 'alert', 'reference-worker'})


class DeploymentError(RuntimeError):
    pass


def execute_handover(service, previous, candidate, *, backend, commit_binding):
    """Never move the authority before readiness and cooperative drain are proven."""
    request = uuid4().hex
    try:
        if not backend.prepare(service, candidate, request):
            backend.cancel(service, previous, request)
            return 'candidate_not_ready'
        if not backend.drain_owner(service, previous, request):
            backend.cancel(service, previous, request)
            return 'drain_cancelled'
    except Exception:
        backend.cancel(service, previous, request)
        raise DeploymentError('RUNTIME_HANDOVER_PRECONDITION_BLOCKED') from None
    try:
        commit_binding()
        backend.activate(service, candidate, request)
        if not backend.verify(service, candidate, request):
            raise DeploymentError('RUNTIME_HANDOVER_OUTCOME_UNKNOWN')
        backend.retire(service, previous, request)
    except Exception:
        halt = getattr(backend, 'halt_unknown', None)
        if halt is not None:
            halt(service, candidate, request)
        # Commit or provider effects may have happened. Do not cancel/resume blindly.
        raise DeploymentError('RUNTIME_HANDOVER_OUTCOME_UNKNOWN') from None
    return 'switched'


def _launchctl(*args):
    try:
        subprocess.run(['/bin/launchctl', *args], check=True, capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        raise DeploymentError('LAUNCHD_OPERATION_FAILED') from None


def _ready_path(service, request):
    if service not in CONTINUOUS or len(request) != 32 or any(c not in '0123456789abcdef' for c in request):
        raise DeploymentError('CANDIDATE_IDENTITY_INVALID')
    return runtime_directory() / f'{service}.candidate-{request}.json'


def _stream_id(identifier):
    try:
        parts = identifier.split('-')
        if len(parts) != 2 or any(not p.isdigit() for p in parts):
            raise ValueError
        return tuple(map(int, parts))
    except (AttributeError, ValueError):
        raise DeploymentError('OBSERVATION_CURSOR_INVALID') from None


def observation_progress(service):
    if service not in {'market-feed', 'live', 'alert', 'reference-worker'}:
        return {}
    from app.redis_connections import get_redis_connection
    from app.market_data.observation_stream import ObservationStream
    kind = 'source' if service in {'market-feed', 'live'} else 'completed'
    consumer = {'market-feed': 'live', 'live': 'live', 'alert': 'alert', 'reference-worker': 'reference'}[service]
    stream = ObservationStream(get_redis_connection(), kind=kind)
    day = stream.registered_day(consumer)
    days = stream.days()
    if day not in days:
        raise DeploymentError('OBSERVATION_DAY_MISSING')
    return {d.isoformat(): {'cursor': stream.cursor(consumer, d), 'tail': stream.tail(d)} for d in days}


def merge_progress(before, drained):
    result = dict(before)
    for day, value in drained.items():
        old = result.get(day, {'cursor': '0-0', 'tail': '0-0'})
        if _stream_id(value['cursor']) < _stream_id(old['cursor']):
            raise DeploymentError('OBSERVATION_PROGRESS_REGRESSED')
        result[day] = {'cursor': value['cursor'], 'tail': old['tail']}
    return result


def progress_reached(current, boundary, *, service=None, proof=None):
    for day, value in boundary.items():
        if day not in current:
            raise DeploymentError('OBSERVATION_DAY_EXPIRED')
        cursor = _stream_id(current[day]['cursor'])
        if cursor < _stream_id(value['cursor']):
            return False
        if cursor < _stream_id(value['tail']):
            # Future input is read but remains unacknowledged until completed.
            if (service != 'live' or not proof or proof.get('trading_day') != day
                    or _stream_id(proof.get('input_read_frontier')) < _stream_id(value['tail'])):
                return False
    return True


def prove_feed_quiescent(binding):
    from datetime import UTC, datetime
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_feed_service
    from app.redis_connections import get_redis_connection
    now = datetime.now(UTC)
    with SessionLocal() as session:
        if not build_market_feed_service(session).quiescent(now):
            raise DeploymentError('MARKET_FEED_SESSION_BREAK_REQUIRED')
    raw = get_redis_connection().get('live:feed:heartbeat')
    if raw is None:
        raise DeploymentError('MARKET_FEED_HEARTBEAT_MISSING')
    value = json.loads(raw)
    generated = datetime.fromisoformat(value['generated_at'])
    if (not 0 <= (now-generated).total_seconds() <= 30 or value.get('input_pending_count') != 0
            or value.get('runtime_generation') != binding.generation
            or value.get('runtime_commit') != binding.commit):
        raise DeploymentError('MARKET_FEED_DRAIN_UNPROVEN')
    progress = observation_progress('market-feed')
    if any(v['cursor'] != v['tail'] for v in progress.values()):
        raise DeploymentError('MARKET_FEED_SOURCE_DRAIN_UNPROVEN')


def owner_process_matches(state, binding):
    from app.market_data.captured_recovery_runtime import _read_launchd_service, _verify_loaded_service
    output = _read_launchd_service(binding.label, root=Path(binding.root))
    if output is None:
        return False
    directory = Path.home() if binding.service in {'api', 'web'} else Path(binding.root)
    fields = _verify_loaded_service(output, root=Path(binding.root), commit=binding.commit,
                                    working_directory=directory)
    return str(state.get('pid')) == fields.get('pid')


def warmup_service(service):
    """Read-only candidate work; no runtime loop or sender is started."""
    if service == 'alert':
        from app.alerts.composition import warmup_alert_runtime
        return warmup_alert_runtime()
    if service == 'reference-worker':
        from app.reference_trading.worker_entry import warmup_reference_worker
        return warmup_reference_worker()
    if service in {'market-feed', 'live'}:
        from app.db.session import SessionLocal
        from app.market_data.composition import build_market_data_service
        from app.market_data.operational_universe import load_operational_products
        from app.market_data.market_phase import MarketPhaseResolver
        from datetime import UTC, datetime
        with SessionLocal() as session:
            market = build_market_data_service(session)
            resolver = MarketPhaseResolver(session)
            products = load_operational_products()
            progress = observation_progress(service)
            for product in products:
                phase = resolver.resolve(product, datetime.now(UTC))
                if phase.trading_day is None:
                    raise DeploymentError('CANDIDATE_SESSION_UNKNOWN')
                market.dominant_segment_for_day(product, phase.trading_day)
            if not products:
                raise DeploymentError('CANDIDATE_SCOPE_EMPTY')
            return {'products': len(products), 'progress': progress}
    if service == 'api':
        from app.main import app
        return {'routes': len(app.routes)}
    if service == 'web':
        from app.core.env import PROJECT_ROOT
        path = PROJECT_ROOT / 'apps/quant-web/dist/index.html'
        if not path.is_file() or path.is_symlink():
            raise DeploymentError('WEB_BUILD_MISSING')
        return {'build_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    raise DeploymentError('SERVICE_HANDOVER_UNSUPPORTED')


def port_is_ready(service):
    from urllib.request import urlopen
    url = 'http://127.0.0.1:8000/api/health' if service == 'api' else 'http://127.0.0.1:5173/'
    try:
        with urlopen(url, timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def _run_port_service(service):
    from app.core.env import PROJECT_ROOT
    from app.runtime_handover import run_supervised
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    if service == 'api':
        command = [str(PROJECT_ROOT / 'services/quant-api/.venv/bin/python'), '-m', 'uvicorn',
                   'app.main:app', '--app-dir', str(PROJECT_ROOT / 'services/quant-api'),
                   '--host', '127.0.0.1', '--port', '8000', '--workers', '1', '--no-access-log']
    else:
        command = ['/opt/homebrew/bin/node', str(PROJECT_ROOT / 'apps/quant-web/node_modules/vite/bin/vite.js'),
                   'preview', str(PROJECT_ROOT / 'apps/quant-web'), '--host', '127.0.0.1', '--port', '5173']
    def run(owner):
        owner.assert_owned()
        child = subprocess.Popen(command, cwd=PROJECT_ROOT)
        try:
            while child.poll() is None and not stopped and not owner.should_drain():
                owner.assert_owned()
                if port_is_ready(service):
                    owner.mark_ready({'http_ready': True})
                sleep(0.1)
            if child.poll() is not None and not stopped:
                raise DeploymentError('PORT_SERVICE_EXITED')
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait()  # Do not release the parent lock while its port child lives.
    try:
        run_supervised(service, run, stop_requested=lambda: stopped)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def run_candidate(service, request, generation):
    from app.core.env import PROJECT_ROOT
    result = warmup_service(service)
    _write(_ready_path(service, request), {'schema_version': 1, 'service': service,
        'request_id': request, 'generation': generation, 'root': str(PROJECT_ROOT),
        'commit': os.environ['GUIYI_RUNTIME_COMMIT'], 'ready': True, 'proof': result})
    # Remain this same supervised process; launchd labels cannot be renamed without restarting.
    while True:
        binding = resolve_service_binding(service)
        if (binding is not None and binding.generation == generation
                and binding.root == str(PROJECT_ROOT)
                and binding.commit == os.environ['GUIYI_RUNTIME_COMMIT']):
            break
        sleep(0.1)
    if service in {'api', 'web'}:
        _run_port_service(service)
    elif service == 'reference-worker':
        from app.reference_trading.worker_entry import main
        main()
    else:
        from app.runtime_entry import entrypoint
        sys.argv = [sys.argv[0], service]
        entrypoint()


class LaunchdBackend:
    """Candidate label becomes the bound active label, then is retired next upgrade."""
    def __init__(self):
        self.candidates = {}
        self.drains = {}
        self.boundaries = {}

    def prepare(self, service, binding, request):
        if service not in CONTINUOUS:
            raise DeploymentError('SERVICE_HANDOVER_UNSUPPORTED')
        old = resolve_service_binding(service)
        if old is None:
            raise DeploymentError('SERVICE_BINDING_REQUIRED')
        _write(runtime_directory() / 'deployment-outcome.json', {
            'schema_version': 1, 'phase': 'prepared', 'service': service,
            'request_id': request, 'previous_generation': old.generation,
            'generation': binding.generation, 'root': binding.root, 'commit': binding.commit})
        try:
            installed = Path.home() / 'Library/LaunchAgents' / f'{old.label}.plist'
            with installed.open('rb') as handle:
                payload = plistlib.load(handle)
            candidate = replace(binding, launchd_label=f'com.guiyi.quant-{service}-candidate-{request}')
            self.candidates[service] = candidate
            payload['Label'] = candidate.label
            payload['WorkingDirectory'] = str(Path.home()) if service in {'api', 'web'} else candidate.root
            payload['KeepAlive'] = True
            payload['RunAtLoad'] = True
            environment = dict(payload['EnvironmentVariables'])
            environment.update(GUIYI_PROJECT_ROOT=candidate.root, GUIYI_RUNTIME_COMMIT=candidate.commit,
                GUIYI_RUNTIME_TAG=candidate.tag, GUIYI_RUNTIME_GENERATION=str(candidate.generation),
                GUIYI_RUNTIME_HANDOVER_ENABLED='1', GUIYI_OBSERVATION_STREAM_ENABLED='1')
            payload['EnvironmentVariables'] = environment
            payload['ProgramArguments'] = ['/bin/bash', str(runtime_directory() / 'run-local-service.sh'),
                'handover-candidate', service, request, str(candidate.generation)]
            path = installed.parent / f'{candidate.label}.plist'
            if path.exists() or path.is_symlink():
                raise DeploymentError('CANDIDATE_LABEL_EXISTS')
            with path.open('xb') as handle:
                handle.write(plistlib.dumps(payload))
            path.chmod(0o600)
            _launchctl('bootstrap', f'gui/{os.getuid()}', str(path))
            deadline = monotonic() + 120
            while monotonic() < deadline:
                proof = _read(_ready_path(service, request))
                if proof is not None:
                    return (proof.get('ready') is True and proof.get('root') == candidate.root
                            and proof.get('commit') == candidate.commit
                            and proof.get('generation') == candidate.generation
                            and proof.get('request_id') == request)
                sleep(0.1)
            return False
        except (OSError, ValueError, DeploymentError):
            return False

    def drain_owner(self, service, binding, request):
        self.boundaries[service] = observation_progress(service)
        self.drains[service] = request_drain(service, generation=binding.generation)
        deadline = monotonic() + 10
        while monotonic() < deadline:
            state = read_service_state(service)
            if (state is not None and state.get('phase') == 'parked'
                    and state.get('generation') == binding.generation):
                # State is a progress report; only the actual OS lock proves no in-flight effects.
                if owner_lock_available(service):
                    drained = observation_progress(service)
                    self.boundaries[service] = merge_progress(self.boundaries[service], drained)
                    if service == 'market-feed':
                        prove_feed_quiescent(binding)
                    return True
            sleep(0.05)
        return False

    def activate(self, service, binding, request):
        # The parked candidate observes the exact registry CAS; no second restart.
        pass

    def verify(self, service, binding, request):
        candidate = self.candidates[service]
        deadline = monotonic() + 10
        while monotonic() < deadline:
            state = read_service_state(service)
            if state and state.get('phase') == 'active' and state.get('generation') == candidate.generation and state.get('ready') is True:
                from app.services.deployment_identity import deployment_identity_health
                identity = deployment_identity_health(root=Path(candidate.root), commit=candidate.commit)
                rows = identity.get('services', {})
                mapping = {'live': 'live_market', 'reference-worker': 'reference_worker', 'market-feed': 'market-feed'}
                if (rows.get(mapping.get(service, service), {}).get('status') == 'matched'
                        and owner_process_matches(state, candidate)
                        and progress_reached(observation_progress(service), self.boundaries[service],
                                             service=service, proof=state.get('proof'))
                        and (service not in {'api', 'web'} or port_is_ready(service))):
                    return True
            sleep(0.1)
        return False

    def halt_unknown(self, service, binding, request):
        candidate = self.candidates[service]
        # A failed registry commit must not revoke a still-authoritative old process.
        if resolve_service_binding(service) != candidate:
            return
        try:
            _write(runtime_directory() / 'deployment-outcome.json', {
                'schema_version': 1, 'phase': 'outcome_unknown', 'service': service,
                'request_id': request, 'root': candidate.root, 'commit': candidate.commit,
                'generation': candidate.generation})
        finally:
            # Prepared journal remains nonterminal if writing fails. Still attempt
            # cooperative stop independently; never kill an in-flight transport.
            request_drain(service, generation=candidate.generation)

    def retire(self, service, binding, request):
        _launchctl('bootout', f'gui/{os.getuid()}/{binding.label}')
        # Only this exact previously bound label is eligible; no broad cleanup.
        path = Path.home() / 'Library/LaunchAgents' / f'{binding.label}.plist'
        path.unlink()
        _write(runtime_directory() / 'deployment-outcome.json', {
            'schema_version': 1, 'phase': 'switched', 'service': service, 'request_id': request})

    def cancel(self, service, binding, request):
        if service in self.drains:
            cancel_drain(service, request_id=self.drains[service])
        candidate = self.candidates.get(service)
        if candidate is not None:
            _launchctl('bootout', f'gui/{os.getuid()}/{candidate.label}')
            (Path.home() / 'Library/LaunchAgents' / f'{candidate.label}.plist').unlink()
        _write(runtime_directory() / 'deployment-outcome.json', {
            'schema_version': 1, 'phase': 'cancelled', 'service': service, 'request_id': request})


def assert_no_unknown_deployment():
    journal = _read(runtime_directory() / 'deployment-outcome.json')
    if journal and journal.get('phase') not in {'switched', 'cancelled'}:
        raise DeploymentError('RUNTIME_HANDOVER_RECOVERY_READBACK_REQUIRED')
    from app.runtime_scheduled import SCHEDULED
    for service in SCHEDULED:
        state = _read(runtime_directory() / f'{service}.scheduled-update.json')
        if state and state.get('phase') not in {'switched', 'scheduled_busy', 'precondition_blocked'}:
            raise DeploymentError('SCHEDULED_RECOVERY_READBACK_REQUIRED')


def apply_plan(payload):
    assert_no_unknown_deployment()
    registry = read_bindings()
    if registry is None:
        raise DeploymentError('TOPOLOGY_BOOTSTRAP_REQUIRED')
    identity = payload['candidate']
    fresh = build_release_plan(registry, candidate_root=Path(identity['root']), tag=identity['tag'],
                               commit=identity['commit'], registry_sha256=bindings_sha256())
    if fresh != payload or fresh['status'] != 'ready':
        raise DeploymentError('RELEASE_PLAN_DRIFT_OR_BLOCKED')
    backend = LaunchdBackend()
    results = {}
    # Preflight all services before changing any owner, including unimplemented job transitions.
    affected = [s for s in payload['affected_services']
                if registry.services[s].enabled or s in {'after-market', 'late-provider-recovery', 'weekly-audit', 'log-rotate'}]
    from app.runtime_scheduled import SCHEDULED
    if set(affected) - (CONTINUOUS | SCHEDULED):
        raise DeploymentError('SERVICE_HANDOVER_UNSUPPORTED')
    from app.services.deployment_identity import deployment_identity_health
    authority = registry.services.get('api') or next(iter(registry.services.values()))
    identity_rows = deployment_identity_health(root=Path(authority.root), commit=authority.commit).get('services', {})
    names = {'live': 'live_market', 'reference-worker': 'reference_worker', 'after-market': 'after_market',
             'late-provider-recovery': 'late_provider_recovery', 'weekly-audit': 'weekly_audit'}
    if any(registry.services[s].enabled and identity_rows.get(names.get(s, s), {}).get('status') != 'matched'
           for s in affected):
        raise DeploymentError('PREVIOUS_SERVICE_IDENTITY_UNPROVEN')
    for service in affected:
        previous = registry.services[service]
        if service == 'market-feed':
            prove_feed_quiescent(previous)
        proposed = ServiceBinding(**payload['candidate_bindings'][service])
        def commit_binding(service=service):
            nonlocal registry
            current = bindings_sha256()
            expected = registry.services[service]
            latest = read_bindings()
            if latest is None or latest != registry or latest.services[service] != expected:
                raise DeploymentError('RELEASE_PLAN_DRIFT_OR_BLOCKED')
            next_binding = backend.candidates[service] if service in CONTINUOUS else proposed
            registry = BindingRegistry(1, {**registry.services, service: next_binding})
            write_bindings(registry, expected_sha256=current)
        if service in SCHEDULED:
            from app.runtime_scheduled import execute_scheduled_update
            result = execute_scheduled_update(service, previous, proposed, commit_binding=commit_binding)
        else:
            result = execute_handover(service, previous, proposed, backend=backend, commit_binding=commit_binding)
        results[service] = result
        if result != 'switched':
            break
    return results


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    plan = sub.add_parser('plan')
    plan.add_argument('--candidate-root', type=Path, required=True)
    plan.add_argument('--tag', required=True)
    plan.add_argument('--commit', required=True)
    apply = sub.add_parser('apply-plan')
    apply.add_argument('--plan', type=Path, required=True)
    candidate = sub.add_parser('candidate')
    candidate.add_argument('service', choices=sorted(CONTINUOUS))
    candidate.add_argument('request')
    candidate.add_argument('generation', type=int)
    port = sub.add_parser('port-service')
    port.add_argument('service', choices=['api', 'web'])
    sub.add_parser('status')
    args = parser.parse_args(argv)
    try:
        if args.mode == 'plan':
            assert_no_unknown_deployment()
            registry = read_bindings()
            if registry is None:
                raise DeploymentError('TOPOLOGY_BOOTSTRAP_REQUIRED')
            result = build_release_plan(registry, candidate_root=args.candidate_root, tag=args.tag,
                                       commit=args.commit, registry_sha256=bindings_sha256())
        elif args.mode == 'status':
            registry = read_bindings()
            if registry is None or 'api' not in registry.services:
                raise DeploymentError('SERVICE_BINDING_REQUIRED')
            from app.services.deployment_identity import deployment_identity_health
            api = registry.services['api']
            result = deployment_identity_health(root=Path(api.root), commit=api.commit)
            from urllib.request import urlopen
            checks = {}
            for name, url in {'api': 'http://127.0.0.1:8000/api/health',
                              'web': 'http://127.0.0.1:5173/',
                              'runtime': 'http://127.0.0.1:8000/api/runtime/health'}.items():
                try:
                    with urlopen(url, timeout=5) as response:
                        valid = response.status == 200
                        if name == 'runtime':
                            health = json.load(response)
                            valid = valid and health.get('status') == 'ok' and health.get('readonly') is True
                        checks[name] = valid
                except Exception:
                    checks[name] = False
            result['http_checks'] = checks
            result['status'] = 'ok' if result['status'] == 'matched' and all(checks.values()) else 'blocked'
        elif args.mode == 'port-service':
            _run_port_service(args.service)
            return 0
        elif args.mode == 'apply-plan':
            with deployment_lock():
                from app.runtime_bindings import _read as read_plan
                raw = read_plan(args.plan)
                if raw is None:
                    raise DeploymentError('RELEASE_PLAN_MISSING')
                outcomes = apply_plan(json.loads(raw))
                result = {'status': 'switched' if all(v == 'switched' for v in outcomes.values()) else 'cancelled',
                          'services': outcomes}
        else:
            run_candidate(args.service, args.request, args.generation)
            return 0
        print(json.dumps(result, sort_keys=True))
        return 1 if result.get('status') in {'blocked', 'cancelled'} else 0
    except DeploymentError as exc:
        code = str(exc) if re.fullmatch(r'[A-Z0-9_]+', str(exc)) else 'RUNTIME_DEPLOYMENT_BLOCKED'
        print(json.dumps({'status': 'blocked', 'code': code}))
        return 1
    except Exception:
        print(json.dumps({'status': 'blocked', 'code': 'RUNTIME_DEPLOYMENT_BLOCKED'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
