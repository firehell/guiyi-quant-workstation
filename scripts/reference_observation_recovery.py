#!/usr/bin/env python3
"""Freeze/apply/read back exact 2026-10-12 Reference interruption recovery.

No notification transport, provider download, Canonical write or service switch.
Apply is a single attempt. Unknown results require readback; never reuse attempt.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
import fcntl
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'services/quant-api'), str(ROOT/'packages/quant-core'), str(ROOT)]


@contextmanager
def parked_reference_guard(*, directory, expected_binding):
    from app.runtime_bindings import resolve_service_binding, bindings_sha256
    from app.runtime_handover import read_service_state, deployment_lock, _read
    binding_hash = bindings_sha256()
    def assert_guard():
        binding = resolve_service_binding('reference-worker')
        owner = read_service_state('reference-worker', runtime_dir=directory)
        handover = _read(directory/'reference-worker.handover.json')
        if (binding is None or asdict(binding) != expected_binding
                or bindings_sha256() != binding_hash or owner is None
                or owner.get('phase') != 'parked' or owner.get('ready') is not False
                or owner.get('generation') != binding.generation
                or handover is None or handover.get('phase') != 'drain'
                or handover.get('generation') != binding.generation):
            raise RuntimeError('RECOVERY_PARKED_OWNER_REQUIRED')
    with deployment_lock(runtime_dir=directory):
        path = directory/'reference-worker.owner.lock'
        fd = os.open(path, os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or info.st_mode & 0o077):
                raise RuntimeError('RECOVERY_OWNER_LOCK_INVALID')
            fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
            def held_guard():
                assert_guard()
                held, disk = os.fstat(fd), path.lstat()
                if (held.st_dev, held.st_ino) != (disk.st_dev, disk.st_ino):
                    raise RuntimeError('RECOVERY_OWNER_LOCK_CHANGED')
            held_guard()
            yield held_guard, binding_hash
        finally:
            os.close(fd)


def verify_code(root, commit):
    if root != ROOT or root.resolve(strict=True) != root or not root.is_dir():
        raise RuntimeError('RECOVERY_EXACT_ROOT_INVALID')
    head = subprocess.run(['git','-C',str(root),'rev-parse','HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(['git','-C',str(root),'-c','core.fsmonitor=false','status','--porcelain','--untracked-files=no'],
                           capture_output=True, text=True, check=True).stdout.strip()
    if head != commit or dirty:
        raise RuntimeError('RECOVERY_EXACT_CODE_INVALID')


def load_dependencies(path):
    from dotenv import dotenv_values
    from scripts.newow_weekly_recovery import _read_private_settings_content
    raw = _read_private_settings_content(path)
    values = dotenv_values(stream=StringIO(raw.decode()))
    for key in ('DATABASE_URL','REDIS_URL','GUIYI_CANONICAL_DATA_ROOT'):
        value = values.get(key)
        if not isinstance(value, str) or not value:
            raise RuntimeError('RECOVERY_DEPENDENCY_CONFIG_INVALID')
        os.environ[key] = value
    os.environ['GUIYI_OBSERVATION_STREAM_ENABLED'] = '1'
    return sha256(raw).hexdigest()


@contextmanager
def components(assert_guard):
    from app.db.session import SessionLocal
    from app.redis_connections import get_redis_connection
    from app.market_data.composition import build_market_data_service, canonical_root
    from app.market_data.catalog import MarketCatalog
    from app.market_data.observation_stream import ObservationStream
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.forward_authority import ForwardMarketAuthority
    from app.reference_trading.journal_recovery import JournalRecoveryAuthority
    from app.reference_trading.bounded_recovery import BoundedForwardRecovery
    from app.reference_trading.composition import build_forward_reference_worker
    from app.reference_trading.live_wake import StreamForwardLiveWake
    from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources
    from app.reference_trading.recording_scope import recording_route_supported
    from app.reference_trading.scheduled_reconciliation import ScheduledCanonicalReconciliation, CompletedCanonicalReader
    from sqlalchemy import text
    with SessionLocal() as session:
        session.execute(text('SET TRANSACTION READ ONLY'))
        mds = build_market_data_service(session)
        catalog = MarketCatalog(session, canonical_root())
        lease = catalog.acquire_maintenance_lock()
        if lease is None:
            raise RuntimeError('SOURCE_BUSY')
        redis = get_redis_connection()
        try:
            repository = ReferenceRepository(SessionLocal)
            authority = ForwardMarketAuthority(mds)
            journal = ObservationStream(redis, kind='completed')
            journal_authority = JournalRecoveryAuthority(journal, authority)
            recovery = BoundedForwardRecovery(SessionLocal, verify_gap=journal_authority.verify_gap)
            # No historical scan, background thread or notification transport is composed.
            reconciliation = ScheduledCanonicalReconciliation(SessionLocal,
                CompletedCanonicalReader(mds, authority.owner_segments), read_guard=nullcontext)
            worker = build_forward_reference_worker(repository=repository, market_read=None, newow_reader=None,
                owner_segments=authority.owner_segments, expected_endpoints=authority.expected_endpoints,
                newow_capability_ready=lambda identity:recording_route_supported(identity.strategy_code, identity.frequency),
                fusion_sources=SavedForwardFusionSources(SessionLocal),
                reconciliation_guard=reconciliation.assert_source_allowed,
                reconciliation_commit_guard=reconciliation.commit_guard, enabled=True)
            worker.assert_owned = assert_guard
            worker.scan_live = False
            wake = StreamForwardLiveWake(redis, repository, worker, mds)
            try:
                yield repository, recovery, journal_authority, worker, wake
            finally:
                wake.close()
        finally:
            redis.close()
            lease.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=('freeze','apply','readback'))
    parser.add_argument('--exact-root', required=True, type=Path)
    parser.add_argument('--exact-commit', required=True)
    parser.add_argument('--binding-generation', required=True, type=int)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--expected-plan-hash')
    parser.add_argument('--scope-file', type=Path)
    parser.add_argument('--scope-sha256')
    parser.add_argument('--attempt', type=Path)
    parser.add_argument('--expires-minutes', type=int, default=60)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if (args.phase == 'apply') != args.apply or not 1 <= args.expires_minutes <= 120:
        raise RuntimeError('RECOVERY_PHASE_INVALID')
    verify_code(args.exact_root, args.exact_commit)
    from app.runtime_bindings import resolve_service_binding
    from app.runtime_handover import runtime_directory
    from app.reference_trading.recovery_campaign import (
        freeze_campaign, apply_campaign, validate_campaign, write_once, AttemptProgress,
    )
    binding = resolve_service_binding('reference-worker')
    if binding is None or binding.generation != args.binding_generation or not binding.enabled:
        raise RuntimeError('RECOVERY_RUNTIME_BINDING_INVALID')
    # Existing activation marker must remain exact; no enablement is done here.
    if (Path(binding.root)/'.run/reference-worker-enabled').read_text() != 'enabled\n':
        raise RuntimeError('REFERENCE_WORKER_NOT_ENABLED')
    directory = runtime_directory()
    config_hash = load_dependencies(directory/'project.env')
    with parked_reference_guard(directory=directory, expected_binding=asdict(binding)) as (assert_guard, binding_hash):
        identity = {'code_root':str(args.exact_root),'code_commit':args.exact_commit,
                    'binding':asdict(binding),'binding_sha256':binding_hash,'config_sha256':config_hash}
        with components(assert_guard) as (repository, recovery, journal_authority, worker, wake):
            if args.phase == 'freeze':
                if args.scope_file is None or args.scope_sha256 is None:
                    raise RuntimeError('RECOVERY_SCOPE_REQUIRED')
                raw = args.scope_file.read_bytes()
                if sha256(raw).hexdigest() != args.scope_sha256:
                    raise RuntimeError('RECOVERY_SCOPE_HASH_CONFLICT')
                products = [group['product'] for group in json.loads(raw)['groups']]
                if len(products) != 45 or len(set(products)) != 45:
                    raise RuntimeError('RECOVERY_SCOPE_INVALID')
                now = datetime.now(UTC)
                frozen = freeze_campaign(repository, recovery, journal_authority, products=products,
                    day=date(2026,10,12), observed_at=now, expires_at=now+timedelta(minutes=args.expires_minutes),
                    identity=identity)
                assert_guard()
                write_once(args.plan, frozen)
                print(json.dumps({'status':'FROZEN_NO_APPLY','plan_hash':frozen['plan_hash'],'groups':45,'streams':180}))
            else:
                frozen = json.loads(args.plan.read_bytes())
                plans = validate_campaign(frozen, expected_hash=args.expected_plan_hash)
                if len(frozen['groups']) != 45 or any(len(group['routes']) != 4 or len(group['plans']) != 4
                        for group in frozen['groups']):
                    raise RuntimeError('RECOVERY_SCOPE_INVALID')
                if frozen['identity'] != identity:
                    raise RuntimeError('RECOVERY_EXECUTION_IDENTITY_DRIFT')
                if args.phase == 'readback':
                    found = [{'stream_id':plan.capture.stream_id,'readback':recovery.readback(plan),
                              'gap_calculation':recovery.consumed_calculation(plan)} for plan in plans]
                    print(json.dumps({'status':'READBACK_ONLY','streams':found}))
                else:
                    if args.attempt is None:
                        raise RuntimeError('RECOVERY_ATTEMPT_REQUIRED')
                    progress = AttemptProgress(args.attempt, plan_hash=frozen['plan_hash'])
                    try:
                        apply_campaign(frozen, recovery=recovery, worker=worker, wake=wake,
                            progress=progress, now=lambda:datetime.now(UTC), assert_guard=assert_guard)
                    finally:
                        progress.close()
                    print(json.dumps({'status':'RECOVERY_COMMITTED','cursor':frozen['tail_id'],
                                      'natural_acceptance':'PENDING_NEW_COMPLETED_OBSERVATION'}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # Never print stack traces, config values, SQL or provider messages.
        code = str(error)
        if not code or not all(char.isupper() or char.isdigit() or char == '_' for char in code):
            code = 'REFERENCE_RECOVERY_FAILED'
        print(json.dumps({'status':'STOPPED_NO_RETRY','reason':code}))
        raise SystemExit(2)
