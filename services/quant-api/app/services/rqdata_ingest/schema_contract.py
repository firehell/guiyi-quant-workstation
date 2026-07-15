from __future__ import annotations

from datetime import date, datetime, time
import hashlib
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd

from app.services.rqdata_ingest.bar_aggregation import aggregate_standard_bars

CANONICAL_BAR_SCHEMA_VERSION = "v1.20260712"
CANONICAL_TIMEZONE = "Asia/Shanghai"
DEFAULT_ADJUSTMENT_TYPE = "dominant_rank1_roll"

DERIVED_FROM_1M_PERIODS = frozenset({"5m", "15m", "30m", "60m", "1d"})
RQDATA_DIRECT_PERIODS = frozenset({"1m", "1w"})

CANONICAL_BAR_COLUMNS: dict[str, str] = {
    "datetime": "timestamp",
    "open": "float",
    "high": "float",
    "low": "float",
    "close": "float",
    "volume": "int",
    "open_interest": "float",
    "symbol": "string",
    "contract": "string",
    "period": "string",
    "provider": "string",
}

CANONICAL_BAR_CONTRACT_V1: dict[str, dict[str, Any]] = {
    "datetime": {"layer": "L1", "storage": "parquet", "dtype": "timestamp", "required": True},
    "open": {"layer": "L1", "storage": "parquet", "dtype": "float", "required": True},
    "high": {"layer": "L1", "storage": "parquet", "dtype": "float", "required": True},
    "low": {"layer": "L1", "storage": "parquet", "dtype": "float", "required": True},
    "close": {"layer": "L1", "storage": "parquet", "dtype": "float", "required": True},
    "volume": {"layer": "L1", "storage": "parquet", "dtype": "int", "required": True},
    "open_interest": {"layer": "L1", "storage": "parquet", "dtype": "float", "required": True},
    "turnover": {"layer": "L1", "storage": "parquet", "dtype": "float", "required": True},
    "period": {"layer": "L1", "storage": "parquet", "dtype": "string", "required": True},
    "provider": {"layer": "L1", "storage": "parquet", "dtype": "string", "required": True},
    "trading_day": {"layer": "L2", "storage": "parquet", "dtype": "date", "required_when": "period != 1m"},
    "source_interval": {"layer": "L2", "storage": "parquet", "dtype": "string", "required_when": "period in derived_from_1m"},
    "data_version": {"layer": "L2", "storage": "parquet", "dtype": "string", "required": False},
    "quality_status": {"layer": "L2", "storage": "parquet", "dtype": "string", "required": False},
    "data_role": {"layer": "L2", "storage": "parquet", "dtype": "string", "required": False},
    "symbol": {"layer": "L3", "storage": "parquet", "dtype": "string", "required": True},
    "contract": {"layer": "L3", "storage": "parquet", "dtype": "string", "required": True},
    "product": {"layer": "L4", "storage": "sidecar", "dtype": "string", "required": False},
    "continuous_contract": {"layer": "L4", "storage": "sidecar", "dtype": "string", "required": False},
    "actual_contract": {"layer": "L4", "storage": "sidecar", "dtype": "string", "required": False},
    "contract_role": {"layer": "L4", "storage": "sidecar", "dtype": "string", "required": False},
    "timezone": {"layer": "L4", "storage": "sidecar", "dtype": "string", "required": False},
    "adjustment_type": {"layer": "L4", "storage": "sidecar", "dtype": "string", "required": False},
}

COMPARE_FIELDS = ("open", "high", "low", "close", "volume", "open_interest", "turnover")


def build_schema_fingerprint(columns: dict[str, str] | list[str], *, schema_version: str = CANONICAL_BAR_SCHEMA_VERSION) -> str:
    if isinstance(columns, list):
        normalized = {column: "unknown" for column in sorted(columns)}
    else:
        normalized = {column: dtype for column, dtype in sorted(columns.items())}
    payload = f"{schema_version}|" + ",".join(f"{column}:{dtype}" for column, dtype in normalized.items())
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def infer_trading_day(value: pd.Timestamp | datetime) -> date:
    timestamp = pd.to_datetime(value)
    if timestamp.hour >= 21:
        return (timestamp + pd.Timedelta(days=1)).date()
    return timestamp.date()


def derive_sidecar_fields(*, symbol: str, contract: str, contract_role: str | None = None) -> dict[str, str]:
    normalized_symbol = symbol.strip().lower()
    normalized_contract = contract.strip()
    role = contract_role or ("dominant_main" if normalized_contract.endswith(".MAIN") else "actual_contract")
    continuous_contract = normalized_contract if role == "dominant_main" else ""
    actual_contract = normalized_contract if role == "actual_contract" else ""
    if normalized_contract.endswith(".MAIN"):
        continuous_contract = normalized_contract
        actual_contract = ""
    else:
        continuous_contract = f"{normalized_symbol}.MAIN"
        actual_contract = normalized_contract
    return {
        "product": normalized_symbol,
        "continuous_contract": continuous_contract,
        "actual_contract": actual_contract,
        "contract_role": role,
        "timezone": CANONICAL_TIMEZONE,
        "adjustment_type": DEFAULT_ADJUSTMENT_TYPE,
    }


def _required_embedded_columns(*, period: str) -> set[str]:
    required = {name for name, spec in CANONICAL_BAR_CONTRACT_V1.items() if spec["storage"] == "parquet" and spec.get("required")}
    normalized_period = period.strip().lower()
    if normalized_period != "1m":
        required.add("trading_day")
    if normalized_period in DERIVED_FROM_1M_PERIODS:
        required.add("source_interval")
    return required


def _read_parquet_columns(path: Path) -> tuple[dict[str, str], list[str]]:
    with duckdb.connect(database=":memory:") as connection:
        columns = {
            item[0]: item[1]
            for item in connection.execute("describe select * from read_parquet(?)", [str(path)]).fetchall()
        }
    return columns, sorted(columns)


def validate_canonical_bar_schema(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "status": "failed",
            "issue_type": "missing_physical_file",
            "columns": [],
            "missing_columns": sorted(CANONICAL_BAR_COLUMNS),
        }
    try:
        columns, column_names = _read_parquet_columns(path)
    except Exception as exc:
        return {
            "status": "failed",
            "issue_type": "duckdb_read_failed",
            "error": str(exc),
            "columns": [],
            "missing_columns": sorted(CANONICAL_BAR_COLUMNS),
        }
    missing_columns = sorted(column for column in CANONICAL_BAR_COLUMNS if column not in columns)
    status = "passed" if not missing_columns else "failed"
    return {
        "status": status,
        "issue_type": "" if status == "passed" else "schema_mismatch",
        "columns": column_names,
        "missing_columns": missing_columns,
        "schema_version": CANONICAL_BAR_SCHEMA_VERSION,
        "fingerprint": build_schema_fingerprint(columns),
    }


def validate_canonical_bar_contract(
    path: Path,
    *,
    period: str,
    contract_role: str | None = None,
    sidecar: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not path.exists():
        return {
            "status": "failed",
            "issue_type": "missing_physical_file",
            "embedded_status": "failed",
            "sidecar_status": "failed",
            "missing_embedded": sorted(_required_embedded_columns(period=period)),
            "missing_sidecar": [],
            "schema_version": CANONICAL_BAR_SCHEMA_VERSION,
            "fingerprint": "",
            "columns": [],
        }
    try:
        columns, column_names = _read_parquet_columns(path)
    except Exception as exc:
        return {
            "status": "failed",
            "issue_type": "duckdb_read_failed",
            "error": str(exc),
            "embedded_status": "failed",
            "sidecar_status": "unverified",
            "missing_embedded": sorted(_required_embedded_columns(period=period)),
            "missing_sidecar": [],
            "schema_version": CANONICAL_BAR_SCHEMA_VERSION,
            "fingerprint": "",
            "columns": [],
        }

    missing_embedded = sorted(column for column in _required_embedded_columns(period=period) if column not in columns)
    embedded_status = "passed" if not missing_embedded else "failed"

    inferred_sidecar = sidecar or {}
    if not inferred_sidecar and "symbol" in columns and "contract" in columns:
        frame = pd.read_parquet(path, columns=["symbol", "contract"])
        if not frame.empty:
            inferred_sidecar = derive_sidecar_fields(
                symbol=str(frame.iloc[0]["symbol"]),
                contract=str(frame.iloc[0]["contract"]),
                contract_role=contract_role,
            )
    missing_sidecar = sorted(
        name
        for name, spec in CANONICAL_BAR_CONTRACT_V1.items()
        if spec["storage"] == "sidecar"
        and name not in {"actual_contract", "adjustment_type"}
        and not inferred_sidecar.get(name)
    )
    if contract_role == "actual_contract" and not inferred_sidecar.get("actual_contract"):
        missing_sidecar.append("actual_contract")
    missing_sidecar = sorted(set(missing_sidecar))
    sidecar_status = "passed" if not missing_sidecar else "sidecar_gap"

    if embedded_status == "failed":
        status = "failed"
        issue_type = "schema_mismatch"
    elif sidecar_status == "sidecar_gap":
        status = "warning"
        issue_type = "sidecar_gap"
    else:
        status = "passed"
        issue_type = ""

    return {
        "status": status,
        "issue_type": issue_type,
        "embedded_status": embedded_status,
        "sidecar_status": sidecar_status,
        "missing_embedded": missing_embedded,
        "missing_sidecar": missing_sidecar,
        "schema_version": CANONICAL_BAR_SCHEMA_VERSION,
        "fingerprint": build_schema_fingerprint(columns),
        "columns": column_names,
        "sidecar": inferred_sidecar,
    }


def aggregate_bars_for_reconcile(frame_1m: pd.DataFrame, period: str) -> pd.DataFrame:
    normalized = period.strip().lower()
    if normalized == "1d":
        return aggregate_standard_bars(frame_1m, "1d")
    if normalized == "1w":
        return aggregate_weekly_from_1m_readonly(frame_1m)
    raise ValueError(f"unsupported reconcile period: {period}")


def aggregate_weekly_from_1m_readonly(
    frame_1m: pd.DataFrame,
    *,
    week_trading_days_resolver: Callable[[date], list[date]] | None = None,
) -> pd.DataFrame:
    data = frame_1m.copy()
    if "trading_day" not in data.columns:
        data["trading_day"] = data["datetime"].map(infer_trading_day)
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    data["trading_day"] = pd.to_datetime(data["trading_day"], errors="coerce").dt.date
    data = data.dropna(subset=["datetime", "trading_day", "open", "high", "low", "close"]).sort_values(
        ["contract", "trading_day", "datetime"]
    )
    if data.empty:
        return data

    grouped_weeks: dict[tuple[Any, int, int], list[pd.Series]] = {}
    for _, row in data.iterrows():
        trading_day = row["trading_day"]
        iso = trading_day.isocalendar()
        key = (row["contract"], iso.year, iso.week)
        grouped_weeks.setdefault(key, []).append(row)

    rows: list[dict[str, Any]] = []
    for (contract, iso_year, iso_week), week_rows in sorted(grouped_weeks.items()):
        trading_days = sorted({row["trading_day"] for row in week_rows})
        if week_trading_days_resolver is not None:
            calendar_days = week_trading_days_resolver(trading_days[0])
            if calendar_days:
                trading_days = calendar_days
        final_day = trading_days[-1]
        week_frame = pd.DataFrame(week_rows)
        rows.append(
            {
                "symbol": week_frame.iloc[0]["symbol"],
                "contract": contract,
                "exchange": week_frame.iloc[0].get("exchange", ""),
                "vt_symbol": week_frame.iloc[0].get("vt_symbol", ""),
                "datetime": datetime.combine(final_day, time.min),
                "trading_day": final_day,
                "interval": "1w",
                "period": "1w",
                "open": float(week_frame["open"].iloc[0]),
                "high": float(week_frame["high"].max()),
                "low": float(week_frame["low"].min()),
                "close": float(week_frame["close"].iloc[-1]),
                "volume": int(week_frame["volume"].sum()),
                "turnover": float(week_frame["turnover"].sum()) if "turnover" in week_frame else 0.0,
                "open_interest": float(week_frame["open_interest"].iloc[-1]),
                "source": week_frame.iloc[0].get("source", "rqdata"),
                "provider": week_frame.iloc[0].get("provider", "rqdata"),
                "data_role": week_frame.iloc[0].get("data_role", "primary"),
                "quality_status": "unchecked",
                "data_version": week_frame.iloc[0].get("data_version", ""),
                "source_contract": week_frame.iloc[-1].get("source_contract", contract),
                "created_at": week_frame.iloc[0].get("created_at"),
                "source_interval": "1m",
                "iso_year": iso_year,
                "iso_week": iso_week,
            }
        )
    return pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)


def _field_compare_status(
  field: str,
  left: Any,
  right: Any,
  *,
  price_tick: float = 1e-12,
) -> tuple[str, float | None]:
    if pd.isna(left) and pd.isna(right):
        return "pass", None
    if field in {"open", "high", "low", "close"}:
        delta = abs(float(left) - float(right))
        if delta <= price_tick:
            return "pass", delta
        if delta <= max(price_tick, 1e-9):
            return "warning", delta
        return "block", delta
    if field == "volume":
        left_value = int(float(left))
        right_value = int(float(right))
        return ("pass", 0.0) if left_value == right_value else ("block", float(abs(left_value - right_value)))
    if field == "open_interest":
        left_value = 0.0 if pd.isna(left) else float(left)
        right_value = 0.0 if pd.isna(right) else float(right)
        delta = abs(left_value - right_value)
        if delta == 0:
            return "pass", delta
        if delta <= 1e-6:
            return "warning", delta
        return "block", delta
    if field == "turnover":
        left_value = 0.0 if pd.isna(left) else float(left)
        right_value = 0.0 if pd.isna(right) else float(right)
        delta = abs(left_value - right_value)
        tolerance = max(0.01, 1e-6 * max(abs(left_value), abs(right_value), 1.0))
        if delta == 0:
            return "pass", delta
        if delta <= tolerance:
            return "warning", delta
        return "block", delta
    return "block", None


def _prepare_overlap_frames(
    aggregated: pd.DataFrame,
    direct: pd.DataFrame,
    *,
    period: str,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    agg = aggregated.copy()
    direct_frame = direct.copy()
    agg["datetime"] = pd.to_datetime(agg["datetime"], errors="coerce")
    direct_frame["datetime"] = pd.to_datetime(direct_frame["datetime"], errors="coerce")
    if "trading_day" in agg.columns:
        agg["trading_day"] = pd.to_datetime(agg["trading_day"], errors="coerce").dt.date
    else:
        agg["trading_day"] = agg["datetime"].map(infer_trading_day)
    if "trading_day" in direct_frame.columns:
        direct_frame["trading_day"] = pd.to_datetime(direct_frame["trading_day"], errors="coerce").dt.date
    else:
        direct_frame["trading_day"] = direct_frame["datetime"].map(infer_trading_day)
    join_key = "trading_day" if period == "1d" else "datetime"
    return agg, direct_frame, join_key


def compare_daily_weekly_overlap(
    *,
    aggregated_path: Path | None = None,
    direct_path: Path | None = None,
    aggregated_frame: pd.DataFrame | None = None,
    direct_frame: pd.DataFrame | None = None,
    period: str = "1d",
    sample_rows: int | None = None,
    price_tick: float = 1e-12,
) -> dict[str, Any]:
    comparison_mode = (
        "aggregated_from_1m_vs_stored_1d"
        if period == "1d"
        else "aggregated_from_1m_readonly_vs_stored_rqdata_direct_1w"
    )
    if aggregated_frame is None:
        if aggregated_path is None or not aggregated_path.exists():
            return {
                "status": "failed",
                "issue_type": "missing_physical_file",
                "comparison_mode": comparison_mode,
                "overlap_rows": 0,
                "block_mismatches": 0,
                "warning_mismatches": 0,
                "mismatches": [],
            }
        aggregated_frame = pd.read_parquet(aggregated_path)
    if direct_frame is None:
        if direct_path is None or not direct_path.exists():
            return {
                "status": "failed",
                "issue_type": "missing_physical_file",
                "comparison_mode": comparison_mode,
                "overlap_rows": 0,
                "block_mismatches": 0,
                "warning_mismatches": 0,
                "mismatches": [],
            }
        direct_frame = pd.read_parquet(direct_path)

    if aggregated_frame.empty or direct_frame.empty:
        return {
            "status": "warning",
            "issue_type": "empty_overlap",
            "comparison_mode": comparison_mode,
            "overlap_rows": 0,
            "block_mismatches": 0,
            "warning_mismatches": 0,
            "mismatches": [],
        }

    agg, direct, join_key = _prepare_overlap_frames(aggregated_frame, direct_frame, period=period)
    merged = agg.merge(direct, on=join_key, suffixes=("_agg", "_direct"), how="inner")
    if sample_rows is not None:
        merged = merged.head(sample_rows)

    mismatches: list[dict[str, Any]] = []
    datetime_alignment_warnings = 0
    for _, row in merged.iterrows():
        if period == "1d":
            agg_dt = pd.to_datetime(row.get("datetime_agg"))
            direct_dt = pd.to_datetime(row.get("datetime_direct"))
            if pd.notna(agg_dt) and pd.notna(direct_dt) and agg_dt != direct_dt:
                datetime_alignment_warnings += 1
                mismatches.append(
                    {
                        "join_key": str(row[join_key]),
                        "field": "datetime_alignment",
                        "aggregated": agg_dt.isoformat(),
                        "direct": direct_dt.isoformat(),
                        "severity": "warning",
                        "delta": None,
                    }
                )
        for field in COMPARE_FIELDS:
            agg_value = row.get(f"{field}_agg")
            direct_value = row.get(f"{field}_direct")
            severity, delta = _field_compare_status(field, agg_value, direct_value, price_tick=price_tick)
            if severity == "pass":
                continue
            mismatches.append(
                {
                    "join_key": str(row[join_key]),
                    "field": field,
                    "aggregated": None if pd.isna(agg_value) else float(agg_value),
                    "direct": None if pd.isna(direct_value) else float(direct_value),
                    "severity": severity,
                    "delta": delta,
                }
            )

    block_mismatches = sum(1 for item in mismatches if item["severity"] == "block")
    warning_mismatches = sum(1 for item in mismatches if item["severity"] == "warning")
    if block_mismatches:
        status = "failed"
        issue_type = "overlap_mismatch"
    elif warning_mismatches:
        status = "warning"
        issue_type = "overlap_warning"
    else:
        status = "passed"
        issue_type = ""

    return {
        "status": status,
        "issue_type": issue_type,
        "comparison_mode": comparison_mode,
        "join_key": join_key,
        "overlap_rows": int(len(merged)),
        "block_mismatches": block_mismatches,
        "warning_mismatches": warning_mismatches,
        "datetime_alignment_warnings": datetime_alignment_warnings,
        "mismatches": mismatches,
    }


def compare_overlap_from_1m_source(
    *,
    source_1m_path: Path,
    stored_path: Path,
    period: str,
    price_tick: float = 1e-12,
) -> dict[str, Any]:
    if not source_1m_path.exists() or not stored_path.exists():
        return {
            "status": "failed",
            "issue_type": "missing_physical_file",
            "comparison_mode": f"1m_source_vs_stored_{period}",
            "overlap_rows": 0,
            "block_mismatches": 0,
            "warning_mismatches": 0,
            "mismatches": [],
        }
    source_frame = pd.read_parquet(source_1m_path)
    aggregated_frame = aggregate_bars_for_reconcile(source_frame, period)
    return compare_daily_weekly_overlap(
        aggregated_frame=aggregated_frame,
        direct_path=stored_path,
        period=period,
        price_tick=price_tick,
    )
