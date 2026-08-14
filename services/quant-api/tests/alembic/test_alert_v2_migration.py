from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = QUANT_API_ROOT / "alembic/versions/20260814_0038_alert_v2.py"
MARKET_TABLES = {
    "exchanges",
    "instruments",
    "contracts",
    "trading_calendars",
    "trading_sessions",
    "main_contract_map",
    "market_datasets",
    "market_partitions",
}
COLLISION_QUERY = """SELECT rule_id, symbol, bar_end, COUNT(*) AS n
FROM alert_events
GROUP BY rule_id, symbol, bar_end
HAVING COUNT(*) > 1
LIMIT 1"""


class RecordingResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def first(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None


class RecordingBind:
    def __init__(
        self,
        recorder: RecordingOperations,
        conflict_rows: list[tuple[object, ...]],
    ) -> None:
        self._recorder = recorder
        self._conflict_rows = conflict_rows

    def execute(self, statement: object) -> RecordingResult:
        sql = str(statement).strip()
        self._recorder.actions.append(("execute", sql))
        self._recorder.executed_sql.append(sql)
        return RecordingResult(self._conflict_rows)


class RecordingOperations:
    def __init__(self, conflict_rows: list[tuple[object, ...]]) -> None:
        self.actions: list[tuple[object, ...]] = []
        self.executed_sql: list[str] = []
        self.market_table_mutations: list[tuple[str, str]] = []
        self.dropped_constraints: list[tuple[str, str, str | None]] = []
        self.renamed_columns: list[tuple[str, str, str]] = []
        self.added_columns: list[tuple[str, object]] = []
        self.dropped_columns: list[tuple[str, str]] = []
        self.created_unique_constraints: list[tuple[str, str, tuple[str, ...]]] = []
        self.created_check_constraints: list[tuple[str, str, str]] = []
        self.seed_table_columns: tuple[str, ...] = ()
        self.seed_rows: list[dict[str, object]] = []
        self.destructive_schema_started = False
        self._bind = RecordingBind(self, conflict_rows)

    def get_bind(self) -> RecordingBind:
        self.actions.append(("get_bind",))
        return self._bind

    def drop_constraint(
        self,
        constraint_name: str,
        table_name: str,
        type_: str | None = None,
        **_: object,
    ) -> None:
        self._record_mutation("drop_constraint", table_name)
        self.dropped_constraints.append((constraint_name, table_name, type_))

    def alter_column(
        self,
        table_name: str,
        column_name: str,
        **kwargs: object,
    ) -> None:
        self._record_mutation("alter_column", table_name)
        new_column_name = kwargs.get("new_column_name")
        if isinstance(new_column_name, str):
            self.renamed_columns.append((table_name, column_name, new_column_name))

    def add_column(self, table_name: str, column: object) -> None:
        self._record_mutation("add_column", table_name)
        self.added_columns.append((table_name, column))

    def drop_column(self, table_name: str, column_name: str) -> None:
        self._record_mutation("drop_column", table_name)
        self.dropped_columns.append((table_name, column_name))

    def create_unique_constraint(
        self,
        constraint_name: str,
        table_name: str,
        columns: list[str] | tuple[str, ...],
        **_: object,
    ) -> None:
        self._record_mutation("create_unique_constraint", table_name)
        self.created_unique_constraints.append(
            (constraint_name, table_name, tuple(columns))
        )

    def create_check_constraint(
        self,
        constraint_name: str,
        table_name: str,
        condition: object,
        **_: object,
    ) -> None:
        self._record_mutation("create_check_constraint", table_name)
        self.created_check_constraints.append(
            (constraint_name, table_name, str(condition))
        )

    def bulk_insert(self, table: object, rows: list[dict[str, object]]) -> None:
        table_name = str(getattr(table, "name"))
        self._record_mutation("bulk_insert", table_name)
        self.seed_table_columns = tuple(table.c.keys())  # type: ignore[attr-defined]
        self.seed_rows.extend(rows)

    def _record_mutation(self, operation: str, table_name: str) -> None:
        self.destructive_schema_started = True
        self.actions.append((operation, table_name))
        if table_name in MARKET_TABLES:
            self.market_table_mutations.append((operation, table_name))


def test_alert_v2_upgrade_changes_only_alert_application_schema() -> None:
    migration = _load_migration()
    recorder = RecordingOperations(conflict_rows=[])
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260814_0038"
    assert migration.down_revision == "20260813_0037"
    assert recorder.actions[:2] == [("get_bind",), ("execute", COLLISION_QUERY)]
    assert recorder.executed_sql == [COLLISION_QUERY]
    assert recorder.market_table_mutations == []
    assert ("alert_rules", "indicator_code") in recorder.dropped_columns
    assert ("alert_rules", "frequency") in recorder.dropped_columns
    assert ("alert_rules", "scope_mode") in recorder.dropped_columns
    assert (
        "ck_alert_rules_frequency",
        "alert_rules",
        "check",
    ) in recorder.dropped_constraints
    assert (
        "ck_alert_rules_scope_mode",
        "alert_rules",
        "check",
    ) in recorder.dropped_constraints
    assert (
        "alert_events",
        "observation_types",
        "result_codes",
    ) in recorder.renamed_columns
    assert (
        "alert_events",
        "notified_at",
        "notification_attempted_at",
    ) in recorder.renamed_columns
    assert _added_column(recorder, "alert_events", "trading_day").nullable is True
    lower_tf_confirmation = _added_column(
        recorder, "alert_events", "lower_tf_confirmation"
    )
    assert lower_tf_confirmation.nullable is False
    assert str(lower_tf_confirmation.server_default.arg) == "false"
    assert (
        "uq_alert_events_rule_symbol_frequency_bar_end",
        "alert_events",
        "unique",
    ) in recorder.dropped_constraints
    assert recorder.created_unique_constraints == [
        (
            "uq_alert_events_rule_symbol_bar_end",
            "alert_events",
            ("rule_id", "symbol", "bar_end"),
        )
    ]
    assert (
        "ck_alert_events_observation_types",
        "alert_events",
        "check",
    ) in recorder.dropped_constraints
    assert recorder.created_check_constraints == [
        (
            "ck_alert_events_result_codes",
            "alert_events",
            "cardinality(result_codes) BETWEEN 1 AND 2 "
            "AND result_codes <@ ARRAY['buy','sell']::varchar[]",
        )
    ]
    assert recorder.seed_table_columns == (
        "rule_code",
        "enabled",
        "scope_products",
    )
    assert recorder.seed_rows == [
        {
            "rule_code": "subing_entry_signal_v1",
            "enabled": True,
            "scope_products": [],
        }
    ]


def test_alert_v2_upgrade_refuses_new_identity_collision() -> None:
    migration = _load_migration()
    recorder = RecordingOperations(
        conflict_rows=[(1, "jm", "2026-08-14T02:30:00+00:00", 2)]
    )
    migration.op = recorder

    with pytest.raises(RuntimeError, match="^ALERT_V2_EVENT_IDENTITY_CONFLICT$"):
        migration.upgrade()

    assert recorder.actions == [("get_bind",), ("execute", COLLISION_QUERY)]
    assert recorder.destructive_schema_started is False


def test_alert_v2_downgrade_fails_closed() -> None:
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="^ALERT_V2_DOWNGRADE_UNSUPPORTED$"):
        migration.downgrade()


def _added_column(
    recorder: RecordingOperations,
    table_name: str,
    column_name: str,
) -> Any:
    matches = [
        column
        for recorded_table, column in recorder.added_columns
        if recorded_table == table_name and getattr(column, "name", None) == column_name
    ]
    assert len(matches) == 1
    return matches[0]


def _load_migration() -> object:
    assert MIGRATION_PATH.exists(), f"missing migration: {MIGRATION_PATH.name}"
    spec = importlib.util.spec_from_file_location("alert_v2_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration
