"""Task-local one-use driver invariants; no production mutation or transport."""
import importlib.util
import json
import os
from pathlib import Path
import pytest

DRIVER = Path('/Volumes/扩展盘/guiyi-quant-workstation/output/newow-v1150-release-20261011/deploy_generation8.py')

@pytest.fixture
def driver():
    spec = importlib.util.spec_from_file_location('newow_gen8_test', DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secure_read_rejects_symlink_and_wrong_mode(driver, tmp_path):
    path = tmp_path / 'state'
    path.write_bytes(b'{}')
    os.chmod(path, 0o600)
    assert driver.secure_bytes(path) == b'{}'
    link = tmp_path / 'link'
    link.symlink_to(path)
    with pytest.raises(OSError):
        driver.secure_bytes(link)
    os.chmod(path, 0o644)
    with pytest.raises(driver.h.ResumeBlocked, match='PRIVATE_FILE_INVALID'):
        driver.secure_bytes(path)


def test_large_frozen_plan_readback(driver, tmp_path):
    path = tmp_path / 'plan'
    raw = b'x' * 1_500_000
    driver.write_exclusive(path, raw)
    assert driver.secure_bytes(path) == raw
    with pytest.raises(FileExistsError):
        driver.write_exclusive(path, b'replaced')
    assert driver.secure_bytes(path) == raw


def test_scope_unknown_never_infers_success_or_retries(driver, monkeypatch):
    monkeypatch.setattr(driver, 'current_attempt', lambda: {'scope_intent': True})
    monkeypatch.setattr(driver, 'core_readback', lambda *a, **kw: pytest.fail('must block before inference'))
    with pytest.raises(driver.h.ResumeBlocked, match='SCOPE_OUTCOME_READBACK_REQUIRED'):
        driver.scope_protected({'scope': {}})


def test_archive_retains_pending_exact_bytes(driver, tmp_path, monkeypatch):
    monkeypatch.setattr(driver.h, 'runtime_directory', lambda: tmp_path)
    raw = b'{"unknown":true,"pending":"original plan"}\n'
    journal = tmp_path / 'topology-old.json'
    driver.write_exclusive(journal, raw)
    monkeypatch.setattr(driver, 'log', lambda *_: None)
    attempt = {}
    driver.archive_prior({'journals': {journal.name: driver.h.digest(raw)}}, attempt)
    archive = tmp_path / ('reference-continuity-generation8.json.' + journal.name + '.bytes')
    assert driver.secure_bytes(archive) == driver.secure_bytes(journal) == raw
    assert attempt['prior_archives_proven'] is True


def test_bijection_rejects_old_open_identity_reuse(driver):
    from app.reference_trading.newow_scope_upgrade import FREQUENCIES, STRATEGIES
    products = [f'p{i}' for i in range(60)]
    mapping = []
    for p in products:
        for s in STRATEGIES:
            for f in FREQUENCIES:
                key = ':'.join((p, s, f))
                mapping.append({'route': [p,s,f], 'old': {'stream_id': 'old:'+key},
                    'new': {'target_stream_id': 'new:'+key, 'product':p,'strategy':s,'frequency':f}})
    core = {'products':products,'mapping':mapping}
    driver.validate_bijection(core)
    mapping[0]['new']['target_stream_id'] = mapping[0]['old']['stream_id']
    with pytest.raises(driver.h.ResumeBlocked, match='UPGRADE_BIJECTION_INVALID'):
        driver.validate_bijection(core)


def test_new_history_namespace_rejects_old_ids(driver, tmp_path, monkeypatch):
    monkeypatch.setattr(driver.h, 'runtime_directory', lambda: tmp_path)
    archive = tmp_path / 'old.bytes'
    driver.write_exclusive(archive, b'old pending facts')
    state = tmp_path / 'newow-historical-refresh-state.json'
    driver.write_exclusive(state, json.dumps({'version':'newow_historical_refresh_v1',
        'cursor':'','routes':{'old':{'status':'pending'}}}).encode())
    monkeypatch.setattr(driver, 'current_attempt', lambda: {'history_archive': str(archive),
        'drained_historical_preimage': {'sha256': driver.h.digest(b'old pending facts')}})
    plan = {'scope': {'expected_count':1,'mapping':[{'new':{'source':{'stream_id':'new-history'}}}]}}
    with pytest.raises(driver.h.ResumeBlocked, match='HISTORY_NEW_NAMESPACE_DRIFT'):
        driver.historical_protected(plan)


def test_full_publication_preserves_every_changed_blob(driver, monkeypatch):
    monkeypatch.setattr(driver.h, '_tracked', lambda p: {'formula':'old'} if str(p)=='old' else {'formula':'new','web':'blob'})
    assert driver.reviewed_changes(Path('old'),Path('new')) == {
        'formula':{'previous':'old','candidate':'new'},'web':{'previous':None,'candidate':'blob'}}


def exercise_actual_bootstrap_and_history_namespace(driver, monkeypatch, tmp_path, engine=None):
    from tests.reference_trading.test_newow_scope_upgrade import fixture
    from tests.reference_trading.test_newow_bootstrap import NOW
    import app.db.session as db_session
    factory, repo, service, plan, old, newplan = fixture(monkeypatch, engine)
    result = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW, clock=lambda: NOW)
    assert result['receipts'][0]['activation_plan_hash'] != newplan['plan_hash']
    monkeypatch.setattr(db_session, 'SessionLocal', factory)
    actual = driver.core_readback(plan, applied=True, receipts=result['receipts'])
    assert actual['new_enabled'] == actual['old_disabled'] == 1
    from copy import deepcopy
    wrong = deepcopy(result['receipts'])
    wrong[0]['activation_plan_hash'] = newplan['plan_hash']
    with pytest.raises(driver.h.ResumeBlocked, match='NEW_ACTIVATION_RECEIPT_DRIFT'):
        driver.core_readback(plan, applied=True, receipts=wrong)
    import app.market_data.operational_universe as universe
    import app.reference_trading.newow_bootstrap as bootstrap
    from app.reference_trading.historical_refresh import build_historical_refresh
    monkeypatch.setattr(universe, 'load_operational_products', lambda: ('rb',))
    monkeypatch.setattr(universe, 'load_active_products', lambda: ('rb',))
    monkeypatch.setattr(bootstrap, 'validate_product_scope', lambda a, b: tuple(a))
    state_path = tmp_path / 'newow-historical-refresh-state.json'
    worker = build_historical_refresh(factory, state_path=state_path)
    routes = worker._routes()
    assert len(routes) == 1
    historical_id = routes[0].identity.stream_id
    assert historical_id == newplan['source']['stream_id']
    assert historical_id != newplan['target_stream_id']
    # Actual worker-derived historical stream identity, not a hand-written forward ID.
    driver.write_exclusive(state_path, json.dumps({'version':'newow_historical_refresh_v1',
        'cursor':historical_id, 'routes':{historical_id:{'status':'pending'}}}).encode())
    archive = tmp_path / 'old.bytes'
    driver.write_exclusive(archive, b'old pending plan retained')
    monkeypatch.setattr(driver.h, 'runtime_directory', lambda: tmp_path)
    monkeypatch.setattr(driver, 'current_attempt', lambda: {'history_archive':str(archive),
        'drained_historical_preimage':{'sha256':driver.h.digest(b'old pending plan retained')}})
    driver.historical_protected({'scope':plan})


def test_actual_bootstrap_receipts_and_history_namespace(driver, monkeypatch, tmp_path):
    exercise_actual_bootstrap_and_history_namespace(driver, monkeypatch, tmp_path)


from tests.alembic.conftest import isolated_postgres_engine

@pytest.mark.isolated_postgresql
def test_postgresql_actual_bootstrap_driver_readback_and_history_namespace(
    driver, isolated_postgres_engine, monkeypatch, tmp_path,
):
    from uuid import uuid4
    engine = isolated_postgres_engine
    schema = 'newow_driver_' + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = engine.execution_options(schema_translate_map={None:schema})
    try:
        exercise_actual_bootstrap_and_history_namespace(driver, monkeypatch, tmp_path, scoped)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
