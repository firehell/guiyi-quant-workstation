from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import fcntl
import json
import os
from types import SimpleNamespace

import pytest

from scripts.reference_history_maintenance import (
    bounded_catchup, execute_catchup, freeze_catchup_plan,
    maintenance_guard, parked_preimage,
)

NOW = datetime(2026, 10, 31, 1, tzinfo=UTC)


@dataclass
class Binding:
    generation: int = 43
    enabled: bool = True


@dataclass
class Identity:
    stream_id: str = 'stream-a'
    strategy_code: str = 'newow_trend'
    product: str = 'jm'
    frequency: str = '60m'


def private_json(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)


@pytest.fixture
def parked(tmp_path):
    tmp_path.chmod(0o700)
    runtime = {'stage': 'drained', 'historical_refresh_alive': False, 'notifications_alive': False}
    owner = {'schema_version': 1, 'service': 'reference-worker', 'generation': 43,
             'phase': 'parked', 'ready': False, 'pid': 123,
             'proof': {'reference_runtime': runtime}}
    handover = {'schema_version': 1, 'service': 'reference-worker', 'generation': 43,
                'phase': 'drain', 'request_id': 'exact-drain'}
    private_json(tmp_path / 'reference-worker.owner.json', owner)
    private_json(tmp_path / 'reference-worker.handover.json', handover)
    lock = tmp_path / 'reference-worker.owner.lock'
    lock.touch(mode=0o600)
    binding = Binding()
    preimage = parked_preimage(tmp_path, binding)
    return tmp_path, owner, handover, binding, preimage


def guard_args(parked):
    folder, _owner, _handover, binding, preimage = parked
    return dict(runtime_dir=folder, expected_preimage=preimage,
                deadline=NOW + timedelta(hours=1), binding_reader=lambda: binding,
                session_boundary=lambda _now: NOW + timedelta(hours=2), now=lambda: NOW)


def test_active_owner_or_unclosed_worker_is_never_a_maintenance_permit(parked):
    folder, owner, _, binding, _ = parked
    owner['phase'] = 'active'
    private_json(folder / 'reference-worker.owner.json', owner)
    with pytest.raises(ValueError, match='OWNER_NOT_PARKED'):
        parked_preimage(folder, binding)
    owner['phase'] = 'parked'
    owner['proof']['reference_runtime']['notifications_alive'] = True
    private_json(folder / 'reference-worker.owner.json', owner)
    with pytest.raises(ValueError, match='OWNER_NOT_PARKED'):
        parked_preimage(folder, binding)


def test_guard_holds_owner_exclusion_and_detects_cancelled_drain(parked):
    folder, _, handover, _, _ = parked
    with maintenance_guard(**guard_args(parked)) as check:
        fd = os.open(folder / 'reference-worker.owner.lock', os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        handover['phase'] = 'cancelled'
        private_json(folder / 'reference-worker.handover.json', handover)
        with pytest.raises(ValueError, match='OWNER_NOT_PARKED'):
            check()


def test_guard_rechecks_session_before_each_native_component_scope(parked):
    args = guard_args(parked)
    ends = iter([NOW + timedelta(hours=1), NOW])
    args['session_boundary'] = lambda _now: next(ends)
    with maintenance_guard(**args) as check:
        with pytest.raises(ValueError, match='WINDOW_ENDED'):
            check.refresh_session()


class State:
    def __init__(self):
        self.value = {'version': 'test', 'cursor': '', 'routes': {}}

    def read(self):
        return self.value

    def write(self, value):
        self.value = value

    @contextmanager
    def exclusive(self):
        yield True


def runner():
    route = SimpleNamespace(identity=Identity(), since=date(2025, 9, 25),
                            computed_through=NOW - timedelta(days=1), reason=None)
    calls = []
    value = SimpleNamespace(_routes=lambda: [route], state=State(), last_progress={},
                            _endpoint=lambda _route, _now: (NOW, NOW.date()),
                            _components=lambda **_kwargs: None)
    def tick(**kwargs):
        calls.append(kwargs)
        route.computed_through = NOW
    value.tick = tick
    value.calls = calls
    return value


def freeze(value, preimage):
    return freeze_catchup_plan(value, ['stream-a'], preimage=preimage,
                               deadline=NOW + timedelta(hours=1), max_ticks=2, now=NOW)


def test_frozen_dryrun_does_not_tick_and_apply_keeps_native_unlimited_batch_quantum(parked):
    folder, _, _, binding, preimage = parked
    value = runner()
    plan = freeze(value, preimage)
    options = dict(expected_plan_hash=plan['plan_hash'], runtime_dir=folder,
                   binding_reader=lambda: binding,
                   session_boundary=lambda _now: NOW + timedelta(hours=2), now=lambda: NOW)
    assert execute_catchup(value, plan, **options)['readonly']
    assert value.calls == []
    assert execute_catchup(value, plan, apply=True, **options)['status'] == 'completed'
    assert len(value.calls) == 1
    assert value.calls[0]['batch_limit'] is None
    assert not value.calls[0]['cancelled']()


def test_changed_intent_or_hash_stops_before_native_tick(parked):
    folder, _, _, binding, preimage = parked
    value = runner()
    plan = freeze(value, preimage)
    options = dict(expected_plan_hash=plan['plan_hash'], apply=True, runtime_dir=folder,
                   binding_reader=lambda: binding,
                   session_boundary=lambda _now: NOW + timedelta(hours=2), now=lambda: NOW)
    value.state.value['routes']['stream-a'] = {'status': 'inflight'}
    with pytest.raises(ValueError, match='INTENT_CHANGED'):
        execute_catchup(value, plan, **options)
    plan['max_ticks'] = 3
    with pytest.raises(ValueError, match='PLAN_HASH_CONFLICT'):
        execute_catchup(value, plan, **options)
    assert value.calls == []


def test_missing_new_asset_is_explicit_not_claimed_as_success(parked):
    with pytest.raises(ValueError, match='ASSET_MISSING'):
        freeze_catchup_plan(runner(), ['new-main-rise'], preimage=parked[-1],
                            deadline=NOW + timedelta(hours=1), max_ticks=1, now=NOW)


def test_tick_budget_is_bounded_even_when_no_progress(parked):
    value = runner()
    plan = freeze(value, parked[-1])
    value.tick = lambda **_kwargs: None
    assert bounded_catchup(value, plan, check=lambda: None, now=lambda: NOW) == {
        'status': 'partial', 'reason': 'TICK_BUDGET_REACHED', 'ticks': 2}


def test_only_blocked_work_stops_without_spinning_or_retrying_unknown(parked):
    value = runner()
    plan = freeze(value, parked[-1])
    value.state.value['routes']['stream-a'] = {'status': 'blocked', 'reason': 'REFRESH_READBACK_REQUIRED'}
    assert bounded_catchup(value, plan, check=lambda: None, now=lambda: NOW) == {
        'status': 'blocked', 'reason': 'NO_RUNNABLE_ROUTES',
        'routes': {'stream-a': 'REFRESH_READBACK_REQUIRED'}, 'ticks': 0}
    assert value.calls == []


def test_disappearing_frozen_route_never_reports_completed(parked):
    value = runner()
    original = value._routes
    plan = freeze(value, parked[-1])
    count = 0
    def disappearing():
        nonlocal count
        count += 1
        return original() if count == 1 else []
    value._routes = disappearing
    with pytest.raises(ValueError, match='ASSET_MISSING'):
        bounded_catchup(value, plan, check=lambda: None, now=lambda: NOW)


def test_real_native_runner_retains_pending_when_component_permission_ends(parked, monkeypatch):
    from app.reference_trading import historical_refresh as native
    monkeypatch.setattr(native, '_canonical_identity', lambda _identity: True)
    route = native.RefreshRoute(Identity(), date(2025, 9, 25), NOW - timedelta(days=1))
    state = State()
    prior = {'status': 'pending', 'reason': 'INTERRUPTED', 'plan': {'retained': 'exact'}}
    state.value['routes']['stream-a'] = prior.copy()
    @contextmanager
    def components(**_kwargs):
        pytest.fail('Permission ended before native components must open')
        yield
    value = native.HistoricalRefresh(routes=lambda: [route],
                                     endpoint=lambda _route, _now: (NOW, NOW.date()),
                                     components=components, state=state)
    plan = freeze_catchup_plan(value, ['stream-a'], preimage=parked[-1],
                               deadline=NOW + timedelta(hours=1), max_ticks=1, now=NOW)
    def check():
        return None
    def ended():
        raise ValueError('REFERENCE_MAINTENANCE_WINDOW_ENDED')
    check.refresh_session = ended
    result = bounded_catchup(value, plan, check=check, now=lambda: NOW)
    assert result['status'] == 'partial'
    assert state.value['routes']['stream-a'] == prior
    assert state.value['cursor'] == ''
