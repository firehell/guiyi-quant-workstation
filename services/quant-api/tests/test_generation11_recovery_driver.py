"""One-use forward deployment recovery, with no production side effects."""
from contextlib import nullcontext
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import plistlib
from types import SimpleNamespace
import pytest

DRIVER=Path('/Volumes/扩展盘/guiyi-quant-workstation/output/newow-v1151-recovery-20261011/deploy_generation11_recovery.py')

@pytest.fixture
def driver():
    spec=importlib.util.spec_from_file_location('gen11_test_driver',DRIVER)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


def test_controller_source_proof_real_bytes(driver):
    proof=driver.controller_proof()
    assert proof[str(DRIVER)]==driver.h.digest(DRIVER.read_bytes())
    assert proof[str(driver.G8_SOURCE)]==driver.G8_SOURCE_SHA


def test_launcher_and_reference_changes_need_exact_review(driver,monkeypatch):
    old,new=Path('old'),Path('new')
    before={k:'unchanged' for k in ('db','live','input','formula','reference','launcher')}
    after={**before,'reference':'reference-patch','launcher':'typed-diagnostic'}
    changes={'services/quant-api/app/runtime_entry.py':{'previous':'oldblob','candidate':'newblob'}}
    monkeypatch.setattr(driver.h,'contract_fingerprints',lambda p:before if p==old else after)
    monkeypatch.setattr(driver.g,'reviewed_changes',lambda *a:changes)
    differences={k:{'old':before[k],'new':after[k]} for k in ('reference','launcher')}
    review={'status':'REVIEW_COMPLETE','old_commit':driver.G8_COMMIT,'candidate_commit':'f'*40,
        'changes':changes,'contract_changes':differences,'scope_identity_preserved':True,
        'history_state_codec_preserved':True,'notification_policy_preserved':True,'live_readiness_not_relaxed':True}
    assert driver.validate_review(old,new,'f'*40,review)[2]==differences
    review['contract_changes']={}
    with pytest.raises(driver.h.ResumeBlocked,match='EXACT_PATCH_REVIEW_UNPROVEN'):
        driver.validate_review(old,new,'f'*40,review)


def test_false_live_keeps_typed_code_and_never_becomes_ready(driver,monkeypatch):
    monkeypatch.setattr(driver.h,'CONTINUOUS',('live',))
    state={'generation':11,'pid':42,'phase':'active','ready':False,'failure_code':None,
        'at':datetime.now(UTC).isoformat(),'proof':{'failure_code':'OBSERVATION_SUBSCRIPTION_MISSING'}}
    monkeypatch.setattr(driver.h,'read_service_state',lambda _:state)
    attempt={'owners':{'live':'42'},'started_at':datetime.now(UTC).isoformat()}
    with pytest.raises(driver.h.ResumeBlocked,match='LIVE_TYPED_POLL_FAILURE'):
        driver.poll_cycles(None,attempt,{})
    assert attempt['failure_typed_proof']['live']['typed_proof']['failure_code']=='OBSERVATION_SUBSCRIPTION_MISSING'
    assert attempt['failure_typed_proof']['live']['ready'] is False


def test_reference_false_thread_blocks_readiness(driver,monkeypatch):
    monkeypatch.setattr(driver.h,'CONTINUOUS',('reference-worker',))
    state={'generation':11,'pid':42,'phase':'active','ready':True,'failure_code':None,
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


def orchestrate(driver,monkeypatch,tmp_path,*,fail_live,fail_journal=False):
    h,g=driver.h,driver.g
    names=(*h.CONTINUOUS,*h.SCHEDULED)
    old_root=tmp_path/'old';old_root.mkdir()
    new_root=tmp_path/'new';new_root.mkdir()
    contracts={key:'a'*64 for key in ('db','live','input','formula','reference','launcher')}
    old=h.BindingRegistry(1,{name:h.ServiceBinding(service=name,root=str(old_root),tag='v1.15.0',commit=driver.G8_COMMIT,
        generation=10,enabled=True,contracts=contracts,launchd_label=None) for name in names})
    new=h.BindingRegistry(1,{name:h.ServiceBinding(service=name,root=str(new_root),tag='v1.15.1',commit='f'*40,
        generation=11,enabled=True,contracts=contracts,launchd_label=None) for name in names})
    registry=[old];calls=[];calendar=set()
    pids={name:str(i+100) for i,name in enumerate(h.CONTINUOUS)}
    requests={name:'existing-'+name for name in h.BUSINESS}
    controls={name:{'schema_version':1,'service':name,'generation':10,'phase':'drain','request_id':request}
        for name,request in requests.items()}
    states={name:{'pid':int(pids[name]),'generation':10,'phase':'active' if name in ('api','web') else 'parked',
        'ready':name in ('api','web'),'proof':{}} for name in h.CONTINUOUS}
    states['reference-worker']['proof']={'reference_runtime':{'stage':'drained','historical_refresh_alive':False,
        'notifications_alive':False}}
    plan={'candidate':{'root':str(new_root),'tag':'v1.15.1','commit':'f'*40},'old':h.asdict(old),'new':h.asdict(new),
        'registry_sha256':'registry-before','owners':pids,'plists':{},'controls':{name:None for name in names},
        'existing_park_requests':requests,'review_path':str(tmp_path/'review.json'),'review_sha256':'review','assets':{}}
    plan['plan_hash']=h.plan_hash(plan)
    monkeypatch.setattr(driver,'freeze',lambda *a:plan)
    monkeypatch.setattr(driver,'facts',lambda *a:None)
    def write_log(attempt,step):
        calls.append(('log',step))
        if fail_journal and step=='failure_typed_proof_frozen':raise OSError('fixture')
    monkeypatch.setattr(driver,'log',write_log)
    monkeypatch.setattr(driver,'archive_originals',lambda *a:calls.append(('archive',)))
    monkeypatch.setattr(driver,'install_plists_assets',lambda *a:calls.append(('install',)))
    monkeypatch.setattr(h,'deployment_lock',lambda:nullcontext())
    monkeypatch.setattr(h,'acquire_owner_locks',lambda *a,**kw:calls.append(('locks',kw.get('services','all-ten'))))
    monkeypatch.setattr(g,'notification_lease',lambda:nullcontext())
    monkeypatch.setattr(g,'maintenance_lease',lambda:nullcontext())
    import app.reference_trading.historical_refresh as history
    monkeypatch.setattr(history.RefreshStateStore,'exclusive',lambda _:nullcontext(True))
    monkeypatch.setattr(h,'read_bindings',lambda:registry[0])
    monkeypatch.setattr(h,'bindings_sha256',lambda:'registry-before')
    monkeypatch.setattr(h,'write_bindings',lambda value,**kw:registry.__setitem__(0,value))
    monkeypatch.setattr(h,'read_service_state',lambda name:states[name])
    monkeypatch.setattr(h,'loaded_identity',lambda binding,**kw:str(states[binding.service]['pid']) if binding.service in states else None)
    monkeypatch.setattr(h,'_read',lambda path:controls.get(path.name.removesuffix('.handover.json')))
    monkeypatch.setattr(g,'control_sha',lambda name:None)
    monkeypatch.setattr(g,'secure_bytes',lambda path,**kw:plistlib.dumps({}) if path.suffix=='.plist' else b'owner')
    monkeypatch.setattr(h,'old_pids_exited',lambda *a:calls.append(('old-pids-exited',)))
    monkeypatch.setattr(h,'runtime_directory',lambda:tmp_path)
    monkeypatch.setattr(driver.s,'calendar_output',lambda binding:'loaded' if binding.service in calendar else None)
    monkeypatch.setattr(h,'parse_disabled_states',lambda _: {old.services[n].label:True for n in h.SCHEDULED})
    monkeypatch.setattr(h,'BootstrapBackend',lambda:SimpleNamespace(_assert_recovery_calendar_safe=lambda _:None))
    monkeypatch.setattr(driver.r,'verify_schedule_state',lambda new,name:calls.append(('calendar-idle-proof',name)))
    import app.runtime_deployment as deployment
    monkeypatch.setattr(deployment,'owner_process_matches',lambda *a:True)
    def request(name,*,generation):
        calls.append(('drain',name,generation))
        rid='new-'+name
        controls[name]={'schema_version':1,'service':name,'generation':generation,'phase':'drain','request_id':rid}
        states[name]['phase']='parked'
        return rid
    monkeypatch.setattr(h,'request_drain',request)
    def launch(command,*args):
        calls.append(('launch',command,*args))
        if command=='bootstrap':
            name=next(n for n in names if old.services[n].label in args[-1])
            if name in h.SCHEDULED:calendar.add(name)
            else:
                states[name]={'pid':int(pids[name])+1000,'generation':11,'phase':'active','ready':True,
                    'at':datetime.now(UTC).isoformat(),'proof':{}}
        return SimpleNamespace(stdout='')
    monkeypatch.setattr(h,'launch',launch)
    def cycles(new,plan,attempt,evidence,deadline):
        calls.append(('healthy-cycles',))
        if fail_live:
            states['live']['ready']=False
            states['live']['proof']={'failure_code':'OBSERVATION_SUBSCRIPTION_MISSING'}
            attempt['failure_typed_proof']=driver.capture_failure_proof()
            raise h.ResumeBlocked('LIVE_TYPED_POLL_FAILURE')
    monkeypatch.setattr(driver,'await_cycles',cycles)
    monkeypatch.setattr(driver,'halt',lambda *a:calls.append(('halt-business',)))
    import app.reference_trading.newow_scope_upgrade as scope
    monkeypatch.setattr(scope.NewowForwardScopeUpgrade,'apply',lambda *a,**kw:pytest.fail('scope migration forbidden'))
    result=driver.apply(plan)
    return result,calls,calendar


def test_recovery_feed_first_no_second_migration_and_calendars_only_after_health(driver,monkeypatch,tmp_path):
    result,calls,calendar=orchestrate(driver,monkeypatch,tmp_path,fail_live=False)
    assert result['phase']=='generation11_ready_calendars_idle'
    assert [c[1] for c in calls if c[0]=='drain']==['api','web']
    starts=[c[-1] for c in calls if c[:2]==('launch','bootstrap')]
    assert 'market-feed' in starts[0]
    assert len(calendar)==4
    health=next(i for i,c in enumerate(calls) if c[0]=='healthy-cycles')
    calendar_enable=next(i for i,c in enumerate(calls) if c[:2]==('launch','enable') and 'after-market' in c[-1])
    assert health<calendar_enable
    assert not any(c[:2]==('launch','kickstart') for c in calls)


def test_live_failure_preserves_typed_proof_parks_and_does_not_enable_calendars(driver,monkeypatch,tmp_path):
    result,calls,calendar=orchestrate(driver,monkeypatch,tmp_path,fail_live=True)
    assert result['phase']=='outcome_unknown'
    assert result['failure_code']=='LIVE_TYPED_POLL_FAILURE'
    assert result['typed_proof']['live']['typed_proof']['failure_code']=='OBSERVATION_SUBSCRIPTION_MISSING'
    assert calendar==set()
    assert ('halt-business',) in calls
    assert len([c for c in calls if c[0]=='drain'])==2


def test_api_web_preflight_does_not_require_parked_business_heartbeat(driver,monkeypatch):
    import app.services.deployment_identity as identity
    import app.runtime_deployment as deployment
    bindings={n:SimpleNamespace(root='/candidate',commit='f'*40,generation=10,service=n) for n in ('api','web')}
    registry=SimpleNamespace(services=bindings)
    monkeypatch.setattr(identity,'deployment_identity_health',lambda **kw:{'services':{n:{'status':'matched'} for n in bindings}})
    monkeypatch.setattr(deployment,'owner_process_matches',lambda *a:True)
    monkeypatch.setattr(driver.h,'read_service_state',lambda n:{'pid':42,'generation':10,'phase':'active','ready':True,'at':datetime.now(UTC).isoformat()})
    monkeypatch.setattr(driver.h,'loaded_identity',lambda _: '42')
    monkeypatch.setattr(driver.h,'http_ready',lambda:True)
    monkeypatch.setattr(driver.b,'heartbeats_ready',lambda _:pytest.fail('parked business heartbeat must not gate API/Web preflight'))
    assert driver.api_web_ready(registry)


def test_failure_proof_journal_error_still_parks_business(driver,monkeypatch,tmp_path):
    result,calls,calendar=orchestrate(driver,monkeypatch,tmp_path,fail_live=True,fail_journal=True)
    assert result['phase']=='outcome_unknown'
    assert result['typed_proof']['live']['typed_proof']['failure_code']=='OBSERVATION_SUBSCRIPTION_MISSING'
    assert ('halt-business',) in calls
    assert not calendar


def test_short_health_window_never_calls_slow_full_scope_facts(driver,monkeypatch):
    import app.services.deployment_identity as identity
    import app.runtime_deployment as deployment
    new=SimpleNamespace(services={n:SimpleNamespace(root='/new',commit='f'*40,service=n) for n in driver.h.CONTINUOUS})
    owners={n:'42' for n in driver.h.CONTINUOUS}
    calls=[]
    monkeypatch.setattr(driver,'facts',lambda _:pytest.fail('fullfacts must be outside short health sampling'))
    monkeypatch.setattr(driver,'poll_cycles',lambda *a:calls.append('poll') or True)
    monkeypatch.setattr(driver.h,'read_bindings',lambda:new)
    monkeypatch.setattr(driver.h,'read_service_state',lambda _: {})
    monkeypatch.setattr(driver.h,'loaded_identity',lambda _: '42')
    monkeypatch.setattr(deployment,'owner_process_matches',lambda *a:True)
    monkeypatch.setattr(identity,'deployment_identity_health',lambda **kw:{'services':{('live_market' if n=='live' else 'reference_worker' if n=='reference-worker' else n):{'status':'matched'} for n in owners}})
    monkeypatch.setattr(driver.h,'http_ready',lambda:True)
    monkeypatch.setattr(driver.b,'heartbeats_ready',lambda _:True)
    driver.await_cycles(new,{}, {'owners':owners},{},driver.monotonic()+1)
    assert calls==['poll','poll']
