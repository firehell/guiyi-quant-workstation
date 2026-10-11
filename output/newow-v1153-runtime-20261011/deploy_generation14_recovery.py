"""Single-use exact gen13 parked partial state -> v1.15.3/gen14 recovery.

Preserve gen13 outcome_unknown bytes. No retry, Scope migration, data/history
reset, notification-policy change, release-source patch or new audience.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import argparse
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import stat
from time import monotonic, sleep

PROJECT = Path('/Volumes/扩展盘/guiyi-quant-workstation')
ROOT = PROJECT / '.worktrees/release-v1.15.3'
CANDIDATE_COMMIT = 'c28438d3d7ad6d6c66272027996f4a25e2facdfe'
HELPER = PROJECT / 'output/newow-v1153-runtime-20261011/deploy_generation13.py'
HELPER_SHA = '8c7e40e0e1655ba0bd52c9ca8c48368bdbc678d99b0b6dde6c94b12e76cc4089'
UNKNOWN_SHA = '97735faf858f628845959eda0755bb379074ca1fc2fc097645486da9cb58b872'
def source_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_nlink != 1 or before.st_mode & 0o022 or before.st_size > 1_048_576
                or path.parent != path.parent.resolve(strict=True)):
            raise RuntimeError('SOURCE_FILE_INVALID')
        raw = os.read(fd, before.st_size + 1)
        def identity(item):
            return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns
        if len(raw) != before.st_size or identity(before) != identity(os.fstat(fd)):
            raise RuntimeError('SOURCE_FILE_DRIFT')
        if identity(before) != identity(os.stat(path,follow_symlinks=False)):
            raise RuntimeError('SOURCE_FILE_DRIFT')
        return raw
    finally:
        os.close(fd)

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv(Path.home() / 'Library/Application Support/GuiyiQuant/project.env', override=True)
    os.environ.setdefault('REDIS_PASSWORD', os.environ.get('POSTGRES_PASSWORD', ''))
    if os.environ.get('REDIS_URL', '') in ('', 'redis://127.0.0.1:6379/0'):
        os.environ['REDIS_URL'] = 'redis://:' + os.environ['REDIS_PASSWORD'] + '@127.0.0.1:6379/0'
    os.environ['GUIYI_PROJECT_ROOT'] = str(ROOT)
    os.environ['GUIYI_OBSERVATION_STREAM_ENABLED'] = '1'
    os.environ['GUIYI_RUNTIME_HANDOVER_ENABLED'] = '1'
if sha256(source_bytes(HELPER)).hexdigest() != HELPER_SHA:
    raise RuntimeError('GENERATION13_HELPER_DRIFT')
spec = importlib.util.spec_from_file_location('gen14_frozen_readonly_helpers', HELPER)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
h, s, b, r, u = g.h, g.s, g.b, g.r, g.u
_OLD_HEALTH_EVIDENCE = None


def attempt_path():
    return h.runtime_directory() / 'reference-continuity-generation14-recovery.json'


def source_attempt():
    raw = u.g.secure_bytes(g.attempt_path())
    h.require(h.digest(raw) == UNKNOWN_SHA, 'GENERATION13_UNKNOWN_JOURNAL_DRIFT')
    value = json.loads(raw)
    h.require(value.get('phase') == 'outcome_unknown' and value.get('failure_code') == 'HTTP_HEALTH_UNPROVEN'
        and value.get('parked_verified') is True and value.get('halt_failed') == []
        and set(value.get('stopped', [])) == set(value.get('started', [])) == set(h.CONTINUOUS)
        and value.get('calendar_intents') == [] and value.get('scheduled_loaded') == [],
        'GENERATION13_PARTIAL_BOUNDARY_INVALID')
    h.require(value['plan'].get('plan_hash') == h.plan_hash(value['plan']), 'GENERATION13_PLAN_HASH_INVALID')
    return value


def controller_proof():
    h.require(h.digest(source_bytes(HELPER)) == HELPER_SHA, 'GENERATION13_HELPER_DRIFT')
    proof = g.controller_proof()
    proof[str(Path(__file__).resolve())] = h.digest(source_bytes(Path(__file__).resolve()))
    return proof


def historical_protected(plan):
    h.require(u.scope_proof() == plan['scope'], 'COMMITTED_SCOPE_DRIFT')
    h.require(g.history_preimage() == plan['historical_preimage'], 'HISTORY_PROTECTED_FACT_DRIFT')
    attempt_raw = h.control_bytes(attempt_path())
    attempt = json.loads(attempt_raw) if attempt_raw else {}
    if attempt.get('history_archive'):
        h.require(attempt.get('plan') == plan and h.digest(u.g.secure_bytes(Path(attempt['history_archive'])))
            == attempt['drained_history_sha256'], 'HISTORY_ARCHIVE_DRIFT')
    if not attempt.get('started'):
        expected = attempt.get('drained_history_sha256', plan['history_sha256'])
        h.require(h.digest(u.history_bytes()) == expected, 'DRAINED_HISTORY_STATE_DRIFT')


def facts(plan):
    h.require(controller_proof() == plan['controller_sha256'], 'CONTROLLER_DRIFT')
    h.require(r.boot_identity() == plan['boot_identity'], 'BOOT_IDENTITY_DRIFT')
    h.require(h.BootstrapBackend().schema_revision() == plan['schema'], 'SCHEMA_DRIFT')
    h.require(h.unchanged_data_facts(h.data_proof(), plan['data']), 'DATA_FACT_DRIFT')
    h.require(b.empty_input_proof() == plan['input'], 'INPUT_IDENTITY_DRIFT')
    h.require(h.rest_window() == plan['session'], 'SESSION_DRIFT')
    historical_protected(plan)
    for name, digest in plan['journals'].items():
        h.require(h.digest(u.g.secure_bytes(h.runtime_directory() / name)) == digest, 'ORIGINAL_JOURNAL_DRIFT')
    h.require(h.digest(u.g.secure_bytes(Path(plan['review_path']))) == plan['review_sha256'], 'PATCH_REVIEW_DRIFT')


def api_web_ready(old):
    from app.runtime_deployment import owner_process_matches
    for name in ('api', 'web'):
        state = h.read_service_state(name)
        h.require(state and state.get('phase') == 'active' and state.get('generation') == 13
            and state.get('ready') is True and not state.get('failure_code')
            and h.pid_string(state.get('pid')) == h.loaded_identity(old.services[name])
            and owner_process_matches(state, old.services[name]), 'OLD_API_WEB_UNPROVEN')
        at = datetime.fromisoformat(state['at'])
        h.require(at.tzinfo is not None and 0 <= (datetime.now(UTC)-at).total_seconds() <= 30,
            'OLD_API_WEB_STALE')
    h.require(h.http_ready(), 'OLD_HTTP_HEALTH_UNPROVEN')


def require_calendar_absent(binding):
    # calendar_output uses the strict launchctl reader: None means explicit
    # rc113 label absence in a proven gui domain. loaded_identity(idle=True)
    # applies only to an existing loaded definition, not an absent label.
    h.require(s.calendar_output(binding) is None, 'CALENDAR_ABSENT_REQUIRED')


def freeze(root, tag, commit, review_path, review_sha):
    from app.runtime_deployment import owner_process_matches, assert_no_unknown_deployment
    import app.reference_trading.composition as reference_module
    import guiyi_quant.newow.product_adapters as formula_module
    assert_no_unknown_deployment()
    h.require(not attempt_path().exists(), 'GENERATION14_ATTEMPT_EXISTS')
    h.require(root == ROOT and tag == 'v1.15.3' and commit == CANDIDATE_COMMIT, 'CANDIDATE_INVALID')
    h.verify_release(root, tag, commit)
    h.require(Path(reference_module.__file__).resolve().is_relative_to(root / 'services/quant-api')
        and Path(formula_module.__file__).resolve().is_relative_to(root / 'packages/quant-core'),
        'CANDIDATE_IMPORT_IDENTITY_UNPROVEN')
    previous = source_attempt()
    old = h.read_bindings()
    h.require(old is not None and h.asdict(old) == previous['plan']['new'] and set(old.services) == h.SERVICES
        and all(binding.generation == 13 and binding.root == str(ROOT) and binding.tag == tag
            and binding.commit == commit and binding.enabled is True and binding.launchd_label is None
            for binding in old.services.values()), 'OLD_BINDING_DRIFT')
    h.require(str(review_path) == previous['plan']['review_path'] and review_sha == previous['plan']['review_sha256']
        and h.digest(u.g.secure_bytes(review_path)) == review_sha, 'PATCH_REVIEW_DRIFT')
    contracts = h.contract_fingerprints(root)
    h.require(all(binding.contracts == contracts for binding in old.services.values()), 'OLD_CONTRACT_DRIFT')
    for name, digest in previous['plan']['journals'].items():
        raw = u.g.secure_bytes(h.runtime_directory() / name)
        archive = u.g.secure_bytes(g.attempt_path().with_name(g.attempt_path().name + '.' + name + '.bytes'))
        h.require(h.digest(raw) == digest and archive == raw, 'PRIOR_JOURNAL_CHAIN_DRIFT')
    h.require(h.digest(u.g.secure_bytes(Path(previous['history_archive']))) == previous['drained_history_sha256'],
        'GENERATION13_HISTORY_ARCHIVE_DRIFT')
    disabled = h.parse_disabled_states(h.launch('print-disabled', f'gui/{os.getuid()}').stdout)
    owners, plists, drains = {}, {}, {}
    for name, binding in old.services.items():
        raw = h.snapshot(Path.home() / 'Library/LaunchAgents' / f'{binding.label}.plist')
        payload = plistlib.loads(raw)
        env = payload.get('EnvironmentVariables', {})
        h.require(payload.get('Label') == binding.label and tuple(payload.get('ProgramArguments', []))
            == h.authorized_program_arguments(binding, Path.home()) and all(env.get(k) == v for k,v in {
                'GUIYI_PROJECT_ROOT':binding.root,'GUIYI_RUNTIME_TAG':tag,'GUIYI_RUNTIME_COMMIT':commit,
                'GUIYI_RUNTIME_GENERATION':'13','GUIYI_RUNTIME_HANDOVER_ENABLED':'1',
                'GUIYI_OBSERVATION_STREAM_ENABLED':'1'}.items()) and payload.get('WorkingDirectory')
            == (str(Path.home()) if name in ('api','web') else binding.root), 'PLIST_DRIFT')
        plists[name], drains[name] = h.digest(raw), g.control_sha(name)
        if name in h.CONTINUOUS:
            state = h.read_service_state(name); owners[name] = previous['owners'][name]
            h.require(state and state.get('generation') == 13 and h.pid_string(state.get('pid')) == owners[name]
                and h.loaded_identity(binding) == owners[name] and owner_process_matches(state,binding), 'OLD_OWNER_DRIFT')
            if name in h.BUSINESS:
                h.require(state.get('phase') == 'parked' and h._read(h.runtime_directory() / f'{name}.handover.json')
                    == {'schema_version':1,'service':name,'generation':13,'phase':'drain',
                        'request_id':previous['halt_requests'][name]}, 'PARTIAL_PARK_PROOF_DRIFT')
            else:
                h.require(state.get('phase') == 'active' and state.get('ready') is True
                    and not disabled.get(binding.label,False), 'OLD_API_WEB_UNPROVEN')
                h.require(drains[name] == previous['drain_sha256'][name], 'RETIRED_CONTROL_UNPROVEN')
        else:
            h.require(disabled.get(binding.label,False) is True, 'CALENDAR_ABSENT_DISABLED_REQUIRED')
            require_calendar_absent(binding)
            h.require(drains[name] == previous['plan']['drains'][name], 'RETIRED_CONTROL_UNPROVEN')
            s.check_inactive_calendar(payload,inputs_only=False)
    g.assert_reference_drained()
    api_web_ready(old)
    dispatcher = h.snapshot(h.runtime_directory() / 'run-local-service.sh')
    h.require(dispatcher == h.snapshot(root / 'scripts/ops/macos/runtime-service-dispatch.sh'), 'DISPATCHER_DRIFT')
    new = h.BindingRegistry(1,{name:replace(binding,generation=14) for name,binding in old.services.items()})
    journals = {path.name:h.digest(u.g.secure_bytes(path)) for path in h.runtime_directory().glob('*.json')
        if path.name.startswith(('topology-','reference-continuity-','reference-generation','reference-history-'))}
    h.require(journals[g.attempt_path().name] == UNKNOWN_SHA, 'GENERATION13_UNKNOWN_JOURNAL_DRIFT')
    h.require(h.maintenance_available(),'PRECONDITION_SOURCE_BUSY')
    plan = {'candidate':{'root':str(root),'tag':tag,'commit':commit},'old':h.asdict(old),'new':h.asdict(new),
        'registry_sha256':h.bindings_sha256(),'owners':owners,'plists':plists,'drains':drains,
        'existing_park_requests':previous['halt_requests'],'journals':journals,'scope':u.scope_proof(),
        'historical_preimage':g.history_preimage(),'history_sha256':h.digest(u.history_bytes()),
        'review_path':str(review_path),'review_sha256':review_sha,'launcher_sha256':h.digest(dispatcher),
        'controller_sha256':controller_proof(),'boot_identity':r.boot_identity(),'session':h.rest_window(),
        'schema':h.SCHEMA,'data':r.frozen_data(h.data_proof()),'input':b.empty_input_proof(),'assets':h.immutable_assets(old)}
    facts(plan)
    plan['plan_hash']=h.plan_hash(plan);g.control_budget(plan)
    api_web_ready(old)
    h.require(h.read_bindings() == old and h.bindings_sha256() == plan['registry_sha256'], 'FINAL_PREIMAGE_DRIFT')
    return plan

def registry(value):
    return h.BindingRegistry(1, {name: h.ServiceBinding(**binding) for name, binding in value['services'].items()})

def control_budget(value):
    h.require(len(json.dumps(value, sort_keys=True, allow_nan=False).encode()) <= 1_048_576,
        'CONTROL_BUDGET_EXCEEDED')

def log(attempt, step):
    attempt['step'] = step
    control_budget(attempt)
    h._write(attempt_path(), attempt)

def finalize(new, plan, attempt):
    try:
        log(attempt, 'final')
    except Exception:
        attempt['phase'] = 'outcome_unknown'
        attempt['failure_code'] = 'FINAL_JOURNAL_WRITE_UNKNOWN'
        try:
            if h.read_bindings() == new and not attempt.get('halted'):
                halt(new, plan, attempt)
        except Exception:
            attempt['halt'] = 'UNPROVEN'
        try:
            log(attempt, 'final_unknown')
        except Exception:
            attempt['journal'] = 'UNPROVEN'
    return {'phase': attempt['phase'], 'failure_code': attempt.get('failure_code'),
        'typed_proof': attempt.get('failure_typed_proof')}

@contextmanager
def maintenance_lease():
    from app.db.session import SessionLocal
    from app.market_data.catalog import MarketCatalog
    from app.market_data.composition import canonical_root
    with SessionLocal() as session:
        lease = MarketCatalog(session, canonical_root()).acquire_maintenance_lock()
        h.require(lease is not None, 'SOURCE_BUSY')
        try:
            yield
        finally:
            lease.release()

def control_sha(name):
    raw = h.control_bytes(h.runtime_directory() / f'{name}.handover.json')
    return h.digest(raw) if raw is not None else None

def assert_reference_drained():
    diag = h.read_service_state('reference-worker').get('proof', {}).get('reference_runtime', {})
    h.require(diag.get('stage') == 'drained' and diag.get('notifications_alive') is False
        and diag.get('historical_refresh_alive') is False, 'REFERENCE_CLOSE_UNPROVEN')

def archive_prior(plan, attempt):
    for name, digest in plan['journals'].items():
        raw = u.g.secure_bytes(h.runtime_directory() / name)
        h.require(h.digest(raw) == digest, 'ORIGINAL_JOURNAL_DRIFT')
        u.g.write_exclusive(attempt_path().with_name(attempt_path().name + '.' + name + '.bytes'), raw)
    log(attempt, 'original_journals_archived')

def capture_failure_proof(snapshot=None):
    # Typed codes and booleans only: never record sender config, URLs or exception messages.
    result={}
    for name in h.CONTINUOUS:
        state=(snapshot.get(name) if snapshot is not None else h.read_service_state(name)) or {}
        result[name]={key:state.get(key) for key in ('phase','ready','generation','at')}
        result[name]['failure_code'] = None if state.get('failure_code') is None else safe_code(state['failure_code'])
        proof=state.get('proof',{})
        result[name]['typed_proof']={}
        if proof.get('failure_code') is not None:
            result[name]['typed_proof']['failure_code']=safe_code(proof['failure_code'])
        for domain,value in proof.items():
            if isinstance(value,dict):
                result[name]['typed_proof'][domain]={key:value[key] for key in (
                    'stage','poll_code','poll_failure_code','last_poll_code','ready','failure_code','blocked_count',
                    'blocked_counts','historical_refresh_alive','notifications_alive','historical_refresh_error','notifications_error')
                    if key in value}
                for key,item in list(result[name]['typed_proof'][domain].items()):
                    if key=='blocked_counts':
                        result[name]['typed_proof'][domain][key]={safe_code(k):v for k,v in item.items()
                            if type(v) is int and v>=0} if isinstance(item,dict) else {}
                    elif key.endswith('code') or key.endswith('error'):
                        result[name]['typed_proof'][domain][key]=None if item is None else safe_code(item)
    return result

def safe_code(value):
    return value if type(value) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}',value) else 'UNCLASSIFIED_FAILURE'

def heartbeat_gate(new):
    from app.redis_connections import get_redis_connection
    connection=get_redis_connection();proof={};valid=True
    try:
        for name,key in (('live','live:heartbeat'),('market-feed','live:feed:heartbeat')):
            raw=connection.get(key);binding=new.services[name]
            value=json.loads(raw) if raw is not None else {}
            age=None
            try:
                at=datetime.fromisoformat(value['generated_at'])
                if at.tzinfo is not None:age=(datetime.now(UTC)-at).total_seconds()
            except (KeyError,TypeError,ValueError):pass
            identity={field:value.get(field)==expected for field,expected in {
                'runtime_root':binding.root,'runtime_commit':binding.commit,'runtime_tag':binding.tag,
                'runtime_generation':binding.generation}.items()}
            matched=all(identity.values())
            ok=bool(age is not None and 0<=age<=30 and value.get('available') is True
                and type(value.get('operational_count')) is int and value['operational_count']==60 and matched)
            proof[name]={'present':raw is not None,'age_seconds':age,'available':value.get('available') is True,
                'operational_count':value.get('operational_count') if type(value.get('operational_count')) is int else None,
                **{field:getattr(binding,field.removeprefix('runtime_')) if identity[field] else 'MISMATCH'
                   for field in ('runtime_root','runtime_commit','runtime_tag','runtime_generation')},
                'identity_matches':identity,'accepted':ok}
            valid=valid and ok
    finally:connection.close()
    return valid,proof

def wait_parked(plan, generation, *, deadline=None):
    deadline = monotonic() + 10 if deadline is None else deadline
    while monotonic() < deadline:
        if all((state := h.read_service_state(name)) and state.get('phase') == 'parked'
            and state.get('generation') == generation and h.pid_string(state.get('pid')) == plan['owners'][name]
            for name in h.CONTINUOUS):
            return True
        sleep(.1)
    return False

def expected_drain_sha(name, request):
    raw = h.control_bytes(h.runtime_directory() / f'{name}.handover.json')
    h.require(raw is not None, 'DRAIN_MISSING')
    h.require(json.loads(raw) == {'schema_version': 1, 'service': name, 'generation': 13,
        'request_id': request, 'phase': 'drain'}, 'DRAIN_DRIFT')
    return h.digest(raw)

def retired_owner(name,state,new,attempt):
    if not (state and state.get('generation')==13 and h.pid_string(state.get('pid'))==attempt['plan']['owners'][name]):
        return False
    raw=u.g.secure_bytes(h.runtime_directory()/f'{name}.owner.json')
    if h.digest(raw)!=attempt.get('previous_owner_sha256',{}).get(name):
        return False
    h.old_pids_exited({'owners':{name:{'pid':attempt['plan']['owners'][name]}}})
    h.require(h.loaded_identity(new.services[name])==attempt['owners'][name],'NEW_LOADED_IDENTITY_DRIFT')
    return True

def poll_cycles(new,attempt,evidence,snapshot=None):
    now=datetime.now(UTC); valid=True
    for name in h.CONTINUOUS:
        state=snapshot.get(name) if snapshot is not None else h.read_service_state(name)
        if not (state and state.get('generation')==14 and h.pid_string(state.get('pid'))==attempt['owners'][name]):
            if retired_owner(name,state,new,attempt):
                valid=False
                continue
            raise h.ResumeBlocked('OWNER_IDENTITY_DRIFT')
        h.require(not state.get('failure_code'),'OWNER_FAILURE')
        if state.get('phase')!='active':
            valid=False
            continue
        at=datetime.fromisoformat(state['at'])
        h.require(at.tzinfo is not None,'OWNER_TIME_INVALID')
        if not 0<=(now-at).total_seconds()<=30:
            valid=False
            continue
        if name=='reference-worker':
            diag=state.get('proof',{}).get('reference_runtime',{})
            h.require(not diag.get('failure_code'),'REFERENCE_UNHEALTHY')
            h.require(diag.get('historical_refresh_error') is None,'HISTORY_REFRESH_FAILED')
            h.require(diag.get('notifications_error') is None,'NOTIFICATIONS_FAILED')
            if (diag.get('blocked_count')!=0 or diag.get('blocked_counts')!={}
                or diag.get('historical_refresh_alive') is not True or diag.get('notifications_alive') is not True
                or diag.get('stage') not in {'scan','cycle'}):
                valid=False
                continue
        if name=='live' and state.get('ready') is not True and state.get('proof',{}).get('failure_code') is not None:
            attempt['failure_typed_proof']=capture_failure_proof()
            attempt['failure_typed_proof'].setdefault('live',{}).setdefault('typed_proof',{})['failure_code']=safe_code(state['proof']['failure_code'])
            raise h.ResumeBlocked('LIVE_TYPED_POLL_FAILURE')
        if state.get('ready') is not True:
            valid=False
            continue
        if at>=datetime.fromisoformat(attempt['started_at']):
            evidence[name]=at.isoformat()
    return valid and all(name in evidence and 0<=(now-datetime.fromisoformat(evidence[name])).total_seconds()<=30
        for name in h.CONTINUOUS)

def halt(new, plan, attempt):
    """Cooperatively park candidate writers; retain API/Web for diagnosis.

    An unknown process is never killed using a stale owner record. The final
    journal remains outcome_unknown and cannot be reused for a retry.
    """
    from app.runtime_deployment import owner_process_matches
    failed, requested = [], {}
    for name in h.SCHEDULED:
        try:
            h.require(h.read_bindings() == new, 'REGISTRY_DRIFT')
            binding = new.services[name]
            with ExitStack() as locks:
                h.acquire_owner_locks(locks, services=(name,))
                h.require(h.read_bindings() == new, 'REGISTRY_DRIFT')
                h.launch('disable', f'gui/{os.getuid()}/{binding.label}')
                if s.calendar_output(binding) is not None:
                    h.require(name in attempt['calendar_intents']
                        and h.loaded_identity(binding, idle=True) is None, 'UNOWNED_CALENDAR_LOADED')
                    attempt.setdefault('calendar_halt_intents', []).append(name)
                    log(attempt, 'calendar_halt_' + name)
                    h.launch('bootout', f'gui/{os.getuid()}/{binding.label}')
                    h.confirm_weekly_absence(binding)
        except Exception:
            failed.append(name)
    for name in h.BUSINESS:
        try:
            state = h.read_service_state(name)
            h.require(h.read_bindings() == new and state and state.get('generation') == 14
                and h.pid_string(state.get('pid')) == attempt['owners'].get(name)
                and h.loaded_identity(new.services[name]) == attempt['owners'][name]
                and state.get('phase') in {'active', 'parked'}
                and owner_process_matches(state, new.services[name]), 'CANDIDATE_OWNER_UNPROVEN')
            attempt.setdefault('halt_drain_intents', []).append(name)
            log(attempt, 'halt_drain_' + name)
            requested[name] = h.request_drain(name, generation=14)
            attempt['halt_requests'] = dict(requested)
            log(attempt, 'halt_drain_written_' + name)
        except Exception:
            failed.append(name)
    deadline, verified = monotonic() + 10, False
    while requested and monotonic() < deadline:
        try:
            h.require(h.read_bindings() == new, 'REGISTRY_DRIFT')
            if all((state := h.read_service_state(name)) and state.get('phase') == 'parked'
                and state.get('generation') == 14 and h.pid_string(state.get('pid')) == attempt['owners'][name]
                for name in requested):
                with ExitStack() as locks:
                    h.acquire_owner_locks(locks, services=tuple(requested))
                    h.require(h.read_bindings() == new, 'REGISTRY_DRIFT')
                    for name, request in requested.items():
                        state = h.read_service_state(name)
                        h.require(state and state.get('phase') == 'parked' and state.get('generation') == 14
                            and h.pid_string(state.get('pid')) == attempt['owners'][name]
                            and h.loaded_identity(new.services[name]) == attempt['owners'][name]
                            and owner_process_matches(state, new.services[name])
                            and h._read(h.runtime_directory() / f'{name}.handover.json') == {
                                'schema_version': 1, 'service': name, 'generation': 14,
                                'phase': 'drain', 'request_id': request}, 'HALT_PARK_PROOF_DRIFT')
                    if 'reference-worker' in requested:
                        assert_reference_drained()
                    verified = set(requested) == set(h.BUSINESS) and not failed
                break
        except Exception:
            failed.extend(name for name in requested if name not in failed)
            break
        sleep(.1)
    attempt['halt_requests'] = requested
    attempt['halted'] = list(h.BUSINESS)
    attempt['parked_verified'] = verified
    if not verified:
        attempt['halt_proof'] = 'UNPROVEN'
        failed.extend(name for name in h.BUSINESS if name not in failed)
    attempt['halt_failed'] = failed

def apply(plan):
    control_budget(plan)
    h.require(plan.get('plan_hash') == h.plan_hash(plan), 'PLAN_HASH_INVALID')
    c = plan['candidate']
    with h.deployment_lock():
        h.require(freeze(Path(c['root']), c['tag'], c['commit'], Path(plan['review_path']), plan['review_sha256']) == plan, 'PLAN_DRIFT')
        h.require(h.maintenance_available(), 'PRECONDITION_SOURCE_BUSY')
        old, new = registry(plan['old']), registry(plan['new'])
        attempt = {'phase': 'prepared', 'plan': plan, 'requests': dict(plan['existing_park_requests']), 'stopped': [], 'started': [], 'bootout_intents': [],
            'scheduled_loaded': [], 'calendar_intents': [], 'drain_sha256': {name:plan['drains'][name] for name in h.BUSINESS}, 'owners': {}, 'bootstrap_intents': [],
            'old_health_gate_evidence': _OLD_HEALTH_EVIDENCE}
        log(attempt, 'prepared')
        try:
            archive_prior(plan, attempt)
            for name in ('api', 'web'):
                h.require(control_sha(name) == plan['drains'][name], 'ORIGINAL_CONTROL_DRIFT')
                log(attempt, 'drain_' + name)
                attempt.setdefault('drain_started_at', monotonic())
                attempt['requests'][name] = h.request_drain(name, generation=13)
                attempt['drain_sha256'][name] = expected_drain_sha(name, attempt['requests'][name])
                log(attempt, 'drain_written_' + name)
            h.require(wait_parked(plan, 13, deadline=attempt.get('drain_started_at', monotonic()) + 10), 'OLD_DRAIN_TIMEOUT')
            with ExitStack() as locks:
                h.acquire_owner_locks(locks)
                from app.reference_trading.historical_refresh import RefreshStateStore
                locks.enter_context(u.g.notification_lease())
                locks.enter_context(maintenance_lease())
                historical_held = locks.enter_context(RefreshStateStore(
                    h.runtime_directory() / 'newow-historical-refresh-state.json').exclusive())
                h.require(historical_held, 'HISTORICAL_STATE_BUSY')
                historical_protected(plan)
                raw_history = u.history_bytes()
                attempt['drained_history_sha256'] = h.digest(raw_history)
                history_archive = attempt_path().with_name(attempt_path().name + '.drained-history.bytes')
                u.g.write_exclusive(history_archive, raw_history)
                attempt['history_archive'] = str(history_archive)
                h.require(u.history_bytes() == raw_history, 'DRAINED_HISTORY_STATE_DRIFT')
                log(attempt, 'drained_history_proven')
                facts(plan)
                h.require(h.read_bindings() == old and h.bindings_sha256() == plan['registry_sha256'], 'REGISTRY_DRIFT')
                for name, binding in old.services.items():
                    path = Path.home() / 'Library/LaunchAgents' / f'{binding.label}.plist'
                    h.require(h.digest(h.snapshot(path)) == plan['plists'][name], 'PLIST_DRIFT')
                    if name in h.CONTINUOUS:
                        from app.runtime_deployment import owner_process_matches
                        h.require(h.loaded_identity(binding) == plan['owners'][name]
                            and owner_process_matches(h.read_service_state(name), binding), 'OLD_PID_DRIFT')
                        control = h._read(h.runtime_directory() / f'{name}.handover.json')
                        h.require(control and control.get('service') == name and control.get('generation') == 13
                            and control.get('phase') == 'drain' and
                            control.get('request_id') == attempt['requests'][name]
                            and control_sha(name) == attempt['drain_sha256'][name], 'DRAIN_DRIFT')
                    else:
                        h.require(control_sha(name) == plan['drains'][name], 'ORIGINAL_CONTROL_DRIFT')
                        require_calendar_absent(binding)
                assert_reference_drained()
                for name in h.CONTINUOUS:
                    attempt['bootout_intents'].append(name)
                    log(attempt, 'bootout_' + name)
                    h.launch('bootout', f'gui/{os.getuid()}/{old.services[name].label}')
                    attempt['stopped'].append(name)
                    log(attempt, 'stopped_' + name)
                deadline = monotonic() + 10
                while True:
                    try:
                        h.old_pids_exited({'owners': {name: {'pid': pid} for name, pid in plan['owners'].items()}})
                        break
                    except h.ResumeBlocked:
                        h.require(monotonic() < deadline, 'OLD_PID_EXIT_UNPROVEN')
                        sleep(.1)
                attempt['previous_owner_sha256'] = {name: h.digest(h.snapshot(h.runtime_directory() / f'{name}.owner.json'))
                    for name in h.CONTINUOUS}
                facts(plan)
                for name, binding in new.services.items():
                    path = Path.home() / 'Library/LaunchAgents' / f'{binding.label}.plist'
                    raw = h.snapshot(path)
                    h.require(h.digest(raw) == plan['plists'][name], 'PLIST_DRIFT')
                    payload = plistlib.loads(raw)
                    h.rebind_plist(payload, binding)
                    log(attempt, 'replace_plist_' + name)
                    temporary = path.with_name(path.name + '.generation14')
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, 'wb') as output:
                        output.write(plistlib.dumps(payload))
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, path)
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                target = Path(c['root']) / '.run'
                target.mkdir(mode=0o700, exist_ok=True)
                h.require(target == target.resolve(strict=True), 'CANDIDATE_ASSET_PATH_INVALID')
                h.require(h.immutable_assets(old) == plan['assets'], 'OLD_ASSET_DRIFT')
                for source, digest in plan['assets'].items():
                    raw = h.snapshot(Path(source))
                    h.require(h.digest(raw) == digest, 'ASSET_DRIFT')
                    destination = target / Path(source).name
                    if destination.exists():
                        h.require(h.digest(h.snapshot(destination)) == digest, 'CANDIDATE_ASSET_CONFLICT')
                    else:
                        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                        with os.fdopen(fd, 'wb') as output:
                            output.write(raw)
                            output.flush()
                            os.fsync(output.fileno())
                h.require(h.digest(h.snapshot(h.runtime_directory() / 'run-local-service.sh')) == plan['launcher_sha256'],
                    'LAUNCHER_DRIFT')
                log(attempt, 'registry_generation14_cas')
                h.write_bindings(new, expected_sha256=plan['registry_sha256'])
                attempt['phase'] = 'binding_committed'
                log(attempt, 'binding_committed')
            for name in u.START_ORDER:
                attempt['bootstrap_intents'].append(name)
                log(attempt, 'bootstrap_' + name)
                h.launch('enable', f'gui/{os.getuid()}/{new.services[name].label}')
                h.launch('bootstrap', f'gui/{os.getuid()}', str(Path.home() / 'Library/LaunchAgents' / f'{new.services[name].label}.plist'))
                attempt['owners'][name] = h.loaded_identity(new.services[name])
                attempt['started'].append(name)
                log(attempt, 'started_' + name)
            attempt['started_at'] = datetime.now(UTC).isoformat()
            attempt['owners'] = {name: h.loaded_identity(new.services[name]) for name in h.CONTINUOUS}
            evidence = {}
            attempt['cycle_evidence'] = evidence
            ready_deadline = monotonic() + 30
            await_cycles(new, plan, attempt, evidence, ready_deadline)
            attempt['phase'] = 'continuous_ready'
            log(attempt, 'continuous_ready')
            for name in h.SCHEDULED:
                binding = new.services[name]
                facts(plan)
                h.require(h.read_bindings() == new, 'REGISTRY_DRIFT')
                h.require(s.calendar_output(binding) is None, 'CALENDAR_NOT_ABSENT')
                payload = plistlib.loads(h.snapshot(Path.home() / 'Library/LaunchAgents' / f'{binding.label}.plist'))
                h.BootstrapBackend()._assert_recovery_calendar_safe(payload)
                if binding.enabled:
                    attempt['calendar_intents'].append(name)
                    log(attempt, 'calendar_bootstrap_' + name)
                    h.launch('enable', f'gui/{os.getuid()}/{binding.label}')
                    h.launch('bootstrap', f'gui/{os.getuid()}', str(Path.home() / 'Library/LaunchAgents' / f'{binding.label}.plist'))
                    attempt['scheduled_loaded'].append(name)
                    log(attempt, 'calendar_loaded_' + name)
                    r.verify_schedule_state(new, name)
            facts(plan)
            historical_protected(plan)
            for name in h.SCHEDULED:
                r.verify_schedule_state(new, name)
            await_fresh_cycles(new, plan, attempt, evidence, monotonic() + 30)
            attempt['cycle_evidence'] = evidence
            attempt['phase'] = 'generation14_ready_calendars_idle'
        except Exception as error:
            try:
                attempt['failure_typed_proof'] = capture_failure_proof()
            except Exception:
                attempt['failure_typed_proof'] = {'capture_code': 'FAILURE_PROOF_READ_UNKNOWN'}
            attempt['phase'] = 'outcome_unknown'
            attempt['failure_code'] = str(error) if isinstance(error, h.ResumeBlocked) else 'GENERATION14_OPERATION_UNKNOWN'
            try:
                if (not attempt['bootout_intents'] and not attempt.get('old_calendar_intents')
                        and h.read_bindings() == old):
                    try:
                        facts(plan)
                        h.require(h.bindings_sha256() == plan['registry_sha256'], 'REGISTRY_DRIFT')
                        for name in ('api', 'web'):
                            if name not in attempt['requests']: continue
                            request = attempt['requests'][name]
                            h.require(h.loaded_identity(old.services[name]) == plan['owners'][name], 'OLD_PID_DRIFT')
                            control = h._read(h.runtime_directory() / f'{name}.handover.json')
                            h.require(control and control.get('service') == name and control.get('generation') == 13
                                and control.get('phase') == 'drain' and control.get('request_id') == request
                                and control_sha(name) == attempt['drain_sha256'][name], 'DRAIN_DRIFT')
                        for name in ('api', 'web'):
                            if name not in attempt['requests']: continue
                            request = attempt['requests'][name]
                            h.cancel_drain(name, request_id=request)
                        attempt['old_drains_cancelled'] = True
                    except Exception:
                        attempt['old_drains_cancelled'] = False
                elif h.read_bindings() == new:
                    halt(new, plan, attempt)
            except Exception:
                attempt['recovery_proof'] = 'UNPROVEN'
            try:
                log(attempt, 'failure_readback_required')
            except Exception:
                attempt['journal'] = 'UNPROVEN'
        return finalize(new, plan, attempt)

def wait_http_startup(new, attempt, *, persist=True, seconds=60):
    """Wait for child listeners without relaxing ownership or business health."""
    from app.runtime_deployment import owner_process_matches
    deadline = monotonic() + seconds
    polls = 0
    started = monotonic()
    while monotonic() < deadline:
        h.require(h.read_bindings() == new, 'REGISTRY_DRIFT')
        snapshot = {name:h.read_service_state(name) for name in h.CONTINUOUS}
        current_owners = True
        for name,state in snapshot.items():
            h.require(h.loaded_identity(new.services[name]) == attempt['owners'][name], 'NEW_LOADED_IDENTITY_DRIFT')
            if not (state and state.get('generation') == 14
                    and h.pid_string(state.get('pid')) == attempt['owners'][name]):
                h.require(retired_owner(name,state,new,attempt), 'OWNER_IDENTITY_DRIFT')
                current_owners = False
                continue
            h.require(not state.get('failure_code') and not state.get('proof',{}).get('failure_code'),
                'STARTUP_OWNER_FAILURE')
            h.require(state.get('phase') == 'active' and owner_process_matches(state,new.services[name]),
                'STARTUP_OWNER_IDENTITY_DRIFT')
            if name == 'reference-worker':
                diag=state.get('proof',{}).get('reference_runtime',{})
                h.require(not diag.get('failure_code') and diag.get('historical_refresh_error') is None
                    and diag.get('notifications_error') is None,'STARTUP_REFERENCE_FAILURE')
        polls += 1
        if h.http_ready() and current_owners and all(snapshot[name].get('ready') is True
                for name in ('api','web')):
            h.require(monotonic() <= deadline, 'HTTP_STARTUP_TIMEOUT')
            attempt['http_startup']={'ready':True,'polls':polls,'seconds':monotonic()-started,
                'at':datetime.now(UTC).isoformat()}
            if persist:log(attempt,'http_startup_ready')
            return
        sleep(.2)
    attempt['http_startup']={'ready':False,'polls':polls,'seconds':monotonic()-started,
        'code':'HTTP_STARTUP_TIMEOUT'}
    raise h.ResumeBlocked('HTTP_STARTUP_TIMEOUT')

def await_cycles(new,plan,attempt,evidence,deadline,*,persist=True):
    from app.services.deployment_identity import deployment_identity_health
    from app.runtime_deployment import owner_process_matches
    # Child startup completes before expensive identity and fresh business sampling.
    wait_http_startup(new,attempt,persist=persist)
    begin=monotonic()
    rows=deployment_identity_health(root=Path(new.services['api'].root),commit=new.services['api'].commit).get('services',{})
    mapping={'live':'live_market','reference-worker':'reference_worker'}
    identity=all(owner_process_matches(h.read_service_state(name),new.services[name])
        and h.loaded_identity(new.services[name])==attempt['owners'][name]
        and rows.get(mapping.get(name,name),{}).get('status')=='matched' for name in h.CONTINUOUS)
    identity_seconds=monotonic()-begin
    h.require(identity,'DEPLOYMENT_IDENTITY_DRIFT')
    attempt['health_preflight']={'identity':identity,'http':True,'identity_seconds':identity_seconds,
        'http_startup':attempt.get('http_startup'), 'at':datetime.now(UTC).isoformat()}
    if persist:log(attempt,'health_preflight')
    await_fresh_cycles(new,plan,attempt,evidence,monotonic()+30,persist=persist)


def await_fresh_cycles(new,plan,attempt,evidence,deadline,*,persist=True):
    # A fresh 30s sample budget begins after the separately recorded heavy preflight.
    while monotonic()<deadline:
        begin=monotonic();sample={'at':datetime.now(UTC).isoformat()}
        try:
            sample['registry']=h.read_bindings()==new
            sample['loaded_pids']=all(h.loaded_identity(new.services[name])==attempt['owners'][name] for name in h.CONTINUOUS)
            sample['heartbeat'],sample['heartbeat_proof']=heartbeat_gate(new)
            snapshot={name:h.read_service_state(name) for name in h.CONTINUOUS}
            sample['owners']=capture_failure_proof(snapshot)
            sample['owner_ready']=poll_cycles(new,attempt,evidence,snapshot)
        except Exception as error:
            sample['failure_code']=str(error) if isinstance(error,h.ResumeBlocked) else 'HEALTH_GATE_READ_UNKNOWN'
            raise
        finally:
            sample['seconds']=monotonic()-begin
            attempt['health_gate_evidence']=sample
            if persist:log(attempt,'health_gate_sample')
        h.require(sample['registry'],'REGISTRY_DRIFT');h.require(sample['loaded_pids'],'NEW_LOADED_IDENTITY_DRIFT')
        if sample['heartbeat'] and sample['owner_ready']:
            h.require(monotonic()<=deadline,'HEALTHY_CYCLE_TIMEOUT')
            return
        sleep(.1)
    raise h.ResumeBlocked('HEALTHY_CYCLE_TIMEOUT')

def readback(plan):
    h.require(plan.get('plan_hash') == h.plan_hash(plan), 'PLAN_HASH_INVALID')
    raw = u.g.secure_bytes(attempt_path())
    attempt = json.loads(raw)
    h.require(attempt.get('phase') == 'generation14_ready_calendars_idle'
        and attempt.get('plan') == plan and not attempt.get('failure_code'), 'OUTCOME_READBACK_REQUIRED')
    new = registry(plan['new'])
    h.require(h.read_bindings() == new, 'REGISTRY_DRIFT')
    facts(plan)
    for name, digest in plan['journals'].items():
        archive = u.g.secure_bytes(attempt_path().with_name(attempt_path().name + '.' + name + '.bytes'))
        h.require(h.digest(archive) == digest and archive == u.g.secure_bytes(h.runtime_directory() / name),
            'PRIOR_ARCHIVE_DRIFT')
    for name, binding in new.services.items():
        h.verify_release(Path(binding.root), binding.tag, binding.commit)
        payload = plistlib.loads(h.snapshot(Path.home() / 'Library/LaunchAgents' / f'{binding.label}.plist'))
        env = payload.get('EnvironmentVariables', {})
        h.require(payload.get('Label') == binding.label and tuple(payload.get('ProgramArguments', []))
            == h.authorized_program_arguments(binding, Path.home()) and all(env.get(k) == v for k, v in {
                'GUIYI_PROJECT_ROOT': binding.root, 'GUIYI_RUNTIME_TAG': binding.tag,
                'GUIYI_RUNTIME_COMMIT': binding.commit, 'GUIYI_RUNTIME_GENERATION': '14',
                'GUIYI_RUNTIME_HANDOVER_ENABLED': '1', 'GUIYI_OBSERVATION_STREAM_ENABLED': '1'}.items())
            and payload.get('WorkingDirectory') == (str(Path.home()) if name in ('api', 'web') else binding.root),
            'PLIST_READBACK_DRIFT')
        if name in h.SCHEDULED:
            r.verify_schedule_state(new, name)
    for source, digest in plan['assets'].items():
        h.require(h.digest(h.snapshot(ROOT / '.run' / Path(source).name)) == digest, 'ASSET_READBACK_DRIFT')
    evidence = {}
    await_cycles(new, plan, attempt, evidence, monotonic() + 30, persist=False)
    return {'phase': 'GENERATION14_INDEPENDENT_READBACK', 'cycle_evidence': evidence,
        'natural_intraday_acceptance': 'PENDING', 'recipient_delivery_acceptance': 'PENDING',
        'health_preflight': attempt.get('health_preflight'), 'health_gate_evidence': attempt.get('health_gate_evidence')}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='mode', required=True)
    p = commands.add_parser('plan')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--tag', required=True)
    p.add_argument('--commit', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--review', type=Path, required=True)
    p.add_argument('--review-sha256', required=True)
    p = commands.add_parser('apply')
    p.add_argument('--plan', type=Path, required=True)
    p = commands.add_parser('readback')
    p.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'plan':
        plan = freeze(args.root, args.tag, args.commit, args.review, args.review_sha256)
        h.private_plan_file(args.output, plan)
        print(json.dumps({'status': 'GENERATION14_PLAN_FROZEN', 'plan_hash': plan['plan_hash'],
            'old_health_gate_evidence': _OLD_HEALTH_EVIDENCE}))
    else:
        handler = apply if args.mode == 'apply' else readback
        print(json.dumps(handler(json.loads(h.control_bytes(args.plan)))))

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED', 'code': str(error) if isinstance(error, h.ResumeBlocked) else type(error).__name__}))
        raise SystemExit(2) from None
