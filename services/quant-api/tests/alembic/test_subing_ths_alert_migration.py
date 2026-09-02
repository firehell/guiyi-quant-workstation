from __future__ import annotations

from collections.abc import Iterator
import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import Engine

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = QUANT_API_ROOT / "alembic/versions/20260902_0044_subing_ths_alert.py"
RETIREMENT_MIGRATION_PATH = (
    QUANT_API_ROOT / "alembic/versions/20260902_0043_retire_subing.py"
)
SUPPORT_PATH = Path(__file__).with_name("test_subing_strategy_alert_migration.py")


def test_migration_is_forward_only_from_exact_0043_parent() -> None:
    migration = _load_module(MIGRATION_PATH)

    assert migration.revision == "20260902_0044"
    assert migration.down_revision == "20260902_0043"
    with pytest.raises(
        RuntimeError,
        match="^SUBING_THS_ALERT_DOWNGRADE_UNSUPPORTED$",
    ):
        migration.downgrade()


@pytest.fixture
def isolated_postgres_engine() -> Iterator[Engine]:
    if not os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip():
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


@pytest.mark.isolated_postgresql
def test_upgrade_from_0042_inserts_disabled_subing_rule_and_preserves_htdy(
    isolated_postgres_engine: Engine,
) -> None:
    support, schema = _prepared_0043_schema(isolated_postgres_engine)
    try:
        with isolated_postgres_engine.begin() as connection:
            support._search_path(connection, schema)
            htdy_rule_before = connection.execute(text(
                "SELECT id, rule_code, enabled, scope_product_frequencies, "
                "created_at, updated_at FROM alert_rules "
                "WHERE rule_code = 'htdy_original_15m'"
            )).mappings().one()
            htdy_events_before = support._htdy_rows(connection)

        support._run_upgrade(isolated_postgres_engine, schema, MIGRATION_PATH)
        with isolated_postgres_engine.begin() as connection:
            support._search_path(connection, schema)
            connection.execute(text(
                "UPDATE alembic_version SET version_num = '20260902_0044'"
            ))
            rules = connection.execute(text(
                "SELECT id, rule_code, enabled, scope_product_frequencies, "
                "created_at, updated_at FROM alert_rules ORDER BY rule_code"
            )).mappings().all()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260902_0044"
            )
            assert [dict(row) for row in rules] == [
                dict(htdy_rule_before),
                {
                    "id": rules[1]["id"],
                    "rule_code": "subing_ths_alert_15m_v1",
                    "enabled": False,
                    "scope_product_frequencies": {},
                    "created_at": rules[1]["created_at"],
                    "updated_at": rules[1]["updated_at"],
                },
            ]
            assert rules[1]["created_at"].tzinfo is not None
            assert rules[1]["updated_at"].tzinfo is not None
            assert support._htdy_rows(connection) == htdy_events_before
            assert connection.scalar(text(
                "SELECT COUNT(*) FROM alert_events e JOIN alert_rules r "
                "ON r.id = e.rule_id "
                "WHERE r.rule_code = 'subing_ths_alert_15m_v1'"
            )) == 0

        assert {
            column["name"]
            for column in sa_inspect(isolated_postgres_engine).get_columns(
                "alert_rules", schema=schema
            )
        } == {
            "id", "rule_code", "enabled", "scope_product_frequencies",
            "created_at", "updated_at",
        }
        assert {
            column["name"]
            for column in sa_inspect(isolated_postgres_engine).get_columns(
                "alert_events", schema=schema
            )
        } == {
            "id", "rule_id", "symbol", "contract", "trading_day", "frequency",
            "bar_end", "result_codes", "detected_at", "notification_attempted_at",
            "created_at",
        }
    finally:
        support._drop_schema(isolated_postgres_engine, schema)


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize(
    "invalid_sql",
    [
        "UPDATE alembic_version SET version_num = '20260826_0042'",
        "INSERT INTO alert_rules "
        "(rule_code, enabled, scope_product_frequencies, created_at, updated_at) "
        "VALUES ('unknown_alert_rule', true, '{}'::json, now(), now())",
        "INSERT INTO alert_rules "
        "(rule_code, enabled, scope_product_frequencies, created_at, updated_at) "
        "VALUES ('subing_ths_alert_15m_v1', false, '{}'::json, now(), now())",
        "UPDATE alert_rules SET scope_product_frequencies = "
        "'{\"jm\":[\"4h\"]}'::json WHERE rule_code = 'htdy_original_15m'",
        "UPDATE alert_events SET contract = 'RB2610' "
        "WHERE rule_id = (SELECT id FROM alert_rules "
        "WHERE rule_code = 'htdy_original_15m')",
    ],
)
def test_preflight_rejects_any_nonexact_0043_state_before_rule_insertion(
    isolated_postgres_engine: Engine,
    invalid_sql: str,
) -> None:
    support, schema = _prepared_0043_schema(isolated_postgres_engine)
    try:
        with isolated_postgres_engine.begin() as connection:
            support._search_path(connection, schema)
            connection.exec_driver_sql(invalid_sql)

        with pytest.raises(
            RuntimeError,
            match="^SUBING_THS_ALERT_PREFLIGHT_FAILED$",
        ):
            support._run_upgrade(isolated_postgres_engine, schema, MIGRATION_PATH)

        with isolated_postgres_engine.connect() as connection:
            support._search_path(connection, schema, local=False)
            assert connection.scalar(text(
                "SELECT COUNT(*) FROM alert_rules "
                "WHERE rule_code = 'subing_ths_alert_15m_v1'"
            )) == (1 if "subing_ths_alert_15m_v1" in invalid_sql else 0)
    finally:
        support._drop_schema(isolated_postgres_engine, schema)


@pytest.mark.isolated_postgresql
def test_postflight_mismatch_rolls_back_rule_insertion(
    isolated_postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    support, schema = _prepared_0043_schema(isolated_postgres_engine)
    try:
        migration = _load_module(MIGRATION_PATH)
        original_postflight = migration._postflight

        def corrupt_then_validate(bind, htdy_rule_before, htdy_events_before) -> None:
            bind.execute(text(
                "UPDATE alert_rules SET enabled = true "
                "WHERE rule_code = 'subing_ths_alert_15m_v1'"
            ))
            original_postflight(bind, htdy_rule_before, htdy_events_before)

        monkeypatch.setattr(migration, "_postflight", corrupt_then_validate)
        with pytest.raises(
            RuntimeError,
            match="^SUBING_THS_ALERT_POSTFLIGHT_FAILED$",
        ):
            _run_loaded_upgrade(isolated_postgres_engine, schema, migration)

        with isolated_postgres_engine.connect() as connection:
            support._search_path(connection, schema, local=False)
            assert connection.scalar(text(
                "SELECT COUNT(*) FROM alert_rules "
                "WHERE rule_code = 'subing_ths_alert_15m_v1'"
            )) == 0
    finally:
        support._drop_schema(isolated_postgres_engine, schema)


def _prepared_0043_schema(engine: Engine) -> tuple[ModuleType, str]:
    support = _load_module(SUPPORT_PATH)
    schema = support._prepared_0041_schema(engine)
    with engine.begin() as connection:
        support._search_path(connection, schema)
        support._seed_realistic_0041_state(connection)
    support._run_upgrade(
        engine,
        schema,
        support.MIGRATION_PATHS[-1],
    )
    with engine.begin() as connection:
        support._search_path(connection, schema)
        connection.execute(text(
            "UPDATE alembic_version SET version_num = '20260826_0042'"
        ))
    support._run_upgrade(engine, schema, RETIREMENT_MIGRATION_PATH)
    with engine.begin() as connection:
        support._search_path(connection, schema)
        connection.execute(text(
            "UPDATE alembic_version SET version_num = '20260902_0043'"
        ))
    return support, schema


def _run_loaded_upgrade(engine: Engine, schema: str, migration: ModuleType) -> None:
    support = _load_module(SUPPORT_PATH)
    with engine.begin() as connection:
        support._search_path(connection, schema)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()


def _load_module(path: Path) -> ModuleType:
    assert path.exists(), f"missing migration: {path.name}"
    spec = importlib.util.spec_from_file_location(
        f"subing_ths_alert_{path.stem}_{uuid4().hex}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
