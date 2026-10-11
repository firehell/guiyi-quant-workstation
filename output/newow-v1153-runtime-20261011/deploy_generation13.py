"""Single-use exact v1.15.1/gen12 -> v1.15.3/gen13 whole-runtime REST switch.

No Scope migration, historical reset, notification policy change or input replay.
The formula fingerprint remains genuine; all old owners exit before registry CAS.
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
OLD_COMMIT = '386031757f37f5f4d373b68c47d50c5dc3215b07'
CANDIDATE_COMMIT = 'c28438d3d7ad6d6c66272027996f4a25e2facdfe'
HELPER = PROJECT / 'output/newow-v1151-recovery-20261011/deploy_generation12_recovery.py'
HELPER_SHA = '744194e507eeec562c5ff6abc4d5eda9260d0173ba6861a0cebd9f431eac49a0'

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
    raise RuntimeError('GENERATION12_HELPER_DRIFT')
spec = importlib.util.spec_from_file_location('gen13_readonly_helpers', HELPER)
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
h, s, b, r = u.h, u.s, u.b, u.r


def attempt_path():
    return h.runtime_directory() / 'reference-continuity-generation13.json'


def controller_proof():
    h.require(h.digest(source_bytes(HELPER)) == HELPER_SHA, 'GENERATION12_HELPER_DRIFT')
    proof = u.controller_proof()
    proof[str(Path(__file__).resolve())] = h.digest(source_bytes(Path(__file__).resolve()))
    return proof


def reviewed_changes(old, root):
    before, after = h._tracked(old), h._tracked(root)
    changes = {key: {'previous': before.get(key), 'candidate': after.get(key)}
        for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    h.require(bool(changes), 'RELEASE_CHANGE_EMPTY')
    return changes


def validate_review(old, root, review):
    changes = reviewed_changes(old, root)
    before, after = h.contract_fingerprints(old), h.contract_fingerprints(root)
    h.require(set(before) == set(after) == {'db', 'live', 'input', 'formula', 'reference', 'launcher'},
        'CONTRACT_KEYS_INVALID')
    delta = {key: {'old': before[key], 'new': after[key]} for key in before if before[key] != after[key]}
    h.require(set(delta) == {'formula'}, 'PROTECTED_CONTRACT_CHANGED')
    required = ('action_semantics_preserved', 'reference_trade_semantics_preserved',
        'scope_identity_preserved', 'history_state_codec_preserved', 'notification_policy_preserved')
    modules = {'packages/quant-core/guiyi_quant/newow/' + item for item in
        ('main_rise.py', 'product_adapters.py', 'subplots.py')}
    modules.add('packages/quant-core/guiyi_quant/lms405/__init__.py')
    h.require(review.get('status') == 'REVIEW_COMPLETE' and review.get('old_commit') == OLD_COMMIT
        and review.get('candidate_commit') == CANDIDATE_COMMIT and review.get('changes') == changes
        and review.get('contract_changes') == delta and all(review.get(key) is True for key in required)
        and modules <= set(review.get('reviewed_modules', [])), 'EXACT_PATCH_REVIEW_UNPROVEN')
    return changes, after, delta


def verify_previous_recovery(old):
    previous = u.read_attempt()
    h.require(previous.get('phase') == 'generation12_ready_calendars_idle'
        and not previous.get('failure_code') and previous.get('plan', {}).get('new') == h.asdict(old)
        and previous['plan'].get('plan_hash') == h.plan_hash(previous['plan'])
        and set(previous.get('stopped', [])) == set(previous.get('started', [])) == set(h.CONTINUOUS),
        'GENERATION12_SUCCESS_UNPROVEN')
    for name, digest in previous['plan']['journals'].items():
        raw = u.g.secure_bytes(h.runtime_directory() / name)
        archive = u.g.secure_bytes(u.attempt_path().with_name(u.attempt_path().name + '.' + name + '.bytes'))
        h.require(h.digest(raw) == digest and archive == raw, 'PRIOR_JOURNAL_CHAIN_DRIFT')
    h.require(h.digest(u.g.secure_bytes(Path(previous['history_archive']))) == previous['plan']['history_sha256'],
        'PRIOR_HISTORY_ARCHIVE_DRIFT')
    u.scope_proof()
    return previous


def validate_control(name, item, previous):
    if name in h.CONTINUOUS:
        expected = {'schema_version': 1, 'service': name, 'generation': 11,
            'phase': 'drain', 'request_id': previous['requests'][name]}
        h.require(item == expected and name in previous['stopped'] and name in previous['started'],
            'RETIRED_CONTROL_UNPROVEN')
    else:
        h.require(control_sha(name) == previous['plan']['controls'][name], 'RETIRED_CONTROL_UNPROVEN')


def history_preimage():
    """Require empty active history routes; bound the scheduling cursor by Scope."""
    from app.reference_trading.historical_refresh import VERSION
    raw = u.history_bytes()
    state = json.loads(raw)
    h.require(isinstance(state, dict) and set(state) == {'version', 'cursor', 'routes'}
        and state['version'] == VERSION and isinstance(state['cursor'], str)
        and isinstance(state['routes'], dict),
        'HISTORY_STATE_INVALID')
    h.require(state['routes'] == {}, 'HISTORY_ACTIVE_ROUTES_UNPROVEN')
    original = u.source_attempt()
    ids = {item['new']['source']['stream_id'] for item in original['plan']['scope']['mapping']}
    h.require(len(ids) == 720 and set(state['routes']) <= ids
        and (not state['cursor'] or state['cursor'] in ids), 'HISTORY_NEW_NAMESPACE_DRIFT')
    protected = json.dumps({'version': state['version'], 'routes': state['routes']},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return {'version': state['version'], 'route_count': len(state['routes']),
        'routes_sha256': h.digest(protected), 'require_empty_routes': True, 'cursor_policy': 'committed_720_namespace_rotation'}


def historical_protected(plan):
    h.require(u.scope_proof() == plan['scope'], 'COMMITTED_SCOPE_DRIFT')
    attempt_raw = h.control_bytes(attempt_path())
    attempt = json.loads(attempt_raw) if attempt_raw else {}
    # A real archive is created only after cooperative drain while all relevant
    # locks are held. Its raw bytes, including that exact cursor, never change.
    if attempt.get('history_archive'):
        h.require(attempt.get('plan') == plan and h.digest(u.g.secure_bytes(Path(attempt['history_archive'])))
            == attempt['drained_history_sha256'], 'HISTORY_ARCHIVE_DRIFT')
    if not attempt.get('started'):
        h.require(history_preimage() == plan['historical_preimage'], 'HISTORY_PROTECTED_FACT_DRIFT')
        if attempt.get('history_archive'):
            h.require(h.digest(u.history_bytes()) == attempt['drained_history_sha256'], 'DRAINED_HISTORY_STATE_DRIFT')


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


def archive_prior(plan, attempt):
    for name, digest in plan['journals'].items():
        raw = u.g.secure_bytes(h.runtime_directory() / name)
        h.require(h.digest(raw) == digest, 'ORIGINAL_JOURNAL_DRIFT')
        u.g.write_exclusive(attempt_path().with_name(attempt_path().name + '.' + name + '.bytes'), raw)
    log(attempt, 'original_journals_archived')

_OLD_HEALTH_EVIDENCE = None


def wait_old_current_ready_all(old, owners):
    """Require one actual all-ready snapshot after expensive preflight.

    Poll/scan sets ready=False naturally. No success is accumulated between
    rounds and no cached false value is promoted to true. Current owner identity
    and the reference threads/blocked state remain mandatory throughout.
    """
    global _OLD_HEALTH_EVIDENCE
    from app.runtime_deployment import owner_process_matches
    deadline = monotonic() + 30
    while monotonic() < deadline:
        snapshot = {name: h.read_service_state(name) for name in h.CONTINUOUS}
        now = datetime.now(UTC)
        for name, state in snapshot.items():
            h.require(state and state.get('generation') == 12 and state.get('phase') == 'active'
                and h.pid_string(state.get('pid')) == owners[name], 'OLD_OWNER_DRIFT')
            h.require(not state.get('failure_code') and not state.get('proof', {}).get('failure_code'),
                'OLD_OWNER_FAILURE')
            at = datetime.fromisoformat(state['at'])
            h.require(at.tzinfo is not None and (now - at).total_seconds() >= 0, 'OLD_OWNER_TIME_INVALID')
        preflight_reference(snapshot['reference-worker'])
        if all(state.get('ready') is True and 0 <= (now - datetime.fromisoformat(state['at'])).total_seconds() <= 30
                for state in snapshot.values()):
            h.require(h.read_bindings() == old, 'REGISTRY_DRIFT')
            for name, state in snapshot.items():
                h.require(h.loaded_identity(old.services[name]) == owners[name]
                    and owner_process_matches(state, old.services[name]), 'OLD_OWNER_DRIFT')
                current = h.read_service_state(name)
                h.require(current and current.get('generation') == 12 and current.get('phase') == 'active'
                    and h.pid_string(current.get('pid')) == owners[name]
                    and not current.get('failure_code') and not current.get('proof', {}).get('failure_code'),
                    'OLD_OWNER_DRIFT')
            preflight_reference(h.read_service_state('reference-worker'))
            finish = datetime.now(UTC)
            h.require(monotonic() <= deadline and all(0 <= (finish - datetime.fromisoformat(state['at'])).total_seconds()
                <= 30 for state in snapshot.values()), 'OLD_HEALTH_SNAPSHOT_TIMEOUT')
            _OLD_HEALTH_EVIDENCE = {'sampled_at': now.isoformat(), 'verified_at': finish.isoformat(),
                'owners': capture_failure_proof(snapshot), 'same_round_all_ready': True}
            return
        sleep(.1)
    raise h.ResumeBlocked('OLD_HEALTH_SNAPSHOT_TIMEOUT')


def freeze(root, tag, commit, review_path, review_sha):
    from app.runtime_deployment import owner_process_matches, assert_no_unknown_deployment
    assert_no_unknown_deployment()
    h.require(not attempt_path().exists(), 'GENERATION13_ATTEMPT_EXISTS')
    h.require(commit == CANDIDATE_COMMIT and tag == 'v1.15.3' and root == ROOT, 'CANDIDATE_INVALID')
    h.verify_release(root, tag, commit)
    import app.reference_trading.composition as reference_module
    import guiyi_quant.newow.product_adapters as formula_module
    h.require(Path(reference_module.__file__).resolve().is_relative_to(root / 'services/quant-api')
        and Path(formula_module.__file__).resolve().is_relative_to(root / 'packages/quant-core'),
        'CANDIDATE_IMPORT_IDENTITY_UNPROVEN')
    old = h.read_bindings()
    h.require(old is not None and set(old.services) == h.SERVICES and all(
        v.tag == 'v1.15.1' and v.commit == OLD_COMMIT and v.generation == 12 and v.launchd_label is None
        and v.enabled is True and Path(v.root) == PROJECT / '.worktrees/release-v1.15.1'
        for v in old.services.values()), 'OLD_BINDING_DRIFT')
    previous = verify_previous_recovery(old)
    review_raw = u.g.secure_bytes(review_path)
    h.require(h.digest(review_raw) == review_sha, 'EXACT_REVIEW_SHA_REQUIRED')
    changes, contracts, contract_changes = validate_review(Path(old.services['api'].root), root, json.loads(review_raw))
    for binding in old.services.values():
        h.verify_release(Path(binding.root), binding.tag, binding.commit)
        h.require(binding.contracts == h.contract_fingerprints(Path(binding.root)), 'OLD_CONTRACT_DRIFT')
        h.require(all(binding.contracts[key] == contracts[key] for key in
            ('db', 'live', 'input', 'reference', 'launcher')), 'PROTECTED_CONTRACT_CHANGED')
    disabled = h.parse_disabled_states(h.launch('print-disabled', f'gui/{os.getuid()}').stdout)
    owners, plists, drains = {}, {}, {}
    for name, binding in old.services.items():
        raw = h.snapshot(Path.home() / 'Library/LaunchAgents' / f'{binding.label}.plist')
        payload = plistlib.loads(raw)
        h.require(payload['Label'] == binding.label and tuple(payload['ProgramArguments']) ==
            h.authorized_program_arguments(binding, Path.home()), 'PLIST_ARGV_DRIFT')
        h.require(all(payload['EnvironmentVariables'].get(key) == value for key, value in {
            'GUIYI_PROJECT_ROOT': binding.root, 'GUIYI_RUNTIME_TAG': binding.tag,
            'GUIYI_RUNTIME_COMMIT': binding.commit, 'GUIYI_RUNTIME_GENERATION': '12',
            'GUIYI_RUNTIME_HANDOVER_ENABLED': '1', 'GUIYI_OBSERVATION_STREAM_ENABLED': '1'}.items()), 'PLIST_ENV_DRIFT')
        expected_directory = str(Path.home()) if binding.service in ('api', 'web') else binding.root
        h.require(payload.get('WorkingDirectory') == expected_directory, 'PLIST_WORKDIR_DRIFT')
        plists[name] = h.digest(raw)
        if name in h.CONTINUOUS:
            state = h.read_service_state(name)
            owners[name] = h.loaded_identity(binding)
            h.require(owners[name] == previous.get('owners', {}).get(name), 'OLD_SUCCESS_PID_DRIFT')
            h.require(not disabled.get(binding.label, False) and state and state.get('generation') == 12
                and h.pid_string(state.get('pid')) == owners[name]
                and state.get('phase') == 'active' and not state.get('failure_code')
                and not state.get('proof', {}).get('failure_code') and owner_process_matches(state, binding), 'OLD_OWNER_DRIFT')
        else:
            h.require(disabled.get(binding.label, False) is False and s.calendar_output(binding) is not None
                and h.loaded_identity(binding, idle=True) is None, 'CALENDAR_ENABLED_IDLE_REQUIRED')
            s.check_inactive_calendar(payload, inputs_only=False)
        control = h.control_bytes(h.runtime_directory() / f'{name}.handover.json')
        if control:
            item = json.loads(control)
            validate_control(name, item, previous)
        h.require(name not in h.CONTINUOUS or control is not None, 'RETIRED_CONTROL_MISSING')
        if name in h.SCHEDULED:
            h.require(control_sha(name) == previous['plan']['controls'][name], 'RETIRED_CONTROL_UNPROVEN')
        drains[name] = h.digest(control) if control else None
    preflight_reference(h.read_service_state('reference-worker'))
    h.require(ready(old, ('api', 'web')), 'INPUTS_OR_WEB_UNAVAILABLE')
    new = h.BindingRegistry(1, {name: replace(binding, root=str(root), tag=tag, commit=commit,
        generation=13, contracts=contracts) for name, binding in old.services.items()})
    launcher = h.snapshot(h.runtime_directory() / 'run-local-service.sh')
    h.require(launcher == h.snapshot(root / 'scripts/ops/macos/runtime-service-dispatch.sh')
        == h.snapshot(Path(old.services['api'].root) / 'scripts/ops/macos/runtime-service-dispatch.sh'), 'DISPATCHER_DRIFT')
    journals = {path.name: h.digest(h.snapshot(path)) for path in h.runtime_directory().glob('topology-*.json')}
    journals.update({path.name: h.digest(u.g.secure_bytes(path)) for path in h.runtime_directory().glob('*.json')
        if path.name.startswith(('reference-continuity-', 'reference-generation', 'reference-history-'))})
    h.require(h.maintenance_available(), 'PRECONDITION_SOURCE_BUSY')
    plan = {'candidate': {'root': str(root), 'tag': tag, 'commit': commit}, 'old': h.asdict(old),
        'new': h.asdict(new), 'registry_sha256': h.bindings_sha256(), 'plists': plists, 'owners': owners,
        'drains': drains, 'journals': journals, 'launcher_sha256': h.digest(launcher),
        'scope': u.scope_proof(), 'schema': h.SCHEMA, 'data': r.frozen_data(h.data_proof()), 'input': b.empty_input_proof(),
        'boot_identity': r.boot_identity(), 'session': h.rest_window(), 'changes': changes,
        'controller_sha256': controller_proof(), 'assets': h.immutable_assets(old), 'historical_preimage': history_preimage(),
        'review_path': str(review_path), 'review_sha256': review_sha, 'contract_changes': contract_changes}
    facts(plan)
    plan['plan_hash'] = h.plan_hash(plan)
    control_budget(plan)
    h.require(h.bindings_sha256() == plan['registry_sha256'] and h.rest_window() == plan['session'],
        'FINAL_PREIMAGE_DRIFT')
    for name, binding in old.services.items():
        path = Path.home() / 'Library/LaunchAgents' / f'{binding.label}.plist'
        h.require(h.digest(h.snapshot(path)) == plan['plists'][name], 'PLIST_DRIFT')
        if name in h.CONTINUOUS:
            h.require(h.loaded_identity(binding) == plan['owners'][name], 'OLD_PID_DRIFT')
        else:
            h.require(s.calendar_output(binding) is not None and h.loaded_identity(binding, idle=True) is None,
                'CALENDAR_ENABLED_IDLE_REQUIRED')
    wait_old_current_ready_all(old, owners)
    return plan

def registry(value):
    return h.BindingRegistry(1, {name: h.ServiceBinding(**binding) for name, binding in value['services'].items()})

def wait_parked(plan, generation, *, deadline=None):
    deadline = monotonic() + 10 if deadline is None else deadline
    while monotonic() < deadline:
        if all((state := h.read_service_state(name)) and state.get('phase') == 'parked'
            and state.get('generation') == generation and h.pid_string(state.get('pid')) == plan['owners'][name]
            for name in h.CONTINUOUS):
            return True
        sleep(.1)
    return False

def ready(new, names):
    from app.services.deployment_identity import deployment_identity_health
    from app.runtime_deployment import owner_process_matches
    rows = deployment_identity_health(root=Path(new.services['api'].root),
        commit=new.services['api'].commit).get('services', {})
    mapping = {'live': 'live_market', 'reference-worker': 'reference_worker'}
    for name in names:
        binding = new.services[name]
        state = h.read_service_state(name)
        if not (state and state.get('generation') == binding.generation and state.get('phase') == 'active'
            and state.get('ready') is True and h.pid_string(state.get('pid')) == h.loaded_identity(binding)):
            return False
        at = datetime.fromisoformat(state['at'])
        if at.tzinfo is None or not 0 <= (datetime.now(UTC) - at).total_seconds() <= 30:
            return False
        if rows.get(mapping.get(name, name), {}).get('status') != 'matched' or not owner_process_matches(state, binding):
            return False
    return h.http_ready() and b.heartbeats_ready(new)

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

def expected_drain_sha(name, request):
    raw = h.control_bytes(h.runtime_directory() / f'{name}.handover.json')
    h.require(raw is not None, 'DRAIN_MISSING')
    h.require(json.loads(raw) == {'schema_version': 1, 'service': name, 'generation': 12,
        'request_id': request, 'phase': 'drain'}, 'DRAIN_DRIFT')
    return h.digest(raw)

def assert_reference_drained():
    diag = h.read_service_state('reference-worker').get('proof', {}).get('reference_runtime', {})
    h.require(diag.get('stage') == 'drained' and diag.get('notifications_alive') is False
        and diag.get('historical_refresh_alive') is False, 'REFERENCE_CLOSE_UNPROVEN')

def preflight_reference(state):
    diag = state.get('proof', {}).get('reference_runtime', {}) if state else {}
    counts = diag.get('blocked_counts')
    h.require(diag.get('stage') in {'scan', 'cycle'} and isinstance(counts, dict)
        and counts == {} and diag.get('blocked_count') == 0
        and diag.get('historical_refresh_alive') is True and diag.get('notifications_alive') is True
        and diag.get('historical_refresh_error') is None and diag.get('notifications_error') is None
        and not diag.get('failure_code'), 'OLD_REFERENCE_UNPROVEN')

def apply(plan):
    control_budget(plan)
    h.require(plan.get('plan_hash') == h.plan_hash(plan), 'PLAN_HASH_INVALID')
    c = plan['candidate']
    with h.deployment_lock():
        h.require(freeze(Path(c['root']), c['tag'], c['commit'], Path(plan['review_path']), plan['review_sha256']) == plan, 'PLAN_DRIFT')
        h.require(h.maintenance_available(), 'PRECONDITION_SOURCE_BUSY')
        old, new = registry(plan['old']), registry(plan['new'])
        attempt = {'phase': 'prepared', 'plan': plan, 'requests': {}, 'stopped': [], 'started': [], 'bootout_intents': [],
            'scheduled_loaded': [], 'calendar_intents': [], 'drain_sha256': {}, 'owners': {}, 'bootstrap_intents': [],
            'old_health_gate_evidence': _OLD_HEALTH_EVIDENCE}
        log(attempt, 'prepared')
        try:
            archive_prior(plan, attempt)
            for name in h.CONTINUOUS:
                h.require(control_sha(name) == plan['drains'][name], 'ORIGINAL_CONTROL_DRIFT')
                log(attempt, 'drain_' + name)
                attempt.setdefault('drain_started_at', monotonic())
                attempt['requests'][name] = h.request_drain(name, generation=12)
                attempt['drain_sha256'][name] = expected_drain_sha(name, attempt['requests'][name])
                log(attempt, 'drain_written_' + name)
            h.require(wait_parked(plan, 12, deadline=attempt.get('drain_started_at', monotonic()) + 10), 'OLD_DRAIN_TIMEOUT')
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
                        h.require(control and control.get('service') == name and control.get('generation') == 12
                            and control.get('phase') == 'drain' and
                            control.get('request_id') == attempt['requests'][name]
                            and control_sha(name) == attempt['drain_sha256'][name], 'DRAIN_DRIFT')
                    else:
                        h.require(control_sha(name) == plan['drains'][name], 'ORIGINAL_CONTROL_DRIFT')
                        h.require(s.calendar_output(binding) is not None and h.loaded_identity(binding, idle=True) is None,
                            'CALENDAR_IDLE_REQUIRED')
                assert_reference_drained()
                for name in h.SCHEDULED:
                    binding = old.services[name]
                    attempt.setdefault('old_calendar_intents', []).append(name)
                    log(attempt, 'stop_old_calendar_' + name)
                    h.launch('disable', f'gui/{os.getuid()}/{binding.label}')
                    if s.calendar_output(binding) is not None:
                        h.require(h.loaded_identity(binding, idle=True) is None, 'CALENDAR_RUNNING')
                        h.launch('bootout', f'gui/{os.getuid()}/{binding.label}')
                    h.confirm_weekly_absence(binding)
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
                    temporary = path.with_name(path.name + '.generation13')
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
                log(attempt, 'registry_generation13_cas')
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
            h.require(poll_cycles(new, attempt, evidence), 'HEALTHY_CYCLE_TIMEOUT')
            historical_protected(plan)
            for name in h.SCHEDULED:
                r.verify_schedule_state(new, name)
            h.require(poll_cycles(new, attempt, evidence), 'HEALTHY_CYCLE_TIMEOUT')
            h.require(heartbeat_gate(new)[0], 'HEARTBEAT_READBACK_UNPROVEN')
            attempt['cycle_evidence'] = evidence
            attempt['phase'] = 'generation13_ready_calendars_idle'
        except Exception as error:
            try:
                attempt['failure_typed_proof'] = capture_failure_proof()
            except Exception:
                attempt['failure_typed_proof'] = {'capture_code': 'FAILURE_PROOF_READ_UNKNOWN'}
            attempt['phase'] = 'outcome_unknown'
            attempt['failure_code'] = str(error) if isinstance(error, h.ResumeBlocked) else 'GENERATION13_OPERATION_UNKNOWN'
            try:
                if (not attempt['bootout_intents'] and not attempt.get('old_calendar_intents')
                        and h.read_bindings() == old):
                    try:
                        facts(plan)
                        h.require(h.bindings_sha256() == plan['registry_sha256'], 'REGISTRY_DRIFT')
                        for name, request in attempt['requests'].items():
                            h.require(h.loaded_identity(old.services[name]) == plan['owners'][name], 'OLD_PID_DRIFT')
                            control = h._read(h.runtime_directory() / f'{name}.handover.json')
                            h.require(control and control.get('service') == name and control.get('generation') == 12
                                and control.get('phase') == 'drain' and control.get('request_id') == request
                                and control_sha(name) == attempt['drain_sha256'][name], 'DRAIN_DRIFT')
                        for name, request in attempt['requests'].items():
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
            h.require(h.read_bindings() == new and state and state.get('generation') == 13
                and h.pid_string(state.get('pid')) == attempt['owners'].get(name)
                and h.loaded_identity(new.services[name]) == attempt['owners'][name]
                and state.get('phase') in {'active', 'parked'}
                and owner_process_matches(state, new.services[name]), 'CANDIDATE_OWNER_UNPROVEN')
            attempt.setdefault('halt_drain_intents', []).append(name)
            log(attempt, 'halt_drain_' + name)
            requested[name] = h.request_drain(name, generation=13)
            attempt['halt_requests'] = dict(requested)
            log(attempt, 'halt_drain_written_' + name)
        except Exception:
            failed.append(name)
    deadline, verified = monotonic() + 10, False
    while requested and monotonic() < deadline:
        try:
            h.require(h.read_bindings() == new, 'REGISTRY_DRIFT')
            if all((state := h.read_service_state(name)) and state.get('phase') == 'parked'
                and state.get('generation') == 13 and h.pid_string(state.get('pid')) == attempt['owners'][name]
                for name in requested):
                with ExitStack() as locks:
                    h.acquire_owner_locks(locks, services=tuple(requested))
                    h.require(h.read_bindings() == new, 'REGISTRY_DRIFT')
                    for name, request in requested.items():
                        state = h.read_service_state(name)
                        h.require(state and state.get('phase') == 'parked' and state.get('generation') == 13
                            and h.pid_string(state.get('pid')) == attempt['owners'][name]
                            and h.loaded_identity(new.services[name]) == attempt['owners'][name]
                            and owner_process_matches(state, new.services[name])
                            and h._read(h.runtime_directory() / f'{name}.handover.json') == {
                                'schema_version': 1, 'service': name, 'generation': 13,
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


def safe_code(value):
    return value if type(value) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}',value) else 'UNCLASSIFIED_FAILURE'

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

def retired_owner(name,state,new,attempt):
    if not (state and state.get('generation')==12 and h.pid_string(state.get('pid'))==attempt['plan']['owners'][name]):
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
        if not (state and state.get('generation')==13 and h.pid_string(state.get('pid'))==attempt['owners'][name]):
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

def await_cycles(new,plan,attempt,evidence,deadline,*,persist=True):
    from app.services.deployment_identity import deployment_identity_health
    from app.runtime_deployment import owner_process_matches
    # Expensive release/HTTP verification runs before the fresh sampling budget.
    begin=monotonic()
    rows=deployment_identity_health(root=Path(new.services['api'].root),commit=new.services['api'].commit).get('services',{})
    mapping={'live':'live_market','reference-worker':'reference_worker'}
    identity=all(owner_process_matches(h.read_service_state(name),new.services[name])
        and h.loaded_identity(new.services[name])==attempt['owners'][name]
        and rows.get(mapping.get(name,name),{}).get('status')=='matched' for name in h.CONTINUOUS)
    identity_seconds=monotonic()-begin;begin=monotonic();http=h.http_ready()
    attempt['health_preflight']={'identity':identity,'http':http,'identity_seconds':identity_seconds,
        'http_seconds':monotonic()-begin,'at':datetime.now(UTC).isoformat()}
    if persist:log(attempt,'health_preflight')
    h.require(identity,'DEPLOYMENT_IDENTITY_DRIFT');h.require(http,'HTTP_HEALTH_UNPROVEN')
    # A fresh 30s sample budget begins after the separately recorded heavy preflight.
    deadline = monotonic() + 30
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
    h.require(attempt.get('phase') == 'generation13_ready_calendars_idle'
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
                'GUIYI_RUNTIME_COMMIT': binding.commit, 'GUIYI_RUNTIME_GENERATION': '13',
                'GUIYI_RUNTIME_HANDOVER_ENABLED': '1', 'GUIYI_OBSERVATION_STREAM_ENABLED': '1'}.items())
            and payload.get('WorkingDirectory') == (str(Path.home()) if name in ('api', 'web') else binding.root),
            'PLIST_READBACK_DRIFT')
        if name in h.SCHEDULED:
            r.verify_schedule_state(new, name)
    for source, digest in plan['assets'].items():
        h.require(h.digest(h.snapshot(ROOT / '.run' / Path(source).name)) == digest, 'ASSET_READBACK_DRIFT')
    evidence = {}
    await_cycles(new, plan, attempt, evidence, monotonic() + 30, persist=False)
    return {'phase': 'GENERATION13_INDEPENDENT_READBACK', 'cycle_evidence': evidence,
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
        print(json.dumps({'status': 'GENERATION13_PLAN_FROZEN', 'plan_hash': plan['plan_hash'],
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
