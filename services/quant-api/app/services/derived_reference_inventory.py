"""Read-only inventory for V2 derived and legacy-reference retirement planning.

The inventory intentionally describes candidates without authorizing migration,
repair, deletion, or any provider access.  It accepts explicit roots and an
optional injected DB-API connection so fixtures and external read-only Gates
can exercise exactly the same collector.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable


SCHEMA_VERSION = 1
COMMAND = "derived-reference-inventory"
CATEGORY_ORDER = (
    "indicator_cache",
    "backtest",
    "signal_review",
    "live_eod_sample",
    "permanent_derived_periods",
    "duplicate_bar_layers",
    "profile_binding_legacy_lineage",
    "report_14_15_references",
)

_CATEGORY_REASONS = {
    "indicator_cache": "indicator and cache outputs are rebuild-only derived artifacts",
    "backtest": "backtest tasks, reports, trades, and orders are rebuild-only consumer outputs",
    "signal_review": "signal and review records are consumer evidence, not historical canonical bars",
    "live_eod_sample": "live, EOD, and research-sample surfaces remain isolated observation outputs",
    "permanent_derived_periods": "derived periods are regenerated from provider-direct canonical 1m bars",
    "duplicate_bar_layers": "raw, standard, and canonical bar layers require explicit retirement classification",
    "profile_binding_legacy_lineage": "Profile, Binding, and legacy lineage remain compatibility-only",
    "report_14_15_references": "report 14/15 references are Git-traceable historical snapshots, not active Gates",
}
_REFERENCE_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".sh", ".ts", ".tsx", ".vue"}
_IGNORED_DIRS = {".git", ".venv", "node_modules", "dist", "__pycache__"}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REPORT_REFERENCE = re.compile(r"report(?:[_\s-]*(?:id)?[_\s:=]*)?(?:14|15)(?:\b|_)", re.IGNORECASE)


@dataclass(frozen=True)
class DerivedReferenceInventoryConfig:
    repo_root: Path
    data_root: Path


def build_derived_reference_inventory(
    config: DerivedReferenceInventoryConfig,
    *,
    connection: Any | None = None,
) -> dict[str, Any]:
    """Collect a deterministic, read-only inventory without touching RQData."""

    repo_root = config.repo_root.resolve(strict=False)
    data_root = config.data_root.resolve(strict=False)
    database, table_inventory = _read_database_inventory(connection)
    filesystem = _read_filesystem_inventory(data_root)
    references = _read_reference_locations(repo_root)
    categories = []
    for category in CATEGORY_ORDER:
        categories.append(
            {
                "category": category,
                "reason": _CATEGORY_REASONS[category],
                "database_tables": _tables_for_category(category, table_inventory),
                "filesystem_paths": _paths_for_category(category, filesystem),
                "reference_locations": _references_for_category(category, references),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "command": COMMAND,
        "readonly": True,
        "safety": {
            "calls_rqdata": False,
            "filesystem_operations": ["read", "stat", "hash"],
            "readonly_database_transaction": True,
            "writes_database": False,
            "writes_filesystem": False,
        },
        "database": database,
        "filesystem": {
            "data_root_exists": data_root.is_dir(),
            "data_root_path": str(data_root),
        },
        "categories": categories,
    }


def _read_database_inventory(connection: Any | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if connection is None:
        return {"available": False, "dialect": None, "tables": []}, []
    dialect = _dialect_name(connection)
    try:
        if dialect == "sqlite":
            connection.execute("PRAGMA query_only = ON")
            names = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()]
            columns = {
                name: {row[1] for row in connection.execute(f"PRAGMA table_info({_quote_identifier(name)})").fetchall()}
                for name in names
            }
        elif dialect == "postgresql":
            _execute(connection, "BEGIN")
            _execute(connection, "SET TRANSACTION READ ONLY")
            names = [
                row[0]
                for row in _fetchall(
                    connection,
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name",
                )
            ]
            columns = {
                name: {
                    row[0]
                    for row in _fetchall(
                        connection,
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
                        (name,),
                    )
                }
                for name in names
            }
        else:
            return {"available": False, "dialect": dialect, "tables": []}, []
        inventory = [_table_record(connection, name, columns[name]) for name in names]
        return {"available": True, "dialect": dialect, "tables": inventory}, inventory
    finally:
        if dialect == "postgresql":
            connection.rollback()


def _dialect_name(connection: Any) -> str:
    if isinstance(connection, sqlite3.Connection):
        return "sqlite"
    dialect = getattr(getattr(connection, "dialect", None), "name", None)
    if isinstance(dialect, str):
        return dialect
    module_name = type(connection).__module__.lower()
    return "postgresql" if "psycopg" in module_name or "postgres" in module_name else "unknown"


def _table_record(connection: Any, name: str, columns: set[str]) -> dict[str, Any]:
    quoted = _quote_identifier(name)
    count = int(_fetchall(connection, f"SELECT COUNT(*) FROM {quoted}")[0][0])
    identifiers = []
    if "id" in columns:
        identifiers = [str(row[0]) for row in _fetchall(connection, f"SELECT id FROM {quoted} ORDER BY id")]
    return {"table": name, "count": count, "ids": identifiers}


def _execute(connection: Any, statement: str) -> None:
    if isinstance(connection, sqlite3.Connection):
        connection.execute(statement)
        return
    cursor = connection.cursor()
    try:
        cursor.execute(statement)
    finally:
        cursor.close()


def _fetchall(
    connection: Any,
    statement: str,
    parameters: tuple[Any, ...] | None = None,
) -> list[tuple[Any, ...]]:
    if isinstance(connection, sqlite3.Connection):
        return list(connection.execute(statement, parameters or ()).fetchall())
    cursor = connection.cursor()
    try:
        cursor.execute(statement, parameters or ())
        return list(cursor.fetchall())
    finally:
        cursor.close()


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError("inventory received an unsafe database identifier")
    return f'"{value}"'


def _read_filesystem_inventory(data_root: Path) -> list[dict[str, Any]]:
    if not data_root.is_dir():
        return []
    records = []
    for path in sorted(item for item in data_root.rglob("*") if item.is_file()):
        relative = path.relative_to(data_root).as_posix()
        records.append(
            {
                "relative": relative,
                "path": f"{data_root.name}/{relative}",
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return records


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_reference_locations(repo_root: Path) -> list[dict[str, Any]]:
    if not repo_root.is_dir():
        return []
    locations = []
    for path in sorted(item for item in repo_root.rglob("*") if _is_reference_file(repo_root, item)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(repo_root).as_posix()
        for line_number, line in enumerate(lines, start=1):
            if _REPORT_REFERENCE.search(line):
                locations.append({"path": relative, "line": line_number})
    return locations


def _is_reference_file(repo_root: Path, path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in _REFERENCE_SUFFIXES:
        return False
    return not any(part in _IGNORED_DIRS for part in path.relative_to(repo_root).parts)


def _tables_for_category(category: str, inventory: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in inventory if _matches_table_category(category, record["table"])]


def _matches_table_category(category: str, table: str) -> bool:
    if category == "indicator_cache":
        return "indicator" in table or "cache" in table
    if category == "backtest":
        return table.startswith("backtest_")
    if category == "signal_review":
        return table.startswith(("signal_", "strategy_signal", "review_"))
    if category == "live_eod_sample":
        return table.startswith(("live_", "after_market_", "research_sample"))
    if category == "permanent_derived_periods":
        return table in {"market_partitions", "market_datasets"}
    if category == "duplicate_bar_layers":
        return table in {"market_data_files", "market_datasets", "market_partitions", "data_gaps"}
    if category == "profile_binding_legacy_lineage":
        return table in {"data_profiles", "profile_active_bindings"} or "lineage" in table
    return False


def _paths_for_category(category: str, inventory: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [record for record in inventory if _matches_path_category(category, record["relative"])]
    return [{key: record[key] for key in ("path", "size_bytes", "sha256")} for record in selected]


def _matches_path_category(category: str, relative: str) -> bool:
    normalized = relative.lower()
    parts = set(normalized.split("/"))
    if category == "indicator_cache":
        return "indicator" in normalized or "cache" in normalized
    if category == "backtest":
        return "backtest" in normalized
    if category == "signal_review":
        return "signal" in normalized or "review" in normalized
    if category == "live_eod_sample":
        return bool(parts & {"live", "eod", "samples", "research_samples"}) or "after_market" in normalized
    if category == "permanent_derived_periods":
        return "derived" in parts and any(period in normalized for period in ("5m", "15m", "30m", "60m"))
    if category == "duplicate_bar_layers":
        return bool(parts & {"raw", "standard", "canonical"})
    if category == "profile_binding_legacy_lineage":
        return any(term in normalized for term in ("profile", "binding", "lineage", "legacy"))
    if category == "report_14_15_references":
        return bool(_REPORT_REFERENCE.search(normalized))
    return False


def _references_for_category(category: str, references: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(references) if category == "report_14_15_references" else []
