"""Bounded read-only inventory for derived and legacy-reference retirement planning."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import sqlite3
import stat
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
DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_FILE_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_IDS = 1_000

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
_CATEGORY_TABLES = {
    "indicator_cache": (),
    "backtest": ("backtest_orders", "backtest_reports", "backtest_tasks", "backtest_trades"),
    "signal_review": (
        "review_attachments", "review_notes", "review_tags", "signal_events", "signal_notifications",
        "signal_scan_tasks", "strategy_signals",
    ),
    "live_eod_sample": (
        "after_market_scheduler_checkpoints", "live_aggregated_bars", "live_aggregation_checkpoints",
        "live_ingest_checkpoints", "live_minute_bars",
    ),
    "permanent_derived_periods": (),
    "duplicate_bar_layers": (),
    "profile_binding_legacy_lineage": ("data_profiles", "profile_active_bindings"),
    "report_14_15_references": (),
}
_TRUSTED_METADATA_TABLES = ("data_gaps", "main_contract_map", "market_datasets", "market_partitions")
_REVIEW_METADATA_TABLES = ("market_data_files",)
_ALLOWED_TABLES = tuple(sorted({table for tables in _CATEGORY_TABLES.values() for table in tables} | set(_TRUSTED_METADATA_TABLES) | set(_REVIEW_METADATA_TABLES)))
_MARKET_DATA_FILE_COLUMNS = (
    "id", "provider", "data_type", "period", "file_path", "data_version", "data_role", "quality_status",
)
_CATALOG_DATASET_COLUMNS = ("id", "provider", "dataset_kind", "frequency")
_CATALOG_PARTITION_COLUMNS = ("id", "dataset_id", "file_uri", "manifest_uri", "manifest_digest", "checksum")
_REFERENCE_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".toml", ".sql", ".html", ".js", ".txt", ".sh", ".ts", ".tsx", ".vue"}
_IGNORED_DIRS = {".git", ".venv", "node_modules", "dist", "__pycache__", ".superpowers"}
_SELF_REFERENCE_PATHS = {
    "scripts/derived_reference_inventory.py",
    "services/quant-api/app/services/derived_reference_inventory.py",
    "services/quant-api/tests/test_derived_reference_inventory.py",
}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NON_ACTIVE_MARKER = re.compile(r"\b(?:historical|frozen|superseded|not\s+active|non-active|archive|compatibility-only)\b", re.IGNORECASE)


@dataclass(frozen=True)
class _ReferenceRule:
    pattern: re.Pattern[str]
    reason: str


_REFERENCE_RULES = {
    "indicator_cache": (_ReferenceRule(re.compile(r"\b(?:indicator|cache)\b", re.IGNORECASE), "active indicator/cache reference"),),
    "backtest": (_ReferenceRule(re.compile(r"\b(?:backtest|BacktestService)\b", re.IGNORECASE), "active backtest reference"),),
    "signal_review": (_ReferenceRule(re.compile(r"\b(?:signal|review|SignalEvent|ReviewNote)\b", re.IGNORECASE), "active signal/review reference"),),
    "live_eod_sample": (_ReferenceRule(re.compile(r"\b(?:live|eod|after[_ -]?market|ResearchSample)\b", re.IGNORECASE), "active live/EOD/sample reference"),),
    "permanent_derived_periods": (_ReferenceRule(re.compile(r"\b(?:derived|5m|15m|30m|60m)\b", re.IGNORECASE), "derived-period reference"),),
    "duplicate_bar_layers": (_ReferenceRule(re.compile(r"\b(?:raw|standard|canonical|MarketDataFile)\b", re.IGNORECASE), "bar-layer reference"),),
    "profile_binding_legacy_lineage": (_ReferenceRule(re.compile(r"\b(?:DataProfile|ActiveBinding|profile|binding|legacy[ _-]?lineage)\b", re.IGNORECASE), "legacy compatibility reference"),),
    "report_14_15_references": (_ReferenceRule(re.compile(r"\breport(?:[_\s-]*(?:id)?[_\s:=]*)?(?:14|15)(?:\b|_)", re.IGNORECASE), "report 14/15 historical reference"),),
}


@dataclass(frozen=True)
class DerivedReferenceInventoryConfig:
    repo_root: Path
    data_root: Path
    max_files: int = DEFAULT_MAX_FILES
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES
    max_ids: int = DEFAULT_MAX_IDS


def build_derived_reference_inventory(
    config: DerivedReferenceInventoryConfig,
    *,
    connection: Any | None = None,
) -> dict[str, Any]:
    """Collect bounded evidence without provider calls, DB writes, or filesystem writes."""

    _validate_limits(config)
    repo_root = config.repo_root.resolve(strict=False)
    data_root = config.data_root.absolute()
    database, table_inventory = _read_database_inventory(connection, max_ids=config.max_ids)
    filesystem = _read_filesystem_inventory(data_root, config)
    references, reference_scan = _read_reference_locations(repo_root, config)
    categories = []
    for category in CATEGORY_ORDER:
        category_references = references[category]
        active_references = [item for item in category_references if item["reference_state"] == "active"]
        categories.append(
            {
                "category": category,
                "reason": _CATEGORY_REASONS[category],
                "database_tables": _tables_for_category(category, table_inventory, database.get("market_data_file_classifications", [])),
                "database_scope": "NOT_APPLICABLE" if not _CATEGORY_TABLES[category] else "APPLICABLE",
                "filesystem_paths": _paths_for_category(category, filesystem["records"]),
                "reference_locations": category_references,
                "active_reference_status": "present" if active_references else "zero_active_references",
                "non_active_reference_count": len(category_references) - len(active_references),
            }
        )
    diagnostics = [*database["diagnostics"], *filesystem["diagnostics"], *reference_scan["diagnostics"]]
    status = "complete" if database["available"] and filesystem["data_root_exists"] and repo_root.is_dir() and not diagnostics and not filesystem["truncated"] and not reference_scan["truncated"] else "incomplete"
    return {
        "schema_version": SCHEMA_VERSION,
        "command": COMMAND,
        "readonly": True,
        "safety": {
            "calls_rqdata": False,
            "filesystem_operations": ["read", "stat", "hash"],
            "readonly_database_transaction": database["available"],
            "writes_database": False,
            "writes_filesystem": False,
        },
        "database": database,
        "filesystem": filesystem,
        "reference_scan": reference_scan,
        "categories": categories,
        "status": status,
        "task07_zero_active_reference_eligible": status == "complete" and all(item["active_reference_status"] == "zero_active_references" for item in categories),
        "diagnostic_count": len(diagnostics),
    }


def _validate_limits(config: DerivedReferenceInventoryConfig) -> None:
    if min(config.max_files, config.max_file_bytes, config.max_total_bytes, config.max_ids) <= 0:
        raise ValueError("inventory limits must be positive")


def _read_database_inventory(connection: Any | None, *, max_ids: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if connection is None:
        return {"available": False, "dialect": None, "tables": [], "diagnostics": [{"code": "DATABASE_NOT_CONFIGURED"}]}, []
    dialect = _dialect_name(connection)
    if dialect not in {"sqlite", "postgresql"}:
        raise ValueError(f"unsupported database dialect: {dialect}")
    diagnostics: list[dict[str, str]] = []
    inventory: list[dict[str, Any]] = []
    try:
        if dialect == "sqlite":
            _execute(connection, "PRAGMA query_only = ON")
        else:
            _execute(connection, "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        table_columns: dict[str, set[str]] = {}
        for table in _ALLOWED_TABLES:
            if not _table_exists(connection, dialect, table):
                diagnostics.append({"code": "TABLE_MISSING", "table": table})
                continue
            columns = _table_columns(connection, dialect, table)
            table_columns[table] = columns
            if "id" not in columns:
                diagnostics.append({"code": "ID_COLUMN_MISSING", "table": table})
                inventory.append({"table": table, "count": _table_count(connection, table), "ids": [], "id_status": "unavailable"})
                continue
            record, limit_hit = _table_record(connection, table, max_ids=max_ids)
            inventory.append(record)
            if limit_hit:
                diagnostics.append({"code": "ID_LIMIT_EXCEEDED", "table": table})
        market_data_file_classifications = _classify_market_data_files(
            connection,
            table_columns=table_columns,
            max_ids=max_ids,
            diagnostics=diagnostics,
        )
        for record in inventory:
            if record["table"] == "market_data_files":
                record["row_classifications"] = market_data_file_classifications
        return {
            "available": True,
            "dialect": dialect,
            "tables": inventory,
            "market_data_file_classifications": market_data_file_classifications,
            "diagnostics": diagnostics,
        }, inventory
    except Exception:
        return {
            "available": False,
            "dialect": dialect,
            "tables": inventory,
            "market_data_file_classifications": [],
            "diagnostics": [*diagnostics, {"code": "DATABASE_SCAN_ERROR"}],
        }, inventory
    finally:
        if dialect == "postgresql":
            connection.rollback()


def _dialect_name(connection: Any) -> str:
    if isinstance(connection, sqlite3.Connection):
        return "sqlite"
    dialect = getattr(getattr(connection, "dialect", None), "name", None)
    if isinstance(dialect, str):
        return dialect
    engine_dialect = getattr(getattr(getattr(connection, "engine", None), "dialect", None), "name", None)
    if isinstance(engine_dialect, str):
        return engine_dialect
    module_name = type(connection).__module__.lower()
    return "postgresql" if "psycopg" in module_name or "postgres" in module_name else "unknown"


def _table_exists(connection: Any, dialect: str, table: str) -> bool:
    if dialect == "sqlite":
        return bool(_fetchall(connection, "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?", ("table", table)))
    rows = _fetchall(connection, "SELECT to_regclass(%s)", (f"public.{table}",))
    return bool(rows and rows[0][0] is not None)


def _table_columns(connection: Any, dialect: str, table: str) -> set[str]:
    if dialect == "sqlite":
        return {row[1] for row in _fetchall(connection, f"PRAGMA table_info({_quote_identifier(table)})")}
    return {
        row[0]
        for row in _fetchall(
            connection,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            ("public", table),
        )
    }


def _table_count(connection: Any, table: str) -> int:
    return int(_fetchall(connection, f"SELECT COUNT(*) FROM {_quote_identifier(table)}")[0][0])


def _table_record(connection: Any, table: str, *, max_ids: int) -> tuple[dict[str, Any], bool]:
    count = _table_count(connection, table)
    rows = _fetchall(connection, f"SELECT id FROM {_quote_identifier(table)} ORDER BY id LIMIT {max_ids + 1}")
    if len(rows) > max_ids:
        return {"table": table, "count": count, "ids": [], "id_status": "limit_exceeded", "disposition": _table_disposition(table)}, True
    return {"table": table, "count": count, "ids": [str(row[0]) for row in rows], "id_status": "complete", "disposition": _table_disposition(table)}, False


def _classify_market_data_files(
    connection: Any,
    *,
    table_columns: dict[str, set[str]],
    max_ids: int,
    diagnostics: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Classify legacy file rows only when their real schema can prove the evidence."""

    required = set(_MARKET_DATA_FILE_COLUMNS)
    columns = table_columns.get("market_data_files")
    if columns is None:
        return []
    missing = sorted(required - columns)
    if missing:
        diagnostics.append({"code": "MARKET_DATA_FILE_CLASSIFICATION_COLUMNS_MISSING", "table": "market_data_files"})
        return []
    catalog = _catalog_evidence(connection, table_columns=table_columns, max_ids=max_ids, diagnostics=diagnostics)
    dialect = _dialect_name(connection)
    rows, limit_hit = _read_rows_with_limit(
        connection,
        dialect=dialect,
        table="market_data_files",
        columns=_MARKET_DATA_FILE_COLUMNS,
        max_ids=max_ids,
    )
    if limit_hit:
        diagnostics.append({"code": "MARKET_DATA_FILE_ROW_LIMIT_EXCEEDED", "table": "market_data_files"})
        return []
    return [_classify_market_data_file_row(row, catalog) for row in rows]


def _catalog_evidence(
    connection: Any,
    *,
    table_columns: dict[str, set[str]],
    max_ids: int,
    diagnostics: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    required_datasets = set(_CATALOG_DATASET_COLUMNS)
    required_partitions = set(_CATALOG_PARTITION_COLUMNS)
    dataset_columns = table_columns.get("market_datasets")
    partition_columns = table_columns.get("market_partitions")
    if dataset_columns is None or partition_columns is None:
        return {}
    if required_datasets - dataset_columns or required_partitions - partition_columns:
        diagnostics.append({"code": "CANONICAL_CATALOG_COLUMNS_MISSING", "table": "market_partitions"})
        return {}
    dialect = _dialect_name(connection)
    placeholder = "?" if dialect == "sqlite" else "%s"
    rows = _fetchall(
        connection,
        "SELECT p.\"file_uri\", d.\"provider\", d.\"frequency\", d.\"dataset_kind\", "
        "p.\"manifest_uri\", p.\"manifest_digest\", p.\"checksum\" "
        "FROM \"market_partitions\" AS p JOIN \"market_datasets\" AS d ON d.\"id\" = p.\"dataset_id\" "
        f"ORDER BY p.\"id\" LIMIT {placeholder}",
        (max_ids + 1,),
    )
    if len(rows) > max_ids:
        diagnostics.append({"code": "CANONICAL_CATALOG_ROW_LIMIT_EXCEEDED", "table": "market_partitions"})
        return {}
    return {
        str(row[0]): {
            "provider": str(row[1]),
            "frequency": str(row[2]),
            "dataset_kind": str(row[3]),
            "manifest_uri": str(row[4]),
            "manifest_digest": str(row[5]),
            "checksum": str(row[6]),
        }
        for row in rows
    }


def _read_rows_with_limit(
    connection: Any,
    *,
    dialect: str,
    table: str,
    columns: tuple[str, ...],
    max_ids: int,
) -> tuple[list[dict[str, str | None]], bool]:
    selected = ", ".join(f'"{column}"' for column in columns)
    placeholder = "?" if dialect == "sqlite" else "%s"
    rows = _fetchall(
        connection,
        f"SELECT {selected} FROM {_quote_identifier(table)} ORDER BY \"id\" LIMIT {placeholder}",
        (max_ids + 1,),
    )
    if len(rows) > max_ids:
        return [], True
    return [dict(zip(columns, (None if value is None else str(value) for value in row), strict=True)) for row in rows], False


def _classify_market_data_file_row(row: dict[str, str | None], catalog: dict[str, dict[str, str]]) -> dict[str, Any]:
    file_path = row["file_path"] or ""
    data_type = (row["data_type"] or "").lower()
    period = (row["period"] or "").lower()
    path = file_path.lower()
    catalog_record = catalog.get(file_path)
    is_derived = "derived" in data_type or (
        period in {"5m", "15m", "30m", "60m"} and "/derived/" in path
    )
    if is_derived:
        disposition = "REBUILD_ONLY"
        reason = "derived data_type is regenerated from provider-direct canonical bars"
        category = "permanent_derived_periods"
    elif _is_trusted_provider_direct_bar(row, catalog_record):
        disposition = "KEEP_TRUSTED_CANONICAL"
        reason = "provider, role, quality, frequency, and catalog partition linkage are verified"
        category = None
    elif any(marker in path for marker in ("/raw/", "/standard/", "/canonical/")):
        disposition = "REVIEW_REQUIRED"
        reason = "canonical-looking file path has no verified catalog partition linkage" if "/canonical/" in path else "bar-layer path requires explicit retirement review"
        category = "duplicate_bar_layers"
    else:
        disposition = "REVIEW_REQUIRED"
        reason = "legacy file metadata has no verified canonical catalog linkage"
        category = None
    return {
        "id": row["id"],
        "provider": row["provider"],
        "data_type": row["data_type"],
        "period": row["period"],
        "file_path": file_path,
        "data_role": row["data_role"],
        "quality_status": row["quality_status"],
        "data_version": row["data_version"],
        "disposition": disposition,
        "reason": reason,
        "category": category,
        "catalog_evidence": "verified" if catalog_record is not None else "missing",
    }


def _is_trusted_provider_direct_bar(row: dict[str, str | None], catalog: dict[str, str] | None) -> bool:
    if catalog is None:
        return False
    data_type = (row["data_type"] or "").lower()
    return (
        row["provider"] == "rqdata"
        and "bar" in data_type
        and row["data_role"] == "primary"
        and row["quality_status"] == "passed"
        and row["provider"] == catalog["provider"]
        and row["period"] == catalog["frequency"]
        and bool(catalog["manifest_uri"] and catalog["manifest_digest"] and catalog["checksum"])
    )


def _table_disposition(table: str) -> str:
    if table in _TRUSTED_METADATA_TABLES:
        return "KEEP_TRUSTED_CANONICAL"
    if table in _REVIEW_METADATA_TABLES:
        return "REVIEW_REQUIRED"
    return "REBUILD_ONLY"


def _execute(connection: Any, statement: str) -> None:
    if hasattr(connection, "exec_driver_sql"):
        connection.exec_driver_sql(statement)
        return
    if isinstance(connection, sqlite3.Connection):
        connection.execute(statement)
        return
    cursor = connection.cursor()
    try:
        cursor.execute(statement)
    finally:
        cursor.close()


def _fetchall(connection: Any, statement: str, parameters: tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
    if hasattr(connection, "exec_driver_sql"):
        return list(connection.exec_driver_sql(statement, parameters or ()).fetchall())
    if isinstance(connection, sqlite3.Connection):
        return list(connection.execute(statement, parameters or ()).fetchall())
    cursor = connection.cursor()
    try:
        cursor.execute(statement, parameters or ())
        return list(cursor.fetchall())
    finally:
        cursor.close()


def _quote_identifier(value: str) -> str:
    if value not in _ALLOWED_TABLES or not _IDENTIFIER.fullmatch(value):
        raise ValueError("inventory received a non-allowlisted database identifier")
    return f'"{value}"'


def _read_filesystem_inventory(data_root: Path, config: DerivedReferenceInventoryConfig) -> dict[str, Any]:
    diagnostics: list[dict[str, str]] = []
    records: list[dict[str, Any]] = []
    if not data_root.exists():
        diagnostics.append({"code": "DATA_ROOT_MISSING", "path": str(data_root)})
        return _filesystem_payload(data_root, records, diagnostics, truncated=False)
    if data_root.is_symlink() or not data_root.is_dir():
        diagnostics.append({"code": "DATA_ROOT_REJECTED", "path": str(data_root)})
        return _filesystem_payload(data_root, records, diagnostics, truncated=True)
    root_resolved = data_root.resolve(strict=True)
    total_bytes = 0
    inspected_files = 0
    truncated = False
    for candidate in _walk_regular_candidates(data_root, diagnostics):
        relative = candidate.relative_to(data_root).as_posix()
        display_path = f"{data_root.name}/{relative}"
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            diagnostics.append({"code": "PATH_RESOLUTION_FAILED", "path": display_path})
            continue
        if not _is_contained(root_resolved, resolved):
            diagnostics.append({"code": "PATH_OUTSIDE_DATA_ROOT", "path": display_path})
            continue
        if inspected_files >= config.max_files:
            diagnostics.append({"code": "MAX_FILES_EXCEEDED", "path": display_path})
            truncated = True
            break
        inspected_files += 1
        record, diagnostic = _read_regular_file_under_root(
            data_root,
            candidate.relative_to(data_root),
            display_path,
            config.max_file_bytes,
            capture_bytes=False,
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
            truncated = True
            continue
        assert record is not None
        if total_bytes + record["size_bytes"] > config.max_total_bytes:
            diagnostics.append({"code": "MAX_TOTAL_BYTES_EXCEEDED", "path": display_path})
            truncated = True
            break
        total_bytes += record["size_bytes"]
        records.append(record)
    return _filesystem_payload(data_root, records, diagnostics, truncated=truncated)


def _filesystem_payload(data_root: Path, records: list[dict[str, Any]], diagnostics: list[dict[str, str]], *, truncated: bool) -> dict[str, Any]:
    return {
        "data_root_exists": data_root.is_dir() and not data_root.is_symlink(),
        "data_root_path": str(data_root),
        "records": records,
        "diagnostics": sorted(diagnostics, key=lambda item: (item["code"], item["path"])),
        "truncated": truncated,
    }


def _walk_regular_candidates(data_root: Path, diagnostics: list[dict[str, str]]) -> Iterable[Path]:
    def walk(directory: Path) -> Iterable[Path]:
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            path = Path(entry.path)
            relative = path.relative_to(data_root).as_posix()
            if entry.is_symlink():
                diagnostics.append({"code": "SYMLINK_SKIPPED", "path": f"{data_root.name}/{relative}"})
                continue
            if entry.is_dir(follow_symlinks=False):
                yield from walk(path)
            elif entry.is_file(follow_symlinks=False):
                yield path
            else:
                diagnostics.append({"code": "NON_REGULAR_SKIPPED", "path": f"{data_root.name}/{relative}"})

    yield from walk(data_root)


def _is_contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _read_regular_file_under_root(
    root: Path,
    relative: Path,
    display_path: str,
    max_file_bytes: int,
    *,
    capture_bytes: bool,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Read once through root-relative nofollow descriptors and verify the opened inode."""

    components = relative.parts
    if not components or any(component in {"", ".", ".."} for component in components):
        return None, {"code": "PATH_REJECTED", "path": display_path}
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    root_fd: int | None = None
    current_fd: int | None = None
    descriptor: int | None = None
    try:
        root_fd = os.open(root, directory_flags)
        current_fd = root_fd
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            return None, {"code": "ROOT_NOT_DIRECTORY", "path": display_path}
        for component in components[:-1]:
            child_fd = os.open(component, directory_flags, dir_fd=current_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = child_fd
            if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
                return None, {"code": "NON_DIRECTORY_COMPONENT", "path": display_path}
        descriptor = os.open(components[-1], flags, dir_fd=current_fd)
    except OSError:
        if current_fd is not None and current_fd != root_fd:
            os.close(current_fd)
        if root_fd is not None:
            os.close(root_fd)
        return None, {"code": "NOFOLLOW_OPEN_FAILED", "path": display_path}
    try:
        assert descriptor is not None
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            return None, {"code": "NON_REGULAR_SKIPPED", "path": display_path}
        if before.st_size > max_file_bytes:
            return None, {"code": "MAX_FILE_BYTES_EXCEEDED", "path": display_path}
        digest = sha256()
        contents = bytearray() if capture_bytes else None
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                if contents is not None:
                    contents.extend(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            return None, {"code": "TOCTOU_CHANGED", "path": display_path}
        record: dict[str, Any] = {"path": display_path, "size_bytes": before.st_size, "sha256": digest.hexdigest(), "disposition": _path_disposition(display_path)}
        if contents is not None:
            record["contents"] = bytes(contents)
        return record, None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if current_fd is not None and current_fd != root_fd:
            os.close(current_fd)
        if root_fd is not None:
            os.close(root_fd)


def _path_disposition(path: str) -> str:
    lowered = path.lower()
    if "/canonical/" in lowered:
        return "REVIEW_REQUIRED"
    if "/derived/" in lowered:
        return "REBUILD_ONLY"
    return "REVIEW_REQUIRED"


def _read_reference_locations(repo_root: Path, config: DerivedReferenceInventoryConfig) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    locations = {category: [] for category in CATEGORY_ORDER}
    if not repo_root.is_dir():
        return locations, {"truncated": False, "diagnostics": [{"code": "REPO_ROOT_MISSING", "path": str(repo_root)}]}
    diagnostics: list[dict[str, str]] = []
    total_bytes = 0
    inspected = 0
    match_count = 0
    output_count = 0
    truncated = False
    root_resolved = repo_root.resolve(strict=True)
    for path in _walk_repo_regular_candidates(repo_root, diagnostics, max_directories=config.max_files):
        if not _is_reference_file(repo_root, path):
            continue
        relative = path.relative_to(repo_root).as_posix()
        if inspected >= config.max_files:
            diagnostics.append({"code": "REPO_MAX_FILES_EXCEEDED", "path": relative})
            truncated = True
            break
        try:
            path.resolve(strict=False).relative_to(root_resolved)
        except (OSError, ValueError):
            diagnostics.append({"code": "REPO_PATH_REJECTED", "path": relative})
            continue
        inspected += 1
        record, diagnostic = _read_regular_file_under_root(
            repo_root, path.relative_to(repo_root), relative, config.max_file_bytes, capture_bytes=True,
        )
        if diagnostic is not None:
            diagnostics.append({"code": f"REPO_{diagnostic['code']}", "path": relative})
            truncated = True
            continue
        assert record is not None
        if total_bytes + record["size_bytes"] > config.max_total_bytes:
            diagnostics.append({"code": "REPO_MAX_TOTAL_BYTES_EXCEEDED", "path": relative})
            truncated = True
            break
        total_bytes += record["size_bytes"]
        try:
            lines = record.pop("contents").decode("utf-8").splitlines()
        except UnicodeDecodeError:
            diagnostics.append({"code": "REPO_NON_UTF8_SKIPPED", "path": relative})
            truncated = True
            continue
        kind = "doc" if path.suffix.lower() == ".md" else "code"
        section_state = _reference_state_for_context(relative, "")
        for line_number, line in enumerate(lines, start=1):
            if path.suffix.lower() == ".md" and line.lstrip().startswith("#"):
                section_state = _reference_state_for_context(relative, line)
            for category in CATEGORY_ORDER:
                for rule in _REFERENCE_RULES[category]:
                    match = rule.pattern.search(line)
                    if match:
                        match_count += 1
                        if match_count > config.max_files:
                            diagnostics.append({"code": "REPO_MAX_MATCHES_EXCEEDED", "path": relative})
                            return locations, _reference_scan_payload(True, diagnostics)
                        output_count += 1
                        if output_count > config.max_files:
                            diagnostics.append({"code": "REPO_MAX_OUTPUTS_EXCEEDED", "path": relative})
                            return locations, _reference_scan_payload(True, diagnostics)
                        reference_state = _reference_state_for_context(relative, line, section_state=section_state)
                        locations[category].append(
                            {
                                "path": relative,
                                "line": line_number,
                                "kind": kind,
                                "matched_token": match.group(0),
                                "reason": rule.reason,
                                "reference_state": reference_state,
                                "disposition": "KEEP_ACTIVE_REFERENCE" if reference_state == "active" else "HISTORICAL_SNAPSHOT",
                                "sha256": record["sha256"],
                            }
                        )
    return locations, _reference_scan_payload(truncated, diagnostics)


def _reference_scan_payload(truncated: bool, diagnostics: list[dict[str, str]]) -> dict[str, Any]:
    return {"truncated": truncated, "diagnostics": sorted(diagnostics, key=lambda item: (item["code"], item["path"]))}


def _walk_repo_regular_candidates(
    repo_root: Path,
    diagnostics: list[dict[str, str]],
    *,
    max_directories: int,
) -> Iterable[Path]:
    directory_count = 0
    directory_budget_exceeded = False

    def walk(directory: Path) -> Iterable[Path]:
        nonlocal directory_count, directory_budget_exceeded
        if directory_budget_exceeded:
            return
        directory_count += 1
        if directory_count > max_directories:
            diagnostics.append({"code": "REPO_MAX_DIRECTORIES_EXCEEDED", "path": directory.relative_to(repo_root).as_posix() or "."})
            directory_budget_exceeded = True
            return
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            diagnostics.append({"code": "REPO_DIRECTORY_OPEN_FAILED", "path": directory.relative_to(repo_root).as_posix() or "."})
            return
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(repo_root).as_posix()
            try:
                if entry.is_symlink():
                    diagnostics.append({"code": "REPO_SYMLINK_SKIPPED", "path": relative})
                elif entry.is_dir(follow_symlinks=False):
                    if entry.name not in _IGNORED_DIRS:
                        yield from walk(path)
                elif entry.is_file(follow_symlinks=False):
                    yield path
                else:
                    diagnostics.append({"code": "REPO_NON_REGULAR_SKIPPED", "path": relative})
            except OSError:
                diagnostics.append({"code": "REPO_PATH_REJECTED", "path": relative})

    yield from walk(repo_root)


def _reference_state_for_context(relative: str, line: str, *, section_state: str | None = None) -> str:
    marker = _NON_ACTIVE_MARKER.search(relative.replace("_", " ").replace("-", " ")) or _NON_ACTIVE_MARKER.search(line)
    if marker is None:
        return section_state if section_state is not None else "active"
    return "historical" if marker.group(0).lower() in {"historical", "archive"} else "non_active"


def _is_reference_file(repo_root: Path, path: Path) -> bool:
    if path.suffix.lower() not in _REFERENCE_SUFFIXES:
        return False
    relative = path.relative_to(repo_root).as_posix()
    return relative not in _SELF_REFERENCE_PATHS and not relative.startswith("services/quant-api/tests/") and not any(
        part in _IGNORED_DIRS for part in path.relative_to(repo_root).parts
    )


def _tables_for_category(
    category: str,
    inventory: Iterable[dict[str, Any]],
    market_data_file_classifications: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    table_names = set(_CATEGORY_TABLES[category])
    records = [record for record in inventory if record["table"] in table_names]
    rows = [record for record in market_data_file_classifications if record["category"] == category]
    if not rows:
        return records
    return [
        *records,
        {
            "table": "market_data_files",
            "count": len(rows),
            "ids": [str(record["id"]) for record in rows],
            "id_status": "complete",
            "disposition": rows[0]["disposition"] if len({record["disposition"] for record in rows}) == 1 else "MIXED",
            "rows": [_public_market_data_file_row(record) for record in rows],
        },
    ]


def _public_market_data_file_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in (
            "id", "provider", "data_type", "period", "file_path", "data_role", "quality_status", "data_version", "disposition", "reason",
        )
    }


def _paths_for_category(category: str, inventory: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in inventory if _matches_path_category(category, record["path"])]


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
        return bool(re.search(r"report(?:[_\s-]*(?:id)?[_\s:=]*)?(?:14|15)(?:\b|_)", normalized, re.IGNORECASE))
    return False
