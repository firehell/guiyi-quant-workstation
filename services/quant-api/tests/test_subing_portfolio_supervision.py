"""The active boundary never creates old runs or hides missing authority facts."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.subing_portfolio_journal import PortfolioJournal, source_hashes, KIND
from app.subing_portfolio_worker import require_active_scope, registered_facts
from app.subing_portfolio_supervision import refresh_facts
from guiyi_quant.subing_one_lot import PORTFOLIO_PRODUCTS, EXPANDED_PORTFOLIO_PRODUCTS, portfolio_policy
from test_subing_portfolio_journal import MemoryStore, inputs


def test_only_sixteen_can_be_initialized_and_history_fourteen_still_replays():
    now = datetime.now(UTC)
    store = MemoryStore()
    with pytest.raises(ValueError, match='ACTIVE_SCOPE_RETIRED'):
        PortfolioJournal.create(store, 'old', now, products=PORTFOLIO_PRODUCTS)
    assert store.record is None
    identity = dict(kind=KIND, policy=portfolio_policy(PORTFOLIO_PRODUCTS),
        started_at=now.isoformat(), code_hashes=source_hashes())
    old = PortfolioJournal(store, 'historical14', identity)
    store.create(old.run_id, identity, old.projection())
    before = deepcopy(store.record)
    assert PortfolioJournal.restore(store, old.run_id).products == PORTFOLIO_PRODUCTS
    with pytest.raises(ValueError, match='ACTIVE_SCOPE_RETIRED'):
        require_active_scope(old.products)
    assert store.record == before


def test_missing_facts_does_not_initialize(tmp_path):
    with pytest.raises(ValueError, match='EXECUTION_FACTS_MISSING_JM'):
        registered_facts(tmp_path, datetime.now(UTC).date(), {'jm': {'contract': 'JM2701'}}, datetime.now(UTC))
    assert list(tmp_path.iterdir()) == []


def test_old_model_http_is_gone_without_reading_state(monkeypatch):
    from app.api.subing_model import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/api/v1/subing-model/status').status_code == 410
        assert client.get('/api/v1/subing-model/accounts').status_code == 410


def test_old_worker_entrypoints_cannot_create_or_restore(monkeypatch):
    from app import subing_model_service
    from app.subing_model import worker
    for entry in (subing_model_service.main, worker.main):
        with pytest.raises(SystemExit, match='RETIRED'):
            entry()


def test_unknown_capture_attempt_is_never_retried(tmp_path, monkeypatch):
    import app.subing_portfolio_supervision as service
    now = datetime(2026, 11, 19, 1, 2, tzinfo=UTC)
    day = now.date()
    contexts = {p: dict(contract=p.upper()+'2701', first_open=(now-timedelta(minutes=2)).isoformat(),
        day_end=(now+timedelta(hours=5)).isoformat()) for p in EXPANDED_PORTFOLIO_PRODUCTS}
    for product in EXPANDED_PORTFOLIO_PRODUCTS:
        target = tmp_path / 'attempts' / f'{day}-{product}-0'
        target.mkdir(parents=True)
        (target / 'intent.json').write_text('{}')
    monkeypatch.setattr(service.subprocess, 'run', lambda *a, **k: pytest.fail('unknown provider attempt retried'))
    refresh_facts(tmp_path, day, contexts, now)
    assert not list(tmp_path.glob('*.json'))


def test_day_boundary_preserves_cash_and_rejects_skipped_day():
    contexts, batches = inputs()
    store = MemoryStore()
    journal = PortfolioJournal.create(store, 'shared', batches[0][1]-timedelta(minutes=1))
    journal.submit(*batches[0], contexts=contexts)
    original = journal.projection()
    restored = PortfolioJournal.restore(store, 'shared')
    assert restored.projection() == original
    # Open/pending positions and risk budget cannot be reset by day advancement.
    tomorrow = batches[0][0]+timedelta(days=1)
    changed = deepcopy(contexts)
    with pytest.raises(ValueError, match='DAY_CONTINUITY_UNPROVEN'):
        restored._next_minute(tomorrow, changed)
    assert restored.projection() == original


def test_losing_singleton_cannot_load_or_overwrite_owner_status(monkeypatch, tmp_path):
    import app.subing_portfolio_worker as worker
    from contextlib import nullcontext
    now = datetime.now(UTC)
    disposed = []
    monkeypatch.setattr(worker, 'STATE_ROOT', tmp_path)
    engine = SimpleNamespace(dispose=lambda: disposed.append('sql'))
    connection = SimpleNamespace(scalar=lambda statement: False)
    model_engine = SimpleNamespace(connect=lambda: nullcontext(connection), dispose=lambda: disposed.append('model'))
    monkeypatch.setattr(worker, 'settings_and_redis', lambda: ({'DATABASE_URL': 'unused'}, SimpleNamespace(close=lambda:None)))
    monkeypatch.setattr(worker, 'normalize_database_url', lambda value: value)
    monkeypatch.setattr(worker, 'create_engine', lambda *a, **k: engine)
    monkeypatch.setattr(worker, 'ObservationStream', lambda *a, **k: None)
    monkeypatch.setattr(worker, 'read_private_settings_content', lambda *a: b'private-url')
    monkeypatch.setattr(worker, 'ModelStore', lambda *a: SimpleNamespace(engine=model_engine))
    monkeypatch.setattr(worker, 'read_registration', lambda *a: pytest.fail('losing owner read registration'))
    monkeypatch.setattr(worker, 'atomic', lambda *a: pytest.fail('losing owner overwrote heartbeat'))
    monkeypatch.setattr('sys.argv', ['worker', '--day', str(now.date()), '--start', '16', '--once'])
    with pytest.raises(SystemExit, match='WORKER_ALREADY_RUNNING'):
        worker.main()
    assert set(disposed) == {'model', 'sql'}


def test_readonly_preflight_never_creates_model_store(monkeypatch, tmp_path):
    import app.subing_portfolio_worker as worker
    now = datetime.now(UTC)
    monkeypatch.setattr(worker, 'settings_and_redis', lambda: ({'DATABASE_URL': 'unused'}, SimpleNamespace(close=lambda:None)))
    monkeypatch.setattr(worker, 'normalize_database_url', lambda value: value)
    monkeypatch.setattr(worker, 'create_engine', lambda *a, **k: SimpleNamespace(dispose=lambda:None))
    monkeypatch.setattr(worker, 'ObservationStream', lambda *a, **k: None)
    monkeypatch.setattr(worker, 'prepare_day', lambda *a: ({'jm': {'contract': 'JM2701'}}, {}))
    monkeypatch.setattr(worker, 'preflight_prefix', lambda *a: {})
    monkeypatch.setattr(worker, 'ModelStore', lambda *a: pytest.fail('preflight created DB owner'))
    monkeypatch.setattr(worker, 'atomic', lambda *a: pytest.fail('preflight wrote state'))
    monkeypatch.setattr('sys.argv', ['worker', '--check', '16', '--day', str(now.date()), '--facts-registry', str(tmp_path)])
    with pytest.raises(SystemExit, match='EXECUTION_FACTS_MISSING_JM'):
        worker.main()
    assert list(tmp_path.iterdir()) == []


def test_lost_registration_recovers_original_shared_run_without_new_equity():
    from app.subing_portfolio_worker import recover_registration
    from contextlib import nullcontext
    def store_with(rows):
        connection = SimpleNamespace(execute=lambda query: SimpleNamespace(all=lambda: rows))
        return SimpleNamespace(engine=SimpleNamespace(connect=lambda:nullcontext(connection)))
    old = ('historical14', {'policy': portfolio_policy(PORTFOLIO_PRODUCTS)})
    shared = ('original16', {'policy': portfolio_policy(EXPANDED_PORTFOLIO_PRODUCTS)})
    assert recover_registration(store_with([old])) is None
    assert recover_registration(store_with([old, shared])) == {'run_id': 'original16'}
    with pytest.raises(ValueError, match='SHARED_OWNER_AMBIGUOUS'):
        recover_registration(store_with([shared, ('duplicate16', shared[1])]))


def test_current_facts_reject_retrospective_and_malformed_before_opening(monkeypatch, tmp_path):
    import app.subing_portfolio_worker as worker
    from scripts.research.subing_model_facts import CAPTURE_VERSION, FEE_POLICY
    contexts, batches = inputs()
    day, at, now, prepared = batches[0]
    context = contexts['jm']
    body = deepcopy(prepared['jm'].execution_facts)
    contract = context['contract']
    body.update(capture_version=CAPTURE_VERSION, time_semantics='current_effective_execution_facts',
        fee_policy_version=FEE_POLICY, fee_assumption=dict(assumed=False, source_day=str(day),
        target_day=str(day), contract=contract))
    body['contracts'][contract].update(start=str(day), end=str(day),
        field_sources={'snapshot_at': body['captured_at']})
    monkeypatch.setattr(worker, 'facts_for', lambda *a: body)
    observations = {(at, 'jm', '1m'): prepared['jm'].envelope}
    assert worker.registered_facts(tmp_path, day, {'jm':context}, now, observations=observations)['jm'] == body
    body['time_semantics'] = 'retrospective'
    with pytest.raises(ValueError, match='CURRENT_FACTS_INVALID_JM'):
        worker.registered_facts(tmp_path, day, {'jm':context}, now, observations=observations)
    body['contracts'][contract] = {}
    with pytest.raises(ValueError, match='CURRENT_FACTS_INVALID_JM'):
        worker.registered_facts(tmp_path, day, {'jm':context}, now, observations=observations)


def test_night_minute_does_not_require_nontrading_day_product_facts(monkeypatch, tmp_path):
    import app.subing_portfolio_worker as worker
    contexts, batches = inputs()
    day, at, now, prepared = batches[0]
    calls = []
    class Clock:
        @staticmethod
        def now(tz): return now
    monkeypatch.setattr(worker, 'datetime', Clock)
    for product, context in contexts.items():
        context['expected_1m'] = [at.isoformat()] if product == 'jm' else [(at+timedelta(hours=8)).isoformat()]
        context['expected_30m'] = []
        context['expected_60m'] = []
    monkeypatch.setattr(worker, 'read_completed', lambda *a: ({(at,'jm','1m'):prepared['jm'].envelope}, '1-0'))
    monkeypatch.setattr(worker, 'refresh_facts', lambda registry, day, scope, now: calls.append(('capture',set(scope))))
    def facts(registry, day, scope, now, **kwargs):
        calls.append(('validate',set(scope)))
        return {'jm': prepared['jm'].execution_facts}
    monkeypatch.setattr(worker, 'registered_facts', facts)
    monkeypatch.setattr(worker, 'atomic', lambda *a: None)
    journal = SimpleNamespace(portfolio=SimpleNamespace(last_at=None), started_at=at-timedelta(minutes=1),
        day=None, run_id='shared', submit=lambda *a, **k:calls.append(('submit',set(a[3]))))
    factor = SimpleNamespace(observation=lambda *a:{}, structure_point={}, hourly={}, frame={'regime':'UNKNOWN'})
    worker.consume_day(journal, day, contexts, {'jm':factor}, None, tmp_path, once=True, refresh=True)
    assert calls == [('capture',{'jm'}), ('validate',{'jm'}), ('submit',{'jm'})]


def test_process_singleton_survives_database_backend_loss(monkeypatch, tmp_path):
    import app.subing_portfolio_worker as worker
    import fcntl
    monkeypatch.setattr(worker, 'STATE_ROOT', tmp_path)
    monkeypatch.setattr(worker, 'settings_and_redis', lambda: ({'DATABASE_URL':'unused'}, SimpleNamespace(close=lambda:None)))
    monkeypatch.setattr(worker, 'normalize_database_url', lambda value:value)
    monkeypatch.setattr(worker, 'create_engine', lambda *a, **k: SimpleNamespace(dispose=lambda:None))
    monkeypatch.setattr(worker, 'ObservationStream', lambda *a, **k:None)
    monkeypatch.setattr(worker, 'ModelStore', lambda *a:pytest.fail('second owner reached DB after backend lock was lost'))
    monkeypatch.setattr(worker, 'atomic', lambda *a:pytest.fail('second owner wrote heartbeat'))
    monkeypatch.setattr('sys.argv', ['worker','--day','2026-11-19','--start','16'])
    # No PostgreSQL lock exists here: the process lock alone must exclude owner 2.
    with (tmp_path/'owner.lock').open('w') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit, match='WORKER_ALREADY_RUNNING'):
            worker.main()


def test_first_owner_waits_for_all_product_sessions_without_warmup_or_run(monkeypatch, tmp_path):
    import app.subing_portfolio_worker as worker
    from contextlib import nullcontext
    now = datetime.now(UTC)
    open_at = now + timedelta(hours=1)
    contexts = {p:{'first_open':open_at.isoformat()} for p in EXPANDED_PORTFOLIO_PRODUCTS}
    calls = []
    monkeypatch.setattr(worker, 'STATE_ROOT', tmp_path)
    monkeypatch.setattr(worker, 'settings_and_redis', lambda: ({'DATABASE_URL':'unused'}, SimpleNamespace(close=lambda:None)))
    monkeypatch.setattr(worker, 'normalize_database_url', lambda value:value)
    monkeypatch.setattr(worker, 'create_engine', lambda *a, **k:SimpleNamespace(dispose=lambda:None))
    monkeypatch.setattr(worker, 'ObservationStream', lambda *a, **k:None)
    monkeypatch.setattr(worker, 'read_private_settings_content', lambda *a:b'private')
    owner = SimpleNamespace(scalar=lambda *a:True)
    engine = SimpleNamespace(connect=lambda:nullcontext(owner), dispose=lambda:None)
    monkeypatch.setattr(worker, 'ModelStore', lambda *a:SimpleNamespace(engine=engine))
    monkeypatch.setattr(worker, 'read_registration', lambda *a:None)
    monkeypatch.setattr(worker, 'recover_registration', lambda *a:None)
    monkeypatch.setattr(worker, 'trading_day', lambda *a:(now.date(),open_at))
    def prepare(*args, warmup=True):
        assert warmup is False
        calls.append('light_context')
        return contexts, {}
    monkeypatch.setattr(worker, 'prepare_day', prepare)
    monkeypatch.setattr(worker, 'atomic', lambda path,value:calls.append(value['status']))
    monkeypatch.setattr(worker.PortfolioJournal, 'create', lambda *a, **k:pytest.fail('opened run without current facts'))
    monkeypatch.setattr('sys.argv', ['worker','--start','16','--once'])
    worker.main()
    assert calls == ['WARMING_UP','light_context','WAITING_EXECUTION_FACTS']


def test_day_only_open_holding_keeps_asof_and_pauses_risk_until_real_day_mark():
    day = datetime.now(UTC).date()
    now = datetime.now(UTC)
    old_mark = SimpleNamespace(bar=SimpleNamespace(trading_day=day-timedelta(days=1)))
    def holding():
        return SimpleNamespace(layers={'base':1}, model=SimpleNamespace(pending=None), pending_known_at=None)
    accounts = {'JM2701':holding(), 'LC2701':holding(), 'FLAT2701':SimpleNamespace(layers={})}
    portfolio = SimpleNamespace(accounts=accounts, marks={'JM2701':old_mark, 'LC2701':old_mark}, unproven_marks=set())
    journal = object.__new__(PortfolioJournal)
    journal.portfolio = portfolio
    journal.contexts = {'jm':{'contract':'JM2701'}, 'lc':{'contract':'LC2701'}}
    raw = {'execution_facts':{'captured_at':now.isoformat()}}
    journal.apply_current_knowledge({'jm':raw}, day, now)
    assert portfolio.unproven_marks == {'LC2701'}
    assert portfolio.marks['LC2701'] is old_mark
    portfolio.marks['JM2701'] = SimpleNamespace(bar=SimpleNamespace(trading_day=day))
    journal.apply_current_knowledge({'lc':raw}, day, now)
    assert portfolio.unproven_marks == set()
