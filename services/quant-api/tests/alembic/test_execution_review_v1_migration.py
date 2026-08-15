from __future__ import annotations

import importlib.util
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)
from app.execution_review.models import (
    TradeDecision,
    TradeEpisode,
    TradeExecution,
    TradeReview,
)


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    QUANT_API_ROOT
    / "alembic/versions/20260815_0039_execution_review_v1.py"
)
EXISTING_TABLES = {
    "exchanges",
    "instruments",
    "contracts",
    "trading_calendars",
    "trading_sessions",
    "main_contract_map",
    "market_datasets",
    "market_partitions",
    "alert_rules",
    "alert_events",
}
NEW_TABLES = {
    "trade_decisions",
    "trade_episodes",
    "trade_executions",
    "trade_reviews",
}


class RecordingOperations:
    def __init__(self) -> None:
        self.created_tables: dict[str, tuple[Any, ...]] = {}
        self.created_indexes: list[
            tuple[str, str, tuple[str, ...], dict[str, object]]
        ] = []
        self.forbidden_calls: list[tuple[str, str]] = []
        self.seed_rows: list[dict[str, object]] = []

    def create_table(self, name: str, *elements: Any) -> object:
        self.created_tables[name] = elements
        return type("CreatedTable", (), {"name": name})()

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str] | tuple[str, ...],
        **kwargs: object,
    ) -> None:
        self.created_indexes.append(
            (name, table_name, tuple(columns), dict(kwargs))
        )

    def bulk_insert(self, _: object, rows: list[dict[str, object]]) -> None:
        self.seed_rows.extend(rows)

    def alter_column(self, table_name: str, *_: object, **__: object) -> None:
        self.forbidden_calls.append(("alter_column", table_name))

    def add_column(self, table_name: str, *_: object, **__: object) -> None:
        self.forbidden_calls.append(("add_column", table_name))

    def drop_column(self, table_name: str, *_: object, **__: object) -> None:
        self.forbidden_calls.append(("drop_column", table_name))

    def drop_table(self, table_name: str) -> None:
        self.forbidden_calls.append(("drop_table", table_name))

    def create_unique_constraint(
        self, _: str, table_name: str, *__: object, **___: object
    ) -> None:
        self.forbidden_calls.append(("create_unique_constraint", table_name))

    def create_check_constraint(
        self, _: str, table_name: str, *__: object, **___: object
    ) -> None:
        self.forbidden_calls.append(("create_check_constraint", table_name))


def test_upgrade_is_strictly_additive_and_matches_domain_contract() -> None:
    migration = _load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260815_0039"
    assert migration.down_revision == "20260814_0038"
    assert set(recorder.created_tables) == NEW_TABLES
    assert EXISTING_TABLES.isdisjoint(recorder.created_tables)
    assert recorder.forbidden_calls == []
    assert recorder.seed_rows == []
    assert len(recorder.created_indexes) == 1
    index_name, table_name, columns, index_options = recorder.created_indexes[0]
    assert (index_name, table_name, columns) == (
        "uq_trade_episodes_symbol_open",
        "trade_episodes",
        ("symbol",),
    )
    assert index_options["unique"] is True
    assert str(index_options["postgresql_where"]) == "closed_at IS NULL"

    assert _column_names(recorder, "trade_executions") == {
        "id",
        "episode_id",
        "trigger_decision_id",
        "sequence_no",
        "execution_type",
        "executed_at",
        "price",
        "quantity",
        "note",
        "created_at",
        "updated_at",
    }
    assert _constraint_names(recorder, "trade_executions") == {
        "uq_trade_executions_episode_sequence",
        "uq_trade_executions_trigger_decision",
        "ck_trade_executions_sequence_positive",
        "ck_trade_executions_type",
        "ck_trade_executions_open_sequence",
        "ck_trade_executions_price_positive",
        "ck_trade_executions_quantity_positive",
    }
    assert _constraint_names(recorder, "trade_episodes") == {
        "uq_trade_episodes_origin_decision",
        "ck_trade_episodes_direction",
        "ck_trade_episodes_multiplier_positive",
        "ck_trade_episodes_multiplier_lineage",
        "ck_trade_episodes_lifecycle",
        "ck_trade_episodes_closed_at",
    }
    assert _constraint_names(recorder, "trade_decisions") == {
        "uq_trade_decisions_alert_event",
        "ck_trade_decisions_disposition",
        "ck_trade_decisions_stop_price_positive",
    }
    assert _constraint_names(recorder, "trade_reviews") == {
        "uq_trade_reviews_episode",
        "ck_trade_reviews_adherence",
    }
    assert _column_names(recorder, "trade_decisions") == {
        "id",
        "alert_event_id",
        "disposition",
        "first_viewed_at",
        "decided_at",
        "primary_not_execute_reason",
        "secondary_not_execute_reasons",
        "decision_note",
        "execution_reason_tags",
        "planned_stop_price",
        "stop_basis",
        "created_at",
        "updated_at",
    }
    assert _column_names(recorder, "trade_episodes") == {
        "id",
        "origin_decision_id",
        "symbol",
        "contract",
        "direction",
        "opened_at",
        "closed_at",
        "close_reason",
        "roll_reference_exit_price",
        "roll_reference_bar_end",
        "contract_multiplier_snapshot",
        "multiplier_policy_id",
        "created_at",
        "updated_at",
    }
    assert _column_names(recorder, "trade_reviews") == {
        "id",
        "episode_id",
        "signal_execution_adherence",
        "entry_tags",
        "holding_tags",
        "exit_tags",
        "market_context_tags",
        "psychology_tags",
        "summary",
        "submitted_at",
        "created_at",
        "updated_at",
    }


def test_downgrade_fails_closed() -> None:
    migration = _load_migration()

    with pytest.raises(
        RuntimeError,
        match="^EXECUTION_REVIEW_V1_DOWNGRADE_UNSUPPORTED$",
    ):
        migration.downgrade()


@pytest.fixture
def isolated_migration_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Config, Engine]]:
    if not os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip():
        pytest.fail("GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required")
    try:
        url = require_isolated_migration_database_url(
            os.environ,
            identity_probe=probe_database_identity,
        )
    except MigrationTestDatabaseSafetyError as exc:
        pytest.fail(str(exc))

    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(QUANT_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url, pool_pre_ping=True)
    _reset_public_schema(engine)
    try:
        yield config, engine
    finally:
        _reset_public_schema(engine)
        engine.dispose()


def test_upgrade_preserves_market_and_alert_signatures_and_adds_only_four_tables(
    isolated_migration_context: tuple[Config, Engine],
) -> None:
    config, engine = isolated_migration_context
    command.upgrade(config, "20260814_0038")
    before_tables = set(sa_inspect(engine).get_table_names())
    before = {
        table_name: _table_signature(engine, table_name)
        for table_name in EXISTING_TABLES
    }

    command.upgrade(config, "20260815_0039")

    inspector = sa_inspect(engine)
    after_tables = set(inspector.get_table_names())
    after = {
        table_name: _table_signature(engine, table_name)
        for table_name in EXISTING_TABLES
    }
    assert EXISTING_TABLES <= before_tables
    assert after == before
    assert after_tables - before_tables == NEW_TABLES
    assert {
        column["name"]
        for column in inspector.get_columns("trade_executions")
    } >= {"sequence_no", "episode_id", "execution_type"}
    assert {
        constraint["name"]
        for constraint in inspector.get_check_constraints("trade_episodes")
    } == {
        "ck_trade_episodes_closed_at",
        "ck_trade_episodes_direction",
        "ck_trade_episodes_lifecycle",
        "ck_trade_episodes_multiplier_lineage",
        "ck_trade_episodes_multiplier_positive",
    }
    assert {
        constraint["name"]
        for constraint in inspector.get_check_constraints("trade_executions")
    } == {
        "ck_trade_executions_open_sequence",
        "ck_trade_executions_price_positive",
        "ck_trade_executions_quantity_positive",
        "ck_trade_executions_sequence_positive",
        "ck_trade_executions_type",
    }
    assert {
        table_name: {
            constraint["name"]
            for constraint in inspector.get_check_constraints(table_name)
        }
        for table_name in ("trade_decisions", "trade_reviews")
    } == {
        "trade_decisions": {
            "ck_trade_decisions_disposition",
            "ck_trade_decisions_stop_price_positive",
        },
        "trade_reviews": {"ck_trade_reviews_adherence"},
    }
    assert {
        table_name: {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(table_name)
        }
        for table_name in NEW_TABLES
    } == {
        "trade_decisions": {"uq_trade_decisions_alert_event"},
        "trade_episodes": {"uq_trade_episodes_origin_decision"},
        "trade_executions": {
            "uq_trade_executions_episode_sequence",
            "uq_trade_executions_trigger_decision",
        },
        "trade_reviews": {"uq_trade_reviews_episode"},
    }
    assert {
        (
            table_name,
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
        )
        for table_name in NEW_TABLES
        for foreign_key in inspector.get_foreign_keys(table_name)
    } == {
        ("trade_decisions", ("alert_event_id",), "alert_events", ("id",)),
        (
            "trade_episodes",
            ("origin_decision_id",),
            "trade_decisions",
            ("id",),
        ),
        ("trade_executions", ("episode_id",), "trade_episodes", ("id",)),
        (
            "trade_executions",
            ("trigger_decision_id",),
            "trade_decisions",
            ("id",),
        ),
        ("trade_reviews", ("episode_id",), "trade_episodes", ("id",)),
    }
    episode_indexes = {
        index["name"]: index
        for index in inspector.get_indexes("trade_episodes")
    }
    assert episode_indexes["uq_trade_episodes_symbol_open"]["unique"] is True
    assert episode_indexes["uq_trade_episodes_symbol_open"]["column_names"] == [
        "symbol"
    ]

    orm_schema = f"execution_review_orm_{uuid4().hex}"
    orm_metadata = MetaData(schema=orm_schema)
    Table("alert_events", orm_metadata, Column("id", Integer, primary_key=True))
    for model in (TradeDecision, TradeEpisode, TradeExecution, TradeReview):
        model.__table__.to_metadata(orm_metadata, schema=orm_schema)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{orm_schema}"')
        orm_metadata.create_all(connection)
    try:
        for table_name in NEW_TABLES:
            assert _constraint_signature(engine, table_name) == _constraint_signature(
                engine,
                table_name,
                schema=orm_schema,
            )
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f'DROP SCHEMA IF EXISTS "{orm_schema}" CASCADE'
            )


def test_postgres_enforces_sequence_episode_lifecycle_and_unique_constraints(
    isolated_migration_context: tuple[Config, Engine],
) -> None:
    config, engine = isolated_migration_context
    command.upgrade(config, "20260815_0039")
    now = datetime(2026, 8, 15, 8, tzinfo=UTC)

    with engine.begin() as connection:
        decision_ids = _seed_decisions(connection, now, count=10)
        open_episode_id = _insert_episode(
            connection,
            decision_ids[0],
            symbol="jm",
            now=now,
        )
        connection.execute(
            text(
                """
                INSERT INTO trade_executions (
                    episode_id, trigger_decision_id, sequence_no, execution_type,
                    executed_at, price, quantity, created_at, updated_at
                ) VALUES (
                    :episode_id, :trigger_decision_id, 1, 'OPEN',
                    :now, 100, 1, :now, :now
                )
                """
            ),
            {
                "episode_id": open_episode_id,
                "trigger_decision_id": decision_ids[0],
                "now": now,
            },
        )

    invalid_statements = [
        (
            """
            INSERT INTO trade_executions (
                episode_id, sequence_no, execution_type, executed_at,
                price, quantity, created_at, updated_at
            ) VALUES (:episode_id, 1, 'OPEN', :now, 100, 1, :now, :now)
            """,
            {"episode_id": open_episode_id, "now": now},
            "uq_trade_executions_episode_sequence",
        ),
        (
            """
            INSERT INTO trade_executions (
                episode_id, sequence_no, execution_type, executed_at,
                price, quantity, created_at, updated_at
            ) VALUES (:episode_id, 2, 'OPEN', :now, 100, 1, :now, :now)
            """,
            {"episode_id": open_episode_id, "now": now},
            "ck_trade_executions_open_sequence",
        ),
        (
            """
            INSERT INTO trade_episodes (
                origin_decision_id, symbol, contract, direction, opened_at,
                closed_at, close_reason, created_at, updated_at
            ) VALUES (
                :decision_id, 'jm', 'JM2701', 'SHORT', :now,
                NULL, NULL, :now, :now
            )
            """,
            {"decision_id": decision_ids[1], "now": now},
            "uq_trade_episodes_symbol_open",
        ),
        (
            """
            INSERT INTO trade_episodes (
                origin_decision_id, symbol, contract, direction, opened_at,
                closed_at, close_reason, created_at, updated_at
            ) VALUES (
                :decision_id, 'j', 'J2701', 'SHORT', :now,
                :closed_at, NULL, :now, :now
            )
            """,
            {
                "decision_id": decision_ids[2],
                "now": now,
                "closed_at": now + timedelta(hours=1),
            },
            "ck_trade_episodes_lifecycle",
        ),
        (
            """
            INSERT INTO trade_episodes (
                origin_decision_id, symbol, contract, direction, opened_at,
                closed_at, close_reason, roll_reference_exit_price,
                roll_reference_bar_end, created_at, updated_at
            ) VALUES (
                :decision_id, 'i', 'I2701', 'LONG', :now,
                :closed_at, 'DOMINANT_ROLL', NULL, NULL, :now, :now
            )
            """,
            {
                "decision_id": decision_ids[3],
                "now": now,
                "closed_at": now + timedelta(hours=1),
            },
            "ck_trade_episodes_lifecycle",
        ),
        (
            """
            INSERT INTO trade_episodes (
                origin_decision_id, symbol, contract, direction, opened_at,
                closed_at, close_reason, roll_reference_exit_price,
                roll_reference_bar_end, created_at, updated_at
            ) VALUES (
                :decision_id, 'rb', 'RB2701', 'LONG', :now,
                :closed_at, 'EXECUTION_NET_ZERO', 100, :now, :now, :now
            )
            """,
            {
                "decision_id": decision_ids[4],
                "now": now,
                "closed_at": now + timedelta(hours=1),
            },
            "ck_trade_episodes_lifecycle",
        ),
        (
            """
            INSERT INTO trade_episodes (
                origin_decision_id, symbol, contract, direction, opened_at,
                closed_at, close_reason, created_at, updated_at
            ) VALUES (
                :decision_id, 'ag', 'AG2701', 'LONG', :now,
                :closed_at, 'EXECUTION_NET_ZERO', :now, :now
            )
            """,
            {
                "decision_id": decision_ids[5],
                "now": now,
                "closed_at": now - timedelta(seconds=1),
            },
            "ck_trade_episodes_closed_at",
        ),
        (
            """
            INSERT INTO trade_episodes (
                origin_decision_id, symbol, contract, direction, opened_at,
                contract_multiplier_snapshot, multiplier_policy_id,
                created_at, updated_at
            ) VALUES (
                :decision_id, 'cu', 'CU2701', 'LONG', :now,
                5, NULL, :now, :now
            )
            """,
            {"decision_id": decision_ids[6], "now": now},
            "ck_trade_episodes_multiplier_lineage",
        ),
    ]

    for statement, parameters, expected_constraint in invalid_statements:
        with pytest.raises(IntegrityError) as exc_info:
            with engine.begin() as connection:
                connection.execute(text(statement), parameters)
        assert exc_info.value.orig.diag.constraint_name == expected_constraint

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO trade_episodes (
                    origin_decision_id, symbol, contract, direction, opened_at,
                    closed_at, close_reason, roll_reference_exit_price,
                    roll_reference_bar_end,
                    created_at, updated_at
                ) VALUES (
                    :open_decision, 'zn', 'ZN2701', 'LONG', :now,
                    NULL, NULL, NULL, NULL, :now, :now
                ), (
                    :roll_decision, 'ag', 'AG2701', 'LONG', :now,
                    :closed_at, 'DOMINANT_ROLL', 100, :bar_end, :now, :now
                ), (
                    :net_zero_decision, 'al', 'AL2701', 'SHORT', :now,
                    :closed_at, 'EXECUTION_NET_ZERO', NULL, NULL, :now, :now
                )
                """
            ),
            {
                "open_decision": decision_ids[7],
                "roll_decision": decision_ids[8],
                "net_zero_decision": decision_ids[9],
                "now": now,
                "closed_at": now + timedelta(hours=1),
                "bar_end": now + timedelta(minutes=30),
            },
        )


def _column_names(recorder: RecordingOperations, table_name: str) -> set[str]:
    return {
        element.name
        for element in recorder.created_tables[table_name]
        if element.__class__.__name__ == "Column"
    }


def _constraint_names(
    recorder: RecordingOperations,
    table_name: str,
) -> set[str]:
    return {
        element.name
        for element in recorder.created_tables[table_name]
        if element.__class__.__name__.endswith("Constraint")
        and element.name is not None
    }


def _load_migration() -> ModuleType:
    assert MIGRATION_PATH.exists(), f"missing migration: {MIGRATION_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "execution_review_v1_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _reset_public_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")


def _table_signature(engine: Engine, table_name: str) -> dict[str, object]:
    inspector = sa_inspect(engine)
    return {
        "columns": sorted(
            (
                column["name"],
                str(column["type"]),
                column["nullable"],
                str(column.get("default")),
            )
            for column in inspector.get_columns(table_name)
        ),
        "pk": inspector.get_pk_constraint(table_name),
        "fks": sorted(
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
                foreign_key.get("name"),
            )
            for foreign_key in inspector.get_foreign_keys(table_name)
        ),
        "checks": sorted(
            (check.get("name"), check.get("sqltext"))
            for check in inspector.get_check_constraints(table_name)
        ),
        "uniques": sorted(
            (
                unique.get("name"),
                tuple(unique.get("column_names") or ()),
            )
            for unique in inspector.get_unique_constraints(table_name)
        ),
        "indexes": sorted(
            (
                index.get("name"),
                tuple(index.get("column_names") or ()),
                index.get("unique"),
                str(index.get("dialect_options")),
            )
            for index in inspector.get_indexes(table_name)
        ),
    }


def _constraint_signature(
    engine: Engine,
    table_name: str,
    *,
    schema: str | None = None,
) -> dict[str, object]:
    inspector = sa_inspect(engine)
    return {
        "fks": sorted(
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
                foreign_key.get("name"),
            )
            for foreign_key in inspector.get_foreign_keys(
                table_name,
                schema=schema,
            )
        ),
        "checks": sorted(
            (check.get("name"), check.get("sqltext"))
            for check in inspector.get_check_constraints(
                table_name,
                schema=schema,
            )
        ),
        "uniques": sorted(
            (
                unique.get("name"),
                tuple(unique.get("column_names") or ()),
            )
            for unique in inspector.get_unique_constraints(
                table_name,
                schema=schema,
            )
        ),
        "indexes": sorted(
            (
                index.get("name"),
                tuple(index.get("column_names") or ()),
                index.get("unique"),
                str(index.get("dialect_options")),
            )
            for index in inspector.get_indexes(
                table_name,
                schema=schema,
            )
            if not index.get("duplicates_constraint")
        ),
    }


def _seed_decisions(connection: Any, now: datetime, *, count: int) -> list[int]:
    rule_id = connection.execute(
        text(
            """
            INSERT INTO alert_rules (
                rule_code, enabled, scope_products, created_at, updated_at
            ) VALUES (
                'execution_review_migration_test', false, '{}', :now, :now
            ) RETURNING id
            """
        ),
        {"now": now},
    ).scalar_one()
    decision_ids: list[int] = []
    for index in range(count):
        event_id = connection.execute(
            text(
                """
                INSERT INTO alert_events (
                    rule_id, symbol, contract, frequency, bar_end, result_codes,
                    detected_at, notification_attempted_at, created_at,
                    trading_day, lower_tf_confirmation
                ) VALUES (
                    :rule_id, :symbol, :contract, '15m', :now, ARRAY['sell'],
                    :now, NULL, :now, DATE '2026-08-15', false
                ) RETURNING id
                """
            ),
            {
                "rule_id": rule_id,
                "symbol": f"t{index}",
                "contract": f"T{index}2701",
                "now": now,
            },
        ).scalar_one()
        decision_ids.append(
            connection.execute(
                text(
                    """
                    INSERT INTO trade_decisions (
                        alert_event_id, disposition, decided_at,
                        secondary_not_execute_reasons, execution_reason_tags,
                        created_at, updated_at
                    ) VALUES (
                        :event_id, 'EXECUTED', :now, '{}', ARRAY['LOCATION_ACCEPTABLE'],
                        :now, :now
                    ) RETURNING id
                    """
                ),
                {"event_id": event_id, "now": now},
            ).scalar_one()
        )
    return decision_ids


def _insert_episode(
    connection: Any,
    decision_id: int,
    *,
    symbol: str,
    now: datetime,
) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO trade_episodes (
                origin_decision_id, symbol, contract, direction, opened_at,
                created_at, updated_at
            ) VALUES (
                :decision_id, :symbol, 'JM2609', 'SHORT', :now, :now, :now
            ) RETURNING id
            """
        ),
        {"decision_id": decision_id, "symbol": symbol, "now": now},
    ).scalar_one()
