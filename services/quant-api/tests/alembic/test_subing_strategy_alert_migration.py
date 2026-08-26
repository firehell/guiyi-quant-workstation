from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATHS = tuple(
    QUANT_API_ROOT / "alembic/versions" / name
    for name in (
        "20260813_0037_alert_v1.py",
        "20260814_0038_alert_v2.py",
        "20260815_0039_execution_review_v1.py",
        "20260825_0040_htdy_frequency_scope.py",
        "20260826_0041_retire_execution_review.py",
        "20260826_0042_subing_strategy_alert.py",
    )
)


def test_migration_is_forward_only_from_exact_0041_parent() -> None:
    migration = _load_migration(MIGRATION_PATHS[-1])

    assert migration.revision == "20260826_0042"
    assert migration.down_revision == "20260826_0041"
    with pytest.raises(
        RuntimeError,
        match="^SUBING_STRATEGY_ALERT_DOWNGRADE_UNSUPPORTED$",
    ):
        migration.downgrade()


@pytest.mark.parametrize(
    "changed",
    [
        {"lower_tf_confirmation": True},
        {"symbol": "JM"},
        {"contract": "RB2610"},
    ],
)
def test_htdy_preflight_rejects_event_facts_that_cannot_be_safely_preserved(
    changed: dict[str, object],
) -> None:
    migration = _load_migration(MIGRATION_PATHS[-1])
    valid = {
        "rule_code": "htdy_original_15m",
        "symbol": "jm",
        "contract": "JM2609",
        "trading_day": date(2026, 8, 26),
        "frequency": "15m",
        "bar_end": datetime(2026, 8, 26, 2, 30, tzinfo=UTC),
        "result_codes": ["buy"],
        "lower_tf_confirmation": False,
        "detected_at": datetime(2026, 8, 26, 2, 30, 1, tzinfo=UTC),
        "notification_attempted_at": datetime(
            2026, 8, 26, 2, 30, 2, tzinfo=UTC
        ),
    }

    assert migration._valid_event(valid) is True
    assert migration._valid_event({**valid, **changed}) is False


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
def test_upgrade_replaces_subing_history_and_preserves_htdy_facts(
    isolated_postgres_engine: Engine,
) -> None:
    schema = _prepared_0041_schema(isolated_postgres_engine)
    try:
        with isolated_postgres_engine.begin() as connection:
            _search_path(connection, schema)
            ids = _seed_realistic_0041_state(connection)
            htdy_before = _htdy_rows(connection)

        _run_upgrade(isolated_postgres_engine, schema, MIGRATION_PATHS[-1])

        with isolated_postgres_engine.connect() as connection:
            _search_path(connection, schema, local=False)
            rules = (
                connection.execute(
                    text(
                        "SELECT id, rule_code, enabled, scope_products, "
                        "scope_product_frequencies FROM alert_rules ORDER BY id"
                    )
                )
                .mappings()
                .all()
            )
            assert [row["rule_code"] for row in rules] == [
                "htdy_original_15m",
                "subing_strategy_v1",
            ]
            subing = next(
                row for row in rules if row["rule_code"] == "subing_strategy_v1"
            )
            assert dict(subing) == {
                "id": ids["subing_rule_id"],
                "rule_code": "subing_strategy_v1",
                "enabled": False,
                "scope_products": ["ag", "jm"],
                "scope_product_frequencies": {},
            }
            assert (
                connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM alert_rules WHERE rule_code = 'subing_entry_signal_v1'"
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    text("SELECT COUNT(*) FROM alert_events WHERE rule_id = :rule_id"),
                    {"rule_id": ids["subing_rule_id"]},
                )
                == 0
            )
            assert _htdy_rows(connection) == htdy_before

        columns = {
            column["name"]
            for column in sa_inspect(isolated_postgres_engine).get_columns(
                "alert_events", schema=schema
            )
        }
        assert "lower_tf_confirmation" not in columns
        assert {"action_id", "strategy_payload"}.issubset(columns)

        with isolated_postgres_engine.begin() as connection:
            _search_path(connection, schema)
            _insert_strategy_event(connection, ids["subing_rule_id"], "action-1")
            assert (
                connection.scalar(
                    text(
                        "SELECT result_codes[1] FROM alert_events WHERE action_id = 'action-1'"
                    )
                )
                == "close_short"
            )

        with pytest.raises(IntegrityError):
            with isolated_postgres_engine.begin() as connection:
                _search_path(connection, schema)
                _insert_strategy_event(
                    connection,
                    ids["subing_rule_id"],
                    "action-1",
                    bar_end=datetime(2026, 8, 26, 3, 15, tzinfo=UTC),
                )

        with pytest.raises(IntegrityError):
            with isolated_postgres_engine.begin() as connection:
                _search_path(connection, schema)
                connection.execute(
                    text(
                        "UPDATE alert_events SET result_codes = "
                        "ARRAY['arbitrary']::varchar[] WHERE action_id = 'action-1'"
                    )
                )
    finally:
        _drop_schema(isolated_postgres_engine, schema)


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize(
    "invalid_sql",
    [
        "UPDATE alembic_version SET version_num = '20260825_0040'",
        'UPDATE alert_rules SET scope_product_frequencies = \'{"jm":["15m"]}\'::json '
        "WHERE rule_code = 'subing_entry_signal_v1'",
        "INSERT INTO alert_rules "
        "(rule_code, enabled, scope_products, scope_product_frequencies) "
        "VALUES ('unknown_active', true, ARRAY[]::varchar[], '{}'::json)",
        "UPDATE alert_events SET lower_tf_confirmation = true "
        "WHERE rule_id = (SELECT id FROM alert_rules "
        "WHERE rule_code = 'htdy_original_15m')",
    ],
)
def test_preflight_failure_is_atomic_at_0041(
    isolated_postgres_engine: Engine,
    invalid_sql: str,
) -> None:
    schema = _prepared_0041_schema(isolated_postgres_engine)
    try:
        with isolated_postgres_engine.begin() as connection:
            _search_path(connection, schema)
            _seed_realistic_0041_state(connection)
            connection.exec_driver_sql(invalid_sql)

        with pytest.raises(
            RuntimeError, match="^SUBING_STRATEGY_ALERT_PREFLIGHT_FAILED$"
        ):
            _run_upgrade(isolated_postgres_engine, schema, MIGRATION_PATHS[-1])

        columns = {
            column["name"]
            for column in sa_inspect(isolated_postgres_engine).get_columns(
                "alert_events", schema=schema
            )
        }
        assert "lower_tf_confirmation" in columns
        assert "action_id" not in columns
        with isolated_postgres_engine.connect() as connection:
            _search_path(connection, schema, local=False)
            assert (
                connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM alert_rules WHERE rule_code = 'subing_entry_signal_v1'"
                    )
                )
                == 1
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM alert_rules WHERE rule_code = 'subing_strategy_v1'"
                    )
                )
                == 0
            )
    finally:
        _drop_schema(isolated_postgres_engine, schema)


def _prepared_0041_schema(engine: Engine) -> str:
    schema = f"subing_strategy_alert_{uuid4().hex}"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    for path in MIGRATION_PATHS[:-1]:
        _run_upgrade(engine, schema, path)
    with engine.begin() as connection:
        _search_path(connection, schema)
        connection.execute(
            text("CREATE TABLE alembic_version (version_num varchar(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('20260826_0041')")
        )
    return schema


def _seed_realistic_0041_state(connection: Connection) -> dict[str, int]:
    connection.execute(
        text(
            "UPDATE alert_rules SET enabled = CASE rule_code "
            "WHEN 'subing_entry_signal_v1' THEN false ELSE true END, "
            "scope_products = CASE rule_code "
            "WHEN 'subing_entry_signal_v1' THEN ARRAY['ag','jm']::varchar[] "
            "ELSE ARRAY[]::varchar[] END, "
            "scope_product_frequencies = CASE rule_code "
            'WHEN \'htdy_original_15m\' THEN \'{"jm":["5m","15m"]}\'::json '
            "ELSE '{}'::json END"
        )
    )
    rule_ids = {
        str(row.rule_code): int(row.id)
        for row in connection.execute(text("SELECT id, rule_code FROM alert_rules"))
    }
    common = {
        "trading_day": "2026-08-26",
        "detected_at": datetime(2026, 8, 26, 2, 30, 1, tzinfo=UTC),
        "notification_at": datetime(2026, 8, 26, 2, 30, 2, tzinfo=UTC),
    }
    connection.execute(
        text(
            "INSERT INTO alert_events "
            "(rule_id, symbol, contract, trading_day, frequency, bar_end, "
            "result_codes, lower_tf_confirmation, detected_at, notification_attempted_at) "
            "VALUES (:rule_id, 'jm', 'JM2609', :trading_day, '15m', :bar_end, "
            "ARRAY['buy']::varchar[], false, :detected_at, :notification_at)"
        ),
        {
            **common,
            "rule_id": rule_ids["htdy_original_15m"],
            "bar_end": datetime(2026, 8, 26, 2, 30, tzinfo=UTC),
        },
    )
    connection.execute(
        text(
            "INSERT INTO alert_events "
            "(rule_id, symbol, contract, trading_day, frequency, bar_end, "
            "result_codes, lower_tf_confirmation, detected_at, notification_attempted_at) "
            "VALUES (:rule_id, 'ag', 'AG2610', :trading_day, '15m', :bar_end, "
            "ARRAY['sell']::varchar[], true, :detected_at, :notification_at)"
        ),
        {
            **common,
            "rule_id": rule_ids["subing_entry_signal_v1"],
            "bar_end": datetime(2026, 8, 26, 2, 45, tzinfo=UTC),
        },
    )
    return {
        "htdy_rule_id": rule_ids["htdy_original_15m"],
        "subing_rule_id": rule_ids["subing_entry_signal_v1"],
    }


def _htdy_rows(connection: Connection) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in connection.execute(
            text(
                "SELECT e.id, e.rule_id, e.symbol, e.contract, e.trading_day, "
                "e.frequency, e.bar_end, e.result_codes, e.detected_at, "
                "e.notification_attempted_at, e.created_at "
                "FROM alert_events e JOIN alert_rules r ON r.id = e.rule_id "
                "WHERE r.rule_code = 'htdy_original_15m' ORDER BY e.id"
            )
        ).mappings()
    ]


def _insert_strategy_event(
    connection: Connection,
    rule_id: int,
    action_id: str,
    *,
    bar_end: datetime = datetime(2026, 8, 26, 3, 0, tzinfo=UTC),
) -> None:
    connection.execute(
        text(
            "INSERT INTO alert_events "
            "(rule_id, symbol, contract, trading_day, frequency, bar_end, "
            "result_codes, action_id, strategy_payload, detected_at) VALUES "
            "(:rule_id, 'jm', 'JM2609', '2026-08-26', '15m', :bar_end, "
            "ARRAY['close_short']::varchar[], :action_id, '{}'::json, :detected_at)"
        ),
        {
            "rule_id": rule_id,
            "action_id": action_id,
            "bar_end": bar_end,
            "detected_at": datetime(2026, 8, 26, 3, 0, 1, tzinfo=UTC),
        },
    )


def _run_upgrade(engine: Engine, schema: str, path: Path) -> None:
    migration = _load_migration(path)
    with engine.begin() as connection:
        _search_path(connection, schema)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()


def _search_path(connection: Connection, schema: str, *, local: bool = True) -> None:
    scope = "LOCAL " if local else ""
    connection.exec_driver_sql(f'SET {scope}search_path TO "{schema}"')


def _drop_schema(engine: Engine, schema: str) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _load_migration(path: Path) -> ModuleType:
    assert path.exists(), f"missing migration: {path.name}"
    spec = importlib.util.spec_from_file_location(
        f"subing_strategy_alert_{path.stem}_{uuid4().hex}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
