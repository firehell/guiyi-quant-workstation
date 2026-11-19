#!/usr/bin/env python3
"""Execute/read back the owner-approved Nov-19 Newow interval retirement once.

Only Reference is drained. Feed, Live, Alert and both model accounts are untouched.
Failure after an uncertain commit leaves the writer parked for exact readback.
"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from functools import partial
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import signal
import time

from reference_observation_recovery import (
    ROOT, load_dependencies, parked_reference_guard, verify_code,
)


def wait_phase(directory, binding, phase, *, timeout=120):
    from app.runtime_handover import read_service_state
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = read_service_state('reference-worker', runtime_dir=directory)
        if state and state.get('generation') == binding.generation and state.get('phase') == phase:
            return
        time.sleep(0.5)
    raise RuntimeError('INTERVAL_RETIREMENT_OWNER_TIMEOUT')


def read_plan(path):
    """Bounded private document; project.env keeps its separate 1 MiB limit."""
    if path.parent.resolve(strict=True) != path.parent:
        raise RuntimeError('INTERVAL_RETIREMENT_PLAN_UNSAFE')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > 32*1024*1024):
            raise RuntimeError('INTERVAL_RETIREMENT_PLAN_UNSAFE')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            raw = stream.read(32*1024*1024 + 1)
        if len(raw) != info.st_size:
            raise RuntimeError('INTERVAL_RETIREMENT_PLAN_CHANGED')
        return json.loads(raw)
    finally:
        os.close(fd)


def cancel_owned(directory, binding, request_id):
    from app.runtime_bindings import resolve_service_binding
    from app.runtime_handover import _read, deployment_lock, cancel_drain, HandoverError
    deadline = time.monotonic() + 10
    while True:
        try:
            with deployment_lock(runtime_dir=directory):
                handover = _read(directory/'reference-worker.handover.json')
                if (resolve_service_binding('reference-worker') == binding and handover and
                        handover.get('request_id') == request_id and handover.get('generation') == binding.generation and
                        handover.get('phase') == 'drain'):
                    cancel_drain('reference-worker', request_id=request_id, runtime_dir=directory)
            return
        except HandoverError as exc:
            if str(exc) != 'RUNTIME_DEPLOYMENT_BUSY' or time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def business_claim_path():
    from app.reference_trading.interval_retirement import INVENTORY_SHA256
    root = Path.home()/'Library/Application Support/GuiyiQuant/reference-interval-retirement-attempts'
    root.mkdir(mode=0o700, exist_ok=True)
    if root.resolve(strict=True) != root or root.stat().st_mode & 0o077:
        raise RuntimeError('INTERVAL_RETIREMENT_CLAIM_UNSAFE')
    return root/(INVENTORY_SHA256+'.json')


@contextmanager
def resources(directory, binding, config_hash, request_id):
    from app.db.session import SessionLocal
    from app.market_data.catalog import MarketCatalog
    from app.market_data.composition import canonical_root
    from app.private_settings import read_private_settings_content
    from app.runtime_handover import _read
    from app.reference_trading.interval_retirement import first_session_endpoint
    with parked_reference_guard(directory=directory, expected_binding=asdict(binding)) as (guard, _):
        with SessionLocal() as session:
            lease = MarketCatalog(session, canonical_root()).acquire_maintenance_lock(
                caller='reference-interval-retirement')
            if lease is None:
                raise RuntimeError('INTERVAL_RETIREMENT_CATALOG_BUSY')
            try:
                def fence():
                    guard()
                    handover = _read(directory/'reference-worker.handover.json')
                    if not handover or handover.get('request_id') != request_id:
                        raise RuntimeError('INTERVAL_RETIREMENT_OWNER_REQUEST_DRIFT')
                    lease.assert_held()
                    if sha256(read_private_settings_content(directory/'project.env')).hexdigest() != config_hash:
                        raise RuntimeError('INTERVAL_RETIREMENT_CONFIG_DRIFT')
                yield SessionLocal, partial(first_session_endpoint, data_root=canonical_root()), fence
            finally:
                lease.release()


def main():
    def terminated(_signum, _frame):
        raise RuntimeError('INTERVAL_RETIREMENT_TERMINATED')
    signal.signal(signal.SIGTERM, terminated)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=('execute', 'readback'))
    parser.add_argument('--exact-root', required=True, type=Path)
    parser.add_argument('--exact-commit', required=True)
    parser.add_argument('--inventory', required=True, type=Path)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--attempt', type=Path)
    parser.add_argument('--expected-plan-hash')
    args = parser.parse_args()
    verify_code(args.exact_root, args.exact_commit)
    from app.runtime_bindings import resolve_service_binding
    from app.runtime_handover import runtime_directory, request_drain, deployment_lock, _read, read_service_state
    from app.private_settings import read_private_settings_content
    binding = resolve_service_binding('reference-worker')
    if binding is None or not binding.enabled or Path(binding.root) != ROOT or binding.commit != args.exact_commit:
        raise RuntimeError('INTERVAL_RETIREMENT_RUNTIME_IDENTITY')
    directory = runtime_directory()
    config_hash = load_dependencies(directory/'project.env')
    from app.db.session import SessionLocal
    if SessionLocal.kw['bind'].dialect.name != 'postgresql':
        raise RuntimeError('INTERVAL_RETIREMENT_POSTGRES_REQUIRED')
    from app.reference_trading.interval_retirement import (
        INVENTORY_SHA256, NewowIntervalRetirement,
    )
    from app.reference_trading.recovery_campaign import write_once, AttemptProgress
    raw = read_private_settings_content(args.inventory)
    if sha256(raw).hexdigest() != INVENTORY_SHA256:
        raise RuntimeError('INTERVAL_RETIREMENT_INVENTORY_HASH')
    inventory = json.loads(raw)
    if args.phase == 'readback':
        from app.db.readonly import readonly_transaction
        from app.reference_trading.newow_bootstrap import _BorrowedSession
        plan = read_plan(args.plan)
        if plan['plan_hash'] != args.expected_plan_hash:
            raise RuntimeError('INTERVAL_RETIREMENT_PLAN_HASH')
        # No owner acquisition, drain or write in the readback path.
        with SessionLocal() as db, readonly_transaction(db, timeout_seconds=120):
            service = NewowIntervalRetirement(lambda: _BorrowedSession(db), inventory=inventory,
                first_endpoint=None, assert_fenced=lambda: None)
            result = service.status(plan)
        print(json.dumps(dict(result=result)))
        return
    if args.attempt is None or args.expected_plan_hash is not None or args.plan.exists():
        raise RuntimeError('INTERVAL_RETIREMENT_NEW_ATTEMPT_REQUIRED')
    claim = business_claim_path()
    if claim.exists():
        raise RuntimeError('INTERVAL_RETIREMENT_CLAIM_CONSUMED_READBACK_ONLY')
    progress = AttemptProgress(args.attempt, plan_hash=INVENTORY_SHA256)
    request_id, safe_to_resume = None, False
    try:
        with deployment_lock(runtime_dir=directory):
            current = resolve_service_binding('reference-worker')
            if current != binding:
                raise RuntimeError('INTERVAL_RETIREMENT_RUNTIME_DRIFT')
            owner = read_service_state('reference-worker', runtime_dir=directory)
            handover = _read(directory/'reference-worker.handover.json')
            if (not owner or owner.get('phase') != 'active' or owner.get('generation') != binding.generation or
                    handover and handover.get('phase') == 'drain'):
                raise RuntimeError('INTERVAL_RETIREMENT_OWNER_BUSY')
            def before_drain(rid):
                nonlocal request_id, safe_to_resume
                progress.record('drain_intent', request_id=rid, binding=asdict(binding))
                request_id, safe_to_resume = rid, True
            request_id = request_drain('reference-worker', generation=binding.generation,
                runtime_dir=directory, before_install=before_drain)
        wait_phase(directory, binding, 'parked')
        safe_to_resume = True
        with resources(directory, binding, config_hash, request_id) as (factory, first, fence):
            now = datetime.now(UTC)
            service = NewowIntervalRetirement(factory, inventory=inventory,
                first_endpoint=first, assert_fenced=fence)
            plan = service.plan(tuple(service.inventory), recording_start=now+timedelta(minutes=45),
                expires_at=now+timedelta(minutes=30), now=now)
            write_once(args.plan, plan)
            if read_plan(args.plan) != plan:
                raise RuntimeError('INTERVAL_RETIREMENT_PLAN_READBACK')
            progress.record('plan_frozen', plan_hash=plan['plan_hash'])
            # Fixed incident-wide claim: changing --attempt or --plan paths
            # never authorizes another business invocation after unknown writes.
            write_once(claim, dict(inventory_sha256=INVENTORY_SHA256,
                plan_hash=plan['plan_hash'], attempt=str(args.attempt),
                runtime_commit=args.exact_commit, binding=asdict(binding), request_id=request_id))
            progress.record('apply_intent', plan_hash=plan['plan_hash'])
            safe_to_resume = False
            result = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=datetime.now(UTC))
            if result != service.status(plan) or len(result['retired']) != 236:
                raise RuntimeError('INTERVAL_RETIREMENT_READBACK_FAILED')
            retired_count = result['retired_originals']
            progress.record('committed', result=result)
            safe_to_resume = True
        if safe_to_resume:
            cancel_owned(directory, binding, request_id)
            progress.record('resume_requested', request_id=request_id)
            wait_phase(directory, binding, 'active')
            progress.record('complete')
            print(json.dumps(dict(status='COMMITTED', plan_hash=plan['plan_hash'],
                                  retired_streams=236, retired_originals=retired_count)))
    except BaseException:
        try:
            progress.record('stopped', safe_to_resume=safe_to_resume, request_id=request_id)
        finally:
            # Audit IO failure must not strand a pre-write drain. Once apply
            # was admitted, an unknown outcome always remains fenced.
            if safe_to_resume and request_id:
                cancel_owned(directory, binding, request_id)
        raise
    finally:
        progress.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        code = str(exc)
        if not code.replace('_', '').isalnum() or not code.isupper():
            code = type(exc).__name__.upper()
        print(json.dumps(dict(status='BLOCKED', code=code)))
        raise SystemExit(1)
