"""Single-owner homepage recovery. Children only compute; the parent publishes."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from uuid import uuid4



from .home_projection import PERIODS, ProjectionError, ProjectionStore
from .home_recovery_state import (
    RecoveryPolicy, WorkStore, eligible, end_compute, failure_detail, finish, probe,
    reconcile, reserve, settle, start_compute,
)

CHILD_SCHEMA = 'newow_home_compute_v1'


class HomeComputeError(RuntimeError):
    def __init__(self, detail):
        self.detail = detail
        self.code = detail['code']
        super().__init__(self.code)


def implementation_identity():
    directory = Path(__file__).parent
    return sha256(b''.join((directory / name).read_bytes() for name in (
        'home_recovery.py', 'home_recovery_state.py', 'home_projection.py',
        'home_projection_composition.py', 'home_child_bootstrap.py',
    ))).hexdigest()


def process_identity(pid):
    try:
        value = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart=', '-o', 'command='],
                               capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return sha256(value.encode()).hexdigest() if value else None


def stop_child(pid, identity):
    if process_identity(pid) != identity:
        return
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while process_identity(pid) == identity and time.monotonic() < deadline:
        time.sleep(.05)
    if process_identity(pid) == identity:
        os.kill(pid, signal.SIGKILL)


def remove_child_output(projection, token):
    from app.market_data.market_home_projection import _open_projection_parent
    directory = projection.with_name(projection.name + '.children')
    parent = _open_projection_parent(directory, create=False)
    if parent is None:
        return
    try:
        try:
            os.unlink(f'{token}.json', dir_fd=parent)
        except FileNotFoundError:
            pass
    finally:
        os.close(parent)


class IsolatedCompute:
    def __init__(self, home, policy, register, clear, *, assert_owned, stop_requested, popen=None):
        self.home, self.policy = home, policy
        self.register, self.clear = register, clear
        self.assert_owned, self.stop_requested = assert_owned, stop_requested
        self.errors = []
        self.popen = popen or subprocess.Popen

    def __call__(self, product, period):
        token = uuid4().hex
        directory = self.home.store.path.with_name(self.home.store.path.name + '.children')
        output = directory / f'{token}.json'
        env = dict(os.environ)
        env['GUIYI_HOME_CHILD_ROOT'] = str(directory)
        parent_read, parent_write = os.pipe()
        command = [sys.executable, '-B', str(Path(__file__).with_name('home_child_bootstrap.py')),
                   '--product', product, '--period', period, '--token', token, '--parent-fd', str(parent_read)]
        try:
            process = self.popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 close_fds=True, pass_fds=(parent_read,))
        except BaseException:
            os.close(parent_read)
            os.close(parent_write)
            raise
        os.close(parent_read)
        started = time.monotonic()
        try:
            identity = process_identity(process.pid)
            if identity is not None:
                self.register({'pid': process.pid, 'identity': identity, 'token': token})
            elif process.poll() is None:
                raise HomeComputeError({'category': 'unknown', 'code': 'HOME_CHILD_IDENTITY_UNAVAILABLE', 'stage': period})
            try:
                os.write(parent_write, b'G')
            except BrokenPipeError:
                if process.poll() is None:
                    raise
            while process.poll() is None:
                self.assert_owned()
                if self.stop_requested():
                    raise HomeComputeError({'category': 'interrupted', 'code': 'HOME_COMPUTE_INTERRUPTED', 'stage': period})
                if time.monotonic() - started >= self.policy.period_seconds:
                    raise HomeComputeError({'category': 'timeout', 'code': 'HOME_COMPUTE_TIMEOUT', 'stage': period})
                time.sleep(.05)
            self.assert_owned()
            if process.returncode != 0:
                if process.returncode == 71:
                    raise HomeComputeError({'category': 'timeout', 'code': 'HOME_COMPUTE_TIMEOUT', 'stage': period})
                raise HomeComputeError({'category': 'unknown', 'code': 'HOME_COMPUTE_EXITED', 'stage': period})
            value = ProjectionStore(output, schema=CHILD_SCHEMA).load()
            if value is None or value.get('token') != token:
                raise HomeComputeError({'category': 'unknown', 'code': 'HOME_COMPUTE_EXITED', 'stage': period})
            if not value.get('ok'):
                raise HomeComputeError(value['detail'])
            return value['items']['facts']
        except HomeComputeError as exc:
            self.errors[:] = [*self.errors, exc.detail][-3:]
            raise
        finally:
            os.close(parent_write)
            if process.poll() is None:
                # This Popen is still our unreaped child, so PID reuse is impossible.
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            # Keep the registration until its private result has been removed.
            remove_child_output(self.home.store.path, token)
            self.clear()


class HomeRecovery:
    def __init__(self, home, *, policy=None, clock=None, monotonic=None, executor=None,
                 assert_owned=None, stop_requested=None, implementation=None, dependency_probe=None):
        self.home = home
        self.policy = policy or RecoveryPolicy()
        self.clock = clock or time.time
        self.monotonic = monotonic or time.monotonic
        self.assert_owned = assert_owned or (lambda: None)
        self.stop_requested = stop_requested or (lambda: False)
        self.implementation = implementation or implementation_identity()
        self.work = WorkStore(home.store.path)
        self.state = None
        self.dependency_probe = dependency_probe or (lambda: bool(self.home.versions()))
        self.executor = executor or IsolatedCompute(home, self.policy, self._register, self._clear,
                                                   assert_owned=self.assert_owned, stop_requested=self.stop_requested)
        self.home.store.write_guard = self.assert_owned
        self.work.write_guard = self.assert_owned

    def _save(self):
        self.assert_owned()
        self.work.save(self.state)

    def _register(self, child):
        self.state['child'] = child
        self._save()

    def _clear(self):
        self.state.pop('child', None)
        self._save()

    def _recover(self):
        child = self.state.get('child')
        if child:
            if (type(child.get('pid')) is not int or child['pid'] <= 1
                    or re.fullmatch(r'[0-9a-f]{64}', child.get('identity', '')) is None
                    or re.fullmatch(r'[0-9a-f]{32}', child.get('token', '')) is None):
                raise ProjectionError()
            stop_child(child['pid'], child['identity'])
            remove_child_output(self.home.store.path, child['token'])
            self.state.pop('child', None)
        for job in self.state['items'].values():
            if job['status'] == 'running':
                # Keep the conservative reservation charged after an unknown exit.
                job.pop('reservation', None)
                finish(job, {'category': 'interrupted', 'code': 'HOME_COMPUTE_INTERRUPTED'}, self.clock(), self.policy)
        self._save()

    def _raw_ready(self, product, target, raw):
        if product == 'overview':
            return raw.get('overview') is not None and not raw.get('overview_failed') and raw.get('overview_versions') == target
        item = raw.get('items', {}).get(product, {})
        return (not item.get('building') and not item.get('failures') and all(
            target.get(period) and item.get('periods', {}).get(period, {}).get('version') == target[period]
            for period in PERIODS))

    def tick(self, products=None):
        """Bounded sweep. A held journal lock is the only scheduling owner."""
        selected = tuple(self.home.products if products is None else products)
        if not selected or len(selected) != len(set(selected)) or not set(selected) <= set(self.home.products):
            raise ProjectionError()
        with self.work.lock():
            self.state = self.work.state()
            self._recover()
            if self.home.store.path.exists() and self.home.store.load() is None:
                raise ProjectionError()
            if self.home.store.building():
                return {'status': 'busy', 'computed': 0}
            try:
                versions = self.home.versions()
                healthy = self.dependency_probe()
            except Exception as exc:
                probe(self.state, False, self.clock())
                self.state['dependency_error'] = failure_detail(exc, stage='source_version')
                self._save()
                return {'status': 'dependency_wait', 'computed': 0}
            probe(self.state, healthy, self.clock())
            if not healthy:
                self.state['dependency_error'] = {'category': 'data', 'code': 'HOME_SOURCE_VERSION_UNAVAILABLE'}
                self._save()
                return {'status': 'dependency_wait', 'computed': 0}
            self.state.pop('dependency_error', None)
            raw = self.home.store.load() or {'items': {}}
            jobs = []
            for product in selected:
                target = {period: versions.get(f'{product}:{period}') for period in PERIODS}
                job = reconcile(self.state, product, target, self.implementation,
                                self._raw_ready(product, target, raw), self.clock())
                jobs.append((product, job))
            if self.home.overview is not None:
                job = reconcile(self.state, 'overview', versions, self.implementation,
                                self._raw_ready('overview', versions, raw), self.clock())
                jobs.append(('overview', job))
            # First attempts on other products always precede retries.
            jobs.sort(key=lambda pair: (pair[1]['attempt'] > 0, pair[1].get('last_at', 0), pair[0] == 'overview'))
            self._save()
            computed = 0
            for product, job in jobs:
                if self.stop_requested():
                    break
                self.assert_owned()
                if not eligible(job, self.state, self.clock(), self.policy):
                    continue
                if not all(job['target'].values()):
                    job.update(status='dependency_wait', next_at=self.clock() + 60,
                               detail={'category': 'data', 'code': 'HOME_SOURCE_VERSION_UNAVAILABLE'})
                    self._save()
                    continue
                try:
                    fresh = self.home.versions()
                except Exception as exc:
                    self.state['dependency_error'] = failure_detail(exc, stage='source_version')
                    probe(self.state, False, self.clock())
                    self._save()
                    break
                current_target = fresh if product == 'overview' else {p: fresh.get(f'{product}:{p}') for p in PERIODS}
                if current_target != job['target']:
                    reconcile(self.state, product, current_target, self.implementation,
                              self._raw_ready(product, current_target, raw), self.clock())
                    self._save()
                    continue
                previous = raw.get('items', {}).get(product, {})
                periods = 1 if product == 'overview' else sum(
                    previous.get('periods', {}).get(p, {}).get('version') != job['target'][p]
                    or p in previous.get('failures', {}) or previous.get('building', False) for p in PERIODS)
                if not reserve(self.state, product, job, self.clock(), max(1, periods) * self.policy.period_seconds, self.policy, starts=max(1, periods)):
                    self._save()
                    continue
                self._save()
                before = self.monotonic()
                detail = None
                old_compute, old_overview, old_versions = self.home.compute, self.home.overview, self.home.versions
                errors = []
                starts = 0
                def compute(p, frequency):
                    nonlocal starts
                    slot = start_compute(self.state, product, job, self.clock(), self.policy)
                    if slot is None:
                        detail = {'category': 'budget', 'code': 'HOME_RECOVERY_BUDGET_WAIT', 'stage': frequency}
                        errors.append(detail)
                        raise HomeComputeError(detail)
                    self._save()
                    starts += 1
                    started = self.monotonic()
                    try:
                        return self.executor(p, frequency)
                    except Exception as exc:
                        errors.append(exc.detail if isinstance(exc, HomeComputeError) else failure_detail(exc, stage=frequency))
                        raise
                    finally:
                        end_compute(self.state, product, job, slot, self.monotonic() - started)
                        self._save()
                def pinned_versions():
                    actual = old_versions()
                    target = actual if product == 'overview' else {p: actual.get(f'{product}:{p}') for p in PERIODS}
                    if target != job['target']:
                        raise HomeComputeError({'category': 'source_changed', 'code': 'HOME_PROJECTION_SOURCE_CHANGED', 'stage': 'verify_source_version'})
                    return actual
                try:
                    self.home.compute = compute
                    self.home.versions = pinned_versions
                    if product == 'overview':
                        self.home.overview = lambda: compute('overview', 'overview')
                        self.home.build_overview()
                    else:
                        self.home.build((product,), include_overview=False)
                    raw = self.home.store.load() or {'items': {}}
                    fresh = self.home.versions()
                    target = fresh if product == 'overview' else {p: fresh.get(f'{product}:{p}') for p in PERIODS}
                    if not self._raw_ready(product, job['target'], raw) or target != job['target']:
                        failures = raw.get('items', {}).get(product, {}).get('failures', {})
                        source_changed = target != job['target'] or 'HOME_PROJECTION_SOURCE_CHANGED' in failures.values()
                        detail = ({'category': 'source_changed', 'code': 'HOME_PROJECTION_SOURCE_CHANGED'}
                                  if source_changed else errors[0] if errors else {'category': 'unknown', 'code': 'HOME_PROJECTION_BUILD_FAILED'})
                except Exception as exc:
                    detail = errors[0] if errors else failure_detail(exc, stage='publish')
                finally:
                    self.home.compute, self.home.overview, self.home.versions = old_compute, old_overview, old_versions
                settle(self.state, product, job, self.monotonic() - before if starts else 0, starts=starts)
                finish(job, detail, self.clock(), self.policy)
                self._save()
                computed += 1
            self.state['checked_at'] = self.clock()
            self._save()
            return {'status': 'passed' if all(j['status'] == 'succeeded' for _, j in jobs) else 'partial', 'computed': computed}


def configure_delivery(home):
    work = WorkStore(home.store.path)
    home.delivery = lambda versions: work.public(home.products, versions)
    return home


def request_home_refresh():
    """The supervised worker detects versions on its next <=60s idle check.

    No second writer, source mutation or opportunistic in-process calculation.
    """
    from .home_projection_composition import build_home_projection
    home = build_home_projection()
    return {'status': 'deferred', 'products': len(home.products)}


def run_home_build(*, output_path=None, products=None):
    from app.market_data.composition import canonical_root
    from app.runtime_bindings import resolve_service_binding
    from .home_projection_composition import build_home_projection
    from .home_projection import projection_path
    home = build_home_projection(output_path=output_path)
    home.store.path = home.store.path.absolute()
    formal = projection_path(canonical_root())
    if home.store.path.parent.resolve() / home.store.path.name == formal:
        # A caller from develop may inspect/request, never publish a formal file.
        binding = resolve_service_binding('home-projection')
        if binding is None or not binding.enabled:
            raise ProjectionError()
        return {**home.read(), 'build_request': {'mode': 'owner', 'readonly': True}}
    if (home.store.path.parent.resolve().is_relative_to(canonical_root())
            or home.store.path.suffix != '.json'):
        raise ProjectionError()
    HomeRecovery(home).tick(products)
    return home.read()


def owner_heartbeat(assert_owned, mark_ready, stop_requested, *, clock=time.monotonic):
    last = None
    def ready():
        nonlocal last
        if mark_ready:
            mark_ready()
        last = clock()
    def guard():
        if assert_owned:
            assert_owned()
        if last is not None and clock() - last >= 5 and not stop_requested():
            ready()
    return guard, ready


def run_home_recovery_forever(*, assert_owned=None, stop_requested=None, mark_ready=None):
    import stat
    from app.core.env import PROJECT_ROOT
    from .home_projection_composition import build_home_projection
    marker = PROJECT_ROOT / '.run/home-projection-enabled'
    fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
                or stat.S_IMODE(meta.st_mode) != 0o600 or os.read(fd, 9) != b'enabled\n'):
            raise ProjectionError()
    finally:
        os.close(fd)
    stop_requested = stop_requested or (lambda: False)
    guard, ready = owner_heartbeat(assert_owned, mark_ready, stop_requested)
    worker = HomeRecovery(build_home_projection(), assert_owned=guard, stop_requested=stop_requested)
    with worker.work.lock():
        worker.state = worker.work.state()
        worker._recover()
    ready()
    while not stop_requested():
        worker.tick()
        for _ in range(60):
            if stop_requested():
                return
            guard()
            time.sleep(1)


def _child(args):
    if os.getenv('GUIYI_HOME_CHILD_GATED') != '1':
        raise ProjectionError()
    if re.fullmatch(r'[0-9a-f]{32}', args.token) is None or args.period not in (*PERIODS, 'overview'):
        raise ProjectionError()
    root = Path(os.environ['GUIYI_HOME_CHILD_ROOT'])
    if not root.is_absolute() or not root.name.endswith('.children'):
        raise ProjectionError()
    from .home_projection_composition import build_home_projection, compute_period
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    store = ProjectionStore(root / f'{args.token}.json', schema=CHILD_SCHEMA)
    def timed_out(*_):
        raise HomeComputeError({'category': 'timeout', 'code': 'HOME_COMPUTE_TIMEOUT', 'stage': args.period})
    signal.signal(signal.SIGALRM, timed_out)
    remaining = signal.getitimer(signal.ITIMER_REAL)[0]
    signal.setitimer(signal.ITIMER_REAL, min(120, remaining) if remaining > 0 else 120)
    try:
        if args.product == 'overview' and args.period == 'overview':
            facts = build_home_projection().overview()
        else:
            if re.fullmatch(r'[a-z]{1,4}', args.product) is None:
                raise ProjectionError()
            with SessionLocal() as session, readonly_transaction(session, timeout_seconds=120):
                facts = compute_period(session, args.product, args.period, datetime.now(UTC))
        payload = {'schema_version': CHILD_SCHEMA, 'token': args.token, 'ok': True, 'items': {'facts': facts}}
    except Exception as exc:
        detail = exc.detail if isinstance(exc, HomeComputeError) else failure_detail(exc, stage=args.period)
        payload = {'schema_version': CHILD_SCHEMA, 'token': args.token, 'ok': False, 'detail': detail, 'items': {}}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    store.save(payload)


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('run')
    child = sub.add_parser('compute')
    for name in ('product', 'period', 'token', 'parent-fd'):
        child.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'compute':
            _child(args)
        else:
            run_home_recovery_forever()
        return 0
    except Exception:
        # CLI/launchd diagnostics never print arbitrary exception text.
        print(json.dumps({'status': 'blocked', 'code': 'HOME_RECOVERY_UNAVAILABLE'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
