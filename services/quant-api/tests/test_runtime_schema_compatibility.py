from copy import deepcopy
from hashlib import sha256

import pytest

from app.runtime_schema_compatibility import (
    ADDITION, ADDITION_BLOB, PARENT, POLICY, SchemaCompatibilityError,
    prove_reference_inbox_addition, validate_transition_proof,
)


def files():
    old = {PARENT: "1" * 40, "services/quant-api/app/db/base.py": "2" * 40}
    return old, {**old, ADDITION: ADDITION_BLOB}


def installed():
    return {"policy": POLICY, "revision": "20261026_0053", "schema_sha256": "a" * 64,
            "database_identity_sha256": "b" * 64}


def prove(old=None, new=None, **kwargs):
    source, target = files()
    return prove_reference_inbox_addition(old or source, new or target, old_heads=("20261015_0052",),
                                           new_heads=("20261026_0053",), installed=installed(), **kwargs)


def test_exact_addition_freezes_old_new_db_and_installed_schema_proof():
    proof = prove()
    assert proof["added_path"] == ADDITION
    assert proof["installed"] == installed()
    validate_transition_proof(proof, old_db=proof["old_db"], new_db=proof["new_db"])


@pytest.mark.parametrize("change", ("extra", "edit", "delete", "wrong0053"))
def test_any_other_db_contract_change_is_rejected(change):
    old, new = files()
    if change == "extra":
        new["services/quant-api/alembic/versions/20261027_0054_other.py"] = "3" * 40
    elif change == "edit":
        new[PARENT] = "3" * 40
    elif change == "delete":
        del new["services/quant-api/app/db/base.py"]
    else:
        new[ADDITION] = "3" * 40
    with pytest.raises(SchemaCompatibilityError):
        prove(old, new)


def test_unknown_head_or_missing_actual_schema_rejected():
    old, new = files()
    for head in ("20261009_0051", "20261027_0054"):
        with pytest.raises(SchemaCompatibilityError):
            prove_reference_inbox_addition(old, new, old_heads=(head,), new_heads=("20261026_0053",), installed=installed())
    with pytest.raises(SchemaCompatibilityError):
        prove_reference_inbox_addition(old, new, old_heads=("20261015_0052",), new_heads=("20261026_0053",), installed={})


def test_tampered_or_wrong_contract_proof_rejected():
    proof = prove()
    tampered = deepcopy(proof)
    tampered["installed"]["schema_sha256"] = sha256(b"tampered").hexdigest()
    with pytest.raises(SchemaCompatibilityError):
        validate_transition_proof(tampered, old_db=proof["old_db"], new_db=proof["new_db"])
    with pytest.raises(SchemaCompatibilityError):
        validate_transition_proof(proof, old_db="c" * 64, new_db=proof["new_db"])


from tests.alembic.conftest import isolated_postgres_engine  # noqa: E402,F401


@pytest.fixture
def installed_inbox_database(isolated_postgres_engine):  # noqa: F811
    from sqlalchemy import create_engine, Table, Column, String, MetaData
    from app.db.base import Base
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from tests.alembic.test_reference_forward_migration import _migration
    from uuid import uuid4
    schema = "cohort_inbox_" + uuid4().hex
    with isolated_postgres_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = isolated_postgres_engine.execution_options(schema_translate_map={None: schema})
    engine = None
    try:
        Base.metadata.create_all(scoped, tables=[table for table in Base.metadata.sorted_tables
                                                if not table.name.startswith("reference_inbox_")])
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            migration = _migration("20261026_0053_reference_inbox.py")
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
        version = Table("alembic_version", MetaData(), Column("version_num", String(32), primary_key=True), schema=schema)
        version.create(isolated_postgres_engine)
        with isolated_postgres_engine.begin() as connection:
            connection.execute(version.insert().values(version_num="20261026_0053"))
        engine = create_engine(isolated_postgres_engine.url, connect_args={"options": "-csearch_path=" + schema})
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.mark.isolated_postgresql
def test_actual_0053_schema_is_verified_readonly_and_bound_to_file_proof(installed_inbox_database):
    from sqlalchemy.orm import Session
    from app.runtime_schema_compatibility import verify_installed_reference_inbox
    with Session(installed_inbox_database) as session:
        evidence = verify_installed_reference_inbox(session)
        assert not session.in_transaction()
        assert evidence["revision"] == "20261026_0053"
    old, new = files()
    proof = prove_reference_inbox_addition(old, new, old_heads=("20261015_0052",),
                                           new_heads=("20261026_0053",), installed=evidence)
    validate_transition_proof(proof, old_db=proof["old_db"], new_db=proof["new_db"])


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("drift", ("head", "column", "check", "trigger", "function"))
def test_schema_or_immutability_drift_is_rejected(installed_inbox_database, drift):
    from sqlalchemy.orm import Session
    from app.runtime_schema_compatibility import verify_installed_reference_inbox
    statements = {
        "head": "UPDATE alembic_version SET version_num='20261015_0052'",
        "column": "ALTER TABLE reference_inbox_inputs ADD COLUMN unexpected text",
        "check": "ALTER TABLE reference_inbox_inputs DROP CONSTRAINT ck_reference_inbox_input_size",
        "trigger": "ALTER TABLE reference_inbox_inputs DISABLE TRIGGER reference_inbox_immutable",
        "function": "CREATE OR REPLACE FUNCTION reference_inbox_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$",
    }
    with installed_inbox_database.begin() as connection:
        connection.exec_driver_sql(statements[drift])
    with Session(installed_inbox_database) as session, pytest.raises(SchemaCompatibilityError):
        verify_installed_reference_inbox(session)


def test_tracked_db_contract_uses_full_preserved_graph_and_known_migration(monkeypatch):
    from pathlib import Path
    from app import runtime_bindings
    from app.runtime_schema_compatibility import tracked_db_contract
    source, target = files()
    monkeypatch.setattr(runtime_bindings, "_tracked", lambda root: target)
    sources = {PARENT: "revision='20261015_0052'\ndown_revision=None\n",
               ADDITION: "revision='20261026_0053'\ndown_revision='20261015_0052'\n"}
    monkeypatch.setattr(runtime_bindings, "_git", lambda root, *args: sources[args[-1].removeprefix("HEAD:")])
    frozen, heads = tracked_db_contract(Path("/unused"))
    assert heads == ("20261026_0053",)
    assert frozen == target
    sources[ADDITION] = "revision='20261026_0053'\ndown_revision='20261001_UNKNOWN'\n"
    with pytest.raises(SchemaCompatibilityError):
        tracked_db_contract(Path("/unused"))


@pytest.mark.isolated_postgresql
def test_native_host_freezes_actual_installed_schema_and_rejects_later_drift(installed_inbox_database, monkeypatch, tmp_path):
    from dataclasses import asdict
    from sqlalchemy.orm import Session
    from app.runtime_cohort_host import CohortHost
    from app.runtime_cohort import CohortError
    from app.runtime_bindings import BindingRegistry, ServiceBinding, CONTRACTS
    from app import runtime_schema_compatibility as module
    from app.db import session as database_module
    old_files, new_files = files()
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    monkeypatch.setattr(module, "tracked_db_contract", lambda root: (old_files, ("20261015_0052",)) if root == old_root
                        else (new_files, ("20261026_0053",)))
    monkeypatch.setattr(database_module, "SessionLocal", lambda: Session(installed_inbox_database))
    old_binding = ServiceBinding("api", str(old_root), "v1.16.10", "a" * 40, 30, True,
                                 {key: module.digest(old_files) if key == "db" else "b" * 64 for key in CONTRACTS})
    new_binding = ServiceBinding("api", str(new_root), "v1.16.11", "c" * 40, 31, True,
                                 {key: module.digest(new_files) if key == "db" else "b" * 64 for key in CONTRACTS})
    old, new = BindingRegistry(1, {"api": old_binding}), BindingRegistry(1, {"api": new_binding})
    host = object.__new__(CohortHost)
    proof = host.schema_compatibility(old, new)
    plan = {"old": asdict(old), "new": asdict(new), "schema_compatibility": proof}
    host.check_schema_compatibility(plan)
    with installed_inbox_database.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE reference_inbox_deliveries DISABLE TRIGGER reference_inbox_immutable")
    with pytest.raises(CohortError):
        host.check_schema_compatibility(plan)


def test_real_preserved_baseline_migration_graph_includes_annotated_revisions(monkeypatch):
    from pathlib import Path
    from app import runtime_bindings
    from app.runtime_schema_compatibility import tracked_db_contract
    root = Path(__file__).resolve().parents[3]
    baseline = "6ca3c3cc337421b30487cb050b814fef0ee28fda"
    git = runtime_bindings._git
    source = {line.split("\t", 1)[1]: line.split()[2]
              for line in git(root, "ls-tree", "-r", baseline).splitlines()}
    monkeypatch.setattr(runtime_bindings, "_tracked", lambda candidate: source)
    monkeypatch.setattr(runtime_bindings, "_git", lambda candidate, *args:
                        git(candidate, *tuple(baseline + arg[4:] if arg.startswith("HEAD:") else arg for arg in args)))
    frozen, heads = tracked_db_contract(root)
    assert PARENT in frozen
    assert ADDITION not in frozen
    assert heads == ("20261015_0052",)


@pytest.mark.parametrize("source", ("revision: str = '0052'\nrevision = '0052'\ndown_revision=None",
                                      "revision: str = 123\ndown_revision=None",
                                      "revision: str = '0052'\ndown_revision = {'not': 'parent'}"))
def test_duplicate_or_nonliteral_invalid_revision_metadata_is_rejected(monkeypatch, source):
    from pathlib import Path
    from app import runtime_bindings
    from app.runtime_schema_compatibility import tracked_db_contract
    monkeypatch.setattr(runtime_bindings, "_tracked", lambda root: {PARENT: "1" * 40})
    monkeypatch.setattr(runtime_bindings, "_git", lambda *args: source)
    with pytest.raises(SchemaCompatibilityError):
        tracked_db_contract(Path("/unused"))


def test_0054_transition_preserves_0053_and_requires_its_own_installed_proof():
    from app.runtime_schema_compatibility import RECOVERY_ADDITION, RECOVERY_BLOB, RECOVERY_POLICY
    old={PARENT:'1'*40, ADDITION:ADDITION_BLOB}
    new={**old,RECOVERY_ADDITION:RECOVERY_BLOB}
    evidence={'policy':RECOVERY_POLICY,'revision':'20261028_0054','schema_sha256':'a'*64,
              'database_identity_sha256':'b'*64}
    proof=prove_reference_inbox_addition(old,new,old_heads=('20261026_0053',),new_heads=('20261028_0054',),installed=evidence)
    validate_transition_proof(proof,old_db=proof['old_db'],new_db=proof['new_db'])
    with pytest.raises(SchemaCompatibilityError):
        prove_reference_inbox_addition(old,{**new,ADDITION:'3'*40},old_heads=('20261026_0053',),new_heads=('20261028_0054',),installed=evidence)
    with pytest.raises(SchemaCompatibilityError):
        prove_reference_inbox_addition(old,new,old_heads=('20261026_0053',),new_heads=('20261028_0054',),installed=installed())


@pytest.fixture
def installed_recovery_database(installed_inbox_database):
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    from tests.alembic.test_reference_forward_migration import _migration
    from sqlalchemy import text
    with installed_inbox_database.begin() as connection:
        migration=_migration('20261028_0054_reference_inbox_recovery.py')
        migration.op=Operations(MigrationContext.configure(connection));migration.upgrade()
        connection.execute(text("UPDATE alembic_version SET version_num='20261028_0054'"))
    return installed_inbox_database


@pytest.mark.isolated_postgresql
def test_actual_0054_schema_and_old_immutability_are_verified(installed_recovery_database, monkeypatch):
    from sqlalchemy.orm import Session
    from app.runtime_schema_compatibility import verify_installed_reference_inbox
    with Session(installed_recovery_database) as db:
        proof=verify_installed_reference_inbox(db)
        assert proof['revision']=='20261028_0054'
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).parent/"reference_trading"))
    from reference_trading.test_inbox_recovery import fixture
    from app.reference_trading.models import ReferenceInboxDelivery
    factory,inbox,recovery,plan,evaluate=fixture(installed_recovery_database)
    recovery.apply(plan,expected_plan_hash=plan.plan_hash,evaluator=evaluate)
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    for statement in ["UPDATE reference_inbox_deliveries SET status='PENDING' WHERE status='BLOCKED'",
                      'UPDATE reference_inbox_recovery_results SET proof_sha256=proof_sha256',
                      'DELETE FROM reference_inbox_recovery_results']:
        with pytest.raises(DBAPIError):
            with installed_recovery_database.begin() as connection:connection.execute(text(statement))
    assert inbox.next_heads()==()


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize('drift',['trigger','column','check'])
def test_0054_result_schema_drift_is_rejected(installed_recovery_database,drift):
    from sqlalchemy.orm import Session
    from app.runtime_schema_compatibility import verify_installed_reference_inbox
    changes={'trigger':'ALTER TABLE reference_inbox_recovery_results DISABLE TRIGGER reference_inbox_recovery_immutable',
             'column':'ALTER TABLE reference_inbox_recovery_results ADD COLUMN unexpected text',
             'check':'ALTER TABLE reference_inbox_recovery_results DROP CONSTRAINT ck_reference_inbox_recovery_progress'}
    with installed_recovery_database.begin() as connection:connection.exec_driver_sql(changes[drift])
    with Session(installed_recovery_database) as db,pytest.raises(SchemaCompatibilityError):verify_installed_reference_inbox(db)


@pytest.mark.isolated_postgresql
def test_postgresql_gap_bridge_retains_original_routes(installed_recovery_database,monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).parent/'reference_trading'))
    from reference_trading.test_inbox_recovery import _exercise_one_gap_bridge
    _exercise_one_gap_bridge(installed_recovery_database)


@pytest.mark.isolated_postgresql
def test_postgresql_concurrent_recovery_claims_compute_at_most_once(installed_recovery_database,monkeypatch):
    from pathlib import Path
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    monkeypatch.syspath_prepend(str(Path(__file__).parent/'reference_trading'))
    from reference_trading.test_inbox_recovery import fixture
    factory,inbox,recovery,plan,evaluate=fixture(installed_recovery_database)
    lock=Lock();calls=[]
    def counted(*args):
        with lock:calls.append(1)
        return evaluate(*args)
    def run():
        try:return ('ok',recovery.apply(plan,expected_plan_hash=plan.plan_hash,evaluator=counted))
        except ValueError as error:return ('rejected',str(error))
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
    assert any(x[0]=='ok' for x in results)
    assert len(calls)==1 and inbox.health()['recovered_calculation_count']==1
