from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import (
    Contract,
    DataQualityReport,
    FeeMarginRule,
    FuturesTradingParameter,
    Instrument,
    MainContractMap,
    MarketDataFile,
    utc_now,
)
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
from app.services.rqdata_ingest.bar_aggregation import aggregate_standard_bars
from app.services.rqdata_ingest.dominant_v2_parquet import contract_segments_from_mapping
from app.services.rqdata_ingest.parquet import sha256_file, write_parquet_atomic


PROVIDER = "rqdata"
CONTINUOUS_SUFFIX = ".MAIN"
SOURCE_PERIOD = "1m"
SUPPORTED_PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d", "1w")
MINUTE_BUNDLE_PERIODS = ("1m", "5m", "15m", "30m", "60m")
RQDATA_ONLY_PERIODS = ("1d", "1w")


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
    jm_only: bool = True,
    local_daily: bool = False,
) -> dict[str, Any]:
    normalized_product = _product(product, jm_only=jm_only)
    normalized_periods = _periods(periods, local_daily=local_daily)
    _validate_date_range(start_date, end_date)
    session.flush()
    mapping = resolve_main_mapping(session, product=normalized_product, trade_date=trade_date)
    actual_contract = _actual_contract(mapping.contract_code)
    parameter_gate = _parameter_gate(session, product=normalized_product, contract=actual_contract, trade_date=trade_date)
    if parameter_gate["status"] != "passed":
        raise ActualContractBarsGateError(f"trading parameter gate failed for {actual_contract} on {trade_date}: {parameter_gate}")

    exchange = _segment_exchange(session, product=normalized_product, contract=actual_contract, trade_date=trade_date)
    output_root = output_root.resolve()
    download_period = _download_period(normalized_periods, local_daily=local_daily)
    period_plan = {
        period: {
            "data_version": _data_version(product=normalized_product, contract=actual_contract, period=period, start_date=start_date, end_date=end_date),
            "raw_path": str(
                _raw_path(
                    output_root,
                    product=normalized_product,
                    contract=actual_contract,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
            if period == download_period
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
        "source_period": download_period,
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
        "local_daily": local_daily,
    }


def run_actual_contract_bars_roll_write(
    *,
    session: Session,
    client: ActualContractBarsClient,
    output_root: Path,
    product: str,
    start_date: date,
    end_date: date,
    periods: tuple[str, ...],
    jm_only: bool = False,
    skip_existing: bool = True,
) -> dict[str, Any]:
    normalized_product = _product(product, jm_only=jm_only)
    normalized_periods = _periods(periods)
    _validate_date_range(start_date, end_date)
    mappings = session.scalars(
        select(MainContractMap)
        .where(
            MainContractMap.instrument_symbol == normalized_product,
            MainContractMap.rank == 1,
            MainContractMap.provider == PROVIDER,
            MainContractMap.trade_date >= start_date,
            MainContractMap.trade_date <= end_date,
        )
        .order_by(MainContractMap.trade_date.asc())
    ).all()
    if not mappings:
        raise ActualContractBarsGateError(
            f"MainContractMap.rank=1 missing for product={normalized_product} between {start_date} and {end_date}"
        )
    records = [
        {"trade_date": mapping.trade_date, "rqdata_order_book_id": _actual_contract(mapping.contract_code)}
        for mapping in mappings
    ]
    segments = contract_segments_from_mapping(records, start_date=start_date, end_date=end_date)
    if not segments:
        raise ActualContractBarsGateError(f"no actual_contract roll segments resolved for product={normalized_product}")

    segment_results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for segment in segments:
        contract = segment["rqdata_order_book_id"]
        segment_start = segment["start_date"]
        segment_end = segment["end_date"]
        segment_exchange = _segment_exchange(
            session,
            product=normalized_product,
            contract=contract,
            trade_date=segment_end,
        )
        if skip_existing and all(
            _canonical_path(
                output_root.resolve(),
                product=normalized_product,
                contract=contract,
                exchange=segment_exchange,
                period=period,
                start_date=segment_start,
                end_date=segment_end,
            ).exists()
            for period in normalized_periods
        ):
            segment_results.append(
                {
                    "actual_contract": contract,
                    "start_date": segment_start.isoformat(),
                    "end_date": segment_end.isoformat(),
                    "status": "skipped_existing",
                    "periods": list(normalized_periods),
                }
            )
            continue
        try:
            result = run_actual_contract_bars_pilot_write(
                session=session,
                client=client,
                output_root=output_root,
                product=normalized_product,
                trade_date=segment_end,
                start_date=segment_start,
                end_date=segment_end,
                periods=normalized_periods,
                jm_only=jm_only,
            )
            segment_results.append(
                {
                    "actual_contract": contract,
                    "start_date": segment_start.isoformat(),
                    "end_date": segment_end.isoformat(),
                    "status": "success",
                    "result": result,
                }
            )
        except ActualContractBarsQualityError as exc:
            error_text = str(exc)
            if "1w" in normalized_periods and "no rows" in error_text.lower():
                try:
                    result = run_actual_contract_bars_pilot_write(
                        session=session,
                        client=client,
                        output_root=output_root,
                        product=normalized_product,
                        trade_date=segment_end,
                        start_date=segment_start,
                        end_date=segment_end,
                        periods=tuple(period for period in normalized_periods if period != "1w"),
                        jm_only=jm_only,
                    )
                    segment_results.append(
                        {
                            "actual_contract": contract,
                            "start_date": segment_start.isoformat(),
                            "end_date": segment_end.isoformat(),
                            "status": "success_1d_only",
                            "skipped_periods": ["1w"],
                            "skip_reason": error_text,
                            "result": result,
                        }
                    )
                    continue
                except (ActualContractBarsGateError, ActualContractBarsQualityError, RuntimeError, ValueError) as retry_exc:
                    failures.append(
                        {
                            "actual_contract": contract,
                            "start_date": segment_start.isoformat(),
                            "end_date": segment_end.isoformat(),
                            "status": "failed",
                            "error": str(retry_exc),
                        }
                    )
                    continue
            failures.append(
                {
                    "actual_contract": contract,
                    "start_date": segment_start.isoformat(),
                    "end_date": segment_end.isoformat(),
                    "status": "failed",
                    "error": error_text,
                }
            )
        except (ActualContractBarsGateError, RuntimeError, ValueError) as exc:
            failures.append(
                {
                    "actual_contract": contract,
                    "start_date": segment_start.isoformat(),
                    "end_date": segment_end.isoformat(),
                    "status": "failed",
                    "error": str(exc),
                }
            )
    return {
        "mode": "roll-write",
        "stage": "DATA-UNIVERSE-8_5G-ACTUAL-CONTRACT-BARS-ROLL",
        "provider": PROVIDER,
        "product": normalized_product,
        "continuous_contract": _continuous_contract(normalized_product),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "segment_count": len(segments),
        "success_count": sum(1 for item in segment_results if item.get("status") == "success"),
        "skipped_count": sum(1 for item in segment_results if item.get("status") == "skipped_existing"),
        "failure_count": len(failures),
        "segments": segment_results,
        "failures": failures,
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
    jm_only: bool = True,
    local_daily: bool = False,
    expected_source_rows: int | None = None,
    data_role: str = "primary",
) -> dict[str, Any]:
    if data_role not in {"primary", "candidate"}:
        raise ValueError("data_role must be primary or candidate")
    plan = plan_actual_contract_bars_pilot(
        session=session,
        output_root=output_root,
        product=product,
        trade_date=trade_date,
        start_date=start_date,
        end_date=end_date,
        periods=periods,
        jm_only=jm_only,
        local_daily=local_daily,
    )
    actual_contract = plan["actual_contract"]
    normalized_product = plan["product"]
    exchange = plan["exchange"]
    output_root = output_root.resolve()

    normalized_periods = tuple(plan["periods"].keys())
    if _is_rqdata_direct_only(normalized_periods):
        period_frames: dict[str, pd.DataFrame] = {}
        raw_paths: dict[str, Path] = {}
        for period in normalized_periods:
            raw_frame = client.contract_bars(actual_contract, start_date, end_date, period)
            if raw_frame.empty:
                raise ActualContractBarsQualityError(
                    f"RQData returned no rows for {actual_contract} {period} {start_date}..{end_date}"
                )
            raw_path = _raw_path(
                output_root,
                product=normalized_product,
                contract=actual_contract,
                period=period,
                start_date=start_date,
                end_date=end_date,
            )
            write_parquet_atomic(raw_frame, raw_path)
            raw_paths[period] = raw_path
            period_frames[period] = normalize_bar_frame(
                raw_frame,
                symbol=normalized_product,
                contract=actual_contract,
                source_contract=actual_contract,
                exchange=exchange,
                frequency=period,
                data_version=_data_version(
                    product=normalized_product,
                    contract=actual_contract,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                ),
            )
        download_period = normalized_periods[0]
        raw_path = raw_paths[download_period]
        raw_frame = pd.read_parquet(raw_path)
    else:
        download_period = _download_period(normalized_periods, local_daily=local_daily)
        raw_frame = client.contract_bars(actual_contract, start_date, end_date, download_period)
        if raw_frame.empty:
            raise ActualContractBarsQualityError(
                f"RQData returned no rows for {actual_contract} {download_period} {start_date}..{end_date}"
            )
        raw_path = _raw_path(
            output_root,
            product=normalized_product,
            contract=actual_contract,
            period=download_period,
            start_date=start_date,
            end_date=end_date,
        )
        write_parquet_atomic(raw_frame, raw_path)

        source_frame = normalize_bar_frame(
            raw_frame,
            symbol=normalized_product,
            contract=actual_contract,
            source_contract=actual_contract,
            exchange=exchange,
            frequency=download_period,
            data_version=_data_version(
                product=normalized_product,
                contract=actual_contract,
                period=download_period,
                start_date=start_date,
                end_date=end_date,
            ),
        )
        if expected_source_rows is not None and len(source_frame) != expected_source_rows:
            raise ActualContractBarsQualityError(
                f"source 1m row_count mismatch for trading-session gate: expected={expected_source_rows}, actual={len(source_frame)}"
            )
        period_frames = _build_period_frames(
            source_frame,
            product=normalized_product,
            contract=actual_contract,
            periods=normalized_periods,
            start_date=start_date,
            end_date=end_date,
            download_period=download_period,
        )
    _ensure_reference_rows(session, symbol=normalized_product, contract=actual_contract, exchange=exchange)

    qualities = {period: _evaluate_actual_contract_bar_quality(frame, period) for period, frame in period_frames.items()}
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
        if _is_rqdata_direct_only(normalized_periods) or period == download_period:
            period_raw_path = raw_paths.get(period, raw_path) if _is_rqdata_direct_only(normalized_periods) else raw_path
            period_raw_frame = pd.read_parquet(period_raw_path) if period_raw_path != raw_path else raw_frame
            _record_raw_file(
                session=session,
                task=task,
                path=period_raw_path,
                symbol=normalized_product,
                contract=actual_contract,
                frequency=period,
                start_time=as_datetime(start_date),
                end_time=as_datetime(end_date, end_of_day=True),
                row_count=len(period_raw_frame),
                data_version=plan["periods"][period]["data_version"],
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
            data_role=data_role,
        )
        task.status = "success"
        task.progress = 100
        task.finished_at = utc_now()
        task.result = {
            "actual_contract_bars_pilot": True,
            "stage": plan["stage"],
            "raw_path": str(raw_path) if period == download_period else None,
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
                "raw_path": str(raw_path) if period == download_period else None,
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
                "data_role": data_role,
                "quality_status": quality.status,
                "row_count": len(frame),
                "min_datetime": summary["min_datetime"],
                "max_datetime": summary["max_datetime"],
                "checksum": summary["checksum"],
                "standard_path": str(path),
                "raw_path": str(raw_path) if period == download_period else "",
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
    download_period: str = SOURCE_PERIOD,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for period in periods:
        if period == download_period:
            frame = source_frame.copy()
        else:
            frame = aggregate_standard_bars(source_frame, period)
        frame["data_version"] = _data_version(product=product, contract=contract, period=period, start_date=start_date, end_date=end_date)
        frames[period] = frame
    return frames


def _evaluate_actual_contract_bar_quality(frame: pd.DataFrame, period: str) -> BarQuality:
    quality = evaluate_bar_quality(frame, period)
    has_hard_error = (
        quality.duplicated_bars
        + quality.abnormal_price_count
        + quality.abnormal_volume_count
        + quality.abnormal_open_interest_count
    ) > 0
    if quality.status != "warning" or has_hard_error or quality.missing_bars <= 0:
        return quality
    details = {
        **quality.details,
        "check_mode": "actual_contract_without_session_calendar",
        "missing_bars_before_session_calendar": quality.missing_bars,
        "missing_bars": 0,
        "missing_bar_note": (
            "Trading-session calendar is not applied for Stage 8.5-6B; natural lunch, night, "
            "holiday and weekend gaps are reported as gap_samples only."
        ),
    }
    return BarQuality(
        status="passed",
        missing_bars=0,
        duplicated_bars=quality.duplicated_bars,
        abnormal_price_count=quality.abnormal_price_count,
        abnormal_volume_count=quality.abnormal_volume_count,
        abnormal_open_interest_count=quality.abnormal_open_interest_count,
        details=details,
    )


def resolve_main_mapping(session: Session, *, product: str, trade_date: date) -> MainContractMap:
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


def _contract_meta(session: Session, contract: str) -> Contract | None:
    return session.scalar(select(Contract).where(Contract.contract_code == contract))


def _instrument_exchange(session: Session, product: str) -> str | None:
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == product.lower()))
    return None if instrument is None else instrument.exchange_code


def _product_trading_parameter_fallback(session: Session, *, product: str, trade_date: date) -> FuturesTradingParameter | None:
    backward = session.scalar(
        select(FuturesTradingParameter)
        .where(
            FuturesTradingParameter.instrument_symbol == product.lower(),
            FuturesTradingParameter.trade_date <= trade_date,
            FuturesTradingParameter.provider == PROVIDER,
        )
        .order_by(
            FuturesTradingParameter.trade_date.desc(),
            FuturesTradingParameter.created_at.desc(),
            FuturesTradingParameter.id.desc(),
        )
    )
    if backward is not None:
        return backward
    return session.scalar(
        select(FuturesTradingParameter)
        .where(
            FuturesTradingParameter.instrument_symbol == product.lower(),
            FuturesTradingParameter.provider == PROVIDER,
        )
        .order_by(
            FuturesTradingParameter.trade_date.asc(),
            FuturesTradingParameter.created_at.asc(),
            FuturesTradingParameter.id.asc(),
        )
    )


def _product_fee_rule_fallback(session: Session, *, product: str, trade_date: date) -> FeeMarginRule | None:
    backward = session.scalar(
        select(FeeMarginRule)
        .where(
            FeeMarginRule.provider == PROVIDER,
            FeeMarginRule.instrument_symbol == product.lower(),
            FeeMarginRule.effective_date <= trade_date,
        )
        .order_by(FeeMarginRule.effective_date.desc(), FeeMarginRule.created_at.desc(), FeeMarginRule.id.desc())
    )
    if backward is not None:
        return backward
    return session.scalar(
        select(FeeMarginRule)
        .where(
            FeeMarginRule.provider == PROVIDER,
            FeeMarginRule.instrument_symbol == product.lower(),
        )
        .order_by(FeeMarginRule.effective_date.asc(), FeeMarginRule.created_at.asc(), FeeMarginRule.id.asc())
    )


def _parameter_gate(session: Session, *, product: str, contract: str, trade_date: date) -> dict[str, Any]:
    contract_meta = _contract_meta(session, contract)
    instrument_exchange = _instrument_exchange(session, product)
    params = session.scalar(
        select(FuturesTradingParameter)
        .where(
            FuturesTradingParameter.contract_code == contract,
            FuturesTradingParameter.trade_date <= trade_date,
            FuturesTradingParameter.provider == PROVIDER,
        )
        .order_by(
            FuturesTradingParameter.trade_date.desc(),
            FuturesTradingParameter.created_at.desc(),
            FuturesTradingParameter.id.desc(),
        )
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
    product_params = None
    product_fee_rule = None
    if params is None or fee_rule is None:
        product_params = _product_trading_parameter_fallback(session, product=product, trade_date=trade_date)
        product_fee_rule = _product_fee_rule_fallback(session, product=product, trade_date=trade_date)
    values = {
        "price_tick": _first_present(
            getattr(params, "price_tick", None),
            getattr(fee_rule, "price_tick", None),
            getattr(product_params, "price_tick", None),
            getattr(product_fee_rule, "price_tick", None),
        ),
        "contract_multiplier": _first_present(
            getattr(params, "contract_multiplier", None),
            getattr(fee_rule, "volume_multiple", None),
            getattr(contract_meta, "contract_multiplier", None),
            getattr(product_params, "contract_multiplier", None),
            getattr(product_fee_rule, "volume_multiple", None),
        ),
        "margin": _first_present(
            getattr(params, "short_margin_ratio", None),
            getattr(params, "long_margin_ratio", None),
            getattr(fee_rule, "margin_rate", None),
            getattr(product_params, "short_margin_ratio", None),
            getattr(product_params, "long_margin_ratio", None),
            getattr(product_fee_rule, "margin_rate", None),
        ),
        "open_commission": _first_present(
            getattr(params, "open_commission", None),
            getattr(fee_rule, "open_fee", None),
            getattr(product_params, "open_commission", None),
            getattr(product_fee_rule, "open_fee", None),
        ),
        "close_commission": _first_present(
            getattr(params, "close_commission", None),
            getattr(fee_rule, "close_fee", None),
            getattr(product_params, "close_commission", None),
            getattr(product_fee_rule, "close_fee", None),
        ),
        "close_today_commission": _first_present(
            getattr(params, "close_today_commission", None),
            getattr(fee_rule, "close_today_fee", None),
            getattr(product_params, "close_today_commission", None),
            getattr(product_fee_rule, "close_today_fee", None),
        ),
        "exchange_code": _first_present(
            getattr(params, "exchange_code", None),
            getattr(fee_rule, "exchange_code", None),
            getattr(contract_meta, "exchange_code", None),
            getattr(product_params, "exchange_code", None),
            getattr(product_fee_rule, "exchange_code", None),
            instrument_exchange,
        ),
    }
    missing = [
        field
        for field in ("price_tick", "contract_multiplier", "margin", "open_commission", "close_commission", "close_today_commission")
        if values[field] is None
    ]
    storage_missing = [field for field in ("price_tick", "contract_multiplier") if values[field] is None]
    backtest_missing = [field for field in ("margin", "open_commission", "close_commission", "close_today_commission") if values[field] is None]
    if values["exchange_code"] is None:
        storage_missing.append("exchange_code")
    used_product_fallback = any(
        value is not None
        for value in (
            getattr(product_params, "price_tick", None),
            getattr(product_fee_rule, "price_tick", None),
            getattr(product_params, "open_commission", None),
            getattr(product_fee_rule, "open_fee", None),
        )
    )
    if params is not None and fee_rule is not None:
        source = "mixed" if missing or _uses_fee_fallback(params, fee_rule) else "futures_trading_parameters"
    elif params is not None:
        source = "futures_trading_parameters"
    elif fee_rule is not None:
        source = "fee_margin_rules"
    elif used_product_fallback:
        source = "product_fallback"
    else:
        source = None
    return {
        "status": "failed" if storage_missing else "passed",
        "source": source,
        "missing_fields": missing,
        "storage_missing_fields": storage_missing,
        "backtest_missing_fields": backtest_missing,
        "backtest_ready": not backtest_missing,
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


def _product(value: str, *, jm_only: bool = True) -> str:
    product = str(value or "").strip().lower()
    if not product:
        raise ActualContractBarsGateError("product is required")
    if jm_only and product != "jm":
        raise ActualContractBarsGateError("Stage 8.5-6 pilot is JM-only")
    return product


def _periods(values: tuple[str, ...], *, local_daily: bool = False) -> tuple[str, ...]:
    periods = tuple(dict.fromkeys(str(item).strip().lower() for item in values if str(item).strip()))
    if not periods:
        raise ActualContractBarsGateError("at least one period is required")
    unsupported = sorted(set(periods) - set(SUPPORTED_PERIODS))
    if unsupported:
        raise ActualContractBarsGateError(f"unsupported periods for Stage 8.5-6: {unsupported}")
    if periods == ("1w",) or (periods == ("1d",) and not local_daily):
        return periods
    rqdata_only_periods = {"1w"} if local_daily else set(RQDATA_ONLY_PERIODS)
    rqdata_only = set(periods) & rqdata_only_periods
    intraday = set(periods) - rqdata_only_periods
    if rqdata_only and intraday:
        raise ActualContractBarsGateError(
            "mixing rqdata-only periods (1d/1w) with minute bundle (1m/5m/15m/30m/60m) is not allowed; run them separately"
        )
    if intraday and SOURCE_PERIOD not in periods:
        raise ActualContractBarsGateError("Stage 8.5-6 pilot requires 1m as source period when downloading intraday periods")
    locally_derived = set(MINUTE_BUNDLE_PERIODS) | ({"1d"} if local_daily else set())
    invalid_intraday = sorted(intraday - locally_derived)
    if invalid_intraday:
        raise ActualContractBarsGateError(f"unsupported intraday periods for Stage 8.5-6: {invalid_intraday}")
    return periods


def _download_period(periods: tuple[str, ...], *, local_daily: bool = False) -> str:
    if periods == ("1d",) and not local_daily:
        return "1d"
    if periods == ("1w",):
        return "1w"
    if set(periods) <= set(RQDATA_ONLY_PERIODS) and not local_daily:
        return periods[0]
    return SOURCE_PERIOD


def _is_rqdata_direct_only(periods: tuple[str, ...]) -> bool:
    return bool(periods) and set(periods) <= set(RQDATA_ONLY_PERIODS)


def _segment_exchange(session: Session, *, product: str, contract: str, trade_date: date) -> str:
    gate = _parameter_gate(session, product=product, contract=contract, trade_date=trade_date)
    exchange = gate.get("exchange_code")
    if exchange:
        return str(exchange).upper()
    contract_meta = _contract_meta(session, contract)
    if contract_meta is not None and contract_meta.exchange_code:
        return str(contract_meta.exchange_code).upper()
    instrument_exchange = _instrument_exchange(session, product)
    if instrument_exchange:
        return str(instrument_exchange).upper()
    raise ActualContractBarsGateError(
        f"exchange_code unresolved for product={product}, contract={contract}, trade_date={trade_date}"
    )


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
    import hashlib

    raw = f"rq_acb_{product}_{contract}_{period}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_v1"
    if len(raw) <= 64:
        return raw
    digest = hashlib.sha256(raw.encode()).hexdigest()[:10]
    compact = f"rq_acb_{product}_{period}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_{digest}"
    return compact[:64]


def _raw_path(
    output_root: Path,
    *,
    product: str,
    contract: str,
    period: str,
    start_date: date,
    end_date: date,
) -> Path:
    normalized_period = period.strip().lower()
    return (
        output_root
        / "raw"
        / PROVIDER
        / "actual_contract_bars"
        / f"product={product}"
        / f"contract={contract}"
        / f"frequency={normalized_period}"
        / f"{contract}_{normalized_period}_raw_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet"
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
