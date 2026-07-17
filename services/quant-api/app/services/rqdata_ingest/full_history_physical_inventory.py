from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any, Iterable

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.multi_primary_rulebook import infer_contract_role
from app.services.rqdata_ingest.schema_contract import CANONICAL_BAR_COLUMNS, build_schema_fingerprint

READY = "FULL_HISTORY_PHYSICAL_INVENTORY_READY"
SMOKE_READY = "FULL_HISTORY_PHYSICAL_INVENTORY_SMOKE_READY"
AUDIT_END = date(2026, 7, 10)
REPRESENTATIVE_PRODUCTS = ("a", "al", "ag", "jm")
_WORKER_STATE = threading.local()

PHYSICAL_INVENTORY_COLUMNS = (
    "asset_identity_key",
    "product",
    "contract_role",
    "contract",
    "period",
    "provider",
    "data_role",
    "data_version",
    "physical_path",
    "project_relative_path",
    "physical_exists",
    "physical_status",
    "physical_min_datetime",
    "physical_max_datetime",
    "row_count",
    "file_size_bytes",
    "schema_hash",
    "schema_summary",
    "schema_status",
    "schema_consistency_status",
    "checksum_declared",
    "checksum_actual",
    "checksum_status",
    "manifest_record_count",
    "manifest_sources",
    "processed_summary_record_count",
    "processed_summary_sources",
    "db_record_count",
    "market_data_file_ids",
    "quality_statuses",
    "quality_statuses_manifest",
    "quality_statuses_processed",
    "quality_statuses_db",
    "quality_report_ids",
    "source_interval",
    "duplicate_identity_count",
    "same_path_identity_count",
    "identity_conflict",
    "extends_beyond_audit_end",
    "error_type",
    "error_message",
)

MANIFEST_COLUMNS = (
    "asset_identity_key",
    "physical_path",
    "manifest_record_count",
    "manifest_sources",
    "declared_data_versions",
    "declared_row_counts",
    "declared_min_datetimes",
    "declared_max_datetimes",
    "declared_checksums",
    "declared_quality_statuses",
    "declared_market_data_file_ids",
    "declared_quality_report_ids",
    "identity_conflict",
)

DB_COLUMNS = (
    "market_data_file_id",
    "product",
    "contract_role",
    "contract",
    "period",
    "provider",
    "data_role",
    "data_version",
    "file_path",
    "normalized_physical_path",
    "start_time",
    "end_time",
    "row_count",
    "file_size_bytes",
    "checksum",
    "quality_status",
    "quality_report_count",
    "quality_report_ids",
    "quality_report_statuses",
    "quality_report_metrics",
    "physical_exists",
)


@dataclass(frozen=True)
class NormalizedPath:
    absolute_path: str
    project_relative_path: str
    outside_project_root: bool


@dataclass(frozen=True)
class InventoryConfig:
    project_root: Path
    audit_end: date = AUDIT_END
    scan_mode: str = "quick"
    products: tuple[str, ...] = ()
    max_workers: int = 4
    require_postgresql: bool = True

    def __post_init__(self) -> None:
        if self.audit_end != AUDIT_END:
            raise ValueError(f"audit_end must be {AUDIT_END.isoformat()}")
        if self.scan_mode not in {"quick", "full"}:
            raise ValueError("scan_mode must be quick or full")
        if self.max_workers < 1:
            raise ValueError("max_workers must be positive")


@dataclass(frozen=True)
class EvidenceRecord:
    source_kind: str
    source_ref: str
    product: str
    contract_role: str
    contract: str
    period: str
    provider: str
    data_role: str
    data_version: str
    physical_path: str
    row_count: int | None = None
    min_datetime: str = ""
    max_datetime: str = ""
    checksum: str = ""
    quality_status: str = ""
    market_data_file_id: int | None = None
    quality_report_ids: tuple[int, ...] = ()
    quality_report_statuses: tuple[str, ...] = ()

    @property
    def identity_key(self) -> str:
        return _identity_key(self)


@dataclass(frozen=True)
class InventoryResult:
    physical_inventory: list[dict[str, Any]]
    manifest_aggregation: list[dict[str, Any]]
    db_inventory: list[dict[str, Any]]
    summary: dict[str, Any]


def normalize_inventory_path(project_root: Path, value: str | Path) -> NormalizedPath:
    root = project_root.resolve()
    path = Path(value)
    absolute = (path if path.is_absolute() else root / path).resolve(strict=False)
    try:
        relative = absolute.relative_to(root).as_posix()
    except ValueError:
        relative = ""
    return NormalizedPath(str(absolute), relative, not bool(relative))


def run_full_history_physical_inventory(config: InventoryConfig, session: Session) -> InventoryResult:
    root = config.project_root.resolve()
    canonical_root = root / "data/parquet/canonical/bars"
    if not canonical_root.is_dir():
        raise FileNotFoundError(f"canonical bars root not found: {canonical_root}")
    dialect = session.get_bind().dialect.name
    if config.require_postgresql and dialect != "postgresql":
        raise RuntimeError(f"ENV_BLOCKED_DB: direct PostgreSQL required, got {dialect}")

    product_filter = {item.strip().lower() for item in config.products if item.strip()}
    manifest_records, manifest_stats = _load_manifest_evidence(root, product_filter)
    processed_records, processed_stats = _load_processed_evidence(root, product_filter)
    db_records, db_rows, db_stats = _load_db_evidence(root, session, product_filter)
    records = manifest_records + processed_records + db_records

    physical_paths = []
    for path in sorted(canonical_root.rglob("*.parquet")):
        context = _path_context(path)
        if product_filter and context["product"] not in product_filter:
            continue
        physical_paths.append(str(path.resolve(strict=False)))

    evidence_paths = {record.physical_path for record in records if record.physical_path}
    all_paths = sorted(set(physical_paths) | evidence_paths)
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        summaries = dict(
            zip(
                all_paths,
                executor.map(lambda item: _scan_with_worker_connection(Path(item), config.scan_mode), all_paths),
                strict=True,
            )
        )

    grouped: dict[tuple[str, str], list[EvidenceRecord]] = defaultdict(list)
    records_by_path: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        if not record.physical_path:
            continue
        grouped[(record.identity_key, record.physical_path)].append(record)
        records_by_path[record.physical_path].append(record)

    for path in physical_paths:
        if path in records_by_path:
            continue
        context = _path_context(Path(path))
        record = EvidenceRecord(
            source_kind="physical",
            source_ref="physical_scan",
            product=context["product"],
            contract_role=infer_contract_role(context["contract"]),
            contract=context["contract"],
            period=context["period"],
            provider=context["provider"],
            data_role="",
            data_version="",
            physical_path=path,
        )
        grouped[(record.identity_key, path)].append(record)
        records_by_path[path].append(record)

    identity_path_counts = defaultdict(set)
    path_identity_counts = defaultdict(set)
    for identity, path in grouped:
        identity_path_counts[identity].add(path)
        path_identity_counts[path].add(identity)

    rows = []
    for (identity, path), group in sorted(grouped.items()):
        physical = summaries.get(path) or scan_physical_asset(Path(path), scan_mode=config.scan_mode)
        manifests = [item for item in group if item.source_kind == "manifest"]
        processed = [item for item in group if item.source_kind == "processed_summary"]
        db_items = [item for item in group if item.source_kind == "db_market_data_file"]
        declared = _values(item.checksum for item in group)
        checksum_status = _checksum_status(config.scan_mode, declared, physical["checksum_actual"])
        sample = group[0]
        normalized = normalize_inventory_path(root, path)
        max_datetime = physical["physical_max_datetime"]
        rows.append(
            {
                "asset_identity_key": identity,
                "product": sample.product,
                "contract_role": sample.contract_role,
                "contract": sample.contract,
                "period": sample.period,
                "provider": sample.provider,
                "data_role": sample.data_role,
                "data_version": sample.data_version,
                "physical_path": path,
                "project_relative_path": normalized.project_relative_path,
                "physical_exists": physical["physical_exists"],
                "physical_status": physical["physical_status"],
                "physical_min_datetime": physical["physical_min_datetime"],
                "physical_max_datetime": max_datetime,
                "row_count": physical["row_count"],
                "file_size_bytes": physical["file_size_bytes"],
                "schema_hash": physical["schema_hash"],
                "schema_summary": physical["schema_summary"],
                "schema_status": physical["schema_status"],
                "schema_consistency_status": "pending",
                "checksum_declared": _json(declared),
                "checksum_actual": physical["checksum_actual"],
                "checksum_status": checksum_status,
                "manifest_record_count": len(manifests),
                "manifest_sources": _json(_values(item.source_ref for item in manifests)),
                "processed_summary_record_count": len(processed),
                "processed_summary_sources": _json(_values(item.source_ref for item in processed)),
                "db_record_count": len(db_items),
                "market_data_file_ids": _json(_values(item.market_data_file_id for item in db_items)),
                "quality_statuses": _json(
                    _values(
                        [item.quality_status for item in group]
                        + [status for item in db_items for status in item.quality_report_statuses]
                    )
                ),
                "quality_statuses_manifest": _json(_values(item.quality_status for item in manifests)),
                "quality_statuses_processed": _json(_values(item.quality_status for item in processed)),
                "quality_statuses_db": _json(
                    _values(
                        [item.quality_status for item in db_items]
                        + [status for item in db_items for status in item.quality_report_statuses]
                    )
                ),
                "quality_report_ids": _json(_values(item_id for item in group for item_id in item.quality_report_ids)),
                "source_interval": physical["source_interval"],
                "duplicate_identity_count": len(identity_path_counts[identity]),
                "same_path_identity_count": len(path_identity_counts[path]),
                "identity_conflict": len(path_identity_counts[path]) > 1,
                "extends_beyond_audit_end": _after_audit_end(max_datetime, config.audit_end),
                "error_type": physical["error_type"],
                "error_message": physical["error_message"],
            }
        )

    fingerprints: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row["schema_hash"]:
            fingerprints[row["asset_identity_key"]].add(row["schema_hash"])
    for row in rows:
        values = fingerprints[row["asset_identity_key"]]
        row["schema_consistency_status"] = "inconsistent" if len(values) > 1 else "consistent" if values else "unavailable"

    manifest_output = _manifest_aggregation(grouped, path_identity_counts)
    unresolved = sum(
        not row["product"] or not row["contract"] or not row["period"] or not row["provider"]
        for row in rows
    )
    represented = sorted({row["product"] for row in rows if row["physical_exists"]})
    representative = {product: product in represented for product in REPRESENTATIVE_PRODUCTS}
    representative_samples = {
        product: _product_sample(rows, product)
        for product in REPRESENTATIVE_PRODUCTS
    }
    parse_errors = manifest_stats["parse_errors"] + processed_stats["parse_errors"]
    status = SMOKE_READY if product_filter else READY
    if parse_errors or unresolved or (not product_filter and not all(representative.values())):
        status = "FULL_HISTORY_PHYSICAL_INVENTORY_PARTIAL"
    summary = {
        "status": status,
        "data_layer_status": "DATA_LAYER_REAUDIT_REQUIRED",
        "audit_end": config.audit_end.isoformat(),
        "scan_mode": config.scan_mode,
        "git_commit": _git_commit(root),
        "scope": "filtered_smoke" if product_filter else "full",
        "products_filter": sorted(product_filter),
        "db_snapshot_source": "direct_postgresql" if dialect == "postgresql" else "test_database",
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "expected_matrix_generated": False,
        "physical_file_count": len(physical_paths),
        "physical_inventory_rows": len(rows),
        "manifest": manifest_stats,
        "processed_summary": processed_stats,
        "database": db_stats,
        "unresolved_identity_count": unresolved,
        "representative_products": representative,
        "representative_product_samples": representative_samples,
        "physical_status_counts": _count(rows, "physical_status"),
        "schema_status_counts": _count(rows, "schema_status"),
        "checksum_status_counts": _count(rows, "checksum_status"),
        "outside_project_root_count": sum(not row["project_relative_path"] for row in rows),
        "path_drift": {
            "outside_project_root_rows": sum(not row["project_relative_path"] for row in rows),
            "outside_canonical_root_rows": sum(
                not _is_relative_to(Path(row["physical_path"]), canonical_root)
                for row in rows
            ),
            "missing_physical_rows": sum(not row["physical_exists"] for row in rows),
            "db_rows_with_missing_physical": sum(not row["physical_exists"] for row in db_rows),
        },
        "anomaly_counts": {
            "empty_file_rows": sum(row["physical_status"] == "empty_file" for row in rows),
            "parquet_read_failed_rows": sum(row["physical_status"] == "parquet_read_failed" for row in rows),
            "schema_mismatch_rows": sum(row["schema_status"] == "schema_mismatch" for row in rows),
            "schema_inconsistent_rows": sum(
                row["schema_consistency_status"] == "inconsistent" for row in rows
            ),
            "identity_conflict_rows": sum(bool(row["identity_conflict"]) for row in rows),
            "duplicate_identity_rows": sum(int(row["duplicate_identity_count"]) > 1 for row in rows),
            "extends_beyond_audit_end_rows": sum(bool(row["extends_beyond_audit_end"]) for row in rows),
        },
    }
    return InventoryResult(rows, manifest_output, db_rows, summary)


def scan_physical_asset(
    path: Path,
    *,
    scan_mode: str,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any]:
    base = {
        "physical_exists": path.is_file(),
        "physical_status": "missing_file",
        "physical_min_datetime": "",
        "physical_max_datetime": "",
        "row_count": None,
        "file_size_bytes": path.stat().st_size if path.is_file() else 0,
        "schema_hash": "",
        "schema_summary": _json({}),
        "schema_status": "unavailable",
        "checksum_actual": "",
        "source_interval": _json([]),
        "error_type": "",
        "error_message": "",
    }
    if not path.is_file():
        return base
    if path.stat().st_size == 0:
        base["physical_status"] = "empty_file"
        base["error_type"] = "EmptyFile"
        return base
    owns_connection = connection is None
    connection = connection or duckdb.connect(database=":memory:")
    try:
        described = connection.execute("describe select * from read_parquet(?)", [str(path)]).fetchall()
        schema = {str(item[0]): str(item[1]) for item in described}
        row = connection.execute(
            "select count(*), min(datetime), max(datetime) from read_parquet(?)",
            [str(path)],
        ).fetchone()
        source_values: list[str] = []
        if "source_interval" in schema:
            source_values = [
                str(item[0])
                for item in connection.execute(
                    "select distinct source_interval from read_parquet(?) where source_interval is not null order by 1",
                    [str(path)],
                ).fetchall()
            ]
    except Exception as exc:  # noqa: BLE001 - each unreadable asset is inventory evidence.
        base["physical_status"] = "parquet_read_failed"
        base["error_type"] = type(exc).__name__
        base["error_message"] = str(exc)[:500]
        return base
    finally:
        if owns_connection:
            connection.close()
    missing = sorted(set(CANONICAL_BAR_COLUMNS) - set(schema))
    base.update(
        {
            "physical_status": "readable",
            "physical_min_datetime": _iso(row[1]),
            "physical_max_datetime": _iso(row[2]),
            "row_count": int(row[0]),
            "schema_hash": build_schema_fingerprint(schema),
            "schema_summary": _json(dict(sorted(schema.items()))),
            "schema_status": "schema_ok" if not missing else "schema_mismatch",
            "source_interval": _json(source_values),
        }
    )
    if scan_mode == "full":
        base["checksum_actual"] = _sha256(path)
    return base


def _scan_with_worker_connection(path: Path, scan_mode: str) -> dict[str, Any]:
    connection = getattr(_WORKER_STATE, "duckdb_connection", None)
    if connection is None:
        connection = duckdb.connect(database=":memory:")
        _WORKER_STATE.duckdb_connection = connection
    return scan_physical_asset(path, scan_mode=scan_mode, connection=connection)


def write_inventory_reports(result: InventoryResult, output_dir: Path) -> dict[str, Path]:
    output_dir = output_dir.resolve(strict=False)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.with_name(f".{output_dir.name}.partial-{os.getpid()}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        _write_csv(staging / "physical_inventory.csv", result.physical_inventory, PHYSICAL_INVENTORY_COLUMNS)
        _write_csv(staging / "manifest_aggregation.csv", result.manifest_aggregation, MANIFEST_COLUMNS)
        _write_csv(staging / "db_inventory.csv", result.db_inventory, DB_COLUMNS)
        (staging / "inventory_summary.json").write_text(
            json.dumps(result.summary, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        staging.rename(output_dir)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "physical_inventory": output_dir / "physical_inventory.csv",
        "manifest_aggregation": output_dir / "manifest_aggregation.csv",
        "db_inventory": output_dir / "db_inventory.csv",
        "inventory_summary": output_dir / "inventory_summary.json",
    }


def _load_manifest_evidence(root: Path, product_filter: set[str]) -> tuple[list[EvidenceRecord], dict[str, int]]:
    records: list[EvidenceRecord] = []
    files = rows_seen = asset_rows = parse_errors = 0
    manifest_root = root / "data/manifests"
    for path in sorted(manifest_root.rglob("*.csv")) if manifest_root.exists() else []:
        files += 1
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                for line_number, row in enumerate(reader, start=2):
                    rows_seen += 1
                    if not _text(row.get("standard_path")) or not _text(row.get("period")):
                        continue
                    record = _record_from_mapping(
                        root,
                        row,
                        source_kind="manifest",
                        source_ref=f"{path.relative_to(root).as_posix()}#{line_number}",
                    )
                    if product_filter and record.product not in product_filter:
                        continue
                    records.append(record)
                    asset_rows += 1
        except (OSError, UnicodeError, csv.Error, ValueError):
            parse_errors += 1
    return records, {"files": files, "rows_seen": rows_seen, "asset_rows": asset_rows, "parse_errors": parse_errors}


def _load_processed_evidence(root: Path, product_filter: set[str]) -> tuple[list[EvidenceRecord], dict[str, int]]:
    records: list[EvidenceRecord] = []
    files = period_records = parse_errors = 0
    processed_root = root / "data/processed/v1b"
    for path in sorted(processed_root.rglob("*.json")) if processed_root.exists() else []:
        files += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for period, details in (payload.get("periods") or {}).items():
                standard = (details or {}).get("standard") or {}
                if not _text(standard.get("path")):
                    continue
                mapping = {
                    "product": payload.get("symbol") or payload.get("product"),
                    "contract": payload.get("contract"),
                    "period": period,
                    "provider": details.get("provider") or standard.get("provider") or "rqdata",
                    "data_role": details.get("data_role") or standard.get("data_role") or "primary",
                    "quality_status": details.get("quality_status") or standard.get("quality_status"),
                    "data_version": details.get("data_version") or standard.get("data_version"),
                    "row_count": standard.get("row_count"),
                    "min_datetime": standard.get("min_datetime"),
                    "max_datetime": standard.get("max_datetime"),
                    "checksum": standard.get("checksum"),
                    "standard_path": standard.get("path"),
                }
                record = _record_from_mapping(
                    root,
                    mapping,
                    source_kind="processed_summary",
                    source_ref=path.relative_to(root).as_posix(),
                )
                if product_filter and record.product not in product_filter:
                    continue
                records.append(record)
                period_records += 1
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            parse_errors += 1
    return records, {"files": files, "period_records": period_records, "parse_errors": parse_errors}


def _load_db_evidence(
    root: Path,
    session: Session,
    product_filter: set[str],
) -> tuple[list[EvidenceRecord], list[dict[str, Any]], dict[str, int]]:
    market_query = select(MarketDataFile).where(MarketDataFile.data_type == "bars")
    quality_query = select(DataQualityReport).where(DataQualityReport.data_type == "bars")
    market_files = list(session.scalars(market_query))
    reports = list(session.scalars(quality_query))
    reports_by_file: dict[int, list[DataQualityReport]] = defaultdict(list)
    market_file_ids = {item.id for item in market_files}
    unlinked = 0
    for report in reports:
        if report.file_id is None or report.file_id not in market_file_ids:
            unlinked += 1
        else:
            reports_by_file[report.file_id].append(report)

    evidence: list[EvidenceRecord] = []
    db_rows: list[dict[str, Any]] = []
    for item in market_files:
        product = _text(item.instrument_symbol).lower()
        if product_filter and product not in product_filter:
            continue
        normalized = normalize_inventory_path(root, item.file_path)
        linked = sorted(reports_by_file.get(item.id, []), key=lambda report: report.id)
        record = EvidenceRecord(
            source_kind="db_market_data_file",
            source_ref=f"market_data_files:{item.id}",
            product=product,
            contract_role=infer_contract_role(_text(item.contract_code)),
            contract=_text(item.contract_code),
            period=_text(item.period),
            provider=_text(item.provider),
            data_role=_text(item.data_role),
            data_version=_text(item.data_version),
            physical_path=normalized.absolute_path,
            row_count=item.row_count,
            min_datetime=_iso(item.start_time),
            max_datetime=_iso(item.end_time),
            checksum=_text(item.checksum),
            quality_status=_text(item.quality_status),
            market_data_file_id=item.id,
            quality_report_ids=tuple(report.id for report in linked),
            quality_report_statuses=tuple(_text(report.status) for report in linked),
        )
        evidence.append(record)
        db_rows.append(
            {
                "market_data_file_id": item.id,
                "product": product,
                "contract_role": record.contract_role,
                "contract": record.contract,
                "period": record.period,
                "provider": record.provider,
                "data_role": record.data_role,
                "data_version": record.data_version,
                "file_path": item.file_path,
                "normalized_physical_path": normalized.absolute_path,
                "start_time": _iso(item.start_time),
                "end_time": _iso(item.end_time),
                "row_count": item.row_count,
                "file_size_bytes": item.file_size_bytes,
                "checksum": _text(item.checksum),
                "quality_status": _text(item.quality_status),
                "quality_report_count": len(linked),
                "quality_report_ids": _json([report.id for report in linked]),
                "quality_report_statuses": _json(_values(report.status for report in linked)),
                "quality_report_metrics": _json(
                    [
                        {
                            "id": report.id,
                            "missing_bars": report.missing_bars,
                            "duplicated_bars": report.duplicated_bars,
                            "abnormal_price_count": report.abnormal_price_count,
                            "abnormal_volume_count": report.abnormal_volume_count,
                        }
                        for report in linked
                    ]
                ),
                "physical_exists": Path(normalized.absolute_path).is_file(),
            }
        )
    db_rows.sort(key=lambda row: int(row["market_data_file_id"]))
    return evidence, db_rows, {
        "market_data_file_rows": len(db_rows),
        "quality_report_rows": sum(len(reports_by_file.get(int(row["market_data_file_id"]), [])) for row in db_rows),
        "unlinked_quality_report_rows": unlinked,
    }


def _record_from_mapping(root: Path, row: dict[str, Any], *, source_kind: str, source_ref: str) -> EvidenceRecord:
    normalized = normalize_inventory_path(root, _text(row.get("standard_path")))
    context = _path_context(Path(normalized.absolute_path))
    product = (_text(row.get("product")) or _text(row.get("symbol")) or context["product"]).lower()
    contract = (
        _text(row.get("actual_contract"))
        or _text(row.get("contract"))
        or _text(row.get("continuous_contract"))
        or context["contract"]
    )
    return EvidenceRecord(
        source_kind=source_kind,
        source_ref=source_ref,
        product=product,
        contract_role=infer_contract_role(contract),
        contract=contract,
        period=_text(row.get("period")) or context["period"],
        provider=_text(row.get("provider")) or context["provider"],
        data_role=_text(row.get("data_role")),
        data_version=_text(row.get("data_version")),
        physical_path=normalized.absolute_path,
        row_count=_integer(row.get("row_count")),
        min_datetime=_text(row.get("min_datetime")),
        max_datetime=_text(row.get("max_datetime")),
        checksum=_text(row.get("checksum")),
        quality_status=_text(row.get("quality_status")),
        market_data_file_id=_integer(row.get("market_data_file_id")),
        quality_report_ids=tuple(item for item in [_integer(row.get("data_quality_report_id"))] if item is not None),
    )


def _manifest_aggregation(
    grouped: dict[tuple[str, str], list[EvidenceRecord]],
    path_identity_counts: dict[str, set[str]],
) -> list[dict[str, Any]]:
    output = []
    for (identity, path), group in sorted(grouped.items()):
        manifests = [item for item in group if item.source_kind == "manifest"]
        if not manifests:
            continue
        output.append(
            {
                "asset_identity_key": identity,
                "physical_path": path,
                "manifest_record_count": len(manifests),
                "manifest_sources": _json(_values(item.source_ref for item in manifests)),
                "declared_data_versions": _json(_values(item.data_version for item in manifests)),
                "declared_row_counts": _json(_values(item.row_count for item in manifests)),
                "declared_min_datetimes": _json(_values(item.min_datetime for item in manifests)),
                "declared_max_datetimes": _json(_values(item.max_datetime for item in manifests)),
                "declared_checksums": _json(_values(item.checksum for item in manifests)),
                "declared_quality_statuses": _json(_values(item.quality_status for item in manifests)),
                "declared_market_data_file_ids": _json(_values(item.market_data_file_id for item in manifests)),
                "declared_quality_report_ids": _json(
                    _values(item_id for item in manifests for item_id in item.quality_report_ids)
                ),
                "identity_conflict": len(path_identity_counts[path]) > 1,
            }
        )
    return output


def _path_context(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for part in path.parts:
        if "=" in part:
            key, value = part.split("=", 1)
            values[key] = value
    return {
        "provider": values.get("provider", ""),
        "period": values.get("period", ""),
        "product": values.get("symbol", "").lower(),
        "contract": values.get("contract", ""),
    }


def _identity_key(item: EvidenceRecord) -> str:
    return "|".join(
        [
            item.product,
            item.contract_role,
            item.contract,
            item.period,
            item.provider,
            item.data_role,
            item.data_version,
        ]
    )


def _checksum_status(mode: str, declared: list[Any], actual: str) -> str:
    if mode == "quick":
        return "not_computed"
    if not declared:
        return "no_declared_checksum"
    if len(declared) > 1:
        return "declared_conflict"
    return "matched" if declared[0] == actual else "mismatch"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _values(values: Iterable[Any]) -> list[Any]:
    unique = {value for value in values if value not in (None, "")}
    return sorted(unique, key=lambda value: (str(type(value)), str(value)))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _integer(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str:
    if value is None:
        return ""
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


def _after_audit_end(value: str, audit_end: date) -> bool:
    if not value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date() > audit_end
    except ValueError:
        return False


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for row in rows:
        result[str(row.get(key, ""))] += 1
    return dict(sorted(result.items()))


def _product_sample(rows: list[dict[str, Any]], product: str) -> dict[str, Any]:
    selected = [row for row in rows if row["product"] == product]
    minimums = [row["physical_min_datetime"] for row in selected if row["physical_min_datetime"]]
    maximums = [row["physical_max_datetime"] for row in selected if row["physical_max_datetime"]]
    return {
        "inventory_rows": len(selected),
        "physical_exists_rows": sum(bool(row["physical_exists"]) for row in selected),
        "manifest_record_count": sum(int(row["manifest_record_count"]) for row in selected),
        "processed_summary_record_count": sum(int(row["processed_summary_record_count"]) for row in selected),
        "db_record_count": sum(int(row["db_record_count"]) for row in selected),
        "physical_min_datetime": min(minimums, default=""),
        "physical_max_datetime": max(maximums, default=""),
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _git_commit(project_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
