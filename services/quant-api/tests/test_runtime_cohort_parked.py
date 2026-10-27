"""A parked old reader must never be restarted after recovery facts exist."""
from dataclasses import asdict
from copy import deepcopy
import pytest
from app import runtime_cohort_host as module
from app import runtime_handover
from app.runtime_bindings import BindingRegistry
from app.runtime_cohort import CohortError
from app.runtime_cohort_host import CohortHost
from tests.test_runtime_cohort_host import binding


def setup(tmp_path, monkeypatch):
    b = binding(tmp_path, 'reference-worker')
    reg = BindingRegistry(1, {'reference-worker': b})
    host = object.__new__(CohortHost)
    host.directory = tmp_path
    control = dict(schema_version=1, service=b.service, generation=b.generation,
                   request_id='a'*32, phase='drain')
    runtime_handover._write(tmp_path/'reference-worker.handover.json', control)
    plan = {'old':asdict(reg), 'new':asdict(reg), 'installed':{
        b.service:dict(parked_drain=deepcopy(control), loaded=True, loaded_pid=6228, plist_hex=b'old'.hex())}}
    host.bindings = lambda:reg
    host.drains = {b.service:control['request_id']}
    host._replace_plist = lambda *_:None
    host.path = lambda _:tmp_path/'ref.plist'
    host.assert_installed = lambda *_:None
    host.definition_absent = lambda _:False
    host.launch = lambda *_args, **_kwargs:pytest.fail('preparked old reader must not be enabled or bootstrapped')
    host.start = lambda *_:pytest.fail('preparked old reader must not restart')
    monkeypatch.setattr(module, 'CONTINUOUS', (b.service,))
    monkeypatch.setattr(module, 'CALENDARS', ())
    monkeypatch.setattr(module, 'owner_process_matches', lambda *_:True)
    monkeypatch.setattr(module, 'owner_lock_available', lambda *_args, **_kw:True)
    monkeypatch.setattr(module, 'cancel_drain', lambda *_args, **_kw:pytest.fail('original drain must remain'))
    monkeypatch.setattr(module, 'read_service_state', lambda _:dict(phase='parked', generation=b.generation, pid=6228))
    return host, plan, b, control


def test_pre_cas_restore_preserves_surviving_parked_owner(tmp_path, monkeypatch):
    host, plan, b, control = setup(tmp_path, monkeypatch)
    host.restore_old(plan)
    assert runtime_handover._read(tmp_path/f'{b.service}.handover.json') == control


def test_exited_parked_reader_is_never_restarted_or_reported_restored(tmp_path, monkeypatch):
    host, plan, b, control = setup(tmp_path, monkeypatch)
    host.definition_absent = lambda _:True
    with pytest.raises(CohortError, match='PARKED_OWNER_FORWARD_RECOVERY_REQUIRED'):
        host.restore_old(plan)
    assert runtime_handover._read(tmp_path/f'{b.service}.handover.json') == control


@pytest.mark.parametrize('field,value', [('phase','cancelled'),('generation',999),('request_id','b'*32)])
def test_changed_drain_rejects_before_any_restore_effect(tmp_path, monkeypatch, field, value):
    host, plan, b, control = setup(tmp_path, monkeypatch)
    host._replace_plist = lambda *_:pytest.fail('must reject before plist mutation')
    control[field] = value
    runtime_handover._write(tmp_path/f'{b.service}.handover.json', control)
    with pytest.raises(CohortError, match='PARKED_DRAIN_CHANGED'):
        host.restore_old(plan)


@pytest.mark.parametrize('field,value', [('schema_version',True),('generation',True),('service','live'),('request_id','x'),('extra',1)])
def test_invalid_frozen_drain_rejected(tmp_path, monkeypatch, field, value):
    host, plan, b, control = setup(tmp_path, monkeypatch)
    plan['installed'][b.service]['parked_drain'][field] = value
    with pytest.raises(CohortError, match='PARKED_DRAIN_UNPROVEN'):
        host._preserved_drain(plan, b.service)


def installed_host(tmp_path, monkeypatch):
    from app import runtime_identity
    from app.runtime_fault_recovery_host import FaultRecoveryHost

    host, plan, b, control = setup(tmp_path, monkeypatch)
    reg = BindingRegistry(1, {b.service: b})
    owner = dict(phase='parked', generation=b.generation, pid=6228)
    host.loaded = lambda *_args, **_kwargs: 6228
    monkeypatch.setattr(module, 'read_service_state', lambda _: owner)
    monkeypatch.setattr(runtime_identity, 'read_launchd_service', lambda *_args, **_kwargs: object())
    monkeypatch.setattr(FaultRecoveryHost, 'installed', lambda *_: {
        b.service: dict(loaded_pid=6228, plist_hex=b'old'.hex())})
    return host, reg, owner, control


def test_installed_freezes_exact_parked_drain_without_rewriting_it(tmp_path, monkeypatch):
    host, reg, _, control = installed_host(tmp_path, monkeypatch)
    path = tmp_path/'reference-worker.handover.json'
    before = path.read_bytes()
    observed = host.installed(reg)
    assert observed['reference-worker']['parked_drain'] == control
    assert observed['reference-worker']['loaded_pid'] == 6228
    assert observed['reference-worker']['loaded'] is True
    assert path.read_bytes() == before


@pytest.mark.parametrize('fault', ['pid', 'generation', 'identity', 'held_lock', 'missing_control', 'bad_control'])
def test_installed_rejects_unproven_park_before_plan_effects(tmp_path, monkeypatch, fault):
    host, reg, owner, control = installed_host(tmp_path, monkeypatch)
    if fault == 'pid':
        owner['pid'] = 6229
    elif fault == 'generation':
        owner['generation'] += 1
    elif fault == 'identity':
        monkeypatch.setattr(module, 'owner_process_matches', lambda *_: False)
    elif fault == 'held_lock':
        monkeypatch.setattr(module, 'owner_lock_available', lambda *_args, **_kw: False)
    elif fault == 'missing_control':
        (tmp_path/'reference-worker.handover.json').unlink()
    else:
        control['phase'] = 'cancelled'
        runtime_handover._write(tmp_path/'reference-worker.handover.json', control)
    with pytest.raises(CohortError, match='COHORT_PARKED_'):
        host.installed(reg)


def test_active_owner_with_old_drain_is_not_inferred_to_be_preserved(tmp_path, monkeypatch):
    host, reg, owner, _ = installed_host(tmp_path, monkeypatch)
    owner['phase'] = 'active'
    assert 'parked_drain' not in host.installed(reg)['reference-worker']


def test_complete_drain_adopts_parked_request_and_drains_other_owner(tmp_path, monkeypatch):
    import json
    from datetime import UTC, datetime
    from app import redis_connections
    from app.db import session as database

    host, plan, reference, control = setup(tmp_path, monkeypatch)
    feed = binding(tmp_path, 'market-feed')
    plan['old'] = asdict(BindingRegistry(1, {reference.service: reference, feed.service: feed}))
    now = datetime(2026, 10, 28, tzinfo=UTC)
    host.now = lambda: now
    host.deadline = float('inf')
    host.session_proof = lambda: {'mode': 'closed_idle'}
    host.loaded = lambda b, **_: 6228 if b.service == reference.service else 6339
    requests = []

    def request(name, generation):
        requests.append(name)
        return runtime_handover.request_drain(name, generation=generation, runtime_dir=tmp_path)

    host.request_drain = request
    monkeypatch.setattr(module, 'CONTINUOUS', (feed.service, reference.service))
    monkeypatch.setattr(module, 'read_service_state', lambda name: {
        'phase': 'parked', 'generation': reference.generation,
        'pid': 6228 if name == reference.service else 6339})
    monkeypatch.setattr(module, 'observation_progress', lambda _: {'day': {'cursor': '1-0', 'tail': '1-0'}})

    class Redis:
        def get(self, key):
            assert key == 'live:feed:heartbeat'
            return json.dumps({'runtime_commit': feed.commit, 'runtime_generation': feed.generation,
                'input_pending_count': 0, 'input_failure': None, 'subscribed_count': 0,
                'generated_at': now.isoformat()})

        def close(self):
            pass

    class ReadSession:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def scalar(self, query):
            assert str(query).startswith('SELECT')
            return 0

    monkeypatch.setattr(redis_connections, 'get_redis_connection', Redis)
    monkeypatch.setattr(database, 'SessionLocal', ReadSession)
    path = tmp_path/'reference-worker.handover.json'
    before = path.read_bytes()
    proof = host.drain(plan)
    assert requests == ['market-feed']
    assert host.drains[reference.service] == control['request_id']
    assert path.read_bytes() == before
    assert proof['owners'][reference.service]['phase'] == 'parked'
    assert runtime_handover._read(tmp_path/'market-feed.handover.json')['request_id'] == host.drains[feed.service]


def test_restore_preserves_plan_park_even_before_cohort_drain_was_called(tmp_path, monkeypatch):
    host, plan, _, control = setup(tmp_path, monkeypatch)
    host.drains = {}
    host.restore_old(plan)
    assert runtime_handover._read(tmp_path/'reference-worker.handover.json') == control


def test_drain_rejects_replacement_pid_even_when_loaded_identity_matches(tmp_path, monkeypatch):
    host, plan, reference, control = setup(tmp_path, monkeypatch)
    host.deadline = float('inf')
    host.loaded = lambda *_args, **_kwargs: 6229
    host.request_drain = lambda *_: pytest.fail('preserved request must not be replaced')
    monkeypatch.setattr(module, 'read_service_state', lambda _: {
        'phase': 'parked', 'generation': reference.generation, 'pid': 6229})
    ticks = iter((0, 0, 11))
    monkeypatch.setattr(module, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(module, 'sleep', lambda _: None)
    with pytest.raises(CohortError, match='COHORT_OLD_DRAIN_TIMEOUT'):
        host.drain(plan)
    assert runtime_handover._read(tmp_path/'reference-worker.handover.json') == control


def test_exited_preserved_owner_does_not_prevent_other_owner_safe_restore(tmp_path, monkeypatch):
    host, plan, reference, control = setup(tmp_path, monkeypatch)
    live = binding(tmp_path, 'live')
    reg = BindingRegistry(1, {reference.service: reference, live.service: live})
    plan['old'] = plan['new'] = asdict(reg)
    plan['installed'][live.service] = dict(loaded=True, loaded_pid=7339, plist_hex=b'live'.hex())
    host.bindings = lambda: reg
    host.drains[live.service] = 'b'*32
    absent = {reference.service, live.service}
    host.definition_absent = lambda b: b.service in absent
    calls = []
    host.launch = lambda *args, **kwargs: calls.append(('launch', args))

    def start(b):
        assert b.service == live.service
        calls.append(('start', b.service))
        absent.remove(b.service)

    host.start = start
    monkeypatch.setattr(module, 'CONTINUOUS', (reference.service, live.service))
    monkeypatch.setattr(module, 'cancel_drain', lambda name, **_: calls.append(('cancel', name)))
    monkeypatch.setattr(module, 'read_service_state', lambda name: {
        'phase': 'parked' if name == reference.service else 'active',
        'generation': reference.generation, 'pid': 6228 if name == reference.service else 7339})
    with pytest.raises(CohortError, match='PARKED_OWNER_FORWARD_RECOVERY_REQUIRED'):
        host.restore_old(plan)
    assert ('cancel', live.service) in calls and ('start', live.service) in calls
    assert not any(reference.label in str(call) or call == ('cancel', reference.service) for call in calls)
    assert runtime_handover._read(tmp_path/'reference-worker.handover.json') == control
