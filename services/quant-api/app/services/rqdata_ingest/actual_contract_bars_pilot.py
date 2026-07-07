from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import DataQualityReport, FeeMarginRule, FuturesTradingParameter, MainContractMap, MarketDataFile, utc_now
from app.services.rqdata_ingest.bar_sample import (
    BarQuality,
    _ensure_reference_rows,
    _record_canonical_file_and_quality,
    _record_raw_file,
    _start_task,
    as_datetime,
    duckdb_bar_summary,
    evaluate_bar_quality,
    normalize_bar_frame,
)
from app.services.rqdata_ingest.parquet import sha256_file, write_parquet_atomic


PROVIDER = "rqdata"
CONTINUOUS_SUFFIX = ".MAIN"
SOURCE_PERIOD = "1m"
SUPPORTED_PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d")


class ActualContractBarsGateError(RuntimeError):
    """Raised when Stage 8.5-6 metadata gates do not allow pilot writes."""


class ActualContractBarsQualityError(RuntimeError):
    """Raised when canonical bars fail the Stage 8.5-6 quality gate."""


class ActualContractBarsClient(Protocol):
    def contract_bars(self, contract: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame: ...


def build_actual_contract_bars_dry_run_payload(
    *,
    product: str,
    trade_date: date,
    start_date: date,
    end_date: date,
    periods: tuple[str, ...],
    output_root: Path,
) -> dict[str, Any]:
    normalized_product = _product(product)
    normalized_periods = _periods(periods)
    _validate_date_range(start_date, end_date)
    return {
        "mode": "dry-run",
        "stage": "DATA-UNIVERSE-8_5F-HISTORICAL-BARS-PILOT-WRITE",
        "provider": PROVIDER,
        "product": normalized_product,
        "continuous_contract": _continuous_contract(normalized_product),
        "actual_contract": None,
        "trade_date": trade_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "periods": list(normalized_periods),
        "output_root": str(output_root),
        "would_construct_rqdata_client": False,
        "would_open_database_session": False,
        "would_call_rqdata": False,
        "would_write_parquet": False,
        "would_write_manifest": False,
        "would_write_database": False,
        "would_register_primary": False,
        "would_send_wechat": False,
        "would_trigger_strategy": False,
        "would_run_backtest": False,
    }


def plan_actual_contract_bars_pilot(
    *,
    session: Session,
    output_root: Path,
    product: str,
    trade_date: date,
    start_date: date,
    end_date: date,
    periods: tuple[str, ...],
) -> dict[str, Any]:
    normalized_product = _product(product)
    normalized_periods = _periods(periods)
    _validate_date_range(start_date, end_date)
    session.flush()
    mapping = _resolve_main_mapping(session, product=normalized_product, trade_date=trade_date)
    actual_contract = _actual_contract(mapping.contract_code)
    parameter_gate = _parameter_gate(session, product=normalized_product, contract=actual_contract, trade_date=trade_date)
    if parameter_gate["status"] != "passed":
        raise ActualContractBarsGateError(f"trading parameter gate failed for {actual_contract} on {trade_date}: {parameter_gate}")

    exchange = str(parameter_gate.get("exchange_code") or "DCE").upper()
    output_root = output_root.resolve()
    period_plan = {
        period: {
            "data_version": _data_version(product=normalized_product, contract=actual_contract, period=period, start_date=start_date, end_date=end_date),
            "raw_path": str(_raw_path(output_root, product=normalized_product, contract=actual_contract, start_date=start_date, end_date=end_date))
            if period == SOURCE_PERIOD
            else None,
            "canonical_path": str(
                _canonical_path(
                    output_root,
                    product=normalized_product,
                    contract=actual_contract,
                    exchange=exchange,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                )
            ),
        }
        for period in normalized_periods
    }
    return {
        "mode": "plan",
        "stage": "DATA-UNIVERSE-8_5F-HISTORICAL-BARS-PILOT-WRITE",
        "provider": PROVIDER,
        "source_period": SOURCE_PERIOD,
        "product": normalized_product,
        "continuous_contract": _continuous_contract(normalized_product),
        "actual_contract": actual_contract,
        "dominant_mapping_date": mapping.trade_date.isoformat(),
        "main_contract_data_version": mapping.data_version,
        "exchange": exchange,
        "trade_date": trade_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "periods": period_plan,
        "manifest_path": str(_manifest_path(output_root, product=normalized_product, contract=actual_contract, start_date=start_date, end_date=end_date)),
        "parameter_gate": parameter_gate,
        "would_write_parquet": True,
        "would_write_database": True,
        "would_register_primary": True,
    }


def run_actual_contract_bars_pilot_write(
    *,
    session: Session,
    client: ActualContractBarsClient,
    output_root: Path,
    product: str,
    trade_date: date,
    start_date: date,
    end_date: date,
    periods: tuple[str, ...],
) -> dict[str, Any]:
    plan = plan_actual_contract_bars_pilot(
        session=session,
        output_root=output_root,
        product=product,
        trade_date=trade_date,
        start_date=start_date,
        end_date=end_date,
        periods=periods,
    )
    actual_contract = plan["actual_contract"]
    normalized_product = plan["product"]
    exchange = plan["exchange"]
    output_root = output_root.resolve()

    raw_frame = client.contract_bars(actual_contract, start_date, end_date, SOURCE_PERIOD)
    if raw_frame.empty:
        raise ActualContractBarsQualityError(f"RQData returned no rows for {actual_contract} {SOURCE_PERIOD} {start_date}..{end_date}")
    raw_path = _raw_path(output_root, product=normalized_product, contract=actual_contract, start_date=start_date, end_date=end_date)
    write_parquet_atomic(raw_frame, raw_path)

    source_frame = normalize_bar_frame(
        raw_frame,
        symbol=normalized_product,
        contract=actual_contract,
        source_contract=actual_contract,
        exchange=exchange,
        frequency=SOURCE_PERIOD,
        data_version=_data_version(
            product=normalized_product,
            contract=actual_contract,
            period=SOURCE_PERIOD,
            start_date=start_date,
            end_date=end_date,
        ),
    )
    _ensure_reference_rows(session, symbol=normalized_product, contract=actual_contract, exchange=exchange)

    period_frames = _build_period_frames(
        source_frame,
        product=normalized_product,
        contract=actual_contract,
        periods=tuple(plan["periods"].keys()),
        start_date=start_date,
        end_date=end_date,
    )
    qualities = {period: evaluate_bar_quality(frame, period) for period, frame in period_frames.items()}
    failed = {period: quality.status for period, quality in qualities.items() if quality.status != "passed"}
    if failed:
        raise ActualContractBarsQualityError(f"quality_status must be passed before primary registration: {failed}")

    manifest_rows: list[dict[str, Any]] = []
    registered: dict[str, Any] = {}
    for period, frame in period_frames.items():
        quality = qualities[period]
        path = _canonical_path(
            output_root,
            product=normalized_product,
            contract=actual_contract,
            exchange=exchange,
            period=period,
            start_date=start_date,
            end_date=end_date,
        )
        frame = frame.copy()
        frame["quality_status"] = quality.status
        write_parquet_atomic(frame, path)
        task = _start_task(
            session=session,
            symbol=normalized_product,
            contract=actual_contract,
            frequency=period,
            start_date=pd.to_datetime(frame["datetime"]).min().date(),
            end_date=pd.to_datetime(frame["datetime"]).max().date(),
        )
        if period == SOURCE_PERIOD:
            _record_raw_file(
                session=session,
                task=task,
                path=raw_path,
                symbol=normalized_product,
                contract=actual_contract,
                frequency=SOURCE_PERIOD,
                start_time=as_datetime(start_date),
                end_time=as_datetime(end_date, end_of_day=True),
                row_count=len(raw_frame),
                data_version=plan["periods"][SOURCE_PERIOD]["data_version"],
            )
        market_file = _record_canonical_file_and_quality(
            session=session,
            task=task,
            path=path,
            frame=frame,
            quality=quality,
            symbol=normalized_product,
            contract=actual_contract,
            frequency=period,
            data_version=plan["periods"][period]["data_version"],
        )
        task.status = "success"
        task.progress = 100
        task.finished_at = utc_now()
        task.result = {
            "actual_contract_bars_pilot": True,
            "stage": plan["stage"],
            "raw_path": str(raw_path) if period == SOURCE_PERIOD else None,
            "canonical_path": str(path),
            "row_count": len(frame),
            "quality_status": quality.status,
            "actual_contract": actual_contract,
            "continuous_contract": plan["continuous_contract"],
        }
        session.flush()
        report = session.scalar(select(DataQualityReport).where(DataQualityReport.file_id == market_file.id))
        if report is not None:
            report.details = {
                **(report.details or {}),
                "actual_contract_bars_pilot": True,
                "stage": plan["stage"],
                "continuous_contract": plan["continuous_contract"],
                "actual_contract": actual_contract,
                "dominant_mapping_date": plan["dominant_mapping_date"],
                "manifest_path": plan["manifest_path"],
                "standard_path": str(path),
                "raw_path": str(raw_path) if period == SOURCE_PERIOD else None,
                "checksum": sha256_file(path),
                "data_version": plan["periods"][period]["data_version"],
                "row_count": len(frame),
            }
        session.flush()
        report_id = None if report is None else report.id
        summary = _period_summary(path=path, frame=frame, quality=quality, market_file=market_file, report_id=report_id)
        registered[period] = summary
        manifest_rows.append(
            {
                "period": period,
                "provider": PROVIDER,
                "source": PROVIDER,
                "product": normalized_product,
                "continuous_contract": plan["continuous_contract"],
                "actual_contract": actual_contract,
                "dominant_mapping_date": plan["dominant_mapping_date"],
                "data_role": "primary",
                "quality_status": quality.status,
                "row_count": len(frame),
                "min_datetime": summary["min_datetime"],
                "max_datetime": summary["max_datetime"],
                "checksum": summary["checksum"],
                "standard_path": str(path),
                "raw_path": str(raw_path) if period == SOURCE_PERIOD else "",
                "market_data_file_id": market_file.id,
                "data_quality_report_id": report_id,
                "data_version": plan["periods"][period]["data_version"],
                "status": "success",
            }
        )

    manifest_path = Path(plan["manifest_path"])
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(manifest_rows).sort_values("period").to_csv(manifest_path, index=False)
    return {
        **plan,
        "mode": "write",
        "writes_database": True,
        "writes_parquet": True,
        "manifest_path": str(manifest_path),
        "raw_path": str(raw_path),
        "raw_checksum": sha256_file(raw_path),
        "raw_rows": len(raw_frame),
        "quality_gate": "passed",
        "periods": registered,
    }


def _build_period_frames(
    source_frame: pd.DataFrame,
    *,
    product: str,
    contract: str,
    periods: tuple[str, ...],
    start_date: date,
    end_date: date,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for period in periods:
        if period == SOURCE_PERIOD:
            frame = source_frame.copy()
        else:
            frame = _aggregate_standard_bars(source_frame, period)
        frame["data_version"] = _data_version(product=product, contract=contract, period=period, start_date=start_date, end_date=end_date)
        frames[period] = frame
    return frames


def _aggregate_standard_bars(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    normalized = period.strip().lower()
    if normalized not in {"5m", "15m", "30m", "60m", "1d"}:
        raise ValueError(f"unsupported actual contract aggregation period: {period}")
    required = {
        "symbol",
        "contract",
        "exchange",
        "vt_symbol",
        "datetime",
        "trading_day",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "open_interest",
        "source",
        "provider",
        "data_role",
        "created_at",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"actual contract standard frame missing required columns for aggregation: {missing}")

    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    data["trading_day"] = pd.to_datetime(data["trading_day"], errors="coerce").dt.date
    data = data.dropna(subset=["datetime", "trading_day", "open", "high", "low", "close"])
    data = data.sort_values(["contract", "trading_day", "datetime"]).reset_index(drop=True)
    if data.empty:
        return data

    if normalized == "1d":
        data["_bucket"] = list(zip(data["contract"], data["trading_day"], strict=False))
    else:
        minutes = int(normalized.removesuffix("m"))
        previous_datetime = data.groupby(["contract", "trading_day"])["datetime"].shift()
        gap_seconds = (data["datetime"] - previous_datetime).dt.total_seconds()
        data["_block"] = gap_seconds.isna() | (gap_seconds > 90)
        data["_block"] = data.groupby(["contract", "trading_day"])["_block"].cumsum()
        data["_offset"] = data.groupby(["contract", "trading_day", "_block"]).cumcount()
        data["_bucket_index"] = data["_offset"] // minutes
        data["_bucket"] = list(zip(data["contract"], data["trading_day"], data["_block"], data["_bucket_index"], strict=False))

    grouped = data.groupby("_bucket", sort=False, dropna=False)
    first = grouped.head(1).set_index("_bucket")
    last = grouped.tail(1).set_index("_bucket")
    result = pd.DataFrame(
        {
            "symbol": first["symbol"],
            "contract": first["contract"],
            "exchange": first["exchange"],
            "vt_symbol": first["vt_symbol"],
            "datetime": last["datetime"],
            "trading_day": first["trading_day"],
            "interval": normalized,
            "period": normalized,
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
            "turnover": grouped["turnover"].sum(),
            "open_interest": grouped["open_interest"].last(),
            "source": first["source"],
            "provider": first["provider"],
            "data_role": first["data_role"],
            "quality_status": "unchecked",
            "data_version": first["data_version"],
            "source_contract": last["source_contract"] if "source_contract" in last.columns else last["contract"],
            "created_at": first["created_at"],
            "source_interval": SOURCE_PERIOD,
            "source_bar_count": grouped.size(),
        }
    )
    return result.sort_values("datetime").reset_index(drop=True)


def _resolve_main_mapping(session: Session, *, product: str, trade_date: date) -> MainContractMap:
    mapping = session.scalar(
        select(MainContractMap)
        .where(
            MainContractMap.instrument_symbol == product,
            MainContractMap.trade_date == trade_date,
            MainContractMap.rank == 1,
            MainContractMap.provider == PROVIDER,
        )
        .order_by(MainContractMap.created_at.desc(), MainContractMap.id.desc())
    )
    if mapping is None:
        raise ActualContractBarsGateError(f"MainContractMap.rank=1 missing for product={product}, trade_date={trade_date}")
    return mapping


def _parameter_gate(session: Session, *, product: str, contract: str, trade_date: date) -> dict[str, Any]:
    params = session.scalar(
        select(FuturesTradingParameter)
        .where(
            FuturesTradingParameter.contract_code == contract,
            FuturesTradingParameter.trade_date == trade_date,
            FuturesTradingParameter.provider == PROVIDER,
        )
        .order_by(FuturesTradingParameter.created_at.desc(), FuturesTradingParameter.id.desc())
    )
    fee_rule = session.scalar(
        select(FeeMarginRule)
        .where(
            FeeMarginRule.provider == PROVIDER,
            FeeMarginRule.contract_code == contract,
            FeeMarginRule.effective_date <= trade_date,
        )
        .order_by(FeeMarginRule.effective_date.desc(), FeeMarginRule.created_at.desc(), FeeMarginRule.id.desc())
    )
    values = {
        "price_tick": _first_present(getattr(params, "price_tick", None), getattr(fee_rule, "price_tick", None)),
        "contract_multiplier": _first_present(getattr(params, "contract_multiplier", None), getattr(fee_rule, "volume_multiple", None)),
        "margin": _first_present(getattr(params, "short_margin_ratio", None), getattr(params, "long_margin_ratio", None), getattr(fee_rule, "margin_rate", None)),
        "open_commission": _first_present(getattr(params, "open_commission", None), getattr(fee_rule, "open_fee", None)),
        "close_commission": _first_present(getattr(params, "close_commission", None), getattr(fee_rule, "close_fee", None)),
        "close_today_commission": _first_present(getattr(params, "close_today_commission", None), getattr(fee_rule, "close_today_fee", None)),
        "exchange_code": _first_present(getattr(params, "exchange_code", None), getattr(fee_rule, "exchange_code", None), "DCE"),
    }
    missing = [
        field
        for field in ("price_tick", "contract_multiplier", "margin", "open_commission", "close_commission", "close_today_commission")
        if values[field] is None
    ]
    if params is not None and fee_rule is not None:
        source = "mixed" if missing or _uses_fee_fallback(params, fee_rule) else "futures_trading_parameters"
    elif params is not None:
        source = "futures_trading_parameters"
    elif fee_rule is not None:
        source = "fee_margin_rules"
    else:
        source = None
    return {
        "status": "failed" if missing else "passed",
        "source": source,
        "missing_fields": missing,
        "product": product,
        "contract_code": contract,
        "trade_date": trade_date.isoformat(),
        "exchange_code": values["exchange_code"],
    }


def _uses_fee_fallback(params: FuturesTradingParameter, fee_rule: FeeMarginRule) -> bool:
    return any(
        getattr(params, params_field) is None and getattr(fee_rule, fee_field) is not None
        for params_field, fee_field in (
            ("price_tick", "price_tick"),
            ("contract_multiplier", "volume_multiple"),
            ("short_margin_ratio", "margin_rate"),
            ("open_commission", "open_fee"),
            ("close_commission", "close_fee"),
            ("close_today_commission", "close_today_fee"),
        )
    )


def _period_summary(
    *,
    path: Path,
    frame: pd.DataFrame,
    quality: BarQuality,
    market_file: MarketDataFile,
    report_id: int | None,
) -> dict[str, Any]:
    datetimes = pd.to_datetime(frame["datetime"], errors="coerce")
    checksum = sha256_file(path)
    return {
        "standard_path": str(path),
        "row_count": len(frame),
        "min_datetime": datetimes.min().to_pydatetime().isoformat(),
        "max_datetime": datetimes.max().to_pydatetime().isoformat(),
        "checksum": checksum,
        "quality_status": quality.status,
        "missing_bars": quality.missing_bars,
        "duplicated_bars": quality.duplicated_bars,
        "abnormal_price_count": quality.abnormal_price_count,
        "abnormal_volume_count": quality.abnormal_volume_count,
        "abnormal_open_interest_count": quality.abnormal_open_interest_count,
        "market_data_file_id": market_file.id,
        "data_quality_report_id": report_id,
        "duckdb": duckdb_bar_summary(path),
    }


def _product(value: str) -> str:
    product = str(value or "").strip().lower()
    if not product:
        raise ActualContractBarsGateError("product is required")
    if product != "jm":
        raise ActualContractBarsGateError("Stage 8.5-6 pilot is JM-only")
    return product


def _periods(values: tuple[str, ...]) -> tuple[str, ...]:
    periods = tuple(dict.fromkeys(str(item).strip().lower() for item in values if str(item).strip()))
    if not periods:
        raise ActualContractBarsGateError("at least one period is required")
    unsupported = sorted(set(periods) - set(SUPPORTED_PERIODS))
    if unsupported:
        raise ActualContractBarsGateError(f"unsupported periods for Stage 8.5-6: {unsupported}")
    if SOURCE_PERIOD not in periods:
        raise ActualContractBarsGateError("Stage 8.5-6 pilot requires 1m as source period")
    return periods


def _validate_date_range(start_date: date, end_date: date) -> None:
    if end_date < start_date:
        raise ActualContractBarsGateError("end_date must be greater than or equal to start_date")


def _actual_contract(value: str) -> str:
    contract = str(value or "").strip().upper()
    if not contract:
        raise ActualContractBarsGateError("MainContractMap.rank=1 returned blank actual_contract")
    if contract.lower().endswith(CONTINUOUS_SUFFIX.lower()) or "." in contract:
        raise ActualContractBarsGateError(f"continuous contract cannot be actual_contract: {value}")
    return contract


def _continuous_contract(product: str) -> str:
    return f"{product}{CONTINUOUS_SUFFIX}"


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _data_version(*, product: str, contract: str, period: str, start_date: date, end_date: date) -> str:
    return f"rqdata_actual_contract_bars_{product}_{contract}_{period}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_v1"


def _raw_path(output_root: Path, *, product: str, contract: str, start_date: date, end_date: date) -> Path:
    return (
        output_root
        / "raw"
        / PROVIDER
        / "actual_contract_bars"
        / f"product={product}"
        / f"contract={contract}"
        / "frequency=1m"
        / f"{contract}_1m_raw_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet"
    )


def _canonical_path(output_root: Path, *, product: str, contract: str, exchange: str, period: str, start_date: date, end_date: date) -> Path:
    return (
        output_root
        / "parquet"
        / "canonical"
        / "bars"
        / f"provider={PROVIDER}"
        / f"period={period}"
        / f"exchange={exchange}"
        / f"symbol={product}"
        / f"contract={contract}"
        / f"{contract}_{period}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet"
    )


def _manifest_path(output_root: Path, *, product: str, contract: str, start_date: date, end_date: date) -> Path:
    return output_root / "manifests" / f"rqdata_actual_contract_bars_{product}_{contract}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.csv"
