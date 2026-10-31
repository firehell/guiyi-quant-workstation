#!/usr/bin/env python3
"""One-shot historical catch-up while the existing Reference owner is parked.

This does not drain, stop, activate, or restart any service. The caller supplies
an exact native drain preimage; the existing source/state locks remain in use.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import fcntl
from hashlib import sha256
import json
import os
import stat
from time import monotonic

from app.runtime_handover import _read, _path, deployment_lock, read_service_state

SERVICE = 'reference-worker'


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def parked_preimage(runtime_dir, binding):
    """Native parked is written only after all foreground/background cleanup."""
    owner = read_service_state(SERVICE, runtime_dir=runtime_dir)
    handover = _read(_path(runtime_dir, SERVICE, 'handover.json'))
    runtime = (owner or {}).get('proof', {}).get('reference_runtime', {})
    if (owner is None or handover is None or not binding.enabled
            or owner.get('phase') != 'parked' or owner.get('ready') is not False
            or owner.get('generation') != binding.generation
            or type(owner.get('pid')) is not int or owner['pid'] <= 0
            or handover.get('schema_version') != 1 or handover.get('service') != SERVICE
            or handover.get('phase') != 'drain' or handover.get('generation') != binding.generation
            or not isinstance(handover.get('request_id'), str) or not handover['request_id']
            or runtime.get('stage') != 'drained'
            or runtime.get('historical_refresh_alive') is not False
            or runtime.get('notifications_alive') is not False):
        raise ValueError('REFERENCE_MAINTENANCE_OWNER_NOT_PARKED')
    return {'owner': owner, 'handover': handover, 'binding': asdict(binding)}


def session_deadline(session_factory, products, *, now):
    """Use the same 60-product authority and 140 second margin as Runtime."""
    from app.db.readonly import readonly_transaction
    from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
    if len(products) != 60 or len(set(products)) != 60:
        raise ValueError('REFERENCE_MAINTENANCE_SCOPE_INVALID')
    ends = []
    with session_factory() as session, readonly_transaction(session, timeout_seconds=15):
        resolver = MarketPhaseResolver(session)
        for product in products:
            phase = resolver.resolve(product, now)
            if (phase.phase not in (MarketPhase.BREAK, MarketPhase.CLOSED)
                    or phase.next_session_start is None
                    or phase.next_session_start <= now + timedelta(seconds=140)):
                raise ValueError('REFERENCE_MAINTENANCE_SESSION_BLOCKED')
            ends.append(phase.next_session_start - timedelta(seconds=140))
    return min(ends)


@contextmanager
def maintenance_guard(*, runtime_dir, expected_preimage, deadline,
                      binding_reader, session_boundary, now=lambda: datetime.now(UTC)):
    """Hold deployment and old-owner exclusion; never overwrite owner proof."""
    if deadline.tzinfo is None or deadline <= now():
        raise ValueError('REFERENCE_MAINTENANCE_DEADLINE_INVALID')
    with deployment_lock(runtime_dir=runtime_dir):
        path = _path(runtime_dir, SERVICE, 'owner.lock')
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise ValueError('REFERENCE_MAINTENANCE_OWNER_INVALID')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('REFERENCE_MAINTENANCE_OWNER_BUSY') from None
            boundary = min(deadline, session_boundary(now()))
            initial_clock = monotonic()
            elapsed_limit = (boundary - now()).total_seconds()

            def check():
                disk = path.lstat()
                if (stat.S_ISLNK(disk.st_mode) or (disk.st_ino, disk.st_dev) != (info.st_ino, info.st_dev)
                        or parked_preimage(runtime_dir, binding_reader()) != expected_preimage):
                    raise ValueError('REFERENCE_MAINTENANCE_PREIMAGE_CHANGED')
                if now() >= boundary or monotonic() - initial_clock >= elapsed_limit:
                    raise ValueError('REFERENCE_MAINTENANCE_WINDOW_ENDED')

            def refresh_session():
                nonlocal boundary, elapsed_limit
                boundary = min(boundary, session_boundary(now()))
                elapsed_limit = min(elapsed_limit, monotonic() - initial_clock + (boundary - now()).total_seconds())
                check()

            check.refresh_session = refresh_session

            check()
            yield check
        finally:
            os.close(fd)


def bounded_catchup(runner, plan, *, check, now=lambda: datetime.now(UTC), progress=lambda _value: None):
    """Use the native runner without its normal inter-round/one-batch quantum.

    Plans remain single-stream and keep their original WorkBudget. New assets
    must first be built through the existing exact-plan/build/resume protocol;
    this entry does not pretend a missing stream was maintained.
    """
    if (plan.get('schema') != 'reference_history_maintenance_v1'
            or type(plan.get('max_ticks')) is not int or not 1 <= plan['max_ticks'] <= 10000
            or not isinstance(plan.get('routes'), list) or not plan['routes']):
        raise ValueError('REFERENCE_MAINTENANCE_PLAN_INVALID')
    frozen = {item['stream_id']: item for item in plan['routes']}
    if len(frozen) != len(plan['routes']):
        raise ValueError('REFERENCE_MAINTENANCE_SCOPE_INVALID')
    original_routes, original_endpoint = runner._routes, runner._endpoint
    original_components = runner._components
    current = {route.identity.stream_id: route for route in original_routes()}
    if set(frozen) - set(current):
        raise ValueError('REFERENCE_MAINTENANCE_ASSET_MISSING')
    for key, value in frozen.items():
        if (digest(asdict(current[key].identity)) != value['identity_sha256']
                or str(current[key].since) != value['since']):
            raise ValueError('REFERENCE_MAINTENANCE_SCOPE_CHANGED')

    def routes():
        observed = {route.identity.stream_id: route for route in original_routes()}
        if set(frozen) - set(observed):
            raise ValueError('REFERENCE_MAINTENANCE_ASSET_MISSING')
        result = [observed[key] for key in frozen]
        if any(digest(asdict(route.identity)) != frozen[route.identity.stream_id]['identity_sha256']
               or str(route.since) != frozen[route.identity.stream_id]['since'] for route in result):
            raise ValueError('REFERENCE_MAINTENANCE_SCOPE_CHANGED')
        return result

    def native_permission(function):
        from app.reference_trading.historical_refresh import RefreshPlanningYield
        try:
            function()
        except ValueError:
            # This precedes component work / DB mutation. Losing maintenance
            # permission must never turn a recoverable intent into blocked.
            raise RefreshPlanningYield() from None

    def endpoint(route, at):
        native_permission(check)
        value = frozen[route.identity.stream_id]
        end = datetime.fromisoformat(value['endpoint'])
        actual, _day = original_endpoint(route, at)
        if end.tzinfo is None or actual < end or end > at:
            raise ValueError('REFERENCE_MAINTENANCE_ENDPOINT_CHANGED')
        from datetime import date
        return end, date.fromisoformat(value['trading_day'])

    @contextmanager
    def components(**kwargs):
        native_permission(getattr(check, 'refresh_session', check))
        after = kwargs.get('after_batch')
        def after_batch(stage, context):
            if after:
                after(stage, context)
            progress({'stage': stage, 'context': context})
        with original_components(**{**kwargs, 'after_batch': after_batch}) as value:
            yield value

    def cancelled():
        try:
            check()
            return False
        except ValueError:
            return True

    runner._routes, runner._endpoint, runner._components = routes, endpoint, components
    try:
        for index in range(plan['max_ticks']):
            check()
            active = routes()
            state = runner.state.read()
            unfinished = [route for route in active
                          if route.reason or route.identity.stream_id in state['routes']
                          or route.computed_through is None
                          or route.computed_through < datetime.fromisoformat(frozen[route.identity.stream_id]['endpoint'])]
            if not unfinished:
                return {'status': 'completed', 'ticks': index}
            blocked = {route.identity.stream_id: state['routes'][route.identity.stream_id].get('reason')
                       for route in unfinished
                       if state['routes'].get(route.identity.stream_id, {}).get('status') == 'blocked'}
            if len(blocked) == len(unfinished):
                return {'status': 'blocked', 'reason': 'NO_RUNNABLE_ROUTES',
                        'routes': blocked, 'ticks': index}
            runner.tick(now=now(), cancelled=cancelled, batch_limit=None)
            progress({'stage': 'tick', 'index': index, 'progress': runner.last_progress})
            if runner.last_progress.get('reason') == 'SOURCE_BUSY':
                return {'status': 'partial', 'reason': 'SOURCE_BUSY', 'ticks': index + 1}
        return {'status': 'partial', 'reason': 'TICK_BUDGET_REACHED', 'ticks': plan['max_ticks']}
    finally:
        runner._routes, runner._endpoint, runner._components = original_routes, original_endpoint, original_components


def freeze_catchup_plan(runner, stream_ids, *, preimage, deadline, max_ticks, now):
    """Read-only exact scope and current durable intent preimage."""
    selected = set(stream_ids)
    if (not selected or len(selected) != len(stream_ids) or len(selected) > 1800
            or type(max_ticks) is not int or not 1 <= max_ticks <= 10000
            or deadline.tzinfo is None or not now < deadline <= now + timedelta(hours=24)):
        raise ValueError('REFERENCE_MAINTENANCE_PLAN_INVALID')
    routes = {route.identity.stream_id: route for route in runner._routes()}
    if selected - set(routes):
        raise ValueError('REFERENCE_MAINTENANCE_ASSET_MISSING')
    state = runner.state.read()
    cells = []
    for key in sorted(selected):
        route = routes[key]
        if route.since is None:
            raise ValueError('REFERENCE_MAINTENANCE_ASSET_MISSING')
        endpoint, day = runner._endpoint(route, now)
        if endpoint.tzinfo is None or endpoint > now:
            raise ValueError('REFERENCE_MAINTENANCE_ENDPOINT_CHANGED')
        prior = state['routes'].get(key)
        if prior is not None and prior['status'] != 'pending':
            raise ValueError('REFERENCE_MAINTENANCE_READBACK_REQUIRED')
        cells.append({'stream_id': key, 'identity_sha256': digest(asdict(route.identity)),
                      'since': str(route.since), 'endpoint': endpoint.isoformat(),
                      'trading_day': day.isoformat(), 'prior_sha256': digest(prior)})
    result = {'schema': 'reference_history_maintenance_v1', 'routes': cells,
              'preimage': preimage, 'deadline': deadline.isoformat(), 'max_ticks': max_ticks}
    return {**result, 'plan_hash': digest(result)}


def execute_catchup(runner, plan, *, expected_plan_hash, apply=False,
                    runtime_dir, binding_reader, session_boundary,
                    now=lambda: datetime.now(UTC), progress=lambda _value: None):
    """Explicit apply boundary; a dry-run never calls native tick."""
    body = {key: value for key, value in plan.items() if key != 'plan_hash'}
    if plan.get('plan_hash') != expected_plan_hash or digest(body) != expected_plan_hash:
        raise ValueError('REFERENCE_MAINTENANCE_PLAN_HASH_CONFLICT')
    deadline = datetime.fromisoformat(plan['deadline'])
    with maintenance_guard(runtime_dir=runtime_dir, expected_preimage=plan['preimage'],
                           deadline=deadline, binding_reader=binding_reader,
                           session_boundary=session_boundary, now=now) as check:
        check()
        # Read the original intents under the same state exclusion used by tick.
        # Release before tick: tick acquires it itself and owns all callback writes.
        with runner.state.exclusive() as acquired:
            if not acquired:
                raise ValueError('SOURCE_BUSY')
            current = runner.state.read()
            for cell in plan['routes']:
                if digest(current['routes'].get(cell['stream_id'])) != cell['prior_sha256']:
                    raise ValueError('REFERENCE_MAINTENANCE_INTENT_CHANGED')
        if not apply:
            return {'status': 'planned', 'readonly': True, 'plan_hash': expected_plan_hash,
                    'stream_count': len(plan['routes'])}
        result = bounded_catchup(runner, plan, check=check, now=now, progress=progress)
        return {**result, 'readonly': False, 'plan_hash': expected_plan_hash}
