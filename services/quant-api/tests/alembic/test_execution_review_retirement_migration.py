from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    QUANT_API_ROOT
    / "alembic/versions/20260826_0041_retire_execution_review.py"
)
TRADE_TABLES = {
    "trade_decisions",
    "trade_episodes",
    "trade_executions",
    "trade_reviews",
}


class RecordingOperations:
    def __init__(self) -> None:
        self.created_tables: list[str] = []
        self.created_indexes: list[tuple[str, str]] = []
        self.dropped_tables: list[str] = []

    def create_table(self, name: str, *_: Any, **__: Any) -> object:
        self.created_tables.append(name)
        return object()

    def create_index(
        self,
        name: str,
        table_name: str,
        *_: Any,
        **__: Any,
    ) -> None:
        self.created_indexes.append((name, table_name))

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)


def test_upgrade_drops_only_execution_review_tables_in_dependency_order() -> None:
    migration = _load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260826_0041"
    assert migration.down_revision == "20260825_0040"
    assert recorder.dropped_tables == [
        "trade_reviews",
        "trade_executions",
        "trade_episodes",
        "trade_decisions",
    ]
    assert recorder.created_tables == []


def test_downgrade_recreates_the_empty_historical_schema() -> None:
    migration = _load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.downgrade()

    assert set(recorder.created_tables) == TRADE_TABLES
    assert recorder.dropped_tables == []
    assert recorder.created_indexes == [
        ("uq_trade_episodes_symbol_open", "trade_episodes")
    ]


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "execution_review_retirement_migration",
        MIGRATION_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
