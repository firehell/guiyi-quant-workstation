from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

from app.services.derived_reference_inventory import (
    DerivedReferenceInventoryConfig,
    build_derived_reference_inventory,
)


def test_inventory_is_deterministic_and_classifies_read_only_surfaces(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    _write_fixture_files(repo_root, data_root)
    connection = _fixture_connection()

    first = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=connection,
    )
    second = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=connection,
    )

    assert first == second
    assert first["schema_version"] == 1
    assert first["command"] == "derived-reference-inventory"
    assert first["safety"] == {
        "calls_rqdata": False,
        "filesystem_operations": ["read", "stat", "hash"],
        "readonly_database_transaction": True,
        "writes_database": False,
        "writes_filesystem": False,
    }
    assert [item["category"] for item in first["categories"]] == [
        "indicator_cache",
        "backtest",
        "signal_review",
        "live_eod_sample",
        "permanent_derived_periods",
        "duplicate_bar_layers",
        "profile_binding_legacy_lineage",
        "report_14_15_references",
    ]

    categories = {item["category"]: item for item in first["categories"]}
    assert all(
        item["database_tables"] or item["filesystem_paths"] or item["reference_locations"]
        for item in categories.values()
    )
    assert categories["backtest"]["database_tables"] == [
        {"count": 1, "ids": ["7"], "table": "backtest_reports"}
    ]
    assert categories["profile_binding_legacy_lineage"]["database_tables"] == [
        {"count": 1, "ids": ["8"], "table": "data_profiles"},
        {"count": 1, "ids": ["9"], "table": "profile_active_bindings"},
    ]
    assert categories["duplicate_bar_layers"]["filesystem_paths"] == [
        {
            "path": "data/parquet/canonical/jm/part-000.parquet",
            "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            "size_bytes": 3,
        },
        {
            "path": "data/raw/jm/source.parquet",
            "sha256": "7692c3ad3540bb803c020b3aee66cd8887123234ea0c6e7143c0add73ff431ed",
            "size_bytes": 3,
        },
        {
            "path": "data/standard/jm/normalized.parquet",
            "sha256": "3fc4ccfe745870e2c0d99f71f30ff0656c8dedd41cc1d7d3d376b0dbe685e2f3",
            "size_bytes": 3,
        },
    ]
    assert categories["report_14_15_references"]["reference_locations"] == [
        {"line": 1, "path": "docs/gate.md"},
        {"line": 1, "path": "services/quant-api/app/example.py"},
    ]


def test_inventory_uses_sqlite_query_only_and_never_emits_write_statement(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "absent-data-root"
    repo_root.mkdir()
    connection = _fixture_connection()
    statements: list[str] = []
    connection.set_trace_callback(statements.append)

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=connection,
    )

    assert result["database"]["dialect"] == "sqlite"
    assert result["filesystem"]["data_root_exists"] is False
    assert any(statement.upper().startswith("PRAGMA QUERY_ONLY = ON") for statement in statements)
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "COMMIT"))
        for statement in statements
    )


def test_cli_emits_stable_json_without_database_configuration(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    _write_fixture_files(repo_root, data_root)
    script = Path(__file__).resolve().parents[3] / "scripts" / "derived_reference_inventory.py"
    command = [sys.executable, str(script), "--repo-root", str(repo_root), "--data-root", str(data_root)]

    first = subprocess.run(command, check=False, capture_output=True, text=True)
    second = subprocess.run(command, check=False, capture_output=True, text=True)

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stderr == second.stderr == ""
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["database"]["available"] is False
    assert payload["readonly"] is True


def test_cli_rejects_delete_and_redacts_injected_database_url(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[3] / "scripts" / "derived_reference_inventory.py"
    secret_url = "postgresql://inventory_user:do-not-print@db.example.invalid/inventory"

    delete_attempt = subprocess.run([sys.executable, str(script), "--delete"], check=False, capture_output=True, text=True)
    invalid_database = subprocess.run(
        [sys.executable, str(script), "--database-url", secret_url, "--repo-root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert delete_attempt.returncode == 2
    assert invalid_database.returncode == 2
    assert secret_url not in invalid_database.stdout + invalid_database.stderr
    assert json.loads(invalid_database.stderr)["command"] == "derived-reference-inventory"


def test_postgresql_collector_sets_read_only_transaction_without_commit(tmp_path: Path) -> None:
    connection = _FakePostgresConnection()

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=tmp_path / "missing-repo", data_root=tmp_path / "missing-data"),
        connection=connection,
    )

    assert result["database"] == {
        "available": True,
        "dialect": "postgresql",
        "tables": [{"count": 1, "ids": ["14"], "table": "backtest_reports"}],
    }
    assert connection.statements[:2] == ["BEGIN", "SET TRANSACTION READ ONLY"]
    assert connection.rollback_count == 1
    assert connection.commit_count == 0
    assert not any(
        statement.upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"))
        for statement in connection.statements
    )


def _fixture_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE backtest_reports (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE strategy_signals (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE review_notes (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE data_profiles (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE profile_active_bindings (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE live_minute_bars (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE indicator_cache (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE market_datasets (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE market_partitions (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE market_data_files (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE data_gaps (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO backtest_reports VALUES (7, 'report');
        INSERT INTO strategy_signals VALUES (3, 'signal');
        INSERT INTO review_notes VALUES (4, 'note');
        INSERT INTO data_profiles VALUES (8, 'profile');
        INSERT INTO profile_active_bindings VALUES (9, 'binding');
        INSERT INTO live_minute_bars VALUES (2, 'live');
        INSERT INTO indicator_cache VALUES (1, 'cache');
        INSERT INTO market_datasets VALUES (10, 'dataset');
        INSERT INTO market_partitions VALUES (11, 'partition');
        INSERT INTO market_data_files VALUES (12, 'file');
        INSERT INTO data_gaps VALUES (13, 'gap');
        """
    )
    connection.commit()
    return connection


def _write_fixture_files(repo_root: Path, data_root: Path) -> None:
    (repo_root / "docs").mkdir(parents=True)
    (repo_root / "services" / "quant-api" / "app").mkdir(parents=True)
    (repo_root / "docs" / "gate.md").write_text("report 14 backup\n", encoding="utf-8")
    (repo_root / "services" / "quant-api" / "app" / "example.py").write_text(
        "report_15_runtime_gate = True\n",
        encoding="utf-8",
    )
    for relative_path, contents in (
        ("raw/jm/source.parquet", b"one"),
        ("standard/jm/normalized.parquet", b"two"),
        ("parquet/canonical/jm/part-000.parquet", b"abc"),
        ("derived/indicators/cache.json", b"{}"),
        ("derived/15m/part.parquet", b"derived"),
        ("backtest/run.json", b"{}"),
        ("signals/event.json", b"{}"),
        ("reviews/note.json", b"{}"),
        ("live/bar.json", b"{}"),
        ("eod/reconcile.json", b"{}"),
        ("samples/sample.json", b"{}"),
        ("legacy/profile/binding.json", b"{}"),
        ("reports/report_14_snapshot.json", b"{}"),
    ):
        path = data_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)


class _FakePostgresConnection:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.rollback_count = 0
        self.commit_count = 0

    def cursor(self) -> _FakePostgresCursor:
        return _FakePostgresCursor(self)

    def rollback(self) -> None:
        self.rollback_count += 1

    def commit(self) -> None:
        self.commit_count += 1


class _FakePostgresCursor:
    def __init__(self, connection: _FakePostgresConnection) -> None:
        self.connection = connection
        self.statement = ""

    def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> None:
        self.statement = statement
        self.connection.statements.append(statement + (f" {parameters!r}" if parameters else ""))

    def fetchall(self) -> list[tuple[object, ...]]:
        if "information_schema.tables" in self.statement:
            return [("backtest_reports",)]
        if "information_schema.columns" in self.statement:
            return [("id",)]
        if "COUNT(*)" in self.statement:
            return [(1,)]
        if "SELECT id" in self.statement:
            return [(14,)]
        return []

    def close(self) -> None:
        return None
