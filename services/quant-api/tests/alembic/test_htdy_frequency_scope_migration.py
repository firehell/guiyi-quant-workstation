from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATHS = (
    QUANT_API_ROOT / "alembic/versions/20260813_0037_alert_v1.py",
    QUANT_API_ROOT / "alembic/versions/20260814_0038_alert_v2.py",
    QUANT_API_ROOT / "alembic/versions/20260815_0039_execution_review_v1.py",
    QUANT_API_ROOT / "alembic/versions/20260825_0040_htdy_frequency_scope.py",
)


class RecordingResult:
    def scalar_one_or_none(self) -> list[str]:
        return ["jm", "rb"]


class RecordingBind:
    def __init__(self, recorder: RecordingOperations) -> None:
        self._recorder = recorder

    def execute(self, statement: object) -> RecordingResult:
        self._recorder.executed_statements.append(str(statement))
        if not getattr(statement, "is_select", False):
            table = getattr(statement, "table", None)
            self._recorder.mutated_tables.add(str(getattr(table, "name", "")))
        return RecordingResult()


class RecordingOperations:
    def __init__(self) -> None:
        self.added_columns: list[tuple[str, object]] = []
        self.dropped_constraints: list[tuple[str, str, str | None]] = []
        self.created_unique_constraints: list[tuple[str, str, tuple[str, ...]]] = []
        self.executed_statements: list[str] = []
        self.mutated_tables: set[str] = set()
        self._bind = RecordingBind(self)

    def add_column(self, table_name: str, column: object) -> None:
        self.added_columns.append((table_name, column))
        self.mutated_tables.add(table_name)

    def get_bind(self) -> RecordingBind:
        return self._bind

    def drop_constraint(
        self,
        constraint_name: str,
        table_name: str,
        type_: str | None = None,
        **_: object,
    ) -> None:
        self.dropped_constraints.append((constraint_name, table_name, type_))
        self.mutated_tables.add(table_name)

    def create_unique_constraint(
        self,
        constraint_name: str,
        table_name: str,
        columns: list[str] | tuple[str, ...],
        **_: object,
    ) -> None:
        self.created_unique_constraints.append(
            (constraint_name, table_name, tuple(columns))
        )
        self.mutated_tables.add(table_name)


def test_upgrade_changes_only_alert_scope_and_event_identity() -> None:
    migration = _load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260825_0040"
    assert migration.down_revision == "20260815_0039"
    assert recorder.mutated_tables == {"alert_rules", "alert_events"}
    assert len(recorder.added_columns) == 1
    table_name, column = recorder.added_columns[0]
    assert table_name == "alert_rules"
    assert column.name == "scope_product_frequencies"
    assert isinstance(column.type, sa.JSON)
    assert column.nullable is False
    assert str(column.server_default.arg) == "'{}'::json"
    assert recorder.dropped_constraints == [
        ("uq_alert_events_rule_symbol_bar_end", "alert_events", "unique")
    ]
    assert recorder.created_unique_constraints == [
        (
            "uq_alert_events_rule_symbol_frequency_bar_end",
            "alert_events",
            ("rule_id", "symbol", "frequency", "bar_end"),
        )
    ]


def test_downgrade_fails_closed() -> None:
    migration = _load_migration()

    with pytest.raises(
        RuntimeError,
        match="^HTDY_FREQUENCY_SCOPE_DOWNGRADE_UNSUPPORTED$",
    ):
        migration.downgrade()


@pytest.fixture
def isolated_postgres_engine() -> Iterator[Engine]:
    if not os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip():
        pytest.fail("GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required")
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


def test_upgrade_transforms_only_htdy_scope_and_allows_frequency_identity(
    isolated_postgres_engine: Engine,
) -> None:
    schema = f"htdy_frequency_scope_{uuid4().hex}"
    with isolated_postgres_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        for migration_path in MIGRATION_PATHS[:-1]:
            _run_upgrade(isolated_postgres_engine, schema, migration_path)

        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            connection.execute(
                text(
                    """
                    UPDATE alert_rules
                    SET scope_products = CASE rule_code
                        WHEN 'htdy_original_15m' THEN ARRAY['jm', 'rb']::varchar[]
                        WHEN 'subing_entry_signal_v1' THEN ARRAY['ag']::varchar[]
                        ELSE scope_products
                    END
                    WHERE rule_code IN (
                        'htdy_original_15m',
                        'subing_entry_signal_v1'
                    )
                    """
                )
            )

        _run_upgrade(isolated_postgres_engine, schema, MIGRATION_PATHS[-1])

        with isolated_postgres_engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            rows = {
                row.rule_code: row
                for row in connection.execute(
                    text(
                        """
                        SELECT rule_code, scope_products, scope_product_frequencies
                        FROM alert_rules
                        WHERE rule_code IN (
                            'htdy_original_15m',
                            'subing_entry_signal_v1'
                        )
                        """
                    )
                ).mappings()
            }
            htdy = rows["htdy_original_15m"]
            subing = rows["subing_entry_signal_v1"]
            assert htdy.scope_products == []
            assert htdy.scope_product_frequencies == {
                "jm": ["15m"],
                "rb": ["15m"],
            }
            assert subing.scope_products == ["ag"]
            assert subing.scope_product_frequencies == {}

        bar_end = datetime(2026, 8, 25, 2, 30, tzinfo=UTC)
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            rule_id = connection.scalar(
                text("SELECT id FROM alert_rules WHERE rule_code = 'htdy_original_15m'")
            )
            event_values = {
                "rule_id": rule_id,
                "symbol": "jm",
                "contract": "JM2609",
                "trading_day": bar_end.date(),
                "bar_end": bar_end,
                "result_codes": ["buy"],
                "lower_tf_confirmation": False,
                "detected_at": bar_end,
                "notification_attempted_at": None,
            }
            connection.execute(
                text(
                    """
                    INSERT INTO alert_events (
                        rule_id, symbol, contract, trading_day, frequency,
                        bar_end, result_codes, lower_tf_confirmation,
                        detected_at, notification_attempted_at
                    ) VALUES (
                        :rule_id, :symbol, :contract, :trading_day, '15m',
                        :bar_end, ARRAY['buy']::varchar[],
                        :lower_tf_confirmation, :detected_at,
                        :notification_attempted_at
                    )
                    """
                ),
                event_values,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO alert_events (
                        rule_id, symbol, contract, trading_day, frequency,
                        bar_end, result_codes, lower_tf_confirmation,
                        detected_at, notification_attempted_at
                    ) VALUES (
                        :rule_id, :symbol, :contract, :trading_day, '5m',
                        :bar_end, ARRAY['buy']::varchar[],
                        :lower_tf_confirmation, :detected_at,
                        :notification_attempted_at
                    )
                    """
                ),
                event_values,
            )

        with pytest.raises(IntegrityError):
            with isolated_postgres_engine.begin() as connection:
                connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
                connection.execute(
                    text(
                        """
                        INSERT INTO alert_events (
                            rule_id, symbol, contract, trading_day, frequency,
                            bar_end, result_codes, lower_tf_confirmation,
                            detected_at, notification_attempted_at
                        ) VALUES (
                            :rule_id, :symbol, :contract, :trading_day, '5m',
                            :bar_end, ARRAY['buy']::varchar[],
                            :lower_tf_confirmation, :detected_at,
                            :notification_attempted_at
                        )
                        """
                    ),
                    event_values,
                )
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _run_upgrade(engine: Engine, schema: str, migration_path: Path) -> None:
    migration = _load_migration_from(
        migration_path,
        f"htdy_frequency_scope_migration_{uuid4().hex}",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()


def _load_migration() -> ModuleType:
    path = MIGRATION_PATHS[-1]
    assert path.exists(), f"missing migration: {path.name}"
    return _load_migration_from(path, "htdy_frequency_scope_migration")


def _load_migration_from(path: Path, module_name: str) -> ModuleType:
    assert path.exists(), f"missing migration: {path.name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration
