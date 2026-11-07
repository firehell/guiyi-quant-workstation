"""Bounded, durable scheduling facts for the sole homepage projection writer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import re

from .home_projection import ProjectionError, ProjectionStore

WORK_SCHEMA = 'newow_home_recovery_v1'
POLICY_VERSION = 'home_recovery_policy_v1'
STATUSES = frozenset({'pending', 'running', 'retry_wait', 'dependency_wait', 'blocked', 'succeeded', 'superseded'})


@dataclass(frozen=True)
class RecoveryPolicy:
    period_seconds: int = 120
    cooldown_seconds: int = 900
    check_seconds: int = 60
    product_starts: int = 6
    product_seconds: int = 360
    initial_seconds: int = 1200
    retry_seconds: int = 600


def stamp(seconds):
    return datetime.fromtimestamp(seconds, UTC).isoformat()


def safe_code(value):
    return value if isinstance(value, str) and re.fullmatch(r'(HOME|NEWOW|MARKET|MAIN_CONTRACT|READ_ONLY)_[A-Z0-9_]{1,100}', value) else 'HOME_PROJECTION_BUILD_FAILED'


def failure_detail(exc, *, stage='compute'):
    """No exception message, SQL, locals or private absolute paths."""
    code = safe_code(getattr(exc, 'code', None))
    from psycopg import OperationalError
    chain = []
    current = exc
    for _ in range(8):
        if current is None or current in chain:
            break
        chain.append(current)
        current = getattr(current, 'orig', None) or current.__cause__
    driver_transient = any(
        (isinstance(getattr(cause, 'sqlstate', None), str) and (
            cause.sqlstate.startswith('08') or cause.sqlstate in {'40001', '40P01', '57P01', '57P02', '57P03'}))
        or (isinstance(cause, OperationalError) and cause.sqlstate is None)
        or isinstance(cause, ConnectionError)
        for cause in chain)
    category = 'unknown'
    if driver_transient:
        category = 'transient'
    elif code in {'HOME_COMPUTE_TIMEOUT', 'NEWOW_READ_CANCELLED'}:
        category = 'timeout'
    elif code == 'HOME_PROJECTION_SOURCE_CHANGED':
        category = 'source_changed'
    elif code.startswith(('MARKET_', 'MAIN_CONTRACT_')) or code in {'NEWOW_DAILY_SNAPSHOT_UNAVAILABLE', 'NEWOW_WEEKLY_UNKNOWN', 'NEWOW_INPUT_UNAVAILABLE'}:
        category = 'data'
    trace = exc.__traceback__
    while trace is not None and trace.tb_next is not None:
        trace = trace.tb_next
    def label(value):
        return value if re.fullmatch(r'[A-Za-z0-9_.<>-]{1,100}', value) else 'redacted'
    return {'code': code, 'category': category, 'stage': stage,
            'exception_type': label(type(exc).__name__),
            'file': label(Path(trace.tb_frame.f_code.co_filename).name) if trace else 'unknown',
            'function': label(trace.tb_frame.f_code.co_name) if trace else 'unknown',
            'line': trace.tb_lineno if trace else 0}


class WorkStore(ProjectionStore):
    def __init__(self, projection_path):
        super().__init__(projection_path.with_name(projection_path.name + '.work.json'),
                         schema=WORK_SCHEMA, max_bytes=256 * 1024, max_items=61)

    def state(self):
        value = self.load()
        if value is None:
            if self.path.exists() or self.path.is_symlink():
                raise ProjectionError()
            return {'schema_version': WORK_SCHEMA, 'items': {}, 'budgets': {}, 'probe': {}}
        _validate_state(value)
        return value

    def public(self, products, versions=None):
        if not self.path.exists() and not self.path.is_symlink():
            return {}
        try:
            state = self.state()
            if state.get('dependency_error'):
                detail = state['dependency_error']
                return {p: {'status': 'dependency_wait', 'category': detail['category'], 'code': safe_code(detail['code'])} for p in products}
            result = {}
            for product in products:
                job = state['items'].get(product)
                if job is None:
                    continue
                if versions is not None and any(job['target'].get(period) != versions.get(f'{product}:{period}') for period in ('1d', '1w')):
                    result[product] = {'status': 'pending', 'category': 'source_changed', 'code': 'HOME_PROJECTION_SOURCE_CHANGED', 'attempt': 0}
                    continue
                item = {'status': job['status'], 'attempt': job.get('attempt', 0)}
                if job['status'] == 'running' and not self.building():
                    item.update(status='retry_wait', category='interrupted', code='HOME_COMPUTE_INTERRUPTED')
                detail = job.get('detail', {})
                if item['status'] == job['status']:
                    item.update({key: detail[key] for key in ('category', 'code') if key in detail})
                for source, target in (('last_at', 'last_attempt_at'), ('next_at', 'next_attempt_at')):
                    if job.get(source) is not None:
                        item[target] = stamp(job[source])
                result[product] = item
            return result
        except (ProjectionError, ValueError, TypeError, OverflowError):
            return {p: {'status': 'blocked', 'category': 'state', 'code': 'HOME_RECOVERY_STATE_INVALID'} for p in products}


def _validate_state(value):
    def number(n):
        if type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 253402300799:
            raise ProjectionError()
    def counter(n):
        if type(n) is not int or not 0 <= n <= 10000000:
            raise ProjectionError()
    try:
        if not isinstance(value.get('budgets'), dict) or len(value['budgets']) > 3 or not isinstance(value.get('probe'), dict):
            raise ProjectionError()
        for key in ('at', 'previous_success_at'):
            if value['probe'].get(key) is not None:
                number(value['probe'][key])
        counter(value['probe'].get('successes', 0))
        if 'budget_at' in value:
            number(value['budget_at'])
        if 'budget_hour' in value and (type(value['budget_hour']) is not int or value['budget_hour'] < 0):
            raise ProjectionError()
        for product, job in value['items'].items():
            if product != 'overview' and re.fullmatch(r'[a-z]{1,4}', product) is None:
                raise ProjectionError()
            if (not isinstance(job, dict) or job.get('status') not in STATUSES
                    or re.fullmatch(r'[0-9a-f]{64}', job.get('id', '')) is None
                    or not isinstance(job.get('target'), dict)
                    or not isinstance(job.get('history'), list) or len(job['history']) > 3):
                raise ProjectionError()
            counter(job['attempt'])
            counter(job['round_attempt'])
            for key in ('created_at', 'last_at', 'next_at', 'stable_at'):
                if job.get(key) is not None:
                    number(job[key])
            _validate_reservation(job.get('reservation'))
            detail = job.get('detail', {})
            if not isinstance(detail, dict):
                raise ProjectionError()
            if 'code' in detail and safe_code(detail['code']) != detail['code']:
                raise ProjectionError()
            if 'category' in detail and detail['category'] not in {'unknown', 'transient', 'timeout', 'data', 'source_changed', 'interrupted', 'state', 'budget'}:
                raise ProjectionError()
        for hour, budget in value['budgets'].items():
            if re.fullmatch(r'[0-9]{1,12}', hour) is None or not isinstance(budget, dict) or not isinstance(budget.get('products'), dict):
                raise ProjectionError()
            number(budget['initial'])
            number(budget['retry'])
            for usage in budget['products'].values():
                counter(usage['starts'])
                number(usage['seconds'])
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ProjectionError() from None


def reconcile(state, product, versions, implementation, ready, now):
    identity = sha256(json.dumps([POLICY_VERSION, product, versions, implementation], sort_keys=True).encode()).hexdigest()
    old = state['items'].get(product)
    if old is None or old['id'] != identity:
        previous = old
        old = {'id': identity, 'target': versions, 'status': 'pending', 'attempt': 0,
               'round_attempt': 0, 'created_at': now, 'history': previous.get('history', []) if previous else []}
        if previous and not ready:
            old['next_at'] = now + 30
        state['items'][product] = old
    elif old['status'] == 'succeeded' and not ready:
        old.update(status='pending', next_at=now + 30)
    if ready:
        old.update(status='succeeded', next_at=None)
        old.pop('detail', None)
    return old


def hour_budget(state, now):
    hour = int(now // 3600)
    # Backwards clocks do not create fresh tokens.
    hour = max(hour, state.get('budget_hour', max((int(k) for k in state['budgets']), default=hour)))
    state['budget_hour'] = hour
    budget = state['budgets'].setdefault(str(hour), {'initial': 0.0, 'retry': 0.0, 'products': {}})
    for key in sorted(state['budgets'], key=int)[:-3]:
        del state['budgets'][key]
    return hour, budget


def probe(state, healthy, now):
    old = state.get('probe', {})
    if old.get('at') is not None and now - old['at'] < 60:
        return
    state['probe'] = {'at': now, 'successes': min(2, old.get('successes', 0) + 1) if healthy else 0,
                      'previous_success_at': old.get('at') if healthy and old.get('successes', 0) else None}


def eligible(job, state, now, policy):
    if job['status'] in {'running', 'blocked', 'succeeded', 'superseded'}:
        return False
    if now < job.get('next_at', 0):
        return False
    if job['status'] == 'dependency_wait':
        health = state.get('probe', {})
        if (health.get('successes', 0) < 2 or job.get('detail', {}).get('category') != 'transient'
                or (health.get('previous_success_at') or 0) < job['next_at']):
            return False
        job['round_attempt'] = 0
    return True


def reserve(state, product, job, now, seconds, policy, *, starts=1):
    if not math.isfinite(now) or not 0 < seconds <= 2 * policy.period_seconds:
        raise ProjectionError()
    hour, budget = hour_budget(state, now)
    usage = budget['products'].setdefault(product, {'starts': 0, 'seconds': 0.0})
    pool = 'initial' if usage['starts'] == 0 else 'retry'
    limit = policy.initial_seconds if pool == 'initial' else policy.retry_seconds
    if usage['starts'] + starts > policy.product_starts or usage['seconds'] + seconds > policy.product_seconds or budget[pool] + seconds > limit:
        job.update(status='retry_wait', next_at=(hour + 1) * 3600,
                   detail={'category': 'budget', 'code': 'HOME_RECOVERY_BUDGET_WAIT'})
        return False
    usage['starts'] += starts
    usage['seconds'] += seconds
    budget[pool] += seconds
    job.update(status='running', attempt=job['attempt'] + 1,
               round_attempt=job.get('round_attempt', 0) + 1, last_at=now, next_at=None,
               reservation={'hour': hour, 'pool': pool, 'seconds': seconds, 'starts': starts, 'at': max(now, hour * 3600)})
    return True


def settle(state, product, job, elapsed, *, starts=None):
    reservation = job.pop('reservation', None)
    if reservation is None:
        return
    if 'slots' in reservation:
        # Slots were charged at their actual starts. Only never-started
        # allocations may be returned; an unended slot retains its upper bound.
        _adjust(state, product, reservation['hour'], reservation['pool'],
                -reservation['pending_seconds'], -reservation['pending_starts'])
        _prune_budgets(state)
        return
    spent = min(reservation['seconds'], max(0.0, elapsed))
    budget = state['budgets'][str(reservation['hour'])]
    if starts is not None:
        budget['products'][product]['starts'] -= max(0, reservation.get('starts', 1) - starts)
    budget[reservation['pool']] -= reservation['seconds']
    budget['products'][product]['seconds'] -= reservation['seconds']
    # Split occupied seconds at UTC hour boundaries, even across a restart window.
    at = reservation['at']
    while spent > 0:
        hour = int(at // 3600)
        portion = min(spent, (hour + 1) * 3600 - at)
        target = state['budgets'].setdefault(str(hour), {'initial': 0.0, 'retry': 0.0, 'products': {}})
        usage = target['products'].setdefault(product, {'starts': 0, 'seconds': 0.0})
        target[reservation['pool']] += portion
        usage['seconds'] += portion
        at += portion
        spent -= portion
    state['budget_at'] = max(state.get('budget_at', 0), at)
    state['budget_hour'] = max(state.get('budget_hour', 0), int(at // 3600))
    for key in sorted(state['budgets'], key=int)[:-3]:
        del state['budgets'][key]


def finish(job, detail, now, policy):
    if detail is None:
        job.update(status='succeeded', next_at=None)
        job.pop('detail', None)
        return
    job['detail'] = detail
    job['history'] = [*job.get('history', []), {'at': now, 'job_id': job['id'], 'target': job['target'], 'attempt': job['attempt'], **detail}][-3:]
    category = detail['category']
    if category == 'budget':
        job.update(status='retry_wait', next_at=job.get('next_at') or (int(now // 3600) + 1) * 3600)
    elif category == 'source_changed':
        job.update(status='retry_wait', next_at=now + 60, stable_at=now)
    elif category == 'transient':
        if job['round_attempt'] >= 3:
            job.update(status='dependency_wait', next_at=now + policy.cooldown_seconds)
        else:
            job.update(status='retry_wait', next_at=now + (30 if job['round_attempt'] == 1 else 120))
    elif category in {'unknown', 'timeout', 'interrupted'} and job['attempt'] < 2:
        job.update(status='retry_wait', next_at=now + 30)
    else:
        job.update(status='blocked', next_at=None)


def _validate_reservation(reservation):
    if reservation is None:
        return
    try:
        if (not isinstance(reservation, dict) or reservation['pool'] not in {'initial', 'retry'}
                or type(reservation['hour']) is not int or reservation['hour'] < 0
                or type(reservation.get('starts', 1)) is not int or not 1 <= reservation.get('starts', 1) <= 2):
            raise ProjectionError()
        for key in ('seconds', 'at'):
            if type(reservation[key]) not in (int, float) or not math.isfinite(reservation[key]) or reservation[key] < 0:
                raise ProjectionError()
        if reservation['seconds'] <= 0:
            raise ProjectionError()
        if 'slots' not in reservation:
            return
        slots = reservation['slots']
        if (not isinstance(slots, list) or len(slots) > reservation['starts']
                or len(slots) > 2 or reservation['pending_starts'] != reservation['starts'] - len(slots)
                or type(reservation['pending_starts']) is not int
                or type(reservation['pending_seconds']) not in (int, float)
                or not math.isfinite(reservation['pending_seconds'])
                or not 0 <= reservation['pending_seconds'] <= reservation['seconds']):
            raise ProjectionError()
        for index, slot in enumerate(slots):
            if (not isinstance(slot, dict) or slot['index'] != index or type(slot['index']) is not int
                    or slot['pool'] not in {'initial', 'retry'} or type(slot['hour']) is not int
                    or not isinstance(slot['charges'], list) or len(slot['charges']) > 2):
                raise ProjectionError()
            for key in ('at', 'seconds', 'elapsed'):
                if key in slot and (type(slot[key]) not in (int, float) or not math.isfinite(slot[key]) or slot[key] < 0):
                    raise ProjectionError()
            if slot['hour'] != int(slot['at'] // 3600) or slot['seconds'] > reservation['seconds']:
                raise ProjectionError()
            if not math.isclose(slot['seconds'], reservation['seconds'] / reservation['starts'], abs_tol=1e-8):
                raise ProjectionError()
            expected_charges = _pieces(slot['at'], slot.get('elapsed', slot['seconds']))
            if (len(expected_charges) != len(slot['charges'])
                    or any(expected['hour'] != actual.get('hour')
                           or not math.isclose(expected['seconds'], actual.get('seconds', -1), abs_tol=1e-8)
                           for expected, actual in zip(expected_charges, slot['charges']))):
                raise ProjectionError()
            for charge in slot['charges']:
                if (not isinstance(charge, dict) or type(charge['hour']) is not int or charge['hour'] < 0
                        or type(charge['seconds']) not in (int, float) or not math.isfinite(charge['seconds'])
                        or not 0 <= charge['seconds'] <= max(slot['seconds'], slot.get('elapsed', 0))):
                    raise ProjectionError()
        if not math.isclose(reservation['pending_seconds'],
                            reservation['seconds'] - sum(slot['seconds'] for slot in slots), abs_tol=1e-8):
            raise ProjectionError()
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise ProjectionError() from None


def _prune_budgets(state):
    for key in sorted(state['budgets'], key=int)[:-3]:
        del state['budgets'][key]


def _pieces(at, seconds):
    pieces = []
    while seconds > 0:
        hour = int(at // 3600)
        portion = min(seconds, (hour + 1) * 3600 - at)
        if portion <= 0 or len(pieces) >= 2:
            raise ProjectionError()
        pieces.append({'hour': hour, 'seconds': portion})
        at += portion
        seconds -= portion
    return pieces


def _adjust(state, product, hour, pool, seconds, starts=0):
    if str(hour) not in state['budgets'] and seconds <= 0 and starts <= 0:
        return  # An expired hour is never recreated merely to refund it.
    budget = state['budgets'].setdefault(str(hour), {'initial': 0.0, 'retry': 0.0, 'products': {}})
    usage = budget['products'].setdefault(product, {'starts': 0, 'seconds': 0.0})
    budget[pool] = max(0.0, budget[pool] + seconds)
    usage['seconds'] = max(0.0, usage['seconds'] + seconds)
    usage['starts'] = max(0, usage['starts'] + starts)


def start_compute(state, product, job, now, policy):
    """Reserve one actual executor call; caller must persist before launching.

    Returns a bounded slot record or None on hourly budget denial. Future time
    portions are prepaid too, so a crash cannot leave cross-hour CPU uncharged.
    """
    reservation = job.get('reservation')
    _validate_reservation(reservation)
    if reservation is None or not math.isfinite(now) or now < 0:
        raise ProjectionError()
    planned = reservation.get('starts', 1)
    if reservation['seconds'] > planned * policy.period_seconds or policy.period_seconds > 3600:
        raise ProjectionError()
    if 'slots' not in reservation:
        reservation.update(slots=[], pending_seconds=reservation['seconds'], pending_starts=planned)
    if reservation['pending_starts'] <= 0 or len(reservation['slots']) >= 2:
        raise ProjectionError()
    hour, _ = hour_budget(state, now)
    at = max(now, hour * 3600, state.get('budget_at', 0))
    hour = int(at // 3600)
    seconds = reservation['seconds'] / planned
    budget = state['budgets'].get(str(hour), {'initial': 0, 'retry': 0, 'products': {}})
    usage = budget['products'].get(product, {'starts': 0, 'seconds': 0})
    pool = reservation['pool'] if hour == reservation['hour'] else ('initial' if usage['starts'] == 0 else 'retry')
    charges = _pieces(at, seconds)
    # Test the complete transfer before changing any funded allocation.
    deltas = {}
    def delta(target_hour, target_pool, amount, starts=0):
        row = deltas.setdefault(target_hour, {'initial': 0.0, 'retry': 0.0, 'seconds': 0.0, 'starts': 0})
        row[target_pool] += amount
        row['seconds'] += amount
        row['starts'] += starts
    if str(reservation['hour']) in state['budgets']:
        delta(reservation['hour'], reservation['pool'], -seconds, -1)
    for charge in charges:
        delta(charge['hour'], pool, charge['seconds'])
    delta(hour, pool, 0, 1)
    for target_hour, changes in deltas.items():
        target = state['budgets'].get(str(target_hour), {'initial': 0, 'retry': 0, 'products': {}})
        used = target['products'].get(product, {'starts': 0, 'seconds': 0})
        if ((changes['starts'] > 0 and used['starts'] + changes['starts'] > policy.product_starts)
                or (changes['seconds'] > 0 and used['seconds'] + changes['seconds'] > policy.product_seconds)
                or any(changes[p] > 0 and target[p] + changes[p] > limit
                       for p, limit in (('initial', policy.initial_seconds), ('retry', policy.retry_seconds)))):
            job.update(status='retry_wait', next_at=(target_hour + 1) * 3600,
                       detail={'category': 'budget', 'code': 'HOME_RECOVERY_BUDGET_WAIT'})
            return None
    _adjust(state, product, reservation['hour'], reservation['pool'], -seconds, -1)
    for charge in charges:
        _adjust(state, product, charge['hour'], pool, charge['seconds'])
    _adjust(state, product, hour, pool, 0, 1)
    reservation['pending_seconds'] = max(0.0, reservation['pending_seconds'] - seconds)
    reservation['pending_starts'] -= 1
    slot = {'index': len(reservation['slots']), 'at': at, 'hour': hour, 'pool': pool,
            'seconds': seconds, 'charges': charges}
    reservation['slots'].append(slot)
    state['budget_at'] = at
    state['budget_hour'] = max(state.get('budget_hour', hour), hour)
    _prune_budgets(state)
    return slot


def end_compute(state, product, job, slot, elapsed):
    """Settle only this executor's monotonic occupancy; caller persists after."""
    reservation = job.get('reservation')
    _validate_reservation(reservation)
    if (reservation is None or not isinstance(slot, dict) or type(slot.get('index')) is not int
            or not 0 <= slot['index'] < len(reservation.get('slots', []))
            or not math.isfinite(elapsed) or elapsed < 0):
        raise ProjectionError()
    current = reservation['slots'][slot['index']]
    if current['at'] != slot.get('at'):
        raise ProjectionError()
    if 'elapsed' in current:
        return
    # A late termination is still actual occupancy, not a refundable saving.
    spent = elapsed
    actual_charges = _pieces(current['at'], spent)
    for charge in current['charges']:
        _adjust(state, product, charge['hour'], current['pool'], -charge['seconds'])
    current['charges'] = actual_charges
    current['elapsed'] = spent
    for charge in current['charges']:
        _adjust(state, product, charge['hour'], current['pool'], charge['seconds'])
    state['budget_at'] = max(state.get('budget_at', 0), current['at'] + spent)
    state['budget_hour'] = max(state.get('budget_hour', 0), int(state['budget_at'] // 3600))
    _prune_budgets(state)
