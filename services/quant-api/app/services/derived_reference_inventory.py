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
    "signal_review",
    "live_eod_sample",
    "permanent_derived_periods",
    "duplicate_bar_layers",
    "profile_binding_legacy_lineage",
    "report_14_15_references",
)
DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_DIRECTORIES = 10_000
DEFAULT_MAX_FILE_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_IDS = 1_000

_CATEGORY_REASONS = {
    "indicator_cache": "indicator and cache outputs are rebuild-only derived artifacts",
    "signal_review": "signal and review records are consumer evidence, not historical canonical bars",
    "live_eod_sample": "live, EOD, and research-sample surfaces remain isolated observation outputs",
    "permanent_derived_periods": "derived periods are regenerated from provider-direct canonical 1m bars",
    "duplicate_bar_layers": "raw, standard, and canonical bar layers require explicit retirement classification",
    "profile_binding_legacy_lineage": "Profile, Binding, and legacy lineage remain compatibility-only",
    "report_14_15_references": "report 14/15 references are Git-traceable historical snapshots, not active Gates",
}
_CATEGORY_TABLES = {
    "indicator_cache": (),
    "signal_review": (
        "review_attachments", "review_notes", "review_tags", "signal_events", "signal_notifications",
        "signal_scan_tasks", "strategy_signals",
    ),
    "live_eod_sample": (
        "after_market_scheduler_checkpoints",
    ),
    "permanent_derived_periods": (),
    "duplicate_bar_layers": (),
    "profile_binding_legacy_lineage": ("data_profiles", "profile_active_bindings"),
    "report_14_15_references": (),
}
_TRUSTED_METADATA_TABLES = (
    "data_download_tasks", "data_gaps", "data_quality_reports", "main_contract_map", "market_datasets", "market_partitions",
)
_REVIEW_METADATA_TABLES = ("market_data_files",)
_ALLOWED_TABLES = tuple(sorted({table for tables in _CATEGORY_TABLES.values() for table in tables} | set(_TRUSTED_METADATA_TABLES) | set(_REVIEW_METADATA_TABLES)))
_MARKET_DATA_FILE_COLUMNS = (
    "id", "provider", "data_type", "instrument_symbol", "contract_code", "period", "file_path", "checksum",
    "data_version", "data_role", "quality_status",
)
_CATALOG_DATASET_COLUMNS = ("id", "provider", "dataset_kind", "symbol", "contract_or_series", "frequency", "adjustment", "schema_version")
_CATALOG_PARTITION_COLUMNS = ("id", "dataset_id", "file_uri", "manifest_uri", "manifest_digest", "checksum", "manifest_version")
_REFERENCE_SUFFIXES = {
    ".cjs", ".conf", ".css", ".diff", ".example", ".html", ".ini", ".js", ".json", ".mako", ".md", ".mjs",
    ".mts", ".py", ".rules", ".service", ".sh", ".sql", ".target", ".template", ".toml", ".ts", ".tsx", ".txt",
    ".vue", ".yaml", ".yml",
}
_REFERENCE_BASENAMES = {".gitignore", ".python-version", "Dockerfile", "GNUmakefile", "Makefile", "README"}
_NON_REFERENCE_TYPE_REASONS = {
    ".csv": "tabular data asset; not executable source or documentation",
    ".lock": "generated dependency lock; not a consumer implementation surface",
    ".parquet": "binary data asset; inventoried through the data-root/catalog path",
    ".pdf": "binary document; not safely searchable as UTF-8 source text",
    ".png": "binary image asset",
    ".pyc": "compiled Python artifact",
    ".svg": "image asset; not an executable consumer surface",
    ".xlsx": "binary spreadsheet asset",
}
_NON_REFERENCE_BASENAME_REASONS = {
    ".git": "worktree metadata pointer",
    ".gitkeep": "empty directory placeholder",
}
_IGNORED_DIRS = {
    ".git", ".pytest_cache", ".ruff_cache", ".superpowers", ".venv", "__pycache__", "dist", "node_modules",
}
_SELF_REFERENCE_PATHS = {
    "scripts/derived_reference_inventory.py",
    "services/quant-api/app/services/derived_reference_inventory.py",
    "services/quant-api/tests/test_derived_reference_inventory.py",
}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ACTUAL_CONTRACT = re.compile(r"^([A-Z]+)[0-9]{3,4}$")
_ARCHIVE_PATH_MARKER = re.compile(r"(?:^|/)(?:archive|archived|归档)(?:/|$)", re.IGNORECASE)
_EXPLICIT_HISTORICAL_DOC_MARKER = re.compile(
    r"^\s*(?:historical\s+snapshot\s*;\s*not\s+active\s+gate|"
    r"historical_snapshot\s*:\s*true\s*;\s*active_gate\s*:\s*false|"
    r"仅历史引用|历史快照且非\s*active\s*gate|已归档)\s*(?::|：|-).*$",
    re.IGNORECASE,
)
_AMBIGUOUS_HISTORY_MARKER = re.compile(r"(?:\bhistorical\b|\bfrozen\b|\bcompatibility-only\b|\bsuperseded\b)", re.IGNORECASE)
_ACTIVE_OVERRIDE_MARKER = re.compile(
    r"(?:\bcurrent\s+(?:signal\s+)?(?:(?:is|remains)\s+)?active\b|\bstill\s+active\b|\bremains\s+active\b|\bin\s+use\b|\bmust\b|当前|仍|继续|在用|不得视为非\s*active|"
    r"not\s+merely\s+historical|must\s+not\s+be\s+treated\s+as\s+not\s+active)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ReferenceRule:
    pattern: re.Pattern[str]
    reason: str


@dataclass(frozen=True)
class _RelationRule:
    rule: str
    table: str
    columns: tuple[str, ...]
    sql_predicate: str
    predicate: str
    parameters: tuple[Any, ...]
    target_columns: tuple[str, ...]
    status: str
    reason: str


_REFERENCE_RULES = {
    "indicator_cache": (_ReferenceRule(re.compile(r"\b(?:indicator|cache)\b", re.IGNORECASE), "active indicator/cache reference"),),
    "signal_review": (_ReferenceRule(re.compile(r"\b(?:signal|review|SignalEvent|ReviewNote)\b", re.IGNORECASE), "active signal/review reference"),),
    "live_eod_sample": (_ReferenceRule(re.compile(r"\b(?:live|eod|after[_ -]?market|ResearchSample)\b", re.IGNORECASE), "active live/EOD/sample reference"),),
    "permanent_derived_periods": (_ReferenceRule(re.compile(r"\b(?:derived|5m|15m|30m|60m)\b", re.IGNORECASE), "derived-period reference"),),
    "duplicate_bar_layers": (_ReferenceRule(re.compile(r"\b(?:raw|standard|canonical|MarketDataFile)\b", re.IGNORECASE), "bar-layer reference"),),
    "profile_binding_legacy_lineage": (_ReferenceRule(re.compile(r"\b(?:DataProfile|ActiveBinding|profile|binding|legacy[ _-]?lineage)\b", re.IGNORECASE), "legacy compatibility reference"),),
    "report_14_15_references": (_ReferenceRule(re.compile(r"\breport(?:[_\s-]*(?:id)?[_\s:=]*)?(?:14|15)(?:\b|_)", re.IGNORECASE), "report 14/15 historical reference"),),
}


_RELATION_RULES = (
    _RelationRule(
        "active_profile_binding", "profile_active_bindings",
        ("id", "profile_id", "market_data_file_id", "data_version", "binding_status"),
        '"binding_status" = {p}', "binding_status = active", ("active",),
        ("profile_id", "market_data_file_id", "data_version"), "active",
        "active binding still targets legacy profile/file/version lineage",
    ),
    _RelationRule(
        "unknown_profile_binding_status", "profile_active_bindings",
        ("id", "profile_id", "market_data_file_id", "data_version", "binding_status"),
        '("binding_status" IS NULL OR "binding_status" NOT IN ({p}, {p}))',
        "binding_status is null or outside active/superseded", ("active", "superseded"),
        ("profile_id", "market_data_file_id", "data_version"), "review_required",
        "unrecognized binding status cannot prove a relationship inactive",
    ),
    _RelationRule(
        "quality_report_file_reference", "data_quality_reports", ("id", "file_id"),
        '"file_id" IS NOT NULL', "file_id is not null", (), ("file_id",), "active",
        "quality evidence still references a market data file row",
    ),
    _RelationRule(
        "market_file_download_task_reference", "market_data_files", ("id", "task_id"),
        '"task_id" IS NOT NULL', "task_id is not null", (), ("task_id",), "review_required",
        "market data file lineage still references a download task",
    ),
    _RelationRule(
        "active_download_task", "data_download_tasks", ("id", "status"),
        '"status" IN ({p}, {p}, {p})', "status in pending/running/retrying", ("pending", "running", "retrying"),
        (), "active", "download task remains active",
    ),
    _RelationRule(
        "unknown_download_task_status", "data_download_tasks", ("id", "status"),
        '("status" IS NULL OR "status" NOT IN ({p}, {p}, {p}, {p}, {p}, {p}, {p}))',
        "status is null or outside known active/inactive values",
        ("pending", "running", "retrying", "completed", "success", "failed", "cancelled"), (), "review_required",
        "unrecognized download status cannot prove the task inactive",
    ),
    _RelationRule(
        "strategy_signal_legacy_or_active", "strategy_signals",
        ("id", "profile_id", "market_data_file_id", "status", "is_active"),
        '("profile_id" IS NOT NULL OR "market_data_file_id" IS NOT NULL OR "is_active" = {p} '
        'OR "status" IN ({p}, {p}, {p}))',
        "legacy profile/file reference or active signal status", (True, "pending", "active", "triggered"),
        ("profile_id", "market_data_file_id"), "review_required",
        "signal lineage or active status still references legacy surfaces",
    ),
    _RelationRule(
        "unknown_strategy_signal_active_state", "strategy_signals", ("id", "is_active"),
        '"is_active" IS NULL', "is_active is null", (), (), "review_required",
        "missing active state cannot prove the signal inactive",
    ),
    _RelationRule(
        "signal_event_legacy_or_active", "signal_events",
        ("id", "profile_id", "market_data_file_id", "lifecycle_status"),
        '("profile_id" IS NOT NULL OR "market_data_file_id" IS NOT NULL OR "lifecycle_status" IN ({p}, {p}, {p}, {p}))',
        "legacy profile/file reference or active lifecycle", ("created", "pending", "active", "new"),
        ("profile_id", "market_data_file_id"), "review_required",
        "signal event lineage or lifecycle remains active",
    ),
    _RelationRule(
        "unknown_signal_event_lifecycle", "signal_events", ("id", "lifecycle_status"),
        '("lifecycle_status" IS NULL OR "lifecycle_status" NOT IN ({p}, {p}, {p}, {p}, {p}, {p}, {p}))',
        "lifecycle is null or outside known active/inactive values",
        ("created", "pending", "active", "new", "viewed", "closed", "archived"), (), "review_required",
        "unrecognized signal event lifecycle cannot prove the event inactive",
    ),
    _RelationRule(
        "review_note_source_reference", "review_notes", ("id", "source_type", "source_id"),
        '"source_id" IS NOT NULL', "source_id is not null", (), ("source_type", "source_id"), "review_required",
        "review evidence still references a consumer row",
    ),
    _RelationRule(
        "review_attachment_reference", "review_attachments", ("id", "review_id"),
        '"review_id" IS NOT NULL', "review_id is not null", (), ("review_id",), "review_required",
        "review attachment still references a review row",
    ),
    _RelationRule(
        "active_review_tag", "review_tags", ("id", "is_active"),
        '"is_active" = {p}', "is_active = true", (True,), (), "review_required",
        "active review tag remains a surviving consumer dependency",
    ),
    _RelationRule(
        "signal_scan_legacy_or_active", "signal_scan_tasks",
        ("id", "profile_id", "market_data_file_id", "status"),
        '("profile_id" IS NOT NULL OR "market_data_file_id" IS NOT NULL OR "status" IN ({p}, {p}, {p}))',
        "legacy profile/file reference or active scan status", ("pending", "running", "retrying"),
        ("profile_id", "market_data_file_id"), "review_required",
        "signal scan lineage or execution remains active",
    ),
    _RelationRule(
        "unknown_signal_scan_status", "signal_scan_tasks", ("id", "status"),
        '("status" IS NULL OR "status" NOT IN ({p}, {p}, {p}, {p}, {p}, {p}, {p}))',
        "status is null or outside known active/inactive values",
        ("pending", "running", "retrying", "completed", "partial_failed", "failed", "cancelled"),
        (), "review_required", "unrecognized signal scan status cannot prove the task inactive",
    ),
    _RelationRule(
        "signal_notification_reference", "signal_notifications", ("id", "event_id", "signal_id", "status"),
        '("event_id" IS NOT NULL OR "signal_id" IS NOT NULL OR "status" IN ({p}, {p}, {p}, {p}))',
        "event/signal reference or pending notification status", ("pending", "retrying", "retry_pending", "sending"),
        ("event_id", "signal_id"), "review_required",
        "notification evidence or delivery remains linked to signal consumers",
    ),
    _RelationRule(
        "unknown_signal_notification_status", "signal_notifications", ("id", "status"),
        '("status" IS NULL OR "status" NOT IN ({p}, {p}, {p}, {p}, {p}, {p}, {p}))',
        "status is null or outside known active/inactive values",
        ("pending", "retrying", "retry_pending", "sending", "sent", "failed", "cancelled"),
        (), "review_required", "unrecognized notification status cannot prove delivery inactive",
    ),
    *tuple(
        _RelationRule(
            f"nonempty_{table}", table, ("id",), "1 = 1", "table contains rows", (), (), "review_required",
            "non-empty live/EOD/sample evidence requires explicit retirement review",
        )
        for table in _CATEGORY_TABLES["live_eod_sample"]
    ),
)


@dataclass(frozen=True)
class DerivedReferenceInventoryConfig:
    repo_root: Path
    data_root: Path
    canonical_root: Path | None = None
    max_files: int = DEFAULT_MAX_FILES
    max_directories: int = DEFAULT_MAX_DIRECTORIES
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
    database, table_inventory = _read_database_inventory(
        connection,
        max_ids=config.max_ids,
        canonical_root=(config.canonical_root or config.data_root).absolute(),
    )
    filesystem = _read_filesystem_inventory(data_root, config)
    references, reference_scan = _read_reference_locations(repo_root, config)
    categories = []
    for category in CATEGORY_ORDER:
        category_references = references[category]
        active_references = [item for item in category_references if item["reference_state"] == "active"]
        review_references = [item for item in category_references if item["reference_state"] == "review_required"]
        category_tables = _tables_for_category(category, table_inventory, database.get("market_data_file_classifications", []))
        categories.append(
            {
                "category": category,
                "reason": _CATEGORY_REASONS[category],
                "database_tables": category_tables,
                "database_scope": _database_scope(database, category_tables),
                "filesystem_paths": _paths_for_category(category, filesystem["records"]),
                "reference_locations": category_references,
                "active_reference_status": "present" if active_references else "review_required" if review_references else "zero_active_references",
                "non_active_reference_count": sum(item["reference_state"] in {"historical", "non_active"} for item in category_references),
                "review_required_count": len(review_references),
            }
        )
    diagnostics = [*database["diagnostics"], *filesystem["diagnostics"], *reference_scan["diagnostics"]]
    status = "complete" if database["available"] and filesystem["data_root_exists"] and repo_root.is_dir() and not diagnostics and not filesystem["truncated"] and not reference_scan["truncated"] else "incomplete"
    active_relation_reference_count = database.get("active_relation_reference_count", 0)
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
        "task07_zero_active_reference_eligible": (
            status == "complete"
            and active_relation_reference_count == 0
            and all(item["active_reference_status"] == "zero_active_references" for item in categories)
        ),
        "diagnostic_count": len(diagnostics),
    }


def _validate_limits(config: DerivedReferenceInventoryConfig) -> None:
    if min(config.max_files, config.max_directories, config.max_file_bytes, config.max_total_bytes, config.max_ids) <= 0:
        raise ValueError("inventory limits must be positive")


def _database_scope(database: dict[str, Any], category_tables: list[dict[str, Any]]) -> str:
    if not database["available"] or database["diagnostics"]:
        return "INCOMPLETE"
    if category_tables:
        return "PRESENT"
    return "COMPLETE"


def _read_database_inventory(
    connection: Any | None,
    *,
    max_ids: int,
    canonical_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if connection is None:
        return {
            "available": False, "dialect": None, "tables": [], "relation_references": [],
            "active_relation_reference_count": 0, "diagnostics": [{"code": "DATABASE_NOT_CONFIGURED"}],
        }, []
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
        relation_references = _read_relation_references(
            connection,
            dialect=dialect,
            table_columns=table_columns,
            max_ids=max_ids,
            diagnostics=diagnostics,
        )
        market_data_file_classifications = _classify_market_data_files(
            connection,
            table_columns=table_columns,
            max_ids=max_ids,
            diagnostics=diagnostics,
            canonical_root=canonical_root,
        )
        for record in inventory:
            if record["table"] == "market_data_files":
                record["row_classifications"] = market_data_file_classifications
        return {
            "available": True,
            "dialect": dialect,
            "tables": inventory,
            "relation_references": relation_references,
            "active_relation_reference_count": sum(
                item["count"] for item in relation_references if item["status"] in {"active", "review_required"}
            ),
            "market_data_file_classifications": market_data_file_classifications,
            "diagnostics": diagnostics,
        }, inventory
    except Exception:
        return {
            "available": False,
            "dialect": dialect,
            "tables": inventory,
            "relation_references": [],
            "active_relation_reference_count": 0,
            "market_data_file_classifications": [],
            "diagnostics": [*diagnostics, {"code": "DATABASE_SCAN_ERROR"}],
        }, inventory
    finally:
        if dialect == "postgresql":
            connection.rollback()


def _read_relation_references(
    connection: Any,
    *,
    dialect: str,
    table_columns: dict[str, set[str]],
    max_ids: int,
    diagnostics: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Evaluate explicit DB relationship rules with exact counts and bounded identifiers."""

    placeholder = "?" if dialect == "sqlite" else "%s"
    records: list[dict[str, Any]] = []
    for rule in _RELATION_RULES:
        columns = table_columns.get(rule.table)
        if columns is None:
            diagnostics.append({"code": "RELATION_TABLE_MISSING", "table": rule.table, "rule": rule.rule})
            records.append(_incomplete_relation_record(rule, "relation table is missing"))
            continue
        missing = sorted(set(rule.columns) - columns)
        if missing:
            diagnostics.append({"code": "RELATION_COLUMNS_MISSING", "table": rule.table, "rule": rule.rule})
            records.append(_incomplete_relation_record(rule, f"required columns missing: {','.join(missing)}"))
            continue
        predicate = rule.sql_predicate.format(p=placeholder)
        selected = ", ".join(f'"{column}"' for column in rule.columns)
        table = _quote_identifier(rule.table)
        count = int(
            _fetchall(connection, f"SELECT COUNT(*) FROM {table} WHERE {predicate}", rule.parameters)[0][0]
        )
        rows = _fetchall(
            connection,
            f"SELECT {selected} FROM {table} WHERE {predicate} ORDER BY \"id\" LIMIT {placeholder}",
            (*rule.parameters, max_ids + 1),
        )
        if len(rows) > max_ids:
            diagnostics.append({"code": "RELATION_ID_LIMIT_EXCEEDED", "table": rule.table, "rule": rule.rule})
            records.append(
                {
                    "rule": rule.rule, "table": rule.table, "predicate": rule.predicate, "count": count,
                    "row_ids": [], "target_ids": {}, "status": "incomplete",
                    "reason": "bounded relationship identifier limit exceeded",
                }
            )
            continue
        mapped = [dict(zip(rule.columns, row, strict=True)) for row in rows]
        target_ids = {
            column: sorted({str(row[column]) for row in mapped if row[column] is not None})
            for column in rule.target_columns
        }
        target_ids = {column: values for column, values in target_ids.items() if values}
        records.append(
            {
                "rule": rule.rule,
                "table": rule.table,
                "predicate": rule.predicate,
                "count": count,
                "row_ids": [str(row["id"]) for row in mapped],
                "target_ids": target_ids,
                "status": rule.status,
                "reason": rule.reason,
            }
        )
    return records


def _incomplete_relation_record(rule: _RelationRule, reason: str) -> dict[str, Any]:
    return {
        "rule": rule.rule, "table": rule.table, "predicate": rule.predicate, "count": 0,
        "row_ids": [], "target_ids": {}, "status": "incomplete", "reason": reason,
    }


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
    canonical_root: Path,
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
    return [
        _classify_market_data_file_row(
            row,
            catalog,
            canonical_root=canonical_root,
            diagnostics=diagnostics,
        )
        for row in rows
    ]


def _catalog_evidence(
    connection: Any,
    *,
    table_columns: dict[str, set[str]],
    max_ids: int,
    diagnostics: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
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
        "SELECT p.\"file_uri\", d.\"provider\", d.\"symbol\", d.\"contract_or_series\", d.\"frequency\", "
        "d.\"dataset_kind\", d.\"adjustment\", d.\"schema_version\", p.\"manifest_uri\", p.\"manifest_digest\", "
        "p.\"checksum\", p.\"manifest_version\" "
        "FROM \"market_partitions\" AS p JOIN \"market_datasets\" AS d ON d.\"id\" = p.\"dataset_id\" "
        f"ORDER BY p.\"id\" LIMIT {placeholder}",
        (max_ids + 1,),
    )
    if len(rows) > max_ids:
        diagnostics.append({"code": "CANONICAL_CATALOG_ROW_LIMIT_EXCEEDED", "table": "market_partitions"})
        return {}
    evidence: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        evidence.setdefault(str(row[0]).replace("\\", "/"), []).append(
            {
            "provider": str(row[1]),
            "symbol": str(row[2]),
            "contract_or_series": str(row[3]),
            "frequency": str(row[4]),
            "dataset_kind": str(row[5]),
            "adjustment": str(row[6]),
            "schema_version": str(row[7]),
            "manifest_uri": str(row[8]),
            "manifest_digest": str(row[9]),
            "checksum": str(row[10]),
            "manifest_version": str(row[11]),
            }
        )
    for file_uri, candidates in evidence.items():
        if len(candidates) > 1:
            diagnostics.append({"code": "CATALOG_FILE_URI_AMBIGUOUS", "table": "market_partitions"})
    return evidence


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


def _classify_market_data_file_row(
    row: dict[str, str | None],
    catalog: dict[str, list[dict[str, str]]],
    *,
    canonical_root: Path,
    diagnostics: list[dict[str, str]],
) -> dict[str, Any]:
    file_path = row["file_path"] or ""
    data_type = (row["data_type"] or "").lower()
    period = (row["period"] or "").lower()
    path = file_path.lower()
    normalized_uri, path_diagnostic = _normalized_catalog_uri(file_path, canonical_root)
    if path_diagnostic is not None:
        diagnostics.append({"code": path_diagnostic, "table": "market_data_files"})
    candidates = catalog.get(normalized_uri, []) if normalized_uri is not None else []
    catalog_record = candidates[0] if len(candidates) == 1 else None
    catalog_evidence = "missing"
    if len(candidates) > 1:
        diagnostics.append({"code": "CATALOG_FILE_URI_AMBIGUOUS", "table": "market_partitions"})
    is_derived = "derived" in data_type or (data_type == "bars" and period in {"5m", "15m", "30m", "60m"})
    if is_derived:
        disposition = "REBUILD_ONLY"
        reason = "legacy bar period is regenerated from provider-direct canonical 1m bars" if data_type == "bars" else "derived data_type is regenerated from provider-direct canonical bars"
        category = "permanent_derived_periods"
    elif catalog_record is not None and _catalog_identity_matches(row, catalog_record):
        diagnostics.append({"code": "PHYSICAL_KEEP_PROOF_REQUIRED", "table": "market_data_files"})
        disposition = "REVIEW_REQUIRED"
        reason = "metadata is aligned but data_version is catalog-unverified and physical manifest/parquet proof is required before KEEP"
        category = "duplicate_bar_layers"
        catalog_evidence = "metadata_aligned_partial_data_version_unverified"
    elif catalog_record is not None:
        diagnostics.append({"code": "CATALOG_IDENTITY_MISMATCH", "table": "market_data_files"})
        disposition = "REVIEW_REQUIRED"
        reason = "catalog identity fields differ from legacy file metadata"
        category = "duplicate_bar_layers"
        catalog_evidence = "mismatch"
    elif any(marker in path for marker in ("/raw/", "/standard/", "/canonical/")):
        disposition = "REVIEW_REQUIRED"
        reason = "canonical-looking file path has no verified catalog partition linkage" if "/canonical/" in path else "bar-layer path requires explicit retirement review"
        category = "duplicate_bar_layers"
        catalog_evidence = "missing"
    else:
        disposition = "REVIEW_REQUIRED"
        reason = "legacy file metadata has no verified canonical catalog linkage"
        category = "duplicate_bar_layers"
        catalog_evidence = "missing"
    return {
        "id": row["id"],
        "provider": row["provider"],
        "data_type": row["data_type"],
        "instrument_symbol": row["instrument_symbol"],
        "contract_code": row["contract_code"],
        "period": row["period"],
        "file_path": file_path,
        "checksum": row["checksum"],
        "data_role": row["data_role"],
        "quality_status": row["quality_status"],
        "data_version": row["data_version"],
        "disposition": disposition,
        "reason": reason,
        "category": category,
        "catalog_evidence": catalog_evidence,
    }


def _catalog_identity_matches(row: dict[str, str | None], catalog: dict[str, str]) -> bool:
    symbol = (row["instrument_symbol"] or "").lower()
    contract = (row["contract_code"] or "").upper()
    catalog_contract = catalog["contract_or_series"].upper()
    base = (
        row["provider"] == "rqdata"
        and row["data_type"] == "bars"
        and row["data_role"] == "primary"
        and row["quality_status"] == "passed"
        and row["provider"] == catalog["provider"]
        and symbol == catalog["symbol"].lower()
        and row["period"] == catalog["frequency"]
        and row["checksum"] == catalog["checksum"]
        and catalog["adjustment"] == "none"
        and catalog["schema_version"] == "canonical-bar-v1"
        and bool(catalog["manifest_uri"] and catalog["manifest_digest"])
    )
    if not base:
        return False
    if catalog["dataset_kind"] == "actual_dominant":
        match = _ACTUAL_CONTRACT.fullmatch(contract)
        return (
            match is not None
            and match.group(1).upper() == symbol.upper()
            and contract == catalog_contract
            and row["period"] in {"1m", "1d", "1w"}
        )
    if catalog["dataset_kind"] == "continuous":
        return catalog_contract == f"{symbol.upper()}.MAIN" and contract == catalog_contract and row["period"] in {"1m", "1d", "1w"}
    return False


def _normalized_catalog_uri(file_path: str, canonical_root: Path) -> tuple[str | None, str | None]:
    candidate = Path(file_path)
    if not candidate.is_absolute():
        return None, "MARKET_DATA_FILE_PATH_NOT_ABSOLUTE"
    try:
        root = canonical_root.resolve(strict=False)
        relative = candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return None, "MARKET_DATA_FILE_PATH_OUTSIDE_CANONICAL_ROOT"
    if not relative.parts:
        return None, "MARKET_DATA_FILE_PATH_INVALID"
    return relative.as_posix(), None


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
    for candidate in _walk_regular_candidates(data_root, diagnostics, max_directories=config.max_directories):
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
            max_stream_bytes=config.max_total_bytes - total_bytes,
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
            truncated = True
            continue
        assert record is not None
        total_bytes += record["size_bytes"]
        records.append(record)
    return _filesystem_payload(data_root, records, diagnostics, truncated=truncated or any("MAX_" in item["code"] for item in diagnostics))


def _filesystem_payload(data_root: Path, records: list[dict[str, Any]], diagnostics: list[dict[str, str]], *, truncated: bool) -> dict[str, Any]:
    return {
        "data_root_exists": data_root.is_dir() and not data_root.is_symlink(),
        "data_root_path": str(data_root),
        "records": records,
        "diagnostics": sorted(diagnostics, key=lambda item: (item["code"], item["path"])),
        "truncated": truncated,
    }


def _walk_regular_candidates(
    data_root: Path,
    diagnostics: list[dict[str, str]],
    *,
    max_directories: int,
) -> Iterable[Path]:
    directory_count = 0
    exhausted = False

    def walk(directory: Path) -> Iterable[Path]:
        nonlocal directory_count, exhausted
        if exhausted:
            return
        directory_count += 1
        if directory_count > max_directories:
            diagnostics.append({"code": "MAX_DIRECTORIES_EXCEEDED", "path": f"{data_root.name}/{directory.relative_to(data_root).as_posix()}"})
            exhausted = True
            return
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            diagnostics.append({"code": "DIRECTORY_OPEN_FAILED", "path": f"{data_root.name}/{directory.relative_to(data_root).as_posix()}"})
            return
        for entry in entries:
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
    max_stream_bytes: int | None = None,
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
        if max_stream_bytes is not None and before.st_size > max_stream_bytes:
            return None, {"code": "MAX_TOTAL_BYTES_EXCEEDED", "path": display_path}
        digest = sha256()
        contents = bytearray() if capture_bytes else None
        streamed = 0
        stream_limit = min(max_file_bytes, max_stream_bytes) if max_stream_bytes is not None else max_file_bytes
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while True:
                remaining = stream_limit - streamed
                if remaining <= 0:
                    break
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                streamed += len(chunk)
                if contents is not None:
                    contents.extend(chunk)
        after = os.fstat(descriptor)
        if after.st_size > max_file_bytes:
            return None, {"code": "MAX_FILE_BYTES_EXCEEDED", "path": display_path}
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            return None, {"code": "TOCTOU_CHANGED", "path": display_path}
        if max_stream_bytes is not None and after.st_size > max_stream_bytes:
            return None, {"code": "MAX_TOTAL_BYTES_EXCEEDED", "path": display_path}
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
    for path in _walk_repo_regular_candidates(repo_root, diagnostics, max_directories=config.max_directories):
        relative = path.relative_to(repo_root).as_posix()
        if path.name in _NON_REFERENCE_BASENAME_REASONS or path.suffix.lower() in _NON_REFERENCE_TYPE_REASONS:
            continue
        if not path.suffix and path.name not in _REFERENCE_BASENAMES:
            diagnostics.append({"code": "REPO_UNKNOWN_EXTENSIONLESS_FILE", "path": relative})
            truncated = True
            continue
        if not _is_reference_file(repo_root, path):
            diagnostics.append({"code": "REPO_UNKNOWN_FILE_TYPE", "path": relative})
            truncated = True
            continue
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
            repo_root,
            path.relative_to(repo_root),
            relative,
            config.max_file_bytes,
            capture_bytes=True,
            max_stream_bytes=config.max_total_bytes - total_bytes,
        )
        if diagnostic is not None:
            diagnostics.append({"code": f"REPO_{diagnostic['code']}", "path": relative})
            truncated = True
            continue
        assert record is not None
        total_bytes += record["size_bytes"]
        try:
            lines = record.pop("contents").decode("utf-8").splitlines()
        except UnicodeDecodeError:
            diagnostics.append({"code": "REPO_NON_UTF8_SKIPPED", "path": relative})
            truncated = True
            continue
        kind = "doc" if path.suffix.lower() in {".md", ".txt"} else "code"
        section_state = _reference_state_for_context(relative, "", kind=kind)
        for line_number, line in enumerate(lines, start=1):
            if path.suffix.lower() == ".md" and line.lstrip().startswith("#"):
                section_state = _reference_state_for_context(relative, line.lstrip("#").strip(), kind=kind)
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
                        reference_state = _reference_state_for_context(relative, line, kind=kind, section_state=section_state)
                        locations[category].append(
                            {
                                "path": relative,
                                "line": line_number,
                                "kind": kind,
                                "matched_token": match.group(0),
                                "reason": rule.reason,
                                "reference_state": reference_state,
                                "disposition": "KEEP_ACTIVE_REFERENCE" if reference_state == "active" else "HISTORICAL_SNAPSHOT" if reference_state in {"historical", "non_active"} else "REVIEW_REQUIRED",
                                "sha256": record["sha256"],
                            }
                        )
    return locations, _reference_scan_payload(truncated or any("MAX_" in item["code"] for item in diagnostics), diagnostics)


def _reference_scan_payload(truncated: bool, diagnostics: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "truncated": truncated,
        "diagnostics": sorted(diagnostics, key=lambda item: (item["code"], item["path"])),
        "explicit_file_type_exclusions": [
            {"file_type": file_type, "reason": reason}
            for file_type, reason in sorted({**_NON_REFERENCE_TYPE_REASONS, **_NON_REFERENCE_BASENAME_REASONS}.items())
        ],
    }


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


def _reference_state_for_context(
    relative: str,
    line: str,
    *,
    kind: str = "doc",
    section_state: str | None = None,
) -> str:
    normalized_path = relative.replace("\\", "/")
    if kind != "doc":
        return "review_required" if _AMBIGUOUS_HISTORY_MARKER.search(line) or _EXPLICIT_HISTORICAL_DOC_MARKER.fullmatch(line) else "active"
    if _ACTIVE_OVERRIDE_MARKER.search(line):
        return "active"
    if _EXPLICIT_HISTORICAL_DOC_MARKER.fullmatch(line):
        return "historical"
    if _ARCHIVE_PATH_MARKER.search(normalized_path):
        return "historical"
    if kind == "doc" and section_state is not None and section_state != "active":
        return section_state
    if _AMBIGUOUS_HISTORY_MARKER.search(line):
        return "review_required"
    return "active"


def _is_reference_file(repo_root: Path, path: Path) -> bool:
    if path.suffix.lower() not in _REFERENCE_SUFFIXES and path.name not in _REFERENCE_BASENAMES:
        return False
    relative = path.relative_to(repo_root).as_posix()
    return relative not in _SELF_REFERENCE_PATHS and not any(
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
            "id", "provider", "data_type", "instrument_symbol", "contract_code", "period", "file_path", "checksum", "data_role", "quality_status", "data_version", "disposition", "reason",
        )
    }


def _paths_for_category(category: str, inventory: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in inventory if _matches_path_category(category, record["path"])]


def _matches_path_category(category: str, relative: str) -> bool:
    normalized = relative.lower()
    parts = set(normalized.split("/"))
    if category == "indicator_cache":
        return "indicator" in normalized or "cache" in normalized
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
