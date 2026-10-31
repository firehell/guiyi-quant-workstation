"""Real PostgreSQL transactions and deployed Inbox immutability, isolated only."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError

from app.db.base import Base
from app.db.migration_test_guard import (
    require_isolated_migration_database_url,
    probe_database_identity,
)
from app.reference_trading.models import (
    ReferenceBatch,
    ReferenceInboxInput,
    ReferenceInboxDelivery,
    ReferenceActivationReceipt,
    ReferenceRevision,
)
from app.reference_trading.repository import RepositoryConflict
from app.reference_trading.inbox import ReferenceInboxRepository
from app.reference_trading.inbox_recovery import verified_resolution_ids
from tests.alembic.test_reference_forward_migration import _migration
from tests.reference_trading.test_htdy_conflict_recovery import (
    conflict_setup,
    _inbox,
    NOW,
)

pytestmark = pytest.mark.isolated_postgresql


@pytest.fixture
def pg_setup(request):
    import os
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    if not os.environ.get("GUIYI_ISOLATED_MIGRATION_DATABASE_URL"):
        pytest.skip("GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required")
    target = require_isolated_migration_database_url(
        os.environ, identity_probe=probe_database_identity
    )
    admin = create_engine(target)
    schema = "htdy_conflict_" + uuid4().hex
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(target, connect_args={"options": "-csearch_path=" + schema})
    try:
        inbox_names = {
            "reference_inbox_inputs",
            "reference_inbox_deliveries",
            "reference_inbox_recovery_results",
        }
        Base.metadata.create_all(
            engine,
            tables=[
                t for t in Base.metadata.sorted_tables if t.name not in inbox_names
            ],
        )
        with engine.begin() as connection:
            for name in [
                "20261026_0053_reference_inbox.py",
                "20261028_0054_reference_inbox_recovery.py",
            ]:
                migration = _migration(name)
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
        yield conflict_setup(engine, products=getattr(request, "param", None))
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def plan(recovery, ids):
    return recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )


def test_real_atomic48_preserves_original_triggers_and_exact_terminal_closure(pg_setup):
    factory, recovery, ids = pg_setup
    delivery = _inbox(factory)
    before = ReferenceInboxRepository(factory).health()
    frozen = plan(recovery, ids)
    result = recovery.apply(frozen, expected_plan_hash=frozen["plan_hash"], now=NOW)
    assert len(result) == 48 and recovery.readback(frozen) == result
    after = ReferenceInboxRepository(factory).health()
    assert after["unfinished_deliveries"] == 0
    assert after["completed_count"] == before["completed_count"] == 0
    assert after["last_calculated_at"] is before["last_calculated_at"] is None
    with factory() as db:
        assert delivery in verified_resolution_ids(db)
        row = db.get(ReferenceInboxDelivery, delivery)
        assert row.status == "PENDING" and row.calculation_batch_id is None
        original = db.get(ReferenceInboxInput, row.input_id)
        identifier = original.input_id
    with pytest.raises(DBAPIError):
        with factory() as db, db.begin():
            db.get(ReferenceInboxInput, identifier).canonical_envelope = "tampered"
    with factory() as db:
        assert delivery in verified_resolution_ids(db)


def test_real_source_drift_rolls_back_entire_scope(pg_setup):
    factory, recovery, ids = pg_setup
    _inbox(factory)
    frozen = plan(recovery, ids)
    original = recovery.verify_source
    recovery.verify_source = lambda *args: {**original(*args), "changed_epoch": True}
    with pytest.raises(RepositoryConflict, match="PREIMAGE_DRIFT"):
        recovery.apply(frozen, expected_plan_hash=frozen["plan_hash"], now=NOW)
    with factory() as db:
        assert len(db.scalars(select(ReferenceActivationReceipt)).all()) == 48
        assert all(r.status == "active" for r in db.scalars(select(ReferenceRevision)))
        assert not db.scalars(
            select(ReferenceBatch).where(
                ReferenceBatch.batch_key.like("htdy-conflict:%")
            )
        ).all()


def test_real_final_fence_loss_has_no_partial_successor(pg_setup):
    factory, recovery, ids = pg_setup
    _inbox(factory)
    frozen = plan(recovery, ids)
    calls = []

    def guard():
        calls.append(True)
        if len(calls) > 1:
            raise ValueError("TEST_FENCE_LOST")

    recovery.assert_fenced = guard
    with pytest.raises(ValueError, match="TEST_FENCE_LOST"):
        recovery.apply(frozen, expected_plan_hash=frozen["plan_hash"], now=NOW)
    with factory() as db:
        assert len(db.scalars(select(ReferenceActivationReceipt)).all()) == 48
        assert all(r.status == "active" for r in db.scalars(select(ReferenceRevision)))


def test_real_unknown_original_remains_unresolved(pg_setup):
    factory, recovery, ids = pg_setup
    delivery = _inbox(factory)
    with factory() as db, db.begin():
        row = db.get(ReferenceInboxDelivery, delivery)
        row.status = "UNKNOWN"
        row.unknown_at = NOW
    with pytest.raises(RepositoryConflict, match="UNKNOWN_DELIVERY"):
        plan(recovery, ids)
    with factory() as db:
        assert db.get(ReferenceInboxDelivery, delivery).status == "UNKNOWN"
        assert delivery not in verified_resolution_ids(db)


@pytest.mark.parametrize("mutation", [None, "entry_price", "holding", "old_valid_to"])
def test_real_open_projection_preservation_and_tamper_rejection(pg_setup, mutation):
    from tests.reference_trading.test_htdy_conflict_recovery import (
        test_open_trade_is_interrupted_without_close_price_or_new_action as check_open,
    )

    check_open(pg_setup, mutation)


@pytest.mark.parametrize("pg_setup", [["hc", "ss", "zn", "rb"]], indirect=True)
def test_real_three_scope_atomic_original_trigger_and_ss_interruption(
    pg_setup, monkeypatch
):
    from tests.reference_trading.test_htdy_three_conflict_scope import configure_three
    from app.reference_trading.models import ReferenceTradeRow, ReferenceActionRow
    from app.reference_trading.htdy_conflict_recovery import _row
    from tests.reference_trading.test_inbox import event
    from dataclasses import replace

    factory, recovery, _ = pg_setup
    factory, recovery, ids = configure_three(factory, recovery, monkeypatch)
    original_event = event(end=NOW - timedelta(minutes=30))
    item = replace(
        original_event,
        channel="live:bar:ss:60m",
        data={**original_event.data, "contract": "SS2612"},
    )
    delivery_id = (
        ReferenceInboxRepository(factory).ingest(item, ingested_at=NOW).delivery_ids[0]
    )
    with factory() as db:
        original_delivery = _row(db.get(ReferenceInboxDelivery, delivery_id))
        originals = {b.batch_id: _row(b) for b in db.scalars(select(ReferenceBatch))}
    frozen = plan(recovery, ids)
    result = recovery.apply(frozen, expected_plan_hash=frozen["plan_hash"], now=NOW)
    assert len(result) == 3 and recovery.readback(frozen) == result
    with factory() as db:
        assert all(_row(db.get(ReferenceBatch, k)) == v for k, v in originals.items())
        assert _row(db.get(ReferenceInboxDelivery, delivery_id)) == original_delivery
        assert delivery_id in verified_resolution_ids(db)
        rows = db.scalars(
            select(ReferenceTradeRow).order_by(ReferenceTradeRow.valid_from_seq)
        ).all()
        assert [r.status for r in rows] == ["OPEN", "DATA_INTERRUPTED"]
        assert rows[1].exit_reference_price is None and rows[1].reference_return is None
        assert len(db.scalars(select(ReferenceActionRow)).all()) == 1
        input_id = db.get(ReferenceInboxDelivery, delivery_id).input_id
    with pytest.raises(DBAPIError):
        with factory() as db, db.begin():
            db.get(ReferenceInboxInput, input_id).canonical_envelope = "tampered"
