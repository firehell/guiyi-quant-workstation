"""Final warm recovery atomicity against an isolated real PostgreSQL schema."""

from uuid import uuid4
import pytest
from sqlalchemy.schema import CreateSchema, DropSchema
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading import test_final_warm_conflict_recovery as cases

pytestmark = pytest.mark.isolated_postgresql


@pytest.mark.parametrize(
    "case",
    [
        cases.test_final_warm_capture_recovery_keeps_existing_evidence_and_activates_flat_state,
        cases.test_final_warm_source_drift_rejects_apply_without_any_revision_change,
    ],
    ids=lambda case: case.__name__,
)
def test_final_warm_pg(case, isolated_postgres_engine):  # noqa: F811
    schema = "final_warm_" + uuid4().hex
    with isolated_postgres_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    scoped = isolated_postgres_engine.execution_options(
        schema_translate_map={None: schema}
    )
    try:
        case(scoped)
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
