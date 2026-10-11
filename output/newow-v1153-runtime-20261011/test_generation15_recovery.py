"""Isolated gen12→13 controller safety; never invoke production adapters."""
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
DRIVER=Path(__file__).with_name('deploy_generation15_recovery.py')
spec=importlib.util.spec_from_file_location('gen13_isolated',DRIVER)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
@pytest.fixture
def driver(): return m

@pytest.mark.parametrize('fault', ['none', 'bootout', 'cas_unknown', 'bootstrap', 'preboot', 'drain_timeout', 'pid_alive', 'cas_drift'])
def test_full_apply_failure_boundaries(monkeypatch, tmp_path, fault):
    from contextlib import contextmanager, nullcontext
    import copy
    import plistlib
    from app.reference_trading import historical_refresh
    names = ('api', 'web', 'reference-worker')
    monkeypatch.setattr(m.h,'BUSINESS',('reference-worker',))
    schedules = ('after-market',)
    bindings = {name: SimpleNamespace(label=name, enabled=True, generation=14) for name in (*names, *schedules)}
    old = SimpleNamespace(services=bindings)
    new = SimpleNamespace(services={name: SimpleNamespace(label=name, enabled=True, generation=15) for name in bindings})
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
    monkeypatch.setattr(m.h, 'read_service_state', lambda _: {'phase':'parked','generation':14,'pid':123})
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
            'generation': 14, 'phase': 'drain', 'request_id': 'request'}))
        (tmp_path/f'{name}.handover.json').chmod(0o600)
        return 'request'
    monkeypatch.setattr(m.h, 'request_drain', request_drain)
    def cancel(name, **_):
        assert not locks_held[0]
        calls.append('cancel:'+name)
    monkeypatch.setattr(m.h, 'cancel_drain', cancel)
    monkeypatch.setattr(m, 'wait_parked', lambda *_, **_kwargs: fault != 'drain_timeout')
    monkeypatch.setattr(m.h, '_read', lambda path: {'service': path.name.split('.')[0], 'generation': 14, 'phase': 'drain', 'request_id': 'request'})
    monkeypatch.setattr(m, 'assert_reference_drained', lambda: calls.append('reference_closed'))
    monkeypatch.setattr(m.r, 'verify_schedule_state', lambda *_: calls.append('calendar_idle'))
    calendar_loaded = [False]
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
    monkeypatch.setattr(m, 'await_fresh_cycles', lambda *_: calls.append('final_fresh_cycles'))
    monkeypatch.setattr(m, 'historical_protected', lambda _: None)
    monkeypatch.setattr(m, 'halt', lambda *_: calls.append('halt_new'))
    monkeypatch.setattr(m, 'log', lambda attempt, _: logs.append(copy.deepcopy(attempt)))
    monkeypatch.setattr(m, 'registry', lambda value: old if value == 'old' else new)
    plan = {'candidate': {'root': str(root), 'tag': 'v1.15.3', 'commit': 'commit'}, 'old': 'old', 'new': 'new',
        'owners': dict.fromkeys(names, '123'), 'plists': plists, 'registry_sha256': 'registry', 'existing_park_requests':{'reference-worker':'request'},
        'review_path':str(tmp_path/'review'), 'review_sha256':'review', 'drains': {**dict.fromkeys(bindings), 'reference-worker': m.h.digest(b'ref_old_control')}, 'assets': {}, 'launcher_sha256': m.h.digest(b'launcher')}
    ref_control = tmp_path/'reference-worker.handover.json'
    ref_control.write_bytes(b'ref_old_control')
    ref_control.chmod(0o600)
    monkeypatch.setattr(m.h, '_read', lambda path: {'service': path.name.split('.')[0], 'generation': 14, 'phase': 'drain',
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
        assert result['phase'] == 'generation15_ready_calendars_idle', (result, calls, logs[-1].get('step'))
        assert calls.index('reference_closed') < calls.index('bootout:api') < calls.index('old_exited') < calls.index('cas') < calls.index('bootstrap:api.plist')
    else:
        assert result['phase'] == 'outcome_unknown'
        if fault in {'preboot', 'drain_timeout'}:
            assert calls[-2:] == ['cancel:api', 'cancel:web']
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
        assert not any(c.startswith('disable:after-market') for c in calls)
        assert calls.index('cas') < calls.index('real_cycles') < calls.index('bootstrap:after-market.plist')
        assert calls.index('bootstrap:after-market.plist') < calls.index('final_fresh_cycles')

def test_false_live_keeps_typed_code_and_never_becomes_ready(driver,monkeypatch):
    monkeypatch.setattr(driver.h,'CONTINUOUS',('live',))
    state={'generation':15,'pid':42,'phase':'active','ready':False,'failure_code':None,
        'at':datetime.now(UTC).isoformat(),'proof':{'failure_code':'OBSERVATION_SUBSCRIPTION_MISSING'}}
    monkeypatch.setattr(driver.h,'read_service_state',lambda _:state)
    attempt={'owners':{'live':'42'},'started_at':datetime.now(UTC).isoformat()}
    with pytest.raises(driver.h.ResumeBlocked,match='LIVE_TYPED_POLL_FAILURE'):
        driver.poll_cycles(None,attempt,{}, {'live':state})
    assert attempt['failure_typed_proof']['live']['typed_proof']['failure_code']=='OBSERVATION_SUBSCRIPTION_MISSING'
    assert attempt['failure_typed_proof']['live']['ready'] is False

def test_reference_false_thread_blocks_readiness(driver,monkeypatch):
    monkeypatch.setattr(driver.h,'CONTINUOUS',('reference-worker',))
    state={'generation':15,'pid':42,'phase':'active','ready':True,'failure_code':None,
        'at':datetime.now(UTC).isoformat(),'proof':{'reference_runtime':{'stage':'cycle','blocked_count':0,
            'blocked_counts':{},'historical_refresh_alive':False,'notifications_alive':True,
            'historical_refresh_error':None,'notifications_error':None}}}
    monkeypatch.setattr(driver.h,'read_service_state',lambda _:state)
    attempt={'owners':{'reference-worker':'42'},'started_at':datetime.now(UTC).isoformat()}
    assert driver.poll_cycles(None,attempt,{}, {'reference-worker':state}) is False

def test_failure_proof_does_not_retain_error_messages(driver,monkeypatch):
    monkeypatch.setattr(driver.h,'CONTINUOUS',('live',))
    monkeypatch.setattr(driver.h,'read_service_state',lambda _:{'proof':{'failure_code':'sensitive url/message',
        'reference_runtime':{'historical_refresh_error':'sensitive detail'}}})
    value=driver.capture_failure_proof()
    assert value['live']['typed_proof']['failure_code']=='UNCLASSIFIED_FAILURE'
    assert value['live']['typed_proof']['reference_runtime']['historical_refresh_error']=='UNCLASSIFIED_FAILURE'
    assert 'sensitive' not in json.dumps(value)

@pytest.mark.parametrize('available',(True,False))
def test_heartbeat_exact_fields_and_failed_availability(driver,monkeypatch,available):
    import app.redis_connections as connections
    new=SimpleNamespace(services={n:SimpleNamespace(root='/new',commit='f'*40,tag='v1.15.3',generation=15) for n in ('live','market-feed')})
    raw=json.dumps({'generated_at':datetime.now(UTC).isoformat(),'available':available,'operational_count':60,
        'runtime_root':'/new','runtime_commit':'f'*40,'runtime_tag':'v1.15.3','runtime_generation':15})
    monkeypatch.setattr(connections,'get_redis_connection',lambda:SimpleNamespace(get=lambda _:raw,close=lambda:None))
    ok,proof=driver.heartbeat_gate(new)
    assert ok is available
    assert proof['live']['accepted'] is available
    assert proof['live']['runtime_generation']==15
    assert proof['live']['identity_matches']['runtime_root'] is True

@pytest.mark.parametrize('fault',('none','notification_alive','unknown_owner','calendar_busy'))
def test_actual_halt_cooperative_and_calendar_locked(monkeypatch,tmp_path,fault):
    from contextlib import contextmanager
    import app.runtime_deployment as dep
    names=('live','reference-worker');schedules=('after-market',)
    monkeypatch.setattr(m.h,'BUSINESS',names)
    monkeypatch.setattr(m.h,'SCHEDULED',schedules)
    new=SimpleNamespace(services={n:SimpleNamespace(service=n,label=n,generation=15) for n in (*names,*schedules)})
    states={n:{'phase':'active','generation':15,'pid':42} for n in names}
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
        assert generation==15
        states[name]['phase']='parked'
        controls[name]={'schema_version':1,'service':name,'generation':15,'phase':'drain','request_id':'r-'+name}
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

def test_readback_never_writes_journal(monkeypatch,tmp_path):
    plan={'new':'new','assets':{},'journals':{}}
    plan['plan_hash']=m.h.plan_hash(plan)
    attempt={'phase':'generation15_ready_calendars_idle','plan':plan}
    raw=json.dumps(attempt).encode();new=SimpleNamespace(services={})
    monkeypatch.setattr(m.u.g,'secure_bytes',lambda _:raw)
    monkeypatch.setattr(m,'registry',lambda _:new)
    monkeypatch.setattr(m.h,'read_bindings',lambda:new)
    monkeypatch.setattr(m,'facts',lambda _:None)
    monkeypatch.setattr(m,'log',lambda *_:pytest.fail('readback write forbidden'))
    def sample(*args,**kw):assert kw['persist'] is False
    monkeypatch.setattr(m,'await_cycles',sample)
    assert m.readback(plan)['phase']=='GENERATION15_INDEPENDENT_READBACK'

def test_registry_read_failure_in_recovery_still_finalizes_unknown(monkeypatch,tmp_path):
    logs=[]
    plan={'candidate':{'root':str(tmp_path),'tag':'v1.15.3','commit':m.CANDIDATE_COMMIT},
        'review_path':str(tmp_path/'review'),'review_sha256':'review','old':'old','new':'new','existing_park_requests':{},'drains':dict.fromkeys(m.h.BUSINESS)}
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

def test_controller_exact_source_and_dependencies():
    proof=m.controller_proof()
    assert proof[str(DRIVER.resolve())]==m.h.digest(DRIVER.read_bytes())
    assert proof[str(m.HELPER)]==m.HELPER_SHA


@pytest.mark.parametrize('fault',('delayed_http','never_http','typed_failure','registry_drift','wrong_generation'))
def test_http_startup_waits_then_enforces_exact_identity(monkeypatch,fault):
    import app.runtime_deployment as dep
    names=('api','web','reference-worker')
    monkeypatch.setattr(m.h,'CONTINUOUS',names)
    new=SimpleNamespace(services={n:SimpleNamespace(service=n) for n in names})
    attempt={'owners':dict.fromkeys(names,'42')};clock=[0.];calls=[]
    monkeypatch.setattr(m,'monotonic',lambda:clock[0])
    monkeypatch.setattr(m,'sleep',lambda _:clock.__setitem__(0,clock[0]+1))
    monkeypatch.setattr(m.h,'read_bindings',lambda:None if fault=='registry_drift' else new)
    monkeypatch.setattr(m.h,'loaded_identity',lambda _: '42')
    monkeypatch.setattr(dep,'owner_process_matches',lambda *_:True)
    monkeypatch.setattr(m,'exact_retired_observation',lambda *_:False)
    def state(name):
        return {'generation':14 if fault=='wrong_generation' else 15,'pid':42,'phase':'active',
            'ready':True,'proof':{'failure_code':'OBSERVATION_SUBSCRIPTION_MISSING'} if fault=='typed_failure' else {}}
    monkeypatch.setattr(m.h,'read_service_state',state)
    monkeypatch.setattr(m,'read_owner_snapshot',lambda name:(state(name),'current'))
    def http():
        calls.append('http');return fault!='never_http' and len(calls)>=3
    monkeypatch.setattr(m.h,'http_ready',http)
    monkeypatch.setattr(m,'log',lambda *_:None)
    if fault=='delayed_http':
        m.wait_http_startup(new,attempt,seconds=5)
        assert attempt['http_startup']['polls']==3 and clock[0]==2
    else:
        code={'never_http':'HTTP_STARTUP_TIMEOUT','typed_failure':'STARTUP_OWNER_FAILURE',
            'registry_drift':'REGISTRY_DRIFT','wrong_generation':'OWNER_IDENTITY_DRIFT'}[fault]
        with pytest.raises(m.h.ResumeBlocked,match=code):m.wait_http_startup(new,attempt,seconds=5)


def test_http_ready_alone_does_not_satisfy_business_gate(monkeypatch):
    import app.services.deployment_identity as identity
    import app.runtime_deployment as dep
    names=('api','web','reference-worker')
    monkeypatch.setattr(m.h,'CONTINUOUS',names)
    new=SimpleNamespace(services={n:SimpleNamespace(service=n,root='/candidate',commit='f'*40) for n in names})
    attempt={'owners':dict.fromkeys(names,'42')};clock=[0.];events=[]
    monkeypatch.setattr(m,'monotonic',lambda:clock[0])
    monkeypatch.setattr(m,'sleep',lambda _:clock.__setitem__(0,clock[0]+31))
    monkeypatch.setattr(m,'wait_http_startup',lambda *_a,**_k:events.append('startup'))
    def identity_health(**_):
        events.append('identity');return {'services':{'api':{'status':'matched'},'web':{'status':'matched'},'reference_worker':{'status':'matched'}}}
    monkeypatch.setattr(identity,'deployment_identity_health',identity_health)
    monkeypatch.setattr(dep,'owner_process_matches',lambda *_:True)
    monkeypatch.setattr(m.h,'loaded_identity',lambda _: '42')
    monkeypatch.setattr(m.h,'read_service_state',lambda _: {})
    monkeypatch.setattr(m.h,'read_bindings',lambda:new)
    monkeypatch.setattr(m,'heartbeat_gate',lambda _:(True,{}))
    monkeypatch.setattr(m,'capture_failure_proof',lambda *_:{})
    monkeypatch.setattr(m,'observe_owners',lambda *_:({},{}))
    monkeypatch.setattr(m,'poll_cycles',lambda *_:False)
    monkeypatch.setattr(m,'log',lambda *_:None)
    with pytest.raises(m.h.ResumeBlocked,match='HEALTHY_CYCLE_TIMEOUT'):
        m.await_cycles(new,{},attempt,{},0)
    assert events==['startup','identity']


def test_unknown_source_receipt_requires_exact_hash(monkeypatch):
    monkeypatch.setattr(m.u.g,'secure_bytes',lambda _:b'{}')
    with pytest.raises(m.h.ResumeBlocked,match='GENERATION14_UNKNOWN_JOURNAL_DRIFT'):m.source_attempt()


@pytest.mark.parametrize('eventually_ready',(False,True))
def test_final_fresh_gate_waits_for_real_current_ready_not_old_evidence(monkeypatch,eventually_ready):
    clock=[0.];polls=[]
    new=SimpleNamespace(services={});attempt={'owners':{}}
    monkeypatch.setattr(m.h,'CONTINUOUS',())
    monkeypatch.setattr(m,'monotonic',lambda:clock[0])
    monkeypatch.setattr(m,'sleep',lambda _:clock.__setitem__(0,clock[0]+1))
    monkeypatch.setattr(m.h,'read_bindings',lambda:new)
    monkeypatch.setattr(m,'heartbeat_gate',lambda _:(True,{}))
    monkeypatch.setattr(m,'capture_failure_proof',lambda *_:{})
    monkeypatch.setattr(m,'log',lambda *_:None)
    monkeypatch.setattr(m,'facts',lambda _:pytest.fail('no heavyweight facts after final fresh sample'))
    def poll(*_):
        polls.append(clock[0]);return eventually_ready and len(polls)>=3
    monkeypatch.setattr(m,'observe_owners',lambda *_:({},{}))
    monkeypatch.setattr(m,'poll_cycles',poll)
    if eventually_ready:
        m.await_fresh_cycles(new,{},attempt,{'old':'success'},5)
        assert polls==[0,1,2]
        assert attempt['health_gate_evidence']['owner_ready'] is True
    else:
        with pytest.raises(m.h.ResumeBlocked,match='HEALTHY_CYCLE_TIMEOUT'):
            m.await_fresh_cycles(new,{},attempt,{'old':'success'},5)
        assert len(polls)==5


@pytest.mark.parametrize('result_kind',('absent','loaded','unexpected_rc113'))
def test_real_strict_calendar_absence_parser_never_uses_loaded_identity(monkeypatch,result_kind):
    import os
    import app.market_data.captured_recovery_runtime as reader
    binding=SimpleNamespace(label='com.guiyi.quant-after-market',root='/candidate')
    absence=f'Could not find service "{binding.label}" in domain for user gui: {os.getuid()}'
    response=SimpleNamespace(returncode=113 if result_kind!='loaded' else 0,
        stdout='' if result_kind!='loaded' else 'loaded definition',
        stderr=absence if result_kind=='absent' else 'unexpected error')
    monkeypatch.setattr(reader,'_read_command',lambda *_a,**_k:'valid gui domain')
    monkeypatch.setattr(reader,'_command_result',lambda *_a,**_k:response)
    monkeypatch.setattr(m.h,'loaded_identity',lambda *_a,**_k:pytest.fail('absent has no loaded identity'))
    if result_kind=='absent':m.require_calendar_absent(binding)
    else:
        with pytest.raises(Exception):m.require_calendar_absent(binding)


def owner_wire(*,generation,pid,ready=True):
    return {'schema_version':1,'service':'live','generation':generation,'pid':pid,
        'phase':'active' if generation==15 else 'parked','ready':ready,
        'at':datetime.now(UTC).isoformat(),'proof':{}}


def test_atomic_owner_inode_survives_real_replace_and_classifies_exact_transition(monkeypatch,tmp_path):
    import os
    import app.runtime_deployment as dep
    p=tmp_path/'live.owner.json'
    old=owner_wire(generation=14,pid=1,ready=False);newstate=owner_wire(generation=15,pid=2)
    oldraw=json.dumps(old).encode();newraw=json.dumps(newstate).encode()
    p.write_bytes(oldraw);p.chmod(0o600)
    monkeypatch.setattr(m.h,'runtime_directory',lambda:tmp_path)
    real_read=os.read;replaced=[False]
    def read_replace(fd,size):
        if not replaced[0]:
            replacement=tmp_path/'replacement';replacement.write_bytes(newraw);replacement.chmod(0o600)
            os.replace(replacement,p);replaced[0]=True
        return real_read(fd,size)
    monkeypatch.setattr(m.os,'read',read_replace)
    observed,digest=m.read_owner_snapshot('live')
    assert observed==old and digest==m.h.digest(oldraw)
    assert p.read_bytes()==newraw
    new=SimpleNamespace(services={'live':SimpleNamespace(service='live')})
    attempt={'owners':{'live':'2'},'plan':{'owners':{'live':'1'},'old':{'services':{'live':{'generation':14}}}},
        'previous_owner_sha256':{'live':m.h.digest(oldraw)}}
    monkeypatch.setattr(m.h,'read_bindings',lambda:new)
    monkeypatch.setattr(m.h,'loaded_identity',lambda _: '2')
    monkeypatch.setattr(m.h,'old_pids_exited',lambda _:None)
    monkeypatch.setattr(dep,'owner_process_matches',lambda state,_:state['pid']==2)
    assert m.classify_owner_observation('live',observed,digest,new,attempt)=='EXACT_RETIRED'
    current,currenthash=m.read_owner_snapshot('live')
    assert m.classify_owner_observation('live',current,currenthash,new,attempt)=='CURRENT'


@pytest.mark.parametrize('fault',('wrong_pid','wrong_gen','unknown_old_hash','current_failure','old_still_alive','registry_drift'))
def test_unknown_owner_observation_never_becomes_retryable_transition(monkeypatch,fault):
    import app.runtime_deployment as dep
    new=SimpleNamespace(services={'live':SimpleNamespace(service='live')})
    attempt={'owners':{'live':'2'},'plan':{'owners':{'live':'1'},'old':{'services':{'live':{'generation':14}}}},
        'previous_owner_sha256':{'live':'old-exact'}}
    state=owner_wire(generation=15,pid=2);digest='new'
    if fault=='wrong_pid':state['pid']=3
    if fault=='wrong_gen':state['generation']=16
    if fault in ('unknown_old_hash','old_still_alive'):state=owner_wire(generation=14,pid=1,ready=False);digest='old-exact'
    if fault=='unknown_old_hash':digest='unknown'
    if fault=='current_failure':state['proof']['failure_code']='OBSERVATION_SUBSCRIPTION_MISSING'
    monkeypatch.setattr(m.h,'read_bindings',lambda:None if fault=='registry_drift' else new)
    monkeypatch.setattr(m.h,'loaded_identity',lambda _: '2')
    monkeypatch.setattr(dep,'owner_process_matches',lambda *_:True)
    def old_exited(_):
        if fault=='old_still_alive':raise m.h.ResumeBlocked('OLD_PID_ALIVE')
    monkeypatch.setattr(m.h,'old_pids_exited',old_exited)
    with pytest.raises(m.h.ResumeBlocked):m.classify_owner_observation('live',state,digest,new,attempt)


def test_real_inplace_owner_content_change_is_rejected(monkeypatch,tmp_path):
    import os
    p=tmp_path/'live.owner.json';raw=json.dumps(owner_wire(generation=15,pid=2)).encode()
    p.write_bytes(raw);p.chmod(0o600)
    monkeypatch.setattr(m.h,'runtime_directory',lambda:tmp_path)
    real_read=os.read
    def read_inplace(fd,size):
        with p.open('ab') as output:output.write(b' ')
        return real_read(fd,size)
    monkeypatch.setattr(m.os,'read',read_inplace)
    with pytest.raises(m.h.ResumeBlocked,match='OWNER_SNAPSHOT_CONTENT_DRIFT'):m.read_owner_snapshot('live')
