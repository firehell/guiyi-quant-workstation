from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.rqdata_ingest.bar_aggregation import (
    AGGREGATED_PERIODS,
    RQDATA_DIRECT_PERIODS,
    SOURCE_PERIOD,
    aggregate_standard_bars,
)
from app.services.rqdata_ingest.jm_v2_parquet import (
    evaluate_standard_dominant_quality,
    normalize_jm_dominant_raw_frame,
)
from app.services.rqdata_ingest.parquet import sha256_file, write_parquet_atomic

FORMAL_START = date(2023, 1, 3)
PERIODS = (*RQDATA_DIRECT_PERIODS, *AGGREGATED_PERIODS)


def build_dominant_v2_parquet_assets(
    *,
    client: Any,
    output_root: Path,
    product: str,
    exchange: str,
    start_date: date,
    end_date: date,
    periods: tuple[str, ...] = PERIODS,
    force: bool = False,
) -> dict[str, Any]:
    symbol = _normalize_product(product)
    contract = f"{symbol}.MAIN"
    exchange_code = str(exchange or "DCE").upper()
    if end_date < start_date:
        raise ValueError("end_date must be greater than or equal to start_date")
    output_root = output_root.resolve()

    normalized_periods = _normalize_periods(periods)
    summaries: dict[str, Any] = {}
    one_minute_standard: pd.DataFrame | None = None

    needs_1m_source = SOURCE_PERIOD in normalized_periods or any(
        period in AGGREGATED_PERIODS for period in normalized_periods
    )
    if needs_1m_source:
        one_minute_standard, one_minute_summary = _build_direct_dominant_period(
            client=client,
            output_root=output_root,
            symbol=symbol,
            contract=contract,
            exchange_code=exchange_code,
            period=SOURCE_PERIOD,
            start_date=start_date,
            end_date=end_date,
            force=force,
        )
        if SOURCE_PERIOD in normalized_periods:
            summaries[SOURCE_PERIOD] = one_minute_summary

    for period in normalized_periods:
        if period == SOURCE_PERIOD:
            continue
        if period in AGGREGATED_PERIODS:
            if one_minute_standard is None:
                raise ValueError(f"missing 1m source frame required to aggregate {period}")
            summaries[period] = _build_aggregated_dominant_period(
                output_root=output_root,
                symbol=symbol,
                contract=contract,
                exchange_code=exchange_code,
                period=period,
                source_frame=one_minute_standard,
                start_date=start_date,
                end_date=end_date,
                force=force,
            )
            continue
        summaries[period] = _build_direct_dominant_period(
            client=client,
            output_root=output_root,
            symbol=symbol,
            contract=contract,
            exchange_code=exchange_code,
            period=period,
            start_date=start_date,
            end_date=end_date,
            force=force,
        )[1]

    return {
        "mode": "dominant-v2-parquet",
        "symbol": symbol,
        "contract": contract,
        "exchange": exchange_code,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "periods": summaries,
        "writes_database": False,
    }


def _build_direct_dominant_period(
    *,
    client: Any,
    output_root: Path,
    symbol: str,
    contract: str,
    exchange_code: str,
    period: str,
    start_date: date,
    end_date: date,
    force: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    data_version = _data_version(symbol, period, start_date, end_date)
    raw_path = _raw_path(output_root, symbol=symbol, period=period, start_date=start_date, end_date=end_date)
    standard_path = _standard_path(
        output_root,
        symbol=symbol,
        exchange=exchange_code,
        contract=contract,
        period=period,
        start_date=start_date,
        end_date=end_date,
    )
    raw_frame = _load_or_download_raw(
        client=client,
        path=raw_path,
        product=symbol,
        exchange=exchange_code,
        period=period,
        start_date=start_date,
        end_date=end_date,
        force=force,
    )
    standard_frame = normalize_jm_dominant_raw_frame(
        raw_frame,
        symbol=symbol,
        exchange=exchange_code,
        interval=period,
        data_version=data_version,
    )
    standard_frame = _filter_by_datetime(standard_frame, start_date=start_date, end_date=end_date)
    if standard_frame.empty:
        raise ValueError(f"{symbol} {period} standard frame is empty after filtering {start_date}..{end_date}")
    quality = evaluate_standard_dominant_quality(standard_frame, period)
    standard_frame["quality_status"] = quality.status
    if standard_path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing dominant v2 standard parquet: {standard_path}")
    write_parquet_atomic(standard_frame, standard_path)
    summary = {
        "data_version": data_version,
        "quality_status": quality.status,
        "derivation_mode": "rqdata_direct",
        "raw": _file_summary(raw_path, raw_frame),
        "standard": _file_summary(standard_path, standard_frame),
        "quality": {
            "status": quality.status,
            "missing_bars": quality.missing_bars,
            "duplicated_bars": quality.duplicated_bars,
            "abnormal_price_count": quality.abnormal_price_count,
            "abnormal_volume_count": quality.abnormal_volume_count,
            "abnormal_open_interest_count": quality.abnormal_open_interest_count,
            "details": quality.details,
        },
    }
    return standard_frame, summary


def _build_aggregated_dominant_period(
    *,
    output_root: Path,
    symbol: str,
    contract: str,
    exchange_code: str,
    period: str,
    source_frame: pd.DataFrame,
    start_date: date,
    end_date: date,
    force: bool,
) -> dict[str, Any]:
    data_version = _data_version(symbol, period, start_date, end_date)
    standard_path = _standard_path(
        output_root,
        symbol=symbol,
        exchange=exchange_code,
        contract=contract,
        period=period,
        start_date=start_date,
        end_date=end_date,
    )
    standard_frame = aggregate_standard_bars(source_frame, period)
    standard_frame["data_version"] = data_version
    standard_frame = _filter_by_datetime(standard_frame, start_date=start_date, end_date=end_date)
    if standard_frame.empty:
        raise ValueError(f"{symbol} {period} aggregated frame is empty after filtering {start_date}..{end_date}")
    quality = evaluate_standard_dominant_quality(standard_frame, period)
    quality_details = {
        **quality.details,
        "derivation_mode": "aggregated_from_1m",
        "source_interval": SOURCE_PERIOD,
    }
    standard_frame["quality_status"] = quality.status
    if standard_path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing dominant v2 standard parquet: {standard_path}")
    write_parquet_atomic(standard_frame, standard_path)
    one_minute_raw_path = _raw_path(output_root, symbol=symbol, period=SOURCE_PERIOD, start_date=start_date, end_date=end_date)
    raw_summary = (
        _file_summary(one_minute_raw_path, pd.read_parquet(one_minute_raw_path))
        if one_minute_raw_path.exists()
        else {"path": str(one_minute_raw_path), "row_count": len(source_frame), "checksum": ""}
    )
    return {
        "data_version": data_version,
        "quality_status": quality.status,
        "derivation_mode": "aggregated_from_1m",
        "raw": raw_summary,
        "standard": _file_summary(standard_path, standard_frame),
        "quality": {
            "status": quality.status,
            "missing_bars": quality.missing_bars,
            "duplicated_bars": quality.duplicated_bars,
            "abnormal_price_count": quality.abnormal_price_count,
            "abnormal_volume_count": quality.abnormal_volume_count,
            "abnormal_open_interest_count": quality.abnormal_open_interest_count,
            "details": quality_details,
        },
    }


def _normalize_periods(periods: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(period.strip().lower() for period in periods if period.strip()))
    if not normalized:
        raise ValueError("at least one period is required")
    unsupported = sorted(set(normalized) - set(PERIODS))
    if unsupported:
        raise ValueError(f"unsupported dominant v2 period: {unsupported}")
    return normalized


def contract_segments_from_mapping(records: list[dict[str, Any]], *, start_date: date, end_date: date) -> list[dict[str, Any]]:
    if not records:
        return []
    segments: list[dict[str, Any]] = []
    current_contract = records[0]["rqdata_order_book_id"]
    current_start = max(records[0]["trade_date"], start_date)
    previous_date = records[0]["trade_date"]
    for record in records[1:]:
        trade_date = record["trade_date"]
        contract = record["rqdata_order_book_id"]
        if contract != current_contract:
            segments.append(_segment(current_contract, current_start, min(previous_date, end_date)))
            current_contract = contract
            current_start = max(trade_date, start_date)
        previous_date = trade_date
    segments.append(_segment(current_contract, current_start, min(previous_date, end_date)))
    return [item for item in segments if item["start_date"] <= item["end_date"]]


def dominant_contract_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    records: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        trade_date = _record_date(record)
        contract = _record_contract(record)
        if trade_date is None or not contract:
            continue
        records.append({"trade_date": trade_date, "rqdata_order_book_id": contract})
    return sorted(records, key=lambda item: item["trade_date"])


def _load_or_download_raw(
    *,
    client: Any,
    path: Path,
    product: str,
    exchange: str,
    period: str,
    start_date: date,
    end_date: date,
    force: bool,
) -> pd.DataFrame:
    if path.exists() and not force:
        return pd.read_parquet(path)
    if period in AGGREGATED_PERIODS:
        raise ValueError(f"refusing to download aggregated period {period} directly from RQData; use 1m source and local aggregation")
    frame = _download_dominant_raw(
        client=client,
        product=product,
        exchange=exchange,
        period=period,
        start_date=start_date,
        end_date=end_date,
    )
    write_parquet_atomic(frame, path)
    return frame


def _download_dominant_raw(*, client: Any, product: str, exchange: str, period: str, start_date: date, end_date: date) -> pd.DataFrame:
    rq_product = client.underlying_symbol(product)
    dominant = client.dominant_contracts(rq_product, start_date, end_date, rank=1)
    dominant_records = dominant_contract_records(dominant)
    if not dominant_records:
        raise ValueError(f"RQData returned no dominant contract mapping for {product} {start_date}..{end_date}")
    frames: list[pd.DataFrame] = []
    for segment in contract_segments_from_mapping(dominant_records, start_date=start_date, end_date=end_date):
        frame = client.contract_bars(segment["rqdata_order_book_id"], segment["start_date"], segment["end_date"], period)
        if frame.empty:
            continue
        raw = frame.copy()
        if not any(column in raw.columns for column in ("datetime", "date", "trading_date", "index")):
            raw["index"] = raw.index
        raw["rqdata_product"] = rq_product
        raw["rqdata_order_book_id"] = segment["rqdata_order_book_id"]
        raw["project_contract"] = segment["project_contract"]
        raw["exchange"] = exchange
        raw["frequency"] = period
        raw["segment_start"] = segment["start_date"].isoformat()
        raw["segment_end"] = segment["end_date"].isoformat()
        frames.append(raw)
    if not frames:
        raise ValueError(f"RQData returned no raw rows for {product} {period} {start_date}..{end_date}")
    output = pd.concat(frames, ignore_index=True)
    output["datetime"] = _raw_datetime_series(output)
    return output.sort_values(["datetime", "rqdata_order_book_id"]).reset_index(drop=True)


def _filter_by_datetime(frame: pd.DataFrame, *, start_date: date, end_date: date) -> pd.DataFrame:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    return data[(data["datetime"] >= start) & (data["datetime"] <= end)].reset_index(drop=True)


def _data_version(symbol: str, period: str, start_date: date, end_date: date) -> str:
    return f"rqdata_{symbol}_standard_{period}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_v2"


def _raw_path(output_root: Path, *, symbol: str, period: str, start_date: date, end_date: date) -> Path:
    return (
        output_root
        / "raw"
        / "rqdata"
        / "dominant_contract_bars"
        / f"product={symbol}"
        / f"frequency={period}"
        / "version=v2"
        / f"{symbol}_{period}_dominant_raw_{start_date:%Y%m%d}_{end_date:%Y%m%d}_v2.parquet"
    )


def _standard_path(
    output_root: Path,
    *,
    symbol: str,
    exchange: str,
    contract: str,
    period: str,
    start_date: date,
    end_date: date,
) -> Path:
    contract_file = contract.replace(".", "_")
    return (
        output_root
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / f"period={period}"
        / f"exchange={exchange}"
        / f"symbol={symbol}"
        / f"contract={contract}"
        / f"{contract_file}_{period}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_v2.parquet"
    )


def _file_summary(path: Path, frame: pd.DataFrame) -> dict[str, Any]:
    datetimes = pd.to_datetime(frame["datetime"], errors="coerce")
    checksum = sha256_file(path) if path.exists() else ""
    return {
        "path": str(path),
        "row_count": len(frame),
        "min_datetime": datetimes.min().to_pydatetime().isoformat(),
        "max_datetime": datetimes.max().to_pydatetime().isoformat(),
        "checksum": checksum,
    }


def _segment(contract: str, start_date: date, end_date: date) -> dict[str, Any]:
    return {
        "rqdata_order_book_id": contract,
        "project_contract": contract.lower(),
        "start_date": start_date,
        "end_date": end_date,
    }


def _record_date(record: dict[str, Any]) -> date | None:
    for key in ("date", "trade_date", "trading_date", "datetime", "index"):
        value = record.get(key)
        if value is None or pd.isna(value):
            continue
        try:
            return pd.to_datetime(value).date()
        except Exception:
            continue
    return None


def _record_contract(record: dict[str, Any]) -> str:
    for key in ("contract", "order_book_id", "dominant_id", "dominant", "symbol", "underlying_order_book_id"):
        value = record.get(key)
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value).strip().upper()
    return ""


def _raw_datetime_series(frame: pd.DataFrame) -> pd.Series:
    for column in ("datetime", "date", "trading_date", "index"):
        if column in frame.columns:
            values = pd.to_datetime(frame[column], errors="coerce")
            if values.notna().any():
                return values
    values = pd.to_datetime(frame.index, errors="coerce")
    if values.notna().any():
        return pd.Series(values, index=frame.index)
    raise ValueError("RQData raw frame does not contain a datetime-like column or index")


def _normalize_product(product: str) -> str:
    return str(product or "").strip().lower()
