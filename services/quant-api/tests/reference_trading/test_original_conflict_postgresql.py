"""Actual PostgreSQL atomic terminal/revision writes in a unique disposable schema."""
from uuid import uuid4
import pytest
from sqlalchemy.schema import CreateSchema, DropSchema
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading import test_original_conflict as cases

pytestmark = pytest.mark.isolated_postgresql

@pytest.mark.parametrize('case', [cases.test_four_route_terminal_is_atomic_non_natural_and_health_conflicted,
    cases.test_two_stage_pending_boundary_requires_pristine_current_revision, cases.test_fence_loss_rolls_back_every_typed_receipt, cases.test_unknown_commit_stops_with_durable_receipts], ids=lambda c: c.__name__)
def test_original_conflict_pg(case, isolated_postgres_engine):  # noqa: F811
    schema = 'original_conflict_' + uuid4().hex
    with isolated_postgres_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    scoped = isolated_postgres_engine.execution_options(schema_translate_map={None: schema})
    try:
        case(scoped)
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
