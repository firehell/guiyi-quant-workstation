"""Exact task CLI. Plan is read-only; restore never drains or sends notifications."""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager, ExitStack
from dataclasses import asdict
from datetime import UTC, date, datetime
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

SERVICES = ('after-market', 'market-feed', 'live', 'alert', 'reference-worker')
HERE = Path(__file__).resolve().parent
DAY = date(2026, 10, 12)
MAX_PLAN_BYTES = 256*1024*1024


def digest(raw):
    return sha256(raw).hexdigest()


def read_file(path, limit=64*1024*1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError('TASK_FILE_INVALID')
        raw = os.read(fd, limit+1)
        after = os.fstat(fd)
        if (len(raw) != info.st_size or (info.st_ino, info.st_size, info.st_mtime_ns) !=
                (after.st_ino, after.st_size, after.st_mtime_ns)):
            raise ValueError('TASK_FILE_DRIFT')
        return raw
    finally:
        os.close(fd)


def save(name, payload):
    target = HERE/name
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()+b'\n'
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        dfd = os.open(HERE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except BaseException:
        # Do not remove a possibly durable attempt or claim it was never written.
        raise
    return target


def candidate_identity(root, commit):
    if not root.is_absolute() or root.resolve(strict=True) != root or re.fullmatch('[0-9a-f]{40}', commit) is None:
        raise ValueError('CANDIDATE_IDENTITY_INVALID')
    head = subprocess.check_output(['/usr/bin/git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if head != commit or subprocess.run(['/usr/bin/git', '-C', str(root), 'diff', '--quiet', 'HEAD', '--'], check=False).returncode:
        raise ValueError('CANDIDATE_IDENTITY_DRIFT')
    return {'root': str(root), 'commit': commit}


def task_plan_hash(payload):
    facts = {key: value for key, value in payload.items() if key != 'task_plan_sha256'}
    return digest(json.dumps(facts, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def serialize_plan(plan):
    value = asdict(plan)
    value['trading_day'] = str(plan.trading_day)
    value['preimages'] = [base64.b64encode(raw).decode('ascii') for raw in plan.preimages]
    value['plan_sha256'] = plan.sha256
    return value


def deserialize_plan(value):
    from app.market_data.observation_restore import ProjectionRestorePlan
    plan = ProjectionRestorePlan(date.fromisoformat(value['trading_day']), tuple(value['keys']),
        tuple(base64.b64decode(raw, validate=True) for raw in value['preimages']), value['changes_json'],
        value['source_tail'], value['source_cursor'], value['source_count'], value['completed_count'])
    if plan.trading_day != DAY or plan.sha256 != value['plan_sha256']:
        raise ValueError('PLAN_HASH_CONFLICT')
    return plan


def bindings(runtime_root, runtime_commit, live_generation):
    from app.runtime_bindings import resolve_service_binding
    result = {}
    for service in SERVICES:
        current = resolve_service_binding(service)
        if (current is None or current.root != str(runtime_root) or current.commit != runtime_commit
                or not current.enabled or (service == 'live' and current.generation != live_generation)):
            raise ValueError('RUNTIME_IDENTITY_DRIFT')
        result[service] = asdict(current)
    return result


def owners(runtime_dir):
    result = {}
    for service in SERVICES:
        try:
            raw = read_file(runtime_dir/f'{service}.owner.json', limit=65536)
        except FileNotFoundError:
            if service != 'after-market':
                raise ValueError('OWNER_STATE_MISSING') from None
            # Scheduled after-market owns its existing OS lock without a supervised owner JSON.
            result[service] = {'sha256': None, 'record': None}
        else:
            result[service] = {'sha256': digest(raw), 'record': json.loads(raw)}
    return result


@contextmanager
def parked_owner_locks(runtime_dir, frozen_bindings, original_owners):
    """Prove existing owner inodes are unheld, without overwriting original failure files."""
    held = []
    try:
        for service in SERVICES:
            path = runtime_dir/f'{service}.owner.lock'
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)  # Never create an owner inode.
            held.append((service, path, fd))
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError('OWNER_LOCK_INVALID')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('OWNER_NOT_PARKED') from None

        def assert_owned():
            for service, path, fd in held:
                a, b = path.lstat(), os.fstat(fd)
                if path.is_symlink() or (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
                    raise ValueError('OWNER_LOCK_DRIFT')
                before = original_owners[service]['record']
                if service == 'after-market' and before is None:
                    if (runtime_dir/f'{service}.owner.json').exists():
                        raise ValueError('OWNER_STATE_DRIFT')
                    continue
                record = json.loads(read_file(runtime_dir/f'{service}.owner.json', limit=65536))
                if (record.get('schema_version') != 1 or record.get('service') != service
                        or record.get('generation') != frozen_bindings[service]['generation']
                        or record.get('phase') not in ('parked', 'stopped') or record.get('ready') is not False
                        or record.get('proof') != before.get('proof')):
                    raise ValueError('OWNER_PARK_OR_FAILURE_PROOF_INVALID')
            # The owner files are not modified, even when the former process PID has exited.
        assert_owned()
        yield assert_owned
    finally:
        for _, _, fd in reversed(held):
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


@contextmanager
def restore_locks(runtime_dir, frozen_bindings, original_owners, products):
    """Same outer deployment exclusion used by Runtime promotion and handover."""
    from app.runtime_handover import deployment_lock
    from app.market_data.live_recovery_guard import after_market_recovery_guard, recovery_guard
    with deployment_lock(runtime_dir=runtime_dir):
        with parked_owner_locks(runtime_dir, frozen_bindings, original_owners) as parked, ExitStack() as guards:
            guard_root = runtime_dir/'live-recovery-guards'
            guards.enter_context(after_market_recovery_guard(root=guard_root, wait=False))
            for symbol in sorted(products):
                guards.enter_context(recovery_guard(symbol, root=guard_root, wait=False))
            yield parked


def protected(runtime_root):
    return {name: digest(read_file(runtime_root/'.run'/name)) for name in (
        'after-market-status.json', 'after-market-history.json')}


def build_plan(redis, runtime_root):
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.session_clock import resolved_session_windows_for_trading_day
    from app.market_data.observation_restore import build_projection_restore_plan
    from app.models import Instrument
    products = load_operational_products()
    if len(products) != 60:
        raise ValueError('OPERATIONAL_SCOPE_DRIFT')
    status = json.loads(read_file(runtime_root/'.run/after-market-status.json'))
    run = status['last_run']
    if run['trading_day'] != str(DAY) or run['status'] != 'passed':
        raise ValueError('NATURAL_RUN_IDENTITY_DRIFT')
    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=600):
        market = build_market_data_service(session)
        rank1 = {symbol: market.dominant_segment_for_day(symbol, DAY).contract for symbol in products}
        sessions = {}
        for symbol in products:
            exchange = session.scalar(select(Instrument.exchange_code).where(Instrument.symbol == symbol,
                                                                           Instrument.is_active.is_(True)))
            if exchange is None:
                raise ValueError('SESSION_EXCHANGE_MISSING')
            sessions[symbol] = tuple(row.window for row in resolved_session_windows_for_trading_day(
                session, exchange=exchange, symbol=symbol, trading_day=DAY))

        def session_for_bar(symbol, bar):
            windows = [window for window in sessions[symbol] if window.start < bar.bar_end <= window.end]
            if len(windows) != 1:
                raise ValueError('SESSION_ENDPOINT_INVALID')
            return windows[0]
        plan = build_projection_restore_plan(redis, day=DAY, products=tuple(products), formal_rank1=rank1,
            natural_live_evidence=run['live_evidence'], session_for_bar=session_for_bar)
    return plan, tuple(products), _authority_hash(rank1, sessions)


def _authority_hash(rank1, sessions):
    facts = {'rank1': rank1, 'sessions': {symbol: [(w.start.isoformat(), w.end.isoformat()) for w in rows]
                                       for symbol, rows in sessions.items()}}
    return digest(json.dumps(facts, sort_keys=True, separators=(',', ':')).encode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('plan', 'verify-plan', 'restore'))
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--candidate-commit', required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--runtime-commit', required=True)
    parser.add_argument('--live-generation', type=int, required=True)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--expected-plan-sha256')
    args = parser.parse_args()
    candidate = candidate_identity(args.candidate_root, args.candidate_commit)
    runtime = candidate_identity(args.runtime_root, args.runtime_commit)
    if args.candidate_root == args.runtime_root:
        raise ValueError('TASK_AND_RUNTIME_ROOT_MUST_DIFFER')
    sys.path[:0] = [str(args.candidate_root/'services/quant-api'), str(args.candidate_root/'packages/quant-core')]
    from dotenv import load_dotenv
    load_dotenv(Path.home()/'Library/Application Support/GuiyiQuant/project.env', override=True)
    os.environ.setdefault('REDIS_PASSWORD', os.environ.get('POSTGRES_PASSWORD', ''))
    if os.environ.get('REDIS_URL', '') in ('', 'redis://127.0.0.1:6379/0'):
        os.environ['REDIS_URL'] = 'redis://:' + os.environ['REDIS_PASSWORD'] + '@127.0.0.1:6379/0'
    from app.market_data import observation_restore
    if Path(observation_restore.__file__).resolve() != args.candidate_root/'services/quant-api/app/market_data/observation_restore.py':
        raise ValueError('IMPORTED_CANDIDATE_DRIFT')
    from app.redis_connections import get_redis_connection
    from app.runtime_handover import runtime_directory
    frozen_bindings = bindings(args.runtime_root, args.runtime_commit, args.live_generation)
    before = protected(args.runtime_root)
    runtime_dir = runtime_directory()
    redis = get_redis_connection()
    try:
        if args.mode == 'plan':
            plan, products, authority = build_plan(redis, args.runtime_root)
            if protected(args.runtime_root) != before:
                raise ValueError('NATURAL_STATUS_DRIFT')
            payload = {'schema_version': 1, 'readonly': True, 'candidate': candidate,
                'runtime': runtime, 'bindings': frozen_bindings, 'protected': before, 'authority_hash': authority,
                'products': products, 'original_owners': owners(runtime_dir), 'plan': serialize_plan(plan),
                'cli_sha256': digest(read_file(Path(__file__).resolve()))}
            payload['task_plan_sha256'] = task_plan_hash(payload)
            destination = args.plan or HERE/'projection-plan.json'
            if destination.parent.resolve() != HERE or destination.is_symlink():
                raise ValueError('PLAN_PATH_INVALID')
            save(destination.name, payload)
            print(json.dumps({'status': 'PLAN_READY', 'plan_sha256': payload['task_plan_sha256'],
                'core_plan_sha256': plan.sha256,
                'source_count': plan.source_count, 'completed_count': plan.completed_count,
                'missing_bars': len(json.loads(plan.changes_json)['bars'])}))
            return
        if args.plan is None or args.plan.resolve().parent != HERE or args.plan.is_symlink():
            raise ValueError('PLAN_PATH_INVALID')
        frozen = json.loads(read_file(args.plan, limit=MAX_PLAN_BYTES))
        plan = deserialize_plan(frozen['plan'])
        task_sha256 = task_plan_hash(frozen)
        if (frozen['schema_version'] != 1 or frozen['candidate'] != candidate or frozen['runtime'] != runtime
                or frozen['bindings'] != frozen_bindings or frozen['protected'] != before
                or frozen.get('task_plan_sha256') != task_sha256 or args.expected_plan_sha256 != task_sha256
                or frozen.get('cli_sha256') != digest(read_file(Path(__file__).resolve()))):
            raise ValueError('FROZEN_IDENTITY_DRIFT')
        if args.mode == 'verify-plan':
            fresh, products, authority = build_plan(redis, args.runtime_root)
            if (fresh.sha256 != plan.sha256 or list(products) != frozen['products']
                    or authority != frozen['authority_hash'] or protected(args.runtime_root) != before):
                raise ValueError('PLAN_OR_AUTHORITY_DRIFT')
            print(json.dumps({'status': 'PLAN_VALID', 'plan_sha256': task_sha256,
                              'source_count': plan.source_count, 'completed_count': plan.completed_count}))
            return
        if any((HERE/name).exists() for name in ('restore-attempt.json', 'restore-result.json', 'restore-unknown.json')):
            raise ValueError('ATTEMPT_ALREADY_SETTLED_NO_RETRY')
        with restore_locks(runtime_dir, frozen_bindings, frozen['original_owners'], frozen['products']) as parked:
            fresh, products, authority = build_plan(redis, args.runtime_root)
            if fresh.sha256 != plan.sha256 or list(products) != frozen['products'] or authority != frozen['authority_hash']:
                raise ValueError('PLAN_OR_AUTHORITY_DRIFT')

            def assert_owned():
                parked()
                if (bindings(args.runtime_root, args.runtime_commit, args.live_generation) != frozen_bindings
                        or protected(args.runtime_root) != before):
                    raise ValueError('OWNER_OR_STATUS_DRIFT')
                if digest(read_file(Path(__file__).resolve())) != frozen['cli_sha256']:
                    raise ValueError('CLI_IDENTITY_DRIFT')
                candidate_identity(args.candidate_root, args.candidate_commit)
                candidate_identity(args.runtime_root, args.runtime_commit)
            assert_owned()
            save('restore-attempt.json', {'at': datetime.now(UTC).isoformat(), 'plan_sha256': task_sha256, 'core_plan_sha256': plan.sha256,
                                        'status': 'UNKNOWN_UNTIL_READBACK'})
            try:
                observation_restore.restore_missing_projections(redis, plan,
                    expected_sha256=plan.sha256, assert_owned=assert_owned)
                readback, _, after_authority = build_plan(redis, args.runtime_root)
                changes = json.loads(readback.changes_json)
                if (changes['bars'] or changes['snapshot'] is not None or after_authority != authority
                        or readback.source_count != plan.source_count or readback.source_cursor != plan.source_cursor
                        or readback.source_tail != plan.source_tail or readback.completed_count != plan.completed_count):
                    raise ValueError('RESTORE_READBACK_FAILED')
                changed_keys = {plan.keys[item['key_index']-1] for item in json.loads(plan.changes_json)['bars']}
                snapshot = json.loads(plan.changes_json)['snapshot']
                if snapshot is not None:
                    changed_keys.add(plan.keys[snapshot['key_index']-1])
                original = dict(zip(plan.keys, plan.preimages))
                after = dict(zip(readback.keys, readback.preimages))
                if any(after.get(key) != value for key, value in original.items() if key not in changed_keys):
                    raise ValueError('PROTECTED_REDIS_FACT_CHANGED')
                assert_owned()
                save('restore-result.json', {'status': 'PROJECTION_RESTORED', 'evidence_class': 'task_repair',
                    'at': datetime.now(UTC).isoformat(), 'candidate': candidate, 'runtime': runtime,
                    'bindings': frozen_bindings, 'natural_status_preimage': before,
                    'source_count': readback.source_count, 'completed_count': readback.completed_count,
                    'source_cursor': readback.source_cursor, 'source_tail': readback.source_tail,
                    'cli_sha256': frozen['cli_sha256'], 'plan_sha256': task_sha256, 'core_plan_sha256': plan.sha256,
                    'source_cursor_unchanged': True, 'completed_prefix_unchanged': True, 'authority_hash': authority,
                    'remaining_missing_bars': 0, 'drain_executed': False, 'natural_status_unchanged': True})
            except Exception as exc:
                save('restore-unknown.json', {'status': 'UNKNOWN_NO_RETRY', 'exception_type': type(exc).__name__})
                raise ValueError('RESTORE_STOPPED_NO_RETRY') from None
        print(json.dumps({'status': 'PROJECTION_RESTORED', 'drain_executed': False}))
    finally:
        redis.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        code = str(exc) if type(exc) is ValueError and re.fullmatch('[A-Z0-9_]+', str(exc)) else 'TASK_STOPPED'
        print(json.dumps({'status': 'STOPPED', 'code': code, 'exception_type': type(exc).__name__}))
        raise SystemExit(1)
