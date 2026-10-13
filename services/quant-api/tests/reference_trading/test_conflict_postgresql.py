"""Real PostgreSQL atomicity for quarantine and revision repair, isolated schema."""
from uuid import uuid4

import pytest
from sqlalchemy.schema import CreateSchema, DropSchema

from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading import test_conflict_recovery as recovery
from tests.reference_trading import test_fault_isolation as isolation

pytestmark = pytest.mark.isolated_postgresql


@pytest.mark.parametrize('case', [
    isolation.test_real_sqlite_quarantine_is_atomic_durable_idempotent_and_preserves_time,
    isolation.test_ownership_loss_rolls_back_all_four_receipts,
    isolation.test_sqlite_unknown_commit_keeps_persisted_receipts_for_restart_readback,
    isolation.test_quarantine_partial_fusion_group_and_altered_original_fail_closed,
    recovery.test_recovery_preserves_old_capture_and_conflict_and_starts_flat_new_revision,
    recovery.test_recovery_source_drift_and_fence_loss_roll_back,
    recovery.test_historical_open_source_is_preserved_but_never_carried_to_new_revision,
], ids=lambda case: case.__name__)
def test_postgresql_conflict_transaction(case, isolated_postgres_engine, monkeypatch, tmp_path):
    schema = 'intraday_conflict_' + uuid4().hex
    with isolated_postgres_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    scoped = isolated_postgres_engine.execution_options(schema_translate_map={None: schema})
    original_group, original_recovery = isolation._quarantine_group, recovery.setup_recovery
    monkeypatch.setattr(isolation, '_quarantine_group', lambda path: original_group(path, engine=scoped))
    monkeypatch.setattr(recovery, 'setup_recovery', lambda **kw: original_recovery(engine=scoped, **kw))
    try:
        if case.__module__ == isolation.__name__:
            case(tmp_path)
        else:
            case()
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
