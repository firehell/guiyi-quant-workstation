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
    "indicator_cache": ("indicator_cache",),
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
_TRUSTED_METADATA_TABLES = ("data_gaps", "market_datasets", "market_partitions")
_REVIEW_METADATA_TABLES = ("market_data_files",)
_ALLOWED_TABLES = tuple(sorted({table for tables in _CATEGORY_TABLES.values() for table in tables} | set(_TRUSTED_METADATA_TABLES) | set(_REVIEW_METADATA_TABLES)))
_REFERENCE_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".toml", ".sql", ".html", ".js", ".txt", ".sh", ".ts", ".tsx", ".vue"}
_IGNORED_DIRS = {".git", ".venv", "node_modules", "dist", "__pycache__", ".superpowers"}
_SELF_REFERENCE_PATHS = {
    "scripts/derived_reference_inventory.py",
    "services/quant-api/app/services/derived_reference_inventory.py",
    "services/quant-api/tests/test_derived_reference_inventory.py",
}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
        categories.append(
            {
                "category": category,
                "reason": _CATEGORY_REASONS[category],
                "database_tables": _tables_for_category(category, table_inventory),
                "filesystem_paths": _paths_for_category(category, filesystem["records"]),
                "reference_locations": category_references,
                "active_reference_status": "present" if category_references else "zero_active_references",
            }
        )
    diagnostics = [*database["diagnostics"], *filesystem["diagnostics"], *reference_scan["diagnostics"]]
    status = "complete" if database["available"] and filesystem["data_root_exists"] and repo_root.is_dir() and not filesystem["truncated"] and not reference_scan["truncated"] else "incomplete"
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
        "task07_zero_active_reference_eligible": status == "complete" and all(not item["reference_locations"] for item in categories),
        "diagnostic_count": len(diagnostics),
    }


def _validate_limits(config: DerivedReferenceInventoryConfig) -> None:
    if min(config.max_files, config.max_file_bytes, config.max_total_bytes, config.max_ids) <= 0:
        raise ValueError("inventory limits must be positive")


def _read_database_inventory(connection: Any | None, *, max_ids: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if connection is None:
        return {"available": False, "dialect": None, "tables": [], "diagnostics": [{"code": "DATABASE_NOT_CONFIGURED"}]}, []
    dialect = _dialect_name(connection)
    diagnostics: list[dict[str, str]] = []
    try:
        if dialect == "sqlite":
            _execute(connection, "PRAGMA query_only = ON")
        elif dialect == "postgresql":
            _execute(connection, "BEGIN")
            _execute(connection, "SET TRANSACTION READ ONLY")
        else:
            raise ValueError(f"unsupported database dialect: {dialect}")
        inventory = []
        for table in _ALLOWED_TABLES:
            if not _table_exists(connection, dialect, table):
                diagnostics.append({"code": "TABLE_MISSING", "table": table})
                continue
            columns = _table_columns(connection, dialect, table)
            if "id" not in columns:
                diagnostics.append({"code": "ID_COLUMN_MISSING", "table": table})
                inventory.append({"table": table, "count": _table_count(connection, table), "ids": [], "id_status": "unavailable"})
                continue
            record, limit_hit = _table_record(connection, table, max_ids=max_ids)
            inventory.append(record)
            if limit_hit:
                diagnostics.append({"code": "ID_LIMIT_EXCEEDED", "table": table})
        return {"available": True, "dialect": dialect, "tables": inventory, "diagnostics": diagnostics}, inventory
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
        record, diagnostic = _read_regular_file(candidate, display_path, config.max_file_bytes)
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


def _read_regular_file(path: Path, display_path: str, max_file_bytes: int) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None, {"code": "NOFOLLOW_OPEN_FAILED", "path": display_path}
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            return None, {"code": "NON_REGULAR_SKIPPED", "path": display_path}
        if before.st_size > max_file_bytes:
            return None, {"code": "MAX_FILE_BYTES_EXCEEDED", "path": display_path}
        digest = sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            return None, {"code": "TOCTOU_CHANGED", "path": display_path}
        return {"path": display_path, "size_bytes": before.st_size, "sha256": digest.hexdigest(), "disposition": _path_disposition(display_path)}, None
    finally:
        os.close(descriptor)


def _path_disposition(path: str) -> str:
    lowered = path.lower()
    if "/canonical/" in lowered:
        return "KEEP_TRUSTED_CANONICAL"
    if "/derived/" in lowered:
        return "REBUILD_ONLY"
    return "REVIEW_REQUIRED"


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_reference_locations(repo_root: Path, config: DerivedReferenceInventoryConfig) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    locations = {category: [] for category in CATEGORY_ORDER}
    if not repo_root.is_dir():
        return locations, {"truncated": False, "diagnostics": [{"code": "REPO_ROOT_MISSING", "path": str(repo_root)}]}
    diagnostics: list[dict[str, str]] = []
    total_bytes = 0
    inspected = 0
    truncated = False
    root_resolved = repo_root.resolve(strict=True)
    for path in sorted(repo_root.rglob("*")):
        if path.is_symlink():
            diagnostics.append({"code": "REPO_SYMLINK_SKIPPED", "path": path.relative_to(repo_root).as_posix()})
            continue
        if not _is_reference_file(repo_root, path):
            continue
        if inspected >= config.max_files:
            diagnostics.append({"code": "REPO_MAX_FILES_EXCEEDED", "path": path.relative_to(repo_root).as_posix()})
            truncated = True
            break
        inspected += 1
        try:
            path.resolve(strict=False).relative_to(root_resolved)
            size = path.stat().st_size
        except (OSError, ValueError):
            diagnostics.append({"code": "REPO_PATH_REJECTED", "path": path.relative_to(repo_root).as_posix()})
            continue
        if size > config.max_file_bytes or total_bytes + size > config.max_total_bytes:
            diagnostics.append({"code": "REPO_BUDGET_EXCEEDED", "path": path.relative_to(repo_root).as_posix()})
            truncated = True
            break
        total_bytes += size
        relative = path.relative_to(repo_root).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        kind = "doc" if path.suffix.lower() == ".md" else "code"
        for line_number, line in enumerate(lines, start=1):
            for category in CATEGORY_ORDER:
                for rule in _REFERENCE_RULES[category]:
                    match = rule.pattern.search(line)
                    if match:
                        locations[category].append(
                            {
                                "path": relative,
                                "line": line_number,
                                "kind": kind,
                                "matched_token": match.group(0),
                                "reason": rule.reason,
                                "reference_state": "historical" if "historical" in line.lower() or "/archive/" in relative else "active",
                                "disposition": "KEEP_ACTIVE_REFERENCE" if "historical" not in line.lower() else "HISTORICAL_SNAPSHOT",
                                "sha256": _sha256(path),
                            }
                        )
    return locations, {"truncated": truncated, "diagnostics": sorted(diagnostics, key=lambda item: (item["code"], item["path"]))}


def _is_reference_file(repo_root: Path, path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in _REFERENCE_SUFFIXES:
        return False
    relative = path.relative_to(repo_root).as_posix()
    return relative not in _SELF_REFERENCE_PATHS and not relative.startswith("services/quant-api/tests/") and not any(
        part in _IGNORED_DIRS for part in path.relative_to(repo_root).parts
    )


def _tables_for_category(category: str, inventory: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    table_names = set(_CATEGORY_TABLES[category])
    return [record for record in inventory if record["table"] in table_names]


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
