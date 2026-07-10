from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import DataQualityReport, FuturesTradingParameter, MarketDataFile
from app.services.rqdata_ingest.bar_aggregation import AGGREGATED_PERIODS


MODE = "stage8_6_active_gate_audit"
DEFAULT_PROFILE = "stage8_6_1d_first"
JM_LATEST_PROFILE = "jm_main_six_period_latest"
SIX_PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d")
ENTRY_PERIODS = ("5m", "15m")
REQUIRED_TRADING_PARAMETER_FIELDS = (
    "price_tick",
    "contract_multiplier",
    "long_margin_ratio",
    "short_margin_ratio",
    "open_commission",
    "close_commission",
    "close_today_commission",
)


def audit_full_universe_active_gate(
    *,
    session: Session,
    project_root: Path,
    products: list[str],
    profile: str = DEFAULT_PROFILE,
) -> dict[str, Any]:
    normalized_products = [_normalize_product(product) for product in products]
    matrix: list[dict[str, Any]] = []
    for product in normalized_products:
        product_rows = _audit_product(session=session, project_root=project_root, product=product, profile=profile)
        matrix.extend(product_rows)

    return {
        "mode": MODE,
        "profile": profile,
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "products": normalized_products,
        "matrix": matrix,
        "product_summary": _build_product_summary(matrix, normalized_products),
        "stage9_readiness": _build_stage9_readiness(session=session, matrix=matrix, products=normalized_products),
    }


def write_stage8_6_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = output_dir / "stage8_6_active_gate_matrix.csv"
    product_summary_path = output_dir / "stage8_6_product_summary.csv"
    stage9_readiness_path = output_dir / "stage8_6_stage9_readiness.csv"
    summary_path = output_dir / "stage8_6_active_gate_summary.md"

    pd.DataFrame(result["matrix"]).to_csv(matrix_path, index=False)
    pd.DataFrame(result["product_summary"]).to_csv(product_summary_path, index=False)
    pd.DataFrame(result["stage9_readiness"]).to_csv(stage9_readiness_path, index=False)
    summary_path.write_text(_render_summary_markdown(result), encoding="utf-8")
    return {
        "matrix": matrix_path,
        "product_summary": product_summary_path,
        "stage9_readiness": stage9_readiness_path,
        "summary_markdown": summary_path,
    }


def _audit_product(*, session: Session, project_root: Path, product: str, profile: str) -> list[dict[str, Any]]:
    periods = SIX_PERIODS if profile in {"jm_six_period_reference", JM_LATEST_PROFILE} and product == "jm" else ("1d",)
    latest_main_only = profile == JM_LATEST_PROFILE
    rows: list[dict[str, Any]] = []
    for period in periods:
        manifest_rows = _dominant_manifest_rows(project_root=project_root, product=product, period=period)
        if manifest_rows:
            manifest_rows = manifest_rows[-1:]
        rows.extend(
            _audit_manifest_row(
                session=session,
                project_root=project_root,
                product=product,
                asset_scope="dominant_main",
                default_contract=f"{product}.MAIN",
                row=row,
                require_local_1m=latest_main_only and period != "1m",
            )
            for row in manifest_rows
        )

    actual_manifest_rows = [] if latest_main_only else _actual_manifest_rows(project_root=project_root, product=product, periods=periods)
    rows.extend(
        _audit_manifest_row(
            session=session,
            project_root=project_root,
            product=product,
            asset_scope="actual_contract",
            default_contract=str(row.get("actual_contract") or ""),
            row=row,
            require_local_1m=False,
        )
        for row in actual_manifest_rows
    )

    if rows:
        return rows
    return [
        _empty_row(
            product=product,
            asset_scope="product",
            contract="",
            period="",
            gate_status="missing",
            blocked_reasons=["missing_manifest", "missing_market_data_file"],
        )
    ]


def _audit_manifest_row(
    *,
    session: Session,
    project_root: Path,
    product: str,
    asset_scope: str,
    default_contract: str,
    row: dict[str, Any],
    require_local_1m: bool,
) -> dict[str, Any]:
    period = _clean_text(row.get("period"))
    contract = _clean_text(row.get("actual_contract")) or default_contract
    standard_path = _resolve_path(project_root, _clean_text(row.get("standard_path")))
    blocked_reasons: list[str] = []
    manifest_status = _clean_text(row.get("status"))
    manifest_quality = _clean_text(row.get("quality_status"))
    manifest_role = _clean_text(row.get("data_role"))
    manifest_row_count = _to_int(row.get("row_count"))
    evidence_source = _clean_text(row.get("evidence_source"))

    if evidence_source == "processed_summary":
        blocked_reasons.append("missing_manifest")
    if manifest_status and manifest_status != "success":
        blocked_reasons.append(f"manifest_status_{manifest_status}")
    if manifest_quality == "failed":
        blocked_reasons.append("manifest_quality_failed")
    elif manifest_quality != "passed":
        blocked_reasons.append(f"manifest_quality_{manifest_quality or 'missing'}")
    if manifest_role != "primary":
        blocked_reasons.append(f"manifest_data_role_{manifest_role or 'missing'}")

    duckdb_summary = _duckdb_summary(standard_path)
    if duckdb_summary["error"]:
        blocked_reasons.append("duckdb_read_failed")
    elif manifest_row_count is not None and duckdb_summary["row_count"] != manifest_row_count:
        blocked_reasons.append("duckdb_row_count_mismatch")
    require_source_interval = (period in AGGREGATED_PERIODS and period != "1d") or require_local_1m
    if require_source_interval and standard_path is not None and standard_path.exists():
        source_interval = _parquet_source_interval(standard_path)
        if source_interval != "1m":
            blocked_reasons.append("missing_source_interval_1m")

    market_file = _find_market_file(session, product=product, contract=contract, period=period, standard_path=standard_path)
    market_file_id: int | None = None
    db_quality_status = ""
    db_row_count: int | None = None
    quality_report_status = ""
    if market_file is None:
        blocked_reasons.append("missing_market_data_file")
    else:
        market_file_id = market_file.id
        db_quality_status = market_file.quality_status
        db_row_count = market_file.row_count
        if market_file.data_role != "primary":
            blocked_reasons.append(f"db_data_role_{market_file.data_role}")
        if market_file.quality_status == "failed":
            blocked_reasons.append("db_quality_failed")
        elif market_file.quality_status != "passed":
            blocked_reasons.append(f"db_quality_{market_file.quality_status}")
        if manifest_row_count is not None and market_file.row_count != manifest_row_count:
            blocked_reasons.append("db_row_count_manifest_mismatch")
        if duckdb_summary["row_count"] is not None and market_file.row_count != duckdb_summary["row_count"]:
            blocked_reasons.append("db_row_count_duckdb_mismatch")

        quality_report = _find_quality_report(session, market_file)
        if quality_report is None:
            blocked_reasons.append("missing_data_quality_report")
        else:
            quality_report_status = quality_report.status
            if quality_report.status == "failed":
                blocked_reasons.append("quality_report_failed")
            elif quality_report.status != "passed":
                blocked_reasons.append(f"quality_report_{quality_report.status}")
            if quality_report.missing_bars:
                blocked_reasons.append("quality_report_missing_bars")
            if quality_report.duplicated_bars:
                blocked_reasons.append("quality_report_duplicated_bars")
            if quality_report.abnormal_price_count:
                blocked_reasons.append("quality_report_abnormal_price")
            if quality_report.abnormal_volume_count:
                blocked_reasons.append("quality_report_abnormal_volume")

    gate_status = _classify_gate_status(blocked_reasons)
    return {
        "product": product,
        "asset_scope": asset_scope,
        "contract": contract,
        "period": period,
        "gate_status": gate_status,
        "blocked_reasons": ",".join(blocked_reasons),
        "manifest_status": manifest_status,
        "manifest_quality_status": manifest_quality,
        "manifest_data_role": manifest_role,
        "manifest_row_count": manifest_row_count,
        "db_market_data_file_id": market_file_id,
        "db_quality_status": db_quality_status,
        "db_row_count": db_row_count,
        "data_quality_report_status": quality_report_status,
        "duckdb_row_count": duckdb_summary["row_count"],
        "duckdb_min_datetime": duckdb_summary["min_datetime"],
        "duckdb_max_datetime": duckdb_summary["max_datetime"],
        "standard_path": str(standard_path) if standard_path is not None else "",
    }


def _dominant_manifest_rows(*, project_root: Path, product: str, period: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest in sorted((project_root / "data" / "manifests").glob(f"rqdata_{product}_v2_history_*.csv")):
        rows.extend(row for row in _read_csv_records(manifest) if _clean_text(row.get("period")) == period)
    return rows or _dominant_summary_rows(project_root=project_root, product=product, period=period)


def _dominant_summary_rows(*, project_root: Path, product: str, period: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary_path in sorted((project_root / "data" / "processed" / "v1b" / product).glob(f"{product}_v2_parquet_*.json")):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        period_summary = (summary.get("periods") or {}).get(period)
        if not isinstance(period_summary, dict):
            continue
        standard = period_summary.get("standard") or {}
        rows.append(
            {
                "evidence_source": "processed_summary",
                "period": period,
                "data_version": period_summary.get("data_version", ""),
                "provider": "rqdata",
                "source": "rqdata",
                "data_role": "primary",
                "quality_status": period_summary.get("quality_status", ""),
                "row_count": standard.get("row_count", ""),
                "min_datetime": standard.get("min_datetime", ""),
                "max_datetime": standard.get("max_datetime", ""),
                "checksum": standard.get("checksum", ""),
                "standard_path": standard.get("path", ""),
                "raw_path": (period_summary.get("raw") or {}).get("path", ""),
                "status": "summary_only",
            }
        )
    return rows


def _actual_manifest_rows(*, project_root: Path, product: str, periods: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest in sorted((project_root / "data" / "manifests").glob(f"rqdata_actual_contract_bars_{product}_*.csv")):
        if manifest.name == "rqdata_actual_contract_bars_batch.csv":
            continue
        rows.extend(row for row in _read_csv_records(manifest) if _clean_text(row.get("period")) in periods)
    return rows


def _read_csv_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return pd.read_csv(path).fillna("").to_dict("records")


def _find_market_file(session: Session, *, product: str, contract: str, period: str, standard_path: Path | None) -> MarketDataFile | None:
    query = select(MarketDataFile).where(
        MarketDataFile.provider == "rqdata",
        MarketDataFile.data_type == "bars",
        MarketDataFile.instrument_symbol == product,
        MarketDataFile.contract_code == contract,
        MarketDataFile.period == period,
    )
    matches = list(session.scalars(query))
    if standard_path is None:
        return matches[0] if matches else None
    resolved_standard = standard_path.resolve()
    for match in matches:
        path = Path(match.file_path)
        if path.resolve() == resolved_standard:
            return match
    return matches[0] if matches else None


def _find_quality_report(session: Session, market_file: MarketDataFile) -> DataQualityReport | None:
    return session.scalar(
        select(DataQualityReport)
        .where(DataQualityReport.file_id == market_file.id)
        .order_by(DataQualityReport.created_at.desc())
    )


def _parquet_source_interval(path: Path) -> str:
    try:
        frame = pd.read_parquet(path, columns=["source_interval"])
    except Exception:
        return ""
    if frame.empty or "source_interval" not in frame.columns:
        return ""
    values = frame["source_interval"].dropna().astype(str).unique().tolist()
    return values[0] if len(values) == 1 else ""


def _duckdb_summary(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"row_count": None, "min_datetime": "", "max_datetime": "", "error": "missing_standard_path"}
    try:
        with duckdb.connect(database=":memory:") as connection:
            row = connection.execute(
                "select count(*) row_count, min(datetime) min_datetime, max(datetime) max_datetime from read_parquet(?)",
                [str(path)],
            ).fetchone()
    except Exception as exc:
        return {"row_count": None, "min_datetime": "", "max_datetime": "", "error": str(exc)}
    return {
        "row_count": int(row[0]),
        "min_datetime": _format_datetime(row[1]),
        "max_datetime": _format_datetime(row[2]),
        "error": "",
    }


def _classify_gate_status(blocked_reasons: list[str]) -> str:
    if not blocked_reasons:
        return "active_passed"
    failed_prefixes = (
        "manifest_status_failed",
        "manifest_quality_failed",
        "db_quality_failed",
        "quality_report_failed",
    )
    if any(reason.startswith(failed_prefixes) for reason in blocked_reasons):
        return "failed"
    if "missing_manifest" in blocked_reasons and "missing_market_data_file" in blocked_reasons:
        return "missing"
    return "audit_pending"


def _build_product_summary(matrix: list[dict[str, Any]], products: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in matrix:
        grouped[row["product"]].append(row)

    summary = []
    for product in products:
        rows = grouped.get(product, [])
        counts = Counter(row["gate_status"] for row in rows)
        product_status = _classify_product_status(counts)
        summary.append(
            {
                "product": product,
                "product_status": product_status,
                "active_passed": counts["active_passed"],
                "audit_pending": counts["audit_pending"],
                "failed": counts["failed"],
                "missing": counts["missing"],
                "total_assets": sum(counts.values()),
            }
        )
    return summary


def _classify_product_status(counts: Counter[str]) -> str:
    if counts["active_passed"] and not (counts["audit_pending"] or counts["failed"] or counts["missing"]):
        return "active_passed"
    if counts["active_passed"]:
        return "active_partial"
    if counts["failed"]:
        return "failed"
    if counts["audit_pending"]:
        return "audit_pending"
    return "missing"


def _build_stage9_readiness(*, session: Session, matrix: list[dict[str, Any]], products: list[str]) -> list[dict[str, Any]]:
    active_actual_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in matrix:
        if row["asset_scope"] == "actual_contract" and row["gate_status"] == "active_passed":
            active_actual_by_product[row["product"]].append(row)

    readiness = []
    for product in products:
        actual_rows = active_actual_by_product.get(product, [])
        actual_contracts = sorted({row["contract"] for row in actual_rows if row["contract"]})
        active_periods = sorted({row["period"] for row in actual_rows if row["period"]})
        missing_entry_periods = [period for period in ENTRY_PERIODS if period not in active_periods]
        blocked_reasons: list[str] = []
        if not actual_contracts:
            blocked_reasons.append("missing_actual_contract_active_passed")
        if missing_entry_periods:
            blocked_reasons.append("missing_entry_periods:" + ",".join(missing_entry_periods))
        for contract in actual_contracts:
            missing_params = _missing_trading_parameter_fields(session, product=product, contract=contract)
            if missing_params:
                blocked_reasons.append(f"missing_trading_parameters:{contract}:{','.join(missing_params)}")
        blocked_reasons.append("signal_event_gate_required_for_bar_end_and_trigger_price")
        readiness.append(
            {
                "product": product,
                "actual_contracts": ",".join(actual_contracts),
                "active_actual_periods": ",".join(active_periods),
                "stage9_status": "stage9_blocked",
                "blocked_reasons": ";".join(blocked_reasons),
            }
        )
    return readiness


def _missing_trading_parameter_fields(session: Session, *, product: str, contract: str) -> list[str]:
    row = session.scalar(
        select(FuturesTradingParameter)
        .where(
            FuturesTradingParameter.provider == "rqdata",
            FuturesTradingParameter.instrument_symbol == product,
            FuturesTradingParameter.contract_code == contract,
        )
        .order_by(FuturesTradingParameter.trade_date.desc())
    )
    if row is None:
        return list(REQUIRED_TRADING_PARAMETER_FIELDS)
    return [field for field in REQUIRED_TRADING_PARAMETER_FIELDS if getattr(row, field) in (None, "")]


def _empty_row(
    *,
    product: str,
    asset_scope: str,
    contract: str,
    period: str,
    gate_status: str,
    blocked_reasons: list[str],
) -> dict[str, Any]:
    return {
        "product": product,
        "asset_scope": asset_scope,
        "contract": contract,
        "period": period,
        "gate_status": gate_status,
        "blocked_reasons": ",".join(blocked_reasons),
        "manifest_status": "",
        "manifest_quality_status": "",
        "manifest_data_role": "",
        "manifest_row_count": None,
        "db_market_data_file_id": None,
        "db_quality_status": "",
        "db_row_count": None,
        "data_quality_report_status": "",
        "duckdb_row_count": None,
        "duckdb_min_datetime": "",
        "duckdb_max_datetime": "",
        "standard_path": "",
    }


def _render_summary_markdown(result: dict[str, Any]) -> str:
    status_counts = Counter(row["product_status"] for row in result["product_summary"])
    matrix_counts = Counter(row["gate_status"] for row in result["matrix"])
    stage9_counts = Counter(row["stage9_status"] for row in result["stage9_readiness"])
    return "\n".join(
        [
            "# Stage 8.6 Active Gate Summary",
            "",
            f"- profile: `{result['profile']}`",
            f"- products: {len(result['products'])}",
            f"- writes_database: `{result['writes_database']}`",
            f"- writes_parquet: `{result['writes_parquet']}`",
            f"- calls_rqdata: `{result['calls_rqdata']}`",
            "",
            "## Product Status",
            "",
            _markdown_counts(status_counts),
            "",
            "## Asset Gate Status",
            "",
            _markdown_counts(matrix_counts),
            "",
            "## Stage 9 Readiness",
            "",
            _markdown_counts(stage9_counts),
            "",
            "Stage 9 remains guarded by `evaluate_stage9_signal_event_gate()`; this audit does not authorize enterprise WeChat sending.",
            "",
        ]
    )


def _markdown_counts(counts: Counter[str]) -> str:
    if not counts:
        return "_No rows._"
    lines = ["| status | count |", "|---|---:|"]
    for status, count in sorted(counts.items()):
        lines.append(f"| {status} | {count} |")
    return "\n".join(lines)


def _resolve_path(project_root: Path, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else project_root / path


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


def _normalize_product(product: str) -> str:
    return product.strip().lower()


def _format_datetime(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
