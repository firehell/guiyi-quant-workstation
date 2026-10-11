"""Dedicated isolated PostgreSQL transaction proof; never accepts production URLs."""
from uuid import uuid4

import pytest

from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_newow_scope_upgrade import assert_second_failure_rolls_back

pytestmark = pytest.mark.isolated_postgresql


def test_postgresql_second_route_failure_rolls_back_first_completed_bootstrap(
    isolated_postgres_engine, monkeypatch,
):
    engine = isolated_postgres_engine
    schema = 'newow_upgrade_' + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        assert_second_failure_rolls_back(monkeypatch, scoped)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
