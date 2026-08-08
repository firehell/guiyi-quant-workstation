from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


PARENT_REVISION = "20260805_0033"
DROP_REVISION = "20260808_0034"
QUANT_API_ROOT = Path(__file__).resolve().parents[2]
DROP_SOURCE = (
    QUANT_API_ROOT / "alembic" / "versions" / "20260808_0034_drop_retired_surfaces.py"
)

DROPPED_TABLES = (
    "live_aggregation_checkpoints",
    "live_aggregated_bars",
    "live_ingest_checkpoints",
    "live_minute_bars",
    "signal_decision_reconciliations",
    "research_samples",
    "retention_runs",
    "signal_decisions",
    "live_observation_bars",
    "signal_notifications",
    "signal_events",
    "strategy_signals",
    "signal_scan_tasks",
    "review_attachments",
    "review_notes",
    "review_tags",
    "watchlist_items",
    "watchlists",
)


def test_retired_surface_drop_revises_backtest_retirement() -> None:
    config = Config(str(QUANT_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    revision = scripts.get_revision(DROP_REVISION)
    assert revision is not None
    assert revision.down_revision == PARENT_REVISION
    assert DROP_REVISION in {item.revision for item in scripts.walk_revisions()}
    # Head may move forward; 0034 remains the parent of subsequent drops.
    assert scripts.get_revision("20260808_0035") is not None
    assert scripts.get_revision("20260808_0035").down_revision == DROP_REVISION


def test_retired_surface_drop_sql_is_irreversible_and_scoped() -> None:
    source = DROP_SOURCE.read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout = '5s'" in source
    assert "DROP TRIGGER IF EXISTS trg_signal_decisions_immutable" in source
    assert "DROP FUNCTION IF EXISTS reject_signal_decision_update()" in source
    assert "DROP TABLE IF EXISTS" in source
    assert "RuntimeError" in source
    for table_name in DROPPED_TABLES:
        assert table_name in source
    assert "market_datasets" not in source
    assert "market_partitions" not in source
    assert "main_contract_map" not in source
    assert "data_gaps" not in source


@pytest.fixture
def isolated_postgres_engine() -> Engine:
    configured_url = os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip()
    if not configured_url:
        pytest.skip("GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required")
    try:
        url = require_isolated_migration_database_url(
            os.environ,
            identity_probe=probe_database_identity,
        )
    except MigrationTestDatabaseSafetyError as exc:
        pytest.fail(str(exc))

    engine = create_engine(url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


def test_surface_drop_removes_stub_tables_and_trigger(
    isolated_postgres_engine: Engine,
) -> None:
    schema = f"surface_drop_{uuid4().hex}"
    with isolated_postgres_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        for table_name in DROPPED_TABLES:
            connection.exec_driver_sql(
                f'CREATE TABLE "{table_name}" (id INTEGER PRIMARY KEY)'
            )
        connection.exec_driver_sql(
            """
            CREATE FUNCTION reject_signal_decision_update()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER trg_signal_decisions_immutable
            BEFORE UPDATE ON signal_decisions
            FOR EACH ROW EXECUTE FUNCTION reject_signal_decision_update();
            """
        )
    try:
        _run_drop_upgrade(isolated_postgres_engine, schema)
        inspector = inspect(isolated_postgres_engine)
        remaining = [
            name
            for name in DROPPED_TABLES
            if inspector.has_table(name, schema=schema)
        ]
        assert remaining == []
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            function_exists = connection.execute(
                text(
                    """
                    SELECT 1
                    FROM pg_proc AS proc
                    JOIN pg_namespace AS ns ON ns.oid = proc.pronamespace
                    WHERE proc.proname = 'reject_signal_decision_update'
                      AND ns.nspname = :schema
                    """
                ),
                {"schema": schema},
            ).scalar()
            assert function_exists is None
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _load_drop_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "retired_surface_drop_migration", DROP_SOURCE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_drop_upgrade(engine: Engine, schema: str) -> None:
    module = _load_drop_module()
    with engine.begin() as connection:
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
