from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = QUANT_API_ROOT / "alembic/versions/20260813_0037_alert_v1.py"
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


class RecordingOperations:
    def __init__(self) -> None:
        self.created_tables: dict[str, tuple[Any, ...]] = {}
        self.created_indexes: list[tuple[str, str, tuple[str, ...]]] = []
        self.seed_rows: list[dict[str, object]] = []
        self.dropped_tables: list[str] = []
        self.forbidden_calls: list[tuple[str, str]] = []

    def create_table(self, name: str, *elements: Any) -> object:
        self.created_tables[name] = elements
        return type("CreatedTable", (), {"name": name})()

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str] | tuple[str, ...],
        **_: object,
    ) -> None:
        self.created_indexes.append((name, table_name, tuple(columns)))

    def bulk_insert(self, _: object, rows: list[dict[str, object]]) -> None:
        self.seed_rows.extend(rows)

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)

    def alter_column(self, table_name: str, *_: object, **__: object) -> None:
        self.forbidden_calls.append(("alter_column", table_name))

    def drop_column(self, table_name: str, *_: object, **__: object) -> None:
        self.forbidden_calls.append(("drop_column", table_name))


def test_alert_v1_upgrade_creates_only_application_tables_and_empty_scope_seed() -> None:
    migration = _load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260813_0037"
    assert migration.down_revision == "20260808_0036"
    assert set(recorder.created_tables) == {"alert_rules", "alert_events"}
    assert MARKET_TABLES.isdisjoint(recorder.created_tables)
    assert recorder.forbidden_calls == []
    assert recorder.created_indexes == [
        ("ix_alert_events_symbol_bar_end", "alert_events", ("symbol", "bar_end"))
    ]
    assert recorder.seed_rows == [
        {
            "rule_code": "htdy_original_15m",
            "indicator_code": "huotian_dayou_original_v0",
            "frequency": "15m",
            "enabled": True,
            "scope_mode": "watchlist",
            "scope_products": [],
        }
    ]


def test_alert_v1_downgrade_drops_only_alert_tables_in_dependency_order() -> None:
    migration = _load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.downgrade()

    assert recorder.dropped_tables == ["alert_events", "alert_rules"]
    assert MARKET_TABLES.isdisjoint(recorder.dropped_tables)


def _load_migration() -> object:
    assert MIGRATION_PATH.exists(), f"missing migration: {MIGRATION_PATH.name}"
    spec = importlib.util.spec_from_file_location("alert_v1_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration
