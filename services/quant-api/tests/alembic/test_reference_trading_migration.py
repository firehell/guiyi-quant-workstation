from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = QUANT_API_ROOT / "alembic/versions/20260919_0047_reference_trading.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        f"reference_trading_migration_{uuid4().hex}", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_trading_migration_is_forward_only_from_unique_head() -> None:
    migration = _load_migration()

    assert migration.revision == "20260919_0047"
    assert migration.down_revision == "20260916_0046"
    with pytest.raises(RuntimeError, match="^REFERENCE_TRADING_DOWNGRADE_UNSUPPORTED$"):
        migration.downgrade()


def test_reference_models_declare_six_disabled_by_default_tables() -> None:
    from app.reference_trading.models import REFERENCE_TABLES, ReferenceStream

    assert REFERENCE_TABLES == {
        "reference_streams",
        "reference_revisions",
        "reference_batches",
        "reference_actions",
        "reference_trades",
        "reference_marks",
    }
    assert ReferenceStream.__table__.c.enabled.default.arg is False
    assert ReferenceStream.__table__.c.row_version.default.arg == 0


@pytest.mark.isolated_postgresql
def test_reference_migration_creates_six_empty_tables_and_preserves_existing_rows(
    isolated_postgres_engine: Engine,
) -> None:
    schema = "reference_p3_" + uuid4().hex
    migration = _load_migration()
    try:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            connection.exec_driver_sql("CREATE TABLE alert_rules (id bigint primary key, payload text)")
            connection.exec_driver_sql("CREATE TABLE market_datasets (id bigint primary key, payload text)")
            connection.exec_driver_sql("INSERT INTO alert_rules VALUES (1, 'alert-before')")
            connection.exec_driver_sql("INSERT INTO market_datasets VALUES (2, 'catalog-before')")
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        inspector = inspect(isolated_postgres_engine)
        assert set(inspector.get_table_names(schema=schema)) >= {
            "alert_rules", "market_datasets",
            "reference_streams", "reference_revisions", "reference_batches",
            "reference_actions", "reference_trades", "reference_marks",
        }
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            assert connection.scalar(text("SELECT payload FROM alert_rules WHERE id=1")) == "alert-before"
            assert connection.scalar(text("SELECT payload FROM market_datasets WHERE id=2")) == "catalog-before"
            assert connection.scalar(text("SELECT count(*) FROM reference_streams")) == 0
            assert connection.scalar(text("SELECT count(*) FROM reference_revisions")) == 0

        trade_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("reference_trades", schema=schema)
        }
        action_indexes = {
            index["name"] for index in inspector.get_indexes("reference_actions", schema=schema)
        }
        assert "ck_reference_trades_exit_complete" in trade_checks
        assert "uq_reference_actions_forward_source" in action_indexes
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
