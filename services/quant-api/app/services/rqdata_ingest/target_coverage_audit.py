from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import (
    DataQualityReport,
    FuturesContinuousContractMap,
    FuturesContractUniverse,
    FuturesTradingParameter,
    MainContractMap,
    MarketDataFile,
    TradingCalendar,
    TradingSession,
)


MODE = "target_coverage_audit"
DEFAULT_AUDIT_END = date(2026, 7, 10)
DEFAULT_MINUTE_START = date(2023, 1, 3)
CATALOG_YEARS = tuple(range(2020, 2027))
DOMINANT_LONG_PERIODS = ("1d", "1w")
DOMINANT_MINUTE_PERIODS = ("1m", "5m", "15m", "30m", "60m")
DERIVED_FROM_1M_PERIODS = ("5m", "15m", "30m", "60m", "1d")
REQUIRED_TRADING_PARAMETER_FIELDS = (
    "price_tick",
    "contract_multiplier",
    "long_margin_ratio",
    "short_margin_ratio",
    "open_commission",
    "close_commission",
    "close_today_commission",
)
PASS_STATUSES = {"passed"}
WARNING_STATUSES = {"warning", "unchecked"}


@dataclass(frozen=True)
class ProductWindow:
    product: str
    window_start: date
    listed_date: date | None
    effective_1d_start: date
    note: str


@dataclass(frozen=True)
class EvidenceRecord:
    product: str
    contract_role: str
    contract: str
    period: str
    provider: str
    data_role: str
    quality_status: str
    start_date: date | None
    end_date: date | None
    row_count: int | None
    checksum: str
    path: Path | None
    evidence_source: str
    manifest_status: str = ""
    db_file_id: int | None = None
    data_version: str = ""
    quality_report_status: str = ""


def load_product_windows(path: Path, products: list[str] | None = None) -> dict[str, ProductWindow]:
    frame = pd.read_csv(path).fillna("")
    allowed = {product.lower() for product in products} if products else None
    windows: dict[str, ProductWindow] = {}
    for row in frame.to_dict("records"):
        product = _clean_text(row.get("product")).lower()
        if not product or allowed is not None and product not in allowed:
            continue
        windows[product] = ProductWindow(
            product=product,
            window_start=_to_date(row.get("window_start")) or date(2020, 1, 2),
            listed_date=_to_date(row.get("product_listed_date")),
            effective_1d_start=_to_date(row.get("effective_1d_start")) or date(2020, 1, 2),
            note=_clean_text(row.get("note")),
        )
    return windows


def audit_target_coverage(
    *,
    session: Session | None,
    project_root: Path,
    product_windows: dict[str, ProductWindow],
    audit_end: date = DEFAULT_AUDIT_END,
    api_coverage: list[dict[str, Any]] | None = None,
    api_quality_reports: list[dict[str, Any]] | None = None,
    db_snapshot_source: str = "database",
    db_error: str = "",
) -> dict[str, Any]:
    products = sorted(product_windows)
    db_snapshot = _load_snapshot_from_session(session) if session is not None else _snapshot_from_api(api_coverage, api_quality_reports)
    manifest_evidence = _load_manifest_evidence(project_root=project_root, products=products)
    processed_evidence = _load_processed_summary_evidence(project_root=project_root, products=products)
    db_evidence = _market_file_evidence(db_snapshot["market_files"], db_snapshot["quality_reports"])

    all_evidence = _merge_evidence(manifest_evidence + processed_evidence + db_evidence)
    target_catalog = _build_target_catalog(product_windows=product_windows, evidence=all_evidence, audit_end=audit_end)
    physical_cache = _build_physical_cache(all_evidence)
    physical_inventory = _build_physical_inventory(evidence=all_evidence, physical_cache=physical_cache)
    coverage_matrix = _build_coverage_matrix(target_catalog=target_catalog, evidence=all_evidence, physical_cache=physical_cache)
    metadata_matrix = _build_metadata_matrix(
        product_windows=product_windows,
        snapshot=db_snapshot,
        audit_end=audit_end,
        db_available=session is not None,
    )
    issue_register = _build_issue_register(coverage_matrix=coverage_matrix, metadata_matrix=metadata_matrix)
    summary = _render_summary(
        products=products,
        audit_end=audit_end,
        db_snapshot_source=db_snapshot_source,
        db_error=db_error,
        target_catalog=target_catalog,
        physical_inventory=physical_inventory,
        coverage_matrix=coverage_matrix,
        metadata_matrix=metadata_matrix,
        issue_register=issue_register,
    )
    return {
        "mode": MODE,
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "db_snapshot_source": db_snapshot_source,
        "db_error": db_error,
        "target_asset_catalog": target_catalog,
        "asset_physical_inventory": physical_inventory,
        "target_coverage_matrix": coverage_matrix,
        "metadata_consistency_matrix": metadata_matrix,
        "issue_register": issue_register,
        "coverage_summary": summary,
    }


def write_target_coverage_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "target_asset_catalog": output_dir / "target_asset_catalog.csv",
        "asset_physical_inventory": output_dir / "asset_physical_inventory.csv",
        "target_coverage_matrix": output_dir / "target_coverage_matrix.csv",
        "metadata_consistency_matrix": output_dir / "metadata_consistency_matrix.csv",
        "issue_register": output_dir / "issue_register.csv",
        "coverage_summary": output_dir / "coverage_summary.md",
    }
    for key, path in outputs.items():
        if key == "coverage_summary":
            path.write_text(result[key], encoding="utf-8")
        else:
            pd.DataFrame(result[key]).to_csv(path, index=False)
    return outputs


def _load_snapshot_from_session(session: Session) -> dict[str, list[Any]]:
    return {
        "market_files": list(session.scalars(select(MarketDataFile))),
        "quality_reports": list(session.scalars(select(DataQualityReport).order_by(DataQualityReport.created_at.desc(), DataQualityReport.id.desc()))),
        "main_contract_map": list(session.scalars(select(MainContractMap).where(MainContractMap.provider == "rqdata"))),
        "contract_universe": list(session.scalars(select(FuturesContractUniverse).where(FuturesContractUniverse.provider == "rqdata"))),
        "continuous_contract_map": list(session.scalars(select(FuturesContinuousContractMap).where(FuturesContinuousContractMap.provider == "rqdata"))),
        "trading_parameters": list(session.scalars(select(FuturesTradingParameter).where(FuturesTradingParameter.provider == "rqdata"))),
        "trading_calendar": list(session.scalars(select(TradingCalendar))),
        "trading_sessions": list(session.scalars(select(TradingSession))),
    }


def _snapshot_from_api(api_coverage: list[dict[str, Any]] | None, api_quality_reports: list[dict[str, Any]] | None) -> dict[str, list[Any]]:
    return {
        "market_files": api_coverage or [],
        "quality_reports": api_quality_reports or [],
        "main_contract_map": [],
        "contract_universe": [],
        "continuous_contract_map": [],
        "trading_parameters": [],
        "trading_calendar": [],
        "trading_sessions": [],
    }


def _load_manifest_evidence(*, project_root: Path, products: list[str]) -> list[EvidenceRecord]:
    rows: list[EvidenceRecord] = []
    product_set = set(products)
    manifest_root = project_root / "data" / "manifests"
    for manifest in sorted(manifest_root.glob("rqdata_*_v2_history_*.csv")):
        product = manifest.name.removeprefix("rqdata_").split("_v2_history_", 1)[0].lower()
        if product not in product_set:
            continue
        for row in _read_csv_records(manifest):
            rows.append(_manifest_record(project_root, row, product=product, contract_role="dominant_main", default_contract=f"{product}.MAIN"))
    for manifest in sorted(manifest_root.glob("rqdata_actual_contract_bars_*.csv")):
        if manifest.name == "rqdata_actual_contract_bars_batch.csv":
            continue
        fallback_product = _actual_contract_manifest_product(manifest.name, product_set)
        for row in _read_csv_records(manifest):
            product = (_clean_text(row.get("product")) or fallback_product).lower()
            if product not in product_set:
                continue
            contract = _clean_text(row.get("actual_contract"))
            rows.append(_manifest_record(project_root, row, product=product, contract_role="actual_contract", default_contract=contract))
    return rows


def _actual_contract_manifest_product(filename: str, products: set[str]) -> str:
    payload = filename.removeprefix("rqdata_actual_contract_bars_")
    matches = [product for product in products if payload.startswith(f"{product}_")]
    return max(matches, key=len) if matches else ""


def _load_processed_summary_evidence(*, project_root: Path, products: list[str]) -> list[EvidenceRecord]:
    rows: list[EvidenceRecord] = []
    for product in products:
        for summary_path in sorted((project_root / "data" / "processed" / "v1b" / product).glob(f"{product}_v2_parquet_*.json")):
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            for period, period_summary in (summary.get("periods") or {}).items():
                standard = (period_summary or {}).get("standard") or {}
                rows.append(
                    EvidenceRecord(
                        product=product,
                        contract_role="dominant_main",
                        contract=f"{product}.MAIN",
                        period=_clean_text(period),
                        provider="rqdata",
                        data_role="primary",
                        quality_status=_clean_text(period_summary.get("quality_status")),
                        start_date=_to_date(standard.get("min_datetime")),
                        end_date=_to_date(standard.get("max_datetime")),
                        row_count=_to_int(standard.get("row_count")),
                        checksum=_clean_text(standard.get("checksum")),
                        path=_resolve_path(project_root, _clean_text(standard.get("path"))),
                        evidence_source="processed_summary",
                        manifest_status="summary_only",
                        data_version=_clean_text(period_summary.get("data_version")),
                    )
                )
    return rows


def _manifest_record(project_root: Path, row: dict[str, Any], *, product: str, contract_role: str, default_contract: str) -> EvidenceRecord:
    return EvidenceRecord(
        product=product,
        contract_role=contract_role,
        contract=_clean_text(row.get("actual_contract")) or default_contract,
        period=_clean_text(row.get("period")),
        provider=_clean_text(row.get("provider")) or "rqdata",
        data_role=_clean_text(row.get("data_role")),
        quality_status=_clean_text(row.get("quality_status")),
        start_date=_to_date(row.get("min_datetime")),
        end_date=_to_date(row.get("max_datetime")),
        row_count=_to_int(row.get("row_count")),
        checksum=_clean_text(row.get("checksum")),
        path=_resolve_path(project_root, _clean_text(row.get("standard_path"))),
        evidence_source="manifest",
        manifest_status=_clean_text(row.get("status")),
        data_version=_clean_text(row.get("data_version")),
    )


def _market_file_evidence(market_files: list[Any], quality_reports: list[Any]) -> list[EvidenceRecord]:
    reports = _quality_reports_by_file_id(quality_reports)
    rows = []
    for item in market_files:
        if _get(item, "provider") != "rqdata" or _get(item, "data_type") != "bars":
            continue
        product = _clean_text(_get(item, "instrument_symbol")).lower()
        contract = _clean_text(_get(item, "contract_code"))
        period = _clean_text(_get(item, "period"))
        role = "dominant_main" if contract.lower() == f"{product}.main" else "actual_contract"
        file_id = _to_int(_get(item, "id"))
        report = reports.get(file_id)
        rows.append(
            EvidenceRecord(
                product=product,
                contract_role=role,
                contract=contract,
                period=period,
                provider="rqdata",
                data_role=_clean_text(_get(item, "data_role")),
                quality_status=_clean_text(_get(item, "quality_status")),
                start_date=_to_date(_get(item, "start_time")),
                end_date=_to_date(_get(item, "end_time")),
                row_count=_to_int(_get(item, "row_count")),
                checksum=_clean_text(_get(item, "checksum")),
                path=Path(_clean_text(_get(item, "file_path"))) if _clean_text(_get(item, "file_path")) else None,
                evidence_source="db_market_data_file",
                db_file_id=file_id,
                data_version=_clean_text(_get(item, "data_version")),
                quality_report_status=_clean_text(_get(report, "status")) if report is not None else "",
            )
        )
    return rows


def _quality_reports_by_file_id(quality_reports: list[Any]) -> dict[int | None, Any]:
    by_file_id: dict[int | None, Any] = {}
    for report in quality_reports:
        file_id = _to_int(_get(report, "file_id"))
        if file_id not in by_file_id:
            by_file_id[file_id] = report
    return by_file_id


def _merge_evidence(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    grouped: dict[tuple[str, str, str, str, str], list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        if not record.product or not record.period:
            continue
        path_key = str(record.path.resolve()) if record.path is not None and record.path.exists() else str(record.path or "")
        grouped[(record.product, record.contract_role, record.contract, record.period, path_key)].append(record)

    merged = []
    for group in grouped.values():
        primary = sorted(group, key=lambda item: _evidence_rank(item.evidence_source))[0]
        merged.append(
            EvidenceRecord(
                product=primary.product,
                contract_role=primary.contract_role,
                contract=primary.contract,
                period=primary.period,
                provider=_first_text(group, "provider"),
                data_role=_first_text(group, "data_role"),
                quality_status=_best_quality(group),
                start_date=_min_date(item.start_date for item in group),
                end_date=_max_date(item.end_date for item in group),
                row_count=_first_int(group, "row_count"),
                checksum=_first_text(group, "checksum"),
                path=primary.path or next((item.path for item in group if item.path is not None), None),
                evidence_source=",".join(sorted({item.evidence_source for item in group})),
                manifest_status=_first_text(group, "manifest_status"),
                db_file_id=_first_int(group, "db_file_id"),
                data_version=_first_text(group, "data_version"),
                quality_report_status=_first_text(group, "quality_report_status"),
            )
        )
    return sorted(merged, key=lambda item: (item.product, item.contract_role, item.contract, item.period, str(item.path or "")))


def _build_target_catalog(
    *,
    product_windows: dict[str, ProductWindow],
    evidence: list[EvidenceRecord],
    audit_end: date,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for product, window in sorted(product_windows.items()):
        for period in DOMINANT_LONG_PERIODS:
            for year in CATALOG_YEARS:
                rows.append(_target_row(window, "dominant_main", f"{product}.MAIN", period, year, audit_end, "dominant_2020_plus"))
        for period in ("1m", *DERIVED_FROM_1M_PERIODS):
            for year in range(DEFAULT_MINUTE_START.year, audit_end.year + 1):
                reason = "dominant_2023_plus_1m" if period == "1m" else "dominant_2023_plus_derived_from_1m"
                rows.append(_target_row(window, "dominant_main", f"{product}.MAIN", period, year, audit_end, reason, min_start=DEFAULT_MINUTE_START))

    actual_keys = {
        (item.product, item.contract, item.period, year)
        for item in evidence
        if item.contract_role == "actual_contract"
        for year in _covered_years(item.start_date, item.end_date)
    }
    for product, contract, period, year in sorted(actual_keys):
        window = product_windows.get(product)
        if window is None:
            continue
        rows.append(_target_row(window, "actual_contract", contract, period, year, audit_end, "actual_contract_discovered"))

    unique: dict[tuple[str, str, str, str, int], dict[str, Any]] = {}
    for row in rows:
        key = (row["product"], row["contract_role"], row["symbol_or_contract"], row["period"], row["year"])
        existing = unique.get(key)
        if existing is None:
            unique[key] = row
        elif row["target_reason"] not in existing["target_reason"]:
            existing["target_reason"] += ";" + row["target_reason"]
    return list(unique.values())


def _target_row(
    window: ProductWindow,
    contract_role: str,
    contract: str,
    period: str,
    year: int,
    audit_end: date,
    reason: str,
    min_start: date | None = None,
) -> dict[str, Any]:
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    expected_start = max(year_start, window.effective_1d_start, min_start or window.effective_1d_start)
    expected_end = min(year_end, audit_end)
    applicable = expected_start <= expected_end
    return {
        "product": window.product,
        "contract_role": contract_role,
        "symbol_or_contract": contract,
        "period": period,
        "year": year,
        "expected_start": expected_start.isoformat() if applicable else "",
        "expected_end": expected_end.isoformat() if applicable else "",
        "target_status": "expected" if applicable else "not_applicable",
        "target_reason": reason,
        "product_listed_date": window.listed_date.isoformat() if window.listed_date else "",
        "effective_1d_start": window.effective_1d_start.isoformat(),
        "note": window.note,
    }


def _build_physical_cache(evidence: list[EvidenceRecord]) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    for item in evidence:
        key = str(item.path or "")
        if key and key not in cache:
            cache[key] = _duckdb_summary(item.path)
    return cache


def _build_physical_inventory(*, evidence: list[EvidenceRecord], physical_cache: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in evidence:
        physical = _physical_for(item.path, physical_cache)
        checksum_status = "checksum_unverified"
        rows.append(
            {
                "product": item.product,
                "contract_role": item.contract_role,
                "symbol_or_contract": item.contract,
                "period": item.period,
                "start_date": _date_text(item.start_date),
                "end_date": _date_text(item.end_date),
                "evidence_source": item.evidence_source,
                "provider": item.provider,
                "data_role": item.data_role,
                "quality_status": item.quality_status,
                "manifest_status": item.manifest_status,
                "manifest_or_db_row_count": item.row_count,
                "db_market_data_file_id": item.db_file_id,
                "data_quality_report_status": item.quality_report_status,
                "physical_path": str(item.path or ""),
                "physical_exists": physical["exists"],
                "duckdb_row_count": physical["row_count"],
                "duckdb_min_datetime": physical["min_datetime"],
                "duckdb_max_datetime": physical["max_datetime"],
                "duckdb_error": physical["error"],
                "checksum_status": checksum_status,
                "row_count_status": _row_count_status(item.row_count, physical["row_count"]),
            }
        )
    return rows


def _build_coverage_matrix(
    *,
    target_catalog: list[dict[str, Any]],
    evidence: list[EvidenceRecord],
    physical_cache: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    evidence_index = _index_evidence(evidence)
    source_interval_cache: dict[str, bool] = {}
    for target in target_catalog:
        evidence_matches = _matching_evidence(target, evidence_index)
        best = evidence_matches[0] if evidence_matches else None
        status, issue_type = _coverage_status(target, best, physical_cache, source_interval_cache)
        rows.append(
            {
                "product": target["product"],
                "contract_role": target["contract_role"],
                "symbol_or_contract": target["symbol_or_contract"],
                "period": target["period"],
                "year": target["year"],
                "status": status,
                "issue_type": issue_type,
                "expected_start": target["expected_start"],
                "expected_end": target["expected_end"],
                "target_reason": target["target_reason"],
                "evidence_source": best.evidence_source if best else "",
                "provider": best.provider if best else "",
                "data_role": best.data_role if best else "",
                "quality_status": best.quality_status if best else "",
                "start_date": _date_text(best.start_date) if best else "",
                "end_date": _date_text(best.end_date) if best else "",
                "row_count": best.row_count if best else None,
                "db_market_data_file_id": best.db_file_id if best else None,
                "standard_path": str(best.path or "") if best else "",
                "recommended_next_task": _recommended_next_task(status, issue_type),
            }
        )
    return rows


def _coverage_status(
    target: dict[str, Any],
    evidence: EvidenceRecord | None,
    physical_cache: dict[str, dict[str, Any]],
    source_interval_cache: dict[str, bool],
) -> tuple[str, str]:
    if target["target_status"] == "not_applicable":
        return "not_applicable", "not_applicable"
    if evidence is None:
        return "missing_manifest", "missing_target_asset"
    if evidence.path is None:
        return "missing_physical_file", "missing_standard_path"
    if not evidence.path.exists():
        return "missing_physical_file", "missing_physical_file"
    physical = _physical_for(evidence.path, physical_cache)
    if physical["error"]:
        return "unknown_error", "duckdb_read_failed"
    if evidence.row_count is not None and physical["row_count"] is not None and evidence.row_count != physical["row_count"]:
        return "row_count_mismatch", "row_count_mismatch"
    if "db_market_data_file" not in evidence.evidence_source:
        return "missing_db_registration", "missing_db_registration"
    if evidence.data_role != "primary":
        return "metadata_gap", f"data_role_{evidence.data_role or 'missing'}"
    if evidence.quality_status == "failed":
        return "metadata_gap", "quality_failed"
    if evidence.quality_status in WARNING_STATUSES or evidence.quality_report_status in WARNING_STATUSES:
        return "covered_warning", "quality_warning"
    if evidence.quality_status in PASS_STATUSES:
        if "derived_from_1m" in target["target_reason"] and target["period"] in DERIVED_FROM_1M_PERIODS and not _has_source_interval_1m(evidence.path, source_interval_cache):
            return "covered_warning", "source_interval_unverified"
        return "covered_passed", ""
    return "covered_warning", "quality_unverified"


def _build_metadata_matrix(
    *,
    product_windows: dict[str, ProductWindow],
    snapshot: dict[str, list[Any]],
    audit_end: date,
    db_available: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for product, window in sorted(product_windows.items()):
        for year in CATALOG_YEARS:
            year_start = max(date(year, 1, 1), window.effective_1d_start)
            year_end = min(date(year, 12, 31), audit_end)
            if year_start > year_end:
                rows.extend(_metadata_rows(product, year, "not_applicable", "not_applicable", "", db_available))
                continue
            rows.extend(
                [
                    _metadata_row(product, year, "main_contract_map_rank1", _has_year_product_rows(snapshot["main_contract_map"], product, year, "trade_date"), db_available),
                    _metadata_row(product, year, "contract_universe", _has_year_product_rows(snapshot["contract_universe"], product, year, "trade_date"), db_available),
                    _metadata_row(product, year, "continuous_contract_map", _has_year_product_rows(snapshot["continuous_contract_map"], product, year, "trade_date"), db_available),
                    _metadata_row(product, year, "trading_parameters", _has_complete_trading_parameters(snapshot["trading_parameters"], product, year), db_available),
                    _metadata_row(product, year, "trading_calendar", _has_year_rows(snapshot["trading_calendar"], year, "trade_date"), db_available),
                    _metadata_row(product, year, "trading_sessions", _has_product_sessions(snapshot["trading_sessions"], product), db_available),
                ]
            )
    return rows


def _metadata_rows(product: str, year: int, status: str, issue_type: str, dataset: str, db_available: bool) -> list[dict[str, Any]]:
    datasets = (dataset,) if dataset else ("main_contract_map_rank1", "contract_universe", "continuous_contract_map", "trading_parameters", "trading_calendar", "trading_sessions")
    return [
        {
            "product": product,
            "year": year,
            "dataset": item,
            "status": status,
            "issue_type": issue_type,
            "db_available": db_available,
            "recommended_next_task": _recommended_next_task(status, issue_type),
        }
        for item in datasets
    ]


def _metadata_row(product: str, year: int, dataset: str, has_rows: bool, db_available: bool) -> dict[str, Any]:
    if not db_available:
        status = "metadata_gap"
        issue = "db_unavailable"
    elif has_rows:
        status = "covered_passed"
        issue = ""
    else:
        status = "metadata_gap"
        issue = f"missing_{dataset}"
    return {
        "product": product,
        "year": year,
        "dataset": dataset,
        "status": status,
        "issue_type": issue,
        "db_available": db_available,
        "recommended_next_task": _recommended_next_task(status, issue),
    }


def _build_issue_register(*, coverage_matrix: list[dict[str, Any]], metadata_matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    for row in coverage_matrix:
        if row["status"] in {"covered_passed", "not_applicable"}:
            continue
        issues.append(
            {
                "issue_type": row["issue_type"],
                "product": row["product"],
                "contract_role": row["contract_role"],
                "symbol_or_contract": row["symbol_or_contract"],
                "period": row["period"],
                "year": row["year"],
                "status": row["status"],
                "evidence_source": row["evidence_source"],
                "recommended_next_task": row["recommended_next_task"],
            }
        )
    for row in metadata_matrix:
        if row["status"] in {"covered_passed", "not_applicable"}:
            continue
        issues.append(
            {
                "issue_type": row["issue_type"],
                "product": row["product"],
                "contract_role": "metadata",
                "symbol_or_contract": row["dataset"],
                "period": "",
                "year": row["year"],
                "status": row["status"],
                "evidence_source": "metadata_table",
                "recommended_next_task": row["recommended_next_task"],
            }
        )
    return issues


def _render_summary(
    *,
    products: list[str],
    audit_end: date,
    db_snapshot_source: str,
    db_error: str,
    target_catalog: list[dict[str, Any]],
    physical_inventory: list[dict[str, Any]],
    coverage_matrix: list[dict[str, Any]],
    metadata_matrix: list[dict[str, Any]],
    issue_register: list[dict[str, Any]],
) -> str:
    coverage_counts = Counter(row["status"] for row in coverage_matrix)
    metadata_counts = Counter(row["status"] for row in metadata_matrix)
    issue_counts = Counter(row["issue_type"] for row in issue_register)
    lines = [
        "# Target Coverage Audit Summary",
        "",
        f"- mode: `{MODE}`",
        f"- audit_end: `{audit_end.isoformat()}`",
        f"- products: {len(products)}",
        f"- target_catalog_rows: {len(target_catalog)}",
        f"- physical_inventory_rows: {len(physical_inventory)}",
        f"- issue_register_rows: {len(issue_register)}",
        "- writes_database: `False`",
        "- writes_parquet: `False`",
        "- calls_rqdata: `False`",
        f"- db_snapshot_source: `{db_snapshot_source}`",
    ]
    if db_error:
        lines.append(f"- db_error: `{db_error}`")
    lines.extend(
        [
            "",
            "## Coverage Status",
            "",
            _markdown_counts(coverage_counts),
            "",
            "## Metadata Status",
            "",
            _markdown_counts(metadata_counts),
            "",
            "## Issue Types",
            "",
            _markdown_counts(issue_counts),
            "",
            "## Scope Notes",
            "",
            "- This report is a target coverage matrix, not a Stage 8.6 active snapshot.",
            "- Stage 8.6 `1326 active_passed / 8 audit_pending` remains a discovered active asset snapshot only.",
            "- The known 8 pending records are not repaired here; this audit only classifies target coverage gaps.",
            "- JM V1-B latest six-period baseline remains separate and should still be verified through the JM Stage 8.6 profile.",
            "- Stage 9 remains blocked until signal-event, actual-contract, trigger-price and metadata gates pass; this audit does not authorize enterprise WeChat sending.",
            "",
        ]
    )
    return "\n".join(lines)


def _index_evidence(evidence: list[EvidenceRecord]) -> dict[tuple[str, str, str, str], list[EvidenceRecord]]:
    indexed: dict[tuple[str, str, str, str], list[EvidenceRecord]] = defaultdict(list)
    for item in evidence:
        indexed[(item.product, item.contract_role, item.contract, item.period)].append(item)
    return indexed


def _matching_evidence(target: dict[str, Any], evidence_index: dict[tuple[str, str, str, str], list[EvidenceRecord]]) -> list[EvidenceRecord]:
    expected_start = _to_date(target["expected_start"])
    expected_end = _to_date(target["expected_end"])
    matches = []
    key = (target["product"], target["contract_role"], target["symbol_or_contract"], target["period"])
    for item in evidence_index.get(key, []):
        if expected_start and expected_end and not _ranges_overlap(item.start_date, item.end_date, expected_start, expected_end):
            continue
        matches.append(item)
    return sorted(matches, key=lambda item: (_evidence_rank(item.evidence_source), item.start_date or date.min))


def _has_year_product_rows(rows: list[Any], product: str, year: int, date_field: str) -> bool:
    return any(_clean_text(_get(row, "instrument_symbol")).lower() == product and _year(_get(row, date_field)) == year for row in rows)


def _has_year_rows(rows: list[Any], year: int, date_field: str) -> bool:
    return any(_year(_get(row, date_field)) == year for row in rows)


def _has_product_sessions(rows: list[Any], product: str) -> bool:
    return any(_clean_text(_get(row, "instrument_symbol")).lower() in {product, ""} for row in rows)


def _has_complete_trading_parameters(rows: list[Any], product: str, year: int) -> bool:
    for row in rows:
        if _clean_text(_get(row, "instrument_symbol")).lower() != product or _year(_get(row, "trade_date")) != year:
            continue
        if all(_get(row, field) not in (None, "") for field in REQUIRED_TRADING_PARAMETER_FIELDS):
            return True
    return False


def _has_source_interval_1m(path: Path | None, cache: dict[str, bool]) -> bool:
    if path is None or not path.exists():
        return False
    key = str(path)
    if key in cache:
        return cache[key]
    try:
        frame = pd.read_parquet(path, columns=["source_interval"])
    except Exception:
        cache[key] = False
        return False
    if "source_interval" not in frame.columns or frame.empty:
        cache[key] = False
        return False
    values = set(frame["source_interval"].dropna().astype(str).unique())
    cache[key] = values == {"1m"}
    return cache[key]


def _duckdb_summary(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"exists": False, "row_count": None, "min_datetime": "", "max_datetime": "", "error": "missing_standard_path"}
    if not path.exists():
        return {"exists": False, "row_count": None, "min_datetime": "", "max_datetime": "", "error": "missing_physical_file"}
    try:
        with duckdb.connect(database=":memory:") as connection:
            row = connection.execute(
                "select count(*) row_count, min(datetime) min_datetime, max(datetime) max_datetime from read_parquet(?)",
                [str(path)],
            ).fetchone()
    except Exception as exc:
        return {"exists": True, "row_count": None, "min_datetime": "", "max_datetime": "", "error": str(exc)}
    return {"exists": True, "row_count": int(row[0]), "min_datetime": _format_datetime(row[1]), "max_datetime": _format_datetime(row[2]), "error": ""}


def _physical_for(path: Path | None, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = str(path or "")
    if key not in cache:
        cache[key] = _duckdb_summary(path)
    return cache[key]


def _row_count_status(expected: int | None, actual: int | None) -> str:
    if expected is None or actual is None:
        return "row_count_unverified"
    return "matched" if expected == actual else "mismatch"


def _recommended_next_task(status: str, issue_type: str) -> str:
    if status == "covered_passed" or status == "not_applicable":
        return ""
    if issue_type == "missing_db_registration":
        return "controlled_metadata_registration_plan"
    if issue_type in {"missing_physical_file", "missing_target_asset", "missing_standard_path"}:
        return "readonly_root_cause_then_backfill_plan"
    if issue_type in {"db_unavailable"}:
        return "rerun_with_readonly_db_or_api_snapshot"
    if issue_type in {"quality_warning", "quality_failed"}:
        return "readonly_quality_root_cause_audit"
    if "trading_parameters" in issue_type:
        return "metadata_parameter_gap_audit"
    return "target_coverage_gap_triage"


def _read_csv_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return pd.read_csv(path).fillna("").to_dict("records")


def _resolve_path(project_root: Path, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _get(item: Any, name: str) -> Any:
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return int(value)


def _to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = _clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(text[:10])


def _year(value: Any) -> int | None:
    parsed = _to_date(value)
    return parsed.year if parsed else None


def _date_text(value: date | None) -> str:
    return value.isoformat() if value else ""


def _format_datetime(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _covered_years(start: date | None, end: date | None) -> list[int]:
    if start is None or end is None:
        return []
    return list(range(start.year, end.year + 1))


def _ranges_overlap(start: date | None, end: date | None, expected_start: date, expected_end: date) -> bool:
    if start is None or end is None:
        return True
    return start <= expected_end and end >= expected_start


def _evidence_rank(source: str) -> int:
    if "db_market_data_file" in source and "manifest" in source:
        return 0
    if "db_market_data_file" in source:
        return 1
    if "manifest" in source:
        return 2
    return 3


def _first_text(group: list[EvidenceRecord], field: str) -> str:
    for item in sorted(group, key=lambda record: _evidence_rank(record.evidence_source)):
        value = _clean_text(getattr(item, field))
        if value:
            return value
    return ""


def _first_int(group: list[EvidenceRecord], field: str) -> int | None:
    for item in sorted(group, key=lambda record: _evidence_rank(record.evidence_source)):
        value = getattr(item, field)
        if value is not None:
            return int(value)
    return None


def _best_quality(group: list[EvidenceRecord]) -> str:
    active_values = [
        _clean_text(item.quality_status)
        for item in sorted(group, key=lambda record: _evidence_rank(record.evidence_source))
        if _clean_text(item.quality_status) and item.evidence_source != "processed_summary"
    ]
    values = active_values or [_clean_text(item.quality_status) for item in group if _clean_text(item.quality_status)]
    if "failed" in values:
        return "failed"
    if "warning" in values:
        return "warning"
    if "passed" in values:
        return "passed"
    return values[0] if values else ""


def _min_date(values: Any) -> date | None:
    cleaned = [value for value in values if value is not None]
    return min(cleaned) if cleaned else None


def _max_date(values: Any) -> date | None:
    cleaned = [value for value in values if value is not None]
    return max(cleaned) if cleaned else None


def _markdown_counts(counts: Counter[str]) -> str:
    if not counts:
        return "_No rows._"
    lines = ["| status | count |", "|---|---:|"]
    for status, count in sorted(counts.items()):
        lines.append(f"| {status} | {count} |")
    return "\n".join(lines)
