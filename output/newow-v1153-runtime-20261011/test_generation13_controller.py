"""Isolated gen12→13 controller safety; never invoke production adapters."""
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
DRIVER=Path(__file__).with_name('deploy_generation13.py')
spec=importlib.util.spec_from_file_location('gen13_isolated',DRIVER)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
@pytest.fixture
def driver(): return m

@pytest.mark.parametrize('fault', ['none', 'calendar', 'bootout', 'cas_unknown', 'bootstrap', 'preboot', 'drain_timeout', 'pid_alive', 'cas_drift'])
def test_full_apply_failure_boundaries(monkeypatch, tmp_path, fault):
    from contextlib import contextmanager, nullcontext
    import copy
    import plistlib
    from app.reference_trading import historical_refresh
    names = ('api', 'reference-worker')
    schedules = ('after-market',)
    bindings = {name: SimpleNamespace(label=name, enabled=True, generation=12) for name in (*names, *schedules)}
    old = SimpleNamespace(services=bindings)
    new = SimpleNamespace(services={name: SimpleNamespace(label=name, enabled=True, generation=13) for name in bindings})
    current = [old]
    calls, logs = [], []
    locks_held = [False]
    @contextmanager
    def lock_context(*_args, **_kwargs):
        locks_held[0] = True
        try:
            yield
        finally:
            locks_held[0] = False
    def lock_stack(stack, **_kwargs):
        stack.enter_context(lock_context())
        calls.append('locks')
        if fault == 'preboot':
            raise OSError()
    monkeypatch.setattr(m.h, 'CONTINUOUS', names)
    monkeypatch.setattr(m.h, 'SCHEDULED', schedules)
    monkeypatch.setattr(m.h, 'deployment_lock', nullcontext)
    monkeypatch.setattr(m, 'maintenance_lease', nullcontext)
    monkeypatch.setattr(m.h, 'maintenance_available', lambda: True)
    monkeypatch.setattr(m.h, 'acquire_owner_locks', lock_stack)
    monkeypatch.setattr(historical_refresh, 'RefreshStateStore', lambda _: SimpleNamespace(exclusive=lambda: nullcontext(True)))
    monkeypatch.setattr(m.u, 'history_bytes', lambda: b'preserved')
    monkeypatch.setattr(m.u.g, 'notification_lease', nullcontext)
    monkeypatch.setattr(m.u, 'START_ORDER', names)
    monkeypatch.setattr(m, 'poll_cycles', lambda *_: True)
    monkeypatch.setattr(m, 'heartbeat_gate', lambda *_: (True, {}))
    import app.runtime_deployment as dep
    monkeypatch.setattr(dep, 'owner_process_matches', lambda *_: True)
    monkeypatch.setattr(m.h, 'read_service_state', lambda _: {'phase':'parked','generation':12,'pid':123})
    monkeypatch.setattr(m, 'capture_failure_proof', lambda *_: {})
    monkeypatch.setattr(m.h, 'runtime_directory', lambda: tmp_path)
    monkeypatch.setattr(m, 'facts', lambda _: None)
    monkeypatch.setattr(m, 'archive_prior', lambda *_: None)
    monkeypatch.setattr(m.h, 'read_bindings', lambda: current[0])
    monkeypatch.setattr(m.h, 'bindings_sha256', lambda: 'registry')
    monkeypatch.setattr(m.h, 'loaded_identity', lambda *_args, **kwargs: None if kwargs.get('idle') else '123')
    def request_drain(name, **_):
        import json
        calls.append('drain:'+name)
        (tmp_path/f'{name}.handover.json').write_text(json.dumps({'schema_version': 1, 'service': name,
            'generation': 12, 'phase': 'drain', 'request_id': 'request'}))
        (tmp_path/f'{name}.handover.json').chmod(0o600)
        return 'request'
    monkeypatch.setattr(m.h, 'request_drain', request_drain)
    def cancel(name, **_):
        assert not locks_held[0]
        calls.append('cancel:'+name)
    monkeypatch.setattr(m.h, 'cancel_drain', cancel)
    monkeypatch.setattr(m, 'wait_parked', lambda *_, **_kwargs: fault != 'drain_timeout')
    monkeypatch.setattr(m.h, '_read', lambda path: {'service': path.name.split('.')[0], 'generation': 12, 'phase': 'drain', 'request_id': 'request'})
    monkeypatch.setattr(m, 'assert_reference_drained', lambda: calls.append('reference_closed'))
    monkeypatch.setattr(m.r, 'verify_schedule_state', lambda *_: calls.append('calendar_idle'))
    calendar_loaded = [True]
    monkeypatch.setattr(m.s, 'calendar_output', lambda binding: b'idle' if calendar_loaded[0] else None)
    monkeypatch.setattr(m.h, 'confirm_weekly_absence', lambda _: calls.append('calendar_absent'))
    def launch(action, *args):
        calls.append(action+':'+args[-1].split('/')[-1])
        if action == 'bootout' and args[-1].endswith('/after-market'):
            calendar_loaded[0] = False
        if fault == 'calendar' and action == 'disable':
            raise OSError()
        if fault == 'bootout' and action == 'bootout' and args[-1].endswith('/api'):
            raise OSError()
        if fault == 'bootstrap' and action == 'bootstrap':
            raise OSError()
    monkeypatch.setattr(m.h, 'launch', launch)
    def old_exited(_):
        calls.append('old_exited')
        if fault == 'pid_alive': raise m.h.ResumeBlocked('OLD_PID_ALIVE')
        for name in names:
            (tmp_path/f'{name}.owner.json').write_bytes(b'old_owner')
    monkeypatch.setattr(m.h, 'old_pids_exited', old_exited)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    root = tmp_path/'candidate'
    root.mkdir()
    launchers = tmp_path/'Library/LaunchAgents'
    launchers.mkdir(parents=True)
    plists = {}
    for name in bindings:
        path = launchers/f'{name}.plist'
        path.write_bytes(plistlib.dumps({'Label': name}))
        plists[name] = m.h.digest(path.read_bytes())
    (tmp_path/'run-local-service.sh').write_bytes(b'launcher')
    monkeypatch.setattr(m.h, 'immutable_assets', lambda _: {})
    monkeypatch.setattr(m.h, 'rebind_plist', lambda payload, binding: payload.update({'Generation': binding.generation}))
    def cas(_new, **_):
        calls.append('cas')
        if fault == 'cas_drift': raise m.h.ResumeBlocked('REGISTRY_DRIFT')
        current[0] = new
        if fault == 'cas_unknown':
            raise OSError()
    monkeypatch.setattr(m.h, 'write_bindings', cas)
    monkeypatch.setattr(m.h.BootstrapBackend, '_assert_recovery_calendar_safe', lambda *_: None)
    monkeypatch.setattr(m, 'await_cycles', lambda *_: calls.append('real_cycles'))
    monkeypatch.setattr(m, 'historical_protected', lambda _: None)
    monkeypatch.setattr(m, 'halt', lambda *_: calls.append('halt_new'))
    monkeypatch.setattr(m, 'log', lambda attempt, _: logs.append(copy.deepcopy(attempt)))
    monkeypatch.setattr(m, 'registry', lambda value: old if value == 'old' else new)
    plan = {'candidate': {'root': str(root), 'tag': 'v1.15.3', 'commit': 'commit'}, 'old': 'old', 'new': 'new',
        'owners': dict.fromkeys(names, '123'), 'plists': plists, 'registry_sha256': 'registry',
        'review_path':str(tmp_path/'review'), 'review_sha256':'review', 'drains': {**dict.fromkeys(bindings), 'reference-worker': m.h.digest(b'ref_old_control')}, 'assets': {}, 'launcher_sha256': m.h.digest(b'launcher')}
    ref_control = tmp_path/'reference-worker.handover.json'
    ref_control.write_bytes(b'ref_old_control')
    ref_control.chmod(0o600)
    monkeypatch.setattr(m.h, '_read', lambda path: {'service': path.name.split('.')[0], 'generation': 12, 'phase': 'drain',
        'request_id': 'request'})
    plan['plan_hash'] = m.h.plan_hash(plan)
    monkeypatch.setattr(m, 'freeze', lambda *_: plan)
    if fault == 'pid_alive':
        tick=[0.]
        monkeypatch.setattr(m,'monotonic',lambda:tick[0])
        monkeypatch.setattr(m,'sleep',lambda _:tick.__setitem__(0,tick[0]+11))
    import app.reference_trading.newow_scope_upgrade as scope
    monkeypatch.setattr(scope.NewowForwardScopeUpgrade,'apply',lambda *_a,**_k:pytest.fail('scope mutation forbidden'))
    result = m.apply(plan)
    if fault == 'none':
        assert result['phase'] == 'generation13_ready_calendars_idle', (result, calls, logs[-1].get('step'))
        assert calls.index('reference_closed') < calls.index('bootout:api') < calls.index('old_exited') < calls.index('cas') < calls.index('bootstrap:api.plist')
    else:
        assert result['phase'] == 'outcome_unknown'
        if fault in {'preboot', 'drain_timeout'}:
            assert calls[-2:] == ['cancel:api', 'cancel:reference-worker']
            assert not any(call.startswith('bootout:') for call in calls)
        else:
            assert not any(call.startswith('cancel:') for call in calls)
        if fault in {'cas_unknown', 'bootstrap'}:
            assert calls[-1] == 'halt_new'

    if fault in {'pid_alive', 'cas_drift'}:
        assert not any(call.startswith('bootstrap:') for call in calls)
    if fault == 'pid_alive':
        assert 'cas' not in calls
        assert result['failure_code'] == 'OLD_PID_EXIT_UNPROVEN'
    if fault == 'none':
        assert calls.index('disable:after-market') < calls.index('bootout:api')
        assert calls.index('cas') < calls.index('real_cycles') < calls.index('bootstrap:after-market.plist')

def test_false_live_keeps_typed_code_and_never_becomes_ready(driver,monkeypatch):
    monkeypatch.setattr(driver.h,'CONTINUOUS',('live',))
    state={'generation':13,'pid':42,'phase':'active','ready':False,'failure_code':None,
        'at':datetime.now(UTC).isoformat(),'proof':{'failure_code':'OBSERVATION_SUBSCRIPTION_MISSING'}}
    monkeypatch.setattr(driver.h,'read_service_state',lambda _:state)
    attempt={'owners':{'live':'42'},'started_at':datetime.now(UTC).isoformat()}
    with pytest.raises(driver.h.ResumeBlocked,match='LIVE_TYPED_POLL_FAILURE'):
        driver.poll_cycles(None,attempt,{})
    assert attempt['failure_typed_proof']['live']['typed_proof']['failure_code']=='OBSERVATION_SUBSCRIPTION_MISSING'
    assert attempt['failure_typed_proof']['live']['ready'] is False

def test_reference_false_thread_blocks_readiness(driver,monkeypatch):
    monkeypatch.setattr(driver.h,'CONTINUOUS',('reference-worker',))
    state={'generation':13,'pid':42,'phase':'active','ready':True,'failure_code':None,
        'at':datetime.now(UTC).isoformat(),'proof':{'reference_runtime':{'stage':'cycle','blocked_count':0,
            'blocked_counts':{},'historical_refresh_alive':False,'notifications_alive':True,
            'historical_refresh_error':None,'notifications_error':None}}}
    monkeypatch.setattr(driver.h,'read_service_state',lambda _:state)
    attempt={'owners':{'reference-worker':'42'},'started_at':datetime.now(UTC).isoformat()}
    assert driver.poll_cycles(None,attempt,{}) is False

def test_failure_proof_does_not_retain_error_messages(driver,monkeypatch):
    monkeypatch.setattr(driver.h,'CONTINUOUS',('live',))
    monkeypatch.setattr(driver.h,'read_service_state',lambda _:{'proof':{'failure_code':'sensitive url/message',
        'reference_runtime':{'historical_refresh_error':'sensitive detail'}}})
    value=driver.capture_failure_proof()
    assert value['live']['typed_proof']['failure_code']=='UNCLASSIFIED_FAILURE'
    assert value['live']['typed_proof']['reference_runtime']['historical_refresh_error']=='UNCLASSIFIED_FAILURE'
    assert 'sensitive' not in json.dumps(value)

@pytest.mark.parametrize('failed_heartbeat',(False,True))
@pytest.mark.parametrize('persist',(False,True))
def test_single_ready_snapshot_after_preflight_and_bad_heartbeat_still_blocks(driver,monkeypatch,failed_heartbeat,persist):
    import app.services.deployment_identity as identity
    import app.runtime_deployment as deployment
    clock=[0.0];calls=[]
    new=SimpleNamespace(services={n:SimpleNamespace(root='/new',commit='f'*40,service=n) for n in driver.h.CONTINUOUS})
    owners={n:'42' for n in driver.h.CONTINUOUS};attempt={'owners':owners}
    monkeypatch.setattr(driver,'monotonic',lambda:clock[0])
    monkeypatch.setattr(driver,'sleep',lambda _:clock.__setitem__(0,clock[0]+121))
    monkeypatch.setattr(driver,'facts',lambda _:pytest.fail('slow facts in short window'))
    def identity_health(**kw):
        clock[0]+=40 # Heavy preflight cannot age a success not sampled yet.
        return {'services':{('live_market' if n=='live' else 'reference_worker' if n=='reference-worker' else n):{'status':'matched'} for n in owners}}
    monkeypatch.setattr(identity,'deployment_identity_health',identity_health)
    monkeypatch.setattr(deployment,'owner_process_matches',lambda *a:True)
    monkeypatch.setattr(driver.h,'http_ready',lambda:True)
    monkeypatch.setattr(driver.h,'read_bindings',lambda:new)
    monkeypatch.setattr(driver.h,'read_service_state',lambda _: {})
    monkeypatch.setattr(driver.h,'loaded_identity',lambda _: '42')
    monkeypatch.setattr(driver,'heartbeat_gate',lambda _:(not failed_heartbeat,{'live':{'accepted':not failed_heartbeat}}))
    def write_log(attempt,step):
        assert persist, 'read-only sampling must never log the source attempt'
        calls.append(step)
    monkeypatch.setattr(driver,'log',write_log)
    def poll(*args):
        calls.append('poll')
        # The previous implementation's second instant poll would fail here.
        return calls.count('poll')==1
    monkeypatch.setattr(driver,'poll_cycles',poll)
    if failed_heartbeat:
        with pytest.raises(driver.h.ResumeBlocked,match='HEALTHY_CYCLE_TIMEOUT'):
            driver.await_cycles(new,{},attempt,{},.5,persist=persist)
    else:driver.await_cycles(new,{},attempt,{},.5,persist=persist)
    assert calls.count('poll')==1
    assert attempt['health_gate_evidence']['heartbeat'] is (not failed_heartbeat)
    assert attempt['health_gate_evidence']['owner_ready'] is True
    assert attempt['health_preflight']['identity_seconds']==40

@pytest.mark.parametrize('available',(True,False))
def test_heartbeat_exact_fields_and_failed_availability(driver,monkeypatch,available):
    import app.redis_connections as connections
    new=SimpleNamespace(services={n:SimpleNamespace(root='/new',commit='f'*40,tag='v1.15.3',generation=13) for n in ('live','market-feed')})
    raw=json.dumps({'generated_at':datetime.now(UTC).isoformat(),'available':available,'operational_count':60,
        'runtime_root':'/new','runtime_commit':'f'*40,'runtime_tag':'v1.15.3','runtime_generation':13})
    monkeypatch.setattr(connections,'get_redis_connection',lambda:SimpleNamespace(get=lambda _:raw,close=lambda:None))
    ok,proof=driver.heartbeat_gate(new)
    assert ok is available
    assert proof['live']['accepted'] is available
    assert proof['live']['runtime_generation']==13
    assert proof['live']['identity_matches']['runtime_root'] is True

def test_controller_proof_pins_dependencies_and_own_source():
    proof=m.controller_proof()
    assert proof[str(DRIVER.resolve())] == m.h.digest(DRIVER.read_bytes())
    assert proof[str(m.HELPER)] == m.HELPER_SHA


def test_exact_real_review_and_only_formula_fingerprint_change():
    path=DRIVER.with_name('reviewer-certified-changes.json')
    review=json.loads(path.read_bytes())
    changes,contracts,delta=m.validate_review(m.PROJECT/'.worktrees/release-v1.15.1',m.ROOT,review)
    assert set(delta)=={'formula'} and len(changes)==109


@pytest.mark.parametrize('key',('db','input','reference','launcher','live'))
def test_five_other_contracts_cannot_change(monkeypatch,key):
    old,root=Path('/old'),Path('/new')
    before=dict.fromkeys(('db','input','reference','launcher','live','formula'),'same')
    after={**before,'formula':'newformula',key:'wrong'}
    monkeypatch.setattr(m.h,'contract_fingerprints',lambda p:before if p==old else after)
    monkeypatch.setattr(m,'reviewed_changes',lambda *_:{'x':{'previous':'a','candidate':'b'}})
    with pytest.raises(m.h.ResumeBlocked,match='PROTECTED_CONTRACT_CHANGED'):m.validate_review(old,root,{})


def test_notification_threads_must_exit_before_old_stop(monkeypatch):
    monkeypatch.setattr(m.h,'read_service_state',lambda _:{'proof':{'reference_runtime':{
        'stage':'drained','notifications_alive':True,'historical_refresh_alive':False}}})
    with pytest.raises(m.h.ResumeBlocked,match='REFERENCE_CLOSE_UNPROVEN'):m.assert_reference_drained()


def test_invalid_plan_hash_never_acquires_lock(monkeypatch):
    monkeypatch.setattr(m.h,'deployment_lock',lambda:pytest.fail('mutation'))
    with pytest.raises(m.h.ResumeBlocked,match='PLAN_HASH_INVALID'):m.apply({'plan_hash':'bad'})


def test_active_old_drain_bounded_to_ten_seconds(monkeypatch):
    clock=[0.]
    monkeypatch.setattr(m,'monotonic',lambda:clock[0])
    monkeypatch.setattr(m,'sleep',lambda _:clock.__setitem__(0,clock[0]+1))
    monkeypatch.setattr(m.h,'CONTINUOUS',('live',))
    monkeypatch.setattr(m.h,'read_service_state',lambda _:{'phase':'active','generation':12,'pid':42})
    assert m.wait_parked({'owners':{'live':'42'}},12) is False
    assert clock[0]==10


def test_history_prestartup_protected_facts_and_afterstartup_archive(monkeypatch,tmp_path):
    raw=b'preserved-history';history=tmp_path/'archive';history.write_bytes(raw);history.chmod(0o600)
    plan={'scope':{'count':720},'historical_preimage':{'route_count':0}}
    monkeypatch.setattr(m.u,'scope_proof',lambda:{'count':720})
    monkeypatch.setattr(m,'history_preimage',lambda:{'route_count':0})
    monkeypatch.setattr(m.u,'history_bytes',lambda:raw)
    monkeypatch.setattr(m.h,'control_bytes',lambda _:None)
    m.historical_protected(plan)
    monkeypatch.setattr(m,'history_preimage',lambda:{'route_count':1})
    with pytest.raises(m.h.ResumeBlocked,match='HISTORY_PROTECTED_FACT_DRIFT'):m.historical_protected(plan)
    monkeypatch.setattr(m.h,'control_bytes',lambda _:json.dumps({'plan':plan,'started':['live'],
        'history_archive':str(history),'drained_history_sha256':m.h.digest(raw)}).encode())
    m.historical_protected(plan)


def test_readback_never_writes_journal(monkeypatch,tmp_path):
    plan={'new':'new','assets':{},'journals':{}}
    plan['plan_hash']=m.h.plan_hash(plan)
    attempt={'phase':'generation13_ready_calendars_idle','plan':plan}
    raw=json.dumps(attempt).encode();new=SimpleNamespace(services={})
    monkeypatch.setattr(m.u.g,'secure_bytes',lambda _:raw)
    monkeypatch.setattr(m,'registry',lambda _:new)
    monkeypatch.setattr(m.h,'read_bindings',lambda:new)
    monkeypatch.setattr(m,'facts',lambda _:None)
    monkeypatch.setattr(m,'log',lambda *_:pytest.fail('readback write forbidden'))
    def sample(*args,**kw):assert kw['persist'] is False
    monkeypatch.setattr(m,'await_cycles',sample)
    assert m.readback(plan)['phase']=='GENERATION13_INDEPENDENT_READBACK'


@pytest.mark.parametrize('fault',('none','notification_alive','unknown_owner','calendar_busy'))
def test_actual_halt_cooperative_and_calendar_locked(monkeypatch,tmp_path,fault):
    from contextlib import contextmanager
    import app.runtime_deployment as dep
    names=('live','reference-worker');schedules=('after-market',)
    monkeypatch.setattr(m.h,'BUSINESS',names)
    monkeypatch.setattr(m.h,'SCHEDULED',schedules)
    new=SimpleNamespace(services={n:SimpleNamespace(service=n,label=n,generation=13) for n in (*names,*schedules)})
    states={n:{'phase':'active','generation':13,'pid':42} for n in names}
    states['reference-worker']['proof']={'reference_runtime':{'stage':'drained',
        'notifications_alive':fault=='notification_alive','historical_refresh_alive':False}}
    if fault=='unknown_owner':states['live']['generation']=12
    owners=dict.fromkeys(names,'42');attempt={'owners':owners,'calendar_intents':['after-market']}
    controls={};calls=[];locked=[]
    monkeypatch.setattr(m.h,'read_bindings',lambda:new)
    monkeypatch.setattr(m.h,'read_service_state',states.get)
    monkeypatch.setattr(m.h,'loaded_identity',lambda binding,**kw:'42' if not kw.get('idle') else ('42' if fault=='calendar_busy' else None))
    monkeypatch.setattr(dep,'owner_process_matches',lambda *_:True)
    monkeypatch.setattr(m,'log',lambda *_:None)
    monkeypatch.setattr(m.h,'runtime_directory',lambda:tmp_path)
    monkeypatch.setattr(m.h,'_read',lambda path:controls.get(path.name.split('.')[0]))
    @contextmanager
    def held(services):
        locked.extend(services);calls.append(('lock',services))
        try:yield
        finally:
            for n in services:locked.remove(n)
    monkeypatch.setattr(m.h,'acquire_owner_locks',lambda stack,services:stack.enter_context(held(services)))
    def launch(command,*args):
        assert 'after-market' in locked, 'calendar mutation outside owner lock'
        calls.append((command,args[-1]))
    monkeypatch.setattr(m.h,'launch',launch)
    def calendar(binding):
        assert binding.service in locked
        return 'idle'
    monkeypatch.setattr(m.s,'calendar_output',calendar)
    monkeypatch.setattr(m.h,'confirm_weekly_absence',lambda _:calls.append(('calendar-absent',)))
    def drain(name,*,generation):
        calls.append(('drain',name,generation))
        assert generation==13
        states[name]['phase']='parked'
        controls[name]={'schema_version':1,'service':name,'generation':13,'phase':'drain','request_id':'r-'+name}
        return 'r-'+name
    monkeypatch.setattr(m.h,'request_drain',drain)
    m.halt(new,{},attempt)
    assert not any(c[0]=='bootout' and 'after-market' not in c[1] for c in calls)
    assert not any(c[0]=='drain' and c[1] in ('api','web') for c in calls)
    if fault=='none':
        assert attempt['parked_verified'] is True and attempt['halt_failed']==[]
        assert next(i for i,c in enumerate(calls) if c[0]=='drain') < next(i for i,c in enumerate(calls) if c==('lock',names))
    else:
        assert attempt['parked_verified'] is False and attempt['halt_proof']=='UNPROVEN'
        assert attempt['halt_failed']
    if fault=='unknown_owner':assert not any(c[:2]==('drain','live') for c in calls)
    if fault=='calendar_busy':assert not any(c[0]=='bootout' for c in calls)


def test_registry_read_failure_in_recovery_still_finalizes_unknown(monkeypatch,tmp_path):
    logs=[]
    plan={'candidate':{'root':str(tmp_path),'tag':'v1.15.3','commit':m.CANDIDATE_COMMIT},
        'review_path':str(tmp_path/'review'),'review_sha256':'review','old':'old','new':'new'}
    plan['plan_hash']=m.h.plan_hash(plan)
    monkeypatch.setattr(m.h,'deployment_lock',nullcontext)
    monkeypatch.setattr(m,'freeze',lambda *_:plan)
    monkeypatch.setattr(m.h,'maintenance_available',lambda:True)
    monkeypatch.setattr(m,'registry',lambda x:x)
    monkeypatch.setattr(m,'log',lambda attempt,step:logs.append((step,json.loads(json.dumps(attempt)))))
    monkeypatch.setattr(m,'capture_failure_proof',lambda:{})
    def fail_archive(*_):raise OSError('initial failure')
    monkeypatch.setattr(m,'archive_prior',fail_archive)
    def fail_registry():raise OSError('registry unavailable')
    monkeypatch.setattr(m.h,'read_bindings',fail_registry)
    monkeypatch.setattr(m.h,'request_drain',lambda *_a,**_k:pytest.fail('retry forbidden'))
    result=m.apply(plan)
    assert result['phase']=='outcome_unknown'
    assert logs[-1][0]=='final'
    assert logs[-1][1]['recovery_proof']=='UNPROVEN'
    assert any(step=='failure_readback_required' for step,_ in logs)


@pytest.mark.parametrize('fault',('none','never_same_round','typed_failure','blocked','pid_drift','identity_drift','stale'))
def test_old_gate_requires_single_actual_all_ready_round(monkeypatch,fault):
    import app.runtime_deployment as dep
    names=('live','reference-worker')
    monkeypatch.setattr(m.h,'CONTINUOUS',names)
    old=SimpleNamespace(services={name:SimpleNamespace(service=name) for name in names})
    owners=dict.fromkeys(names,'42');tick=[0.];rounds=[0]
    monkeypatch.setattr(m,'monotonic',lambda:tick[0])
    monkeypatch.setattr(m,'sleep',lambda _:tick.__setitem__(0,tick[0]+1))
    monkeypatch.setattr(m.h,'read_bindings',lambda:old)
    monkeypatch.setattr(m.h,'loaded_identity',lambda _: '42')
    monkeypatch.setattr(dep,'owner_process_matches',lambda *_:fault!='identity_drift')
    def state(name):
        if name=='live':rounds[0]+=1
        ready=rounds[0]>=2
        if fault=='never_same_round':ready=(rounds[0]%2==0)==(name=='live')
        result={'phase':'active','generation':12,'pid':42,'ready':ready,'at':datetime.now(UTC).isoformat(),'proof':{}}
        if fault=='typed_failure':result['proof']={'failure_code':'OBSERVATION_SUBSCRIPTION_MISSING'}
        if fault=='pid_drift':result['pid']=43
        if fault=='stale':result['at']=(datetime.now(UTC)-timedelta(seconds=31)).isoformat()
        if name=='reference-worker':result['proof']={'reference_runtime':{'stage':'cycle' if ready else 'scan',
            'blocked_count':1 if fault=='blocked' else 0,'blocked_counts':{'SOURCE_BUSY':1} if fault=='blocked' else {},
            'historical_refresh_alive':True,'notifications_alive':True,
            'historical_refresh_error':None,'notifications_error':None}}
        return result
    monkeypatch.setattr(m.h,'read_service_state',state)
    if fault=='none':
        m.wait_old_current_ready_all(old,owners)
        proof=m._OLD_HEALTH_EVIDENCE
        assert proof['same_round_all_ready'] is True
        assert all(row['ready'] is True for row in proof['owners'].values())
        assert tick[0]==1
    else:
        code={'never_same_round':'OLD_HEALTH_SNAPSHOT_TIMEOUT','typed_failure':'OLD_OWNER_FAILURE',
            'blocked':'OLD_REFERENCE_UNPROVEN','pid_drift':'OLD_OWNER_DRIFT','identity_drift':'OLD_OWNER_DRIFT',
            'stale':'OLD_HEALTH_SNAPSHOT_TIMEOUT'}[fault]
        with pytest.raises(m.h.ResumeBlocked,match=code):m.wait_old_current_ready_all(old,owners)


@pytest.mark.parametrize('fault',('none','cursor_namespace','nonempty_routes','version','inflight'))
def test_active_history_cursor_rotation_only_empty_authority_bound(monkeypatch,fault):
    ids={'id-'+str(i) for i in range(720)}
    mapping=[{'new':{'source':{'stream_id':key}}} for key in sorted(ids)]
    monkeypatch.setattr(m.u,'source_attempt',lambda:{'plan':{'scope':{'mapping':mapping}}})
    state={'version':'newow_historical_refresh_v1','routes':{},'cursor':'id-1'}
    monkeypatch.setattr(m.u,'history_bytes',lambda:json.dumps(state).encode())
    if fault=='cursor_namespace':state['cursor']='outside'
    if fault=='nonempty_routes':state['routes']={'id-1':{'status':'pending','plan':{}}}
    if fault=='inflight':state['routes']={'id-1':{'status':'inflight'}}
    if fault=='version':state['version']='wrong'
    if fault=='none':
        before=m.history_preimage();state['cursor']='id-2'
        assert m.history_preimage()==before
        assert before['require_empty_routes'] is True and before['route_count']==0
        assert state['cursor']=='id-2', 'controller must not reset actual scheduling cursor'
    else:
        with pytest.raises(m.h.ResumeBlocked):m.history_preimage()


def test_drained_history_exact_bytes_reject_any_later_cursor_change(monkeypatch,tmp_path):
    raw=b'full-real-drained-history';archive=tmp_path/'history';archive.write_bytes(raw);archive.chmod(0o600)
    plan={'scope':{'count':720},'historical_preimage':{'routes':'same'}}
    attempt={'plan':plan,'started':[],'history_archive':str(archive),'drained_history_sha256':m.h.digest(raw)}
    monkeypatch.setattr(m.u,'scope_proof',lambda:{'count':720})
    monkeypatch.setattr(m.h,'control_bytes',lambda _:json.dumps(attempt).encode())
    monkeypatch.setattr(m,'history_preimage',lambda:{'routes':'same'})
    monkeypatch.setattr(m.u,'history_bytes',lambda:raw)
    m.historical_protected(plan)
    monkeypatch.setattr(m.u,'history_bytes',lambda:b'cursor-change')
    with pytest.raises(m.h.ResumeBlocked,match='DRAINED_HISTORY_STATE_DRIFT'):m.historical_protected(plan)
