from __future__ import annotations

import importlib.util
import inspect
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect as sa_inspect
from sqlalchemy.engine import Engine

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DATA_TABLES = {
    "exchanges",
    "instruments",
    "contracts",
    "trading_calendars",
    "trading_sessions",
    "main_contract_map",
    "market_datasets",
    "market_partitions",
}
RETIRED_TABLES = {
    "data_sources",
    "data_download_tasks",
    "market_data_files",
    "data_quality_reports",
    "fee_margin_rules",
    "futures_trading_parameters",
    "futures_ex_factors",
    "futures_warehouse_stocks",
    "futures_roll_yields",
    "futures_member_ranks",
    "futures_basis",
    "futures_contract_universe",
    "futures_continuous_contract_map",
}


def test_canonical_foundation_migration_is_new_irreversible_head() -> None:
    path = (
        QUANT_API_ROOT
        / "alembic/versions/20260808_0036_converge_canonical_data_foundation.py"
    )
    spec = importlib.util.spec_from_file_location("canonical_foundation_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "20260808_0036"
    assert migration.down_revision == "20260808_0035"
    assert set(migration.RETIRED_TABLES) == RETIRED_TABLES
    assert "DROP TABLE IF EXISTS contract_specs" in inspect.getsource(migration.upgrade)
    assert "DROP VIEW IF EXISTS data_core_main_contract_map" in inspect.getsource(
        migration.upgrade
    )
    assert "uq_trading_sessions_identity" in inspect.getsource(migration.upgrade)
    assert "SET LOCAL lock_timeout" in inspect.getsource(migration.upgrade)
    assert "actual_dominant" not in inspect.getsource(migration.upgrade)
    with pytest.raises(RuntimeError, match="irreversible"):
        migration.downgrade()


@pytest.fixture
def isolated_migration_context(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Config, Engine]:
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

    monkeypatch.setenv("DATABASE_URL", url)
    config = Config()
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url, pool_pre_ping=True)
    _reset_public_schema(engine)
    try:
        yield config, engine
    finally:
        _reset_public_schema(engine)
        engine.dispose()


@pytest.mark.parametrize("start_revision", [None, "20260808_0035"])
def test_canonical_foundation_upgrades_empty_and_0035_databases(
    isolated_migration_context: tuple[Config, Engine],
    start_revision: str | None,
) -> None:
    config, engine = isolated_migration_context
    if start_revision is not None:
        command.upgrade(config, start_revision)
    command.upgrade(config, "head")

    inspector = sa_inspect(engine)
    tables = set(inspector.get_table_names())
    assert ACTIVE_DATA_TABLES <= tables
    assert RETIRED_TABLES.isdisjoint(tables)
    assert "data_core_main_contract_map" not in inspector.get_view_names()
    assert {
        "kind",
        "symbol",
        "series_or_contract",
        "frequency",
    } <= {column["name"] for column in inspector.get_columns("market_datasets")}
    partition_columns = {column["name"] for column in inspector.get_columns("market_partitions")}
    assert {"file_uri", "row_count", "coverage_start", "coverage_end"} <= partition_columns
    assert {"manifest_uri", "checksum", "manifest_digest"}.isdisjoint(partition_columns)
    assert {"contract_specs", "data_gaps"}.isdisjoint(tables)
    assert {
        "effective_from",
        "effective_to",
    } <= {column["name"] for column in inspector.get_columns("trading_sessions")}


def _reset_public_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
