from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app.models.data_center import utc_now
from app.services.rqdata_ingest.bar_sample import BarQuality, abnormal_ohlc_mask
from app.services.rqdata_ingest.parquet import sha256_file, write_parquet_atomic


SYMBOL = "jm"
EXCHANGE = "DCE"
CONTRACT = "jm.MAIN"
PRODUCT = "JM"
FORMAL_START = date(2023, 1, 3)


def build_jm_v2_parquet_assets(
    *,
    client: Any,
    output_root: Path,
    start_date: date,
    end_date: date,
    periods: tuple[str, ...] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from app.services.rqdata_ingest.dominant_v2_parquet import PERIODS, build_dominant_v2_parquet_assets

    selected_periods = periods if periods is not None else PERIODS
    result = build_dominant_v2_parquet_assets(
        client=client,
        output_root=output_root,
        product=SYMBOL,
        exchange=EXCHANGE,
        start_date=start_date,
        end_date=end_date,
        periods=selected_periods,
        force=force,
    )
    return {
        **result,
        "mode": "jm-v2-parquet",
        "symbol": SYMBOL,
        "contract": CONTRACT,
        "exchange": EXCHANGE,
    }


def _load_or_download_raw(
    *,
    client: Any,
    path: Path,
    period: str,
    start_date: date,
    end_date: date,
    force: bool,
) -> pd.DataFrame:
    if path.exists() and not force:
        return pd.read_parquet(path)
    frame = _download_dominant_raw(client=client, period=period, start_date=start_date, end_date=end_date)
    write_parquet_atomic(frame, path)
    return frame


def _download_dominant_raw(*, client: Any, period: str, start_date: date, end_date: date) -> pd.DataFrame:
    rq_product = client.underlying_symbol(PRODUCT)
    dominant = client.dominant_contracts(rq_product, start_date, end_date, rank=1)
    dominant_records = _dominant_contract_records(dominant)
    if not dominant_records:
        raise ValueError(f"RQData returned no JM dominant contract mapping for {start_date}..{end_date}")
    frames: list[pd.DataFrame] = []
    for segment in _contract_segments(dominant_records, start_date=start_date, end_date=end_date):
        frame = client.contract_bars(segment["rqdata_order_book_id"], segment["start_date"], segment["end_date"], period)
        if frame.empty:
            continue
        raw = frame.copy()
        if not any(column in raw.columns for column in ("datetime", "date", "trading_date", "index")):
            raw["index"] = raw.index
        raw["rqdata_product"] = rq_product
        raw["rqdata_order_book_id"] = segment["rqdata_order_book_id"]
        raw["project_contract"] = segment["project_contract"]
        raw["exchange"] = EXCHANGE
        raw["frequency"] = period
        raw["segment_start"] = segment["start_date"].isoformat()
        raw["segment_end"] = segment["end_date"].isoformat()
        frames.append(raw)
    if not frames:
        raise ValueError(f"RQData returned no JM raw rows for {period} {start_date}..{end_date}")
    output = pd.concat(frames, ignore_index=True)
    output["datetime"] = _raw_datetime_series(output)
    return output.sort_values(["datetime", "rqdata_order_book_id"]).reset_index(drop=True)


def normalize_jm_dominant_raw_frame(
    raw_frame: pd.DataFrame,
    *,
    symbol: str,
    exchange: str,
    interval: str,
    data_version: str,
) -> pd.DataFrame:
    raw = raw_frame.copy()
    datetimes = _raw_datetime_series(raw)
    source_symbol = raw.get("rqdata_order_book_id", raw.get("order_book_id", raw.get("project_contract")))
    if source_symbol is None:
        raise ValueError("JM raw frame missing source contract column")
    source_symbol = source_symbol.astype(str).str.lower()
    contract = f"{symbol}.MAIN"
    frame = pd.DataFrame(
        {
            "symbol": symbol,
            "contract": contract,
            "exchange": exchange,
            "vt_symbol": f"{contract}.{exchange}",
            "datetime": datetimes,
            "trading_day": _trading_day_series(raw, datetimes),
            "interval": interval,
            "period": interval,
            "open": _numeric_series(raw, "open"),
            "high": _numeric_series(raw, "high"),
            "low": _numeric_series(raw, "low"),
            "close": _numeric_series(raw, "close"),
            "volume": _numeric_series(raw, "volume", default=0.0),
            "turnover": _numeric_series(raw, "turnover", "total_turnover", "amount", default=0.0),
            "open_interest": _numeric_series(raw, "open_interest", "open_oi", "close_oi", default=0.0),
            "source": "rqdata",
            "provider": "rqdata",
            "source_symbol": source_symbol,
            "data_role": "primary",
            "quality_status": "unchecked",
            "data_version": data_version,
            "created_at": utc_now(),
        }
    )
    frame = frame.dropna(subset=["datetime", "open", "high", "low", "close"]).sort_values("datetime").reset_index(drop=True)
    return frame[
        [
            "symbol",
            "contract",
            "exchange",
            "vt_symbol",
            "datetime",
            "trading_day",
            "interval",
            "period",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "open_interest",
            "source",
            "provider",
            "source_symbol",
            "data_role",
            "quality_status",
            "data_version",
            "created_at",
        ]
    ]


def evaluate_standard_dominant_quality(frame: pd.DataFrame, interval: str) -> BarQuality:
    sorted_frame = frame.sort_values("datetime")
    duplicated_mask = sorted_frame.duplicated(subset=["datetime"])
    abnormal_price_mask = abnormal_ohlc_mask(sorted_frame)
    abnormal_volume_mask = sorted_frame["volume"] < 0
    abnormal_open_interest_mask = sorted_frame["open_interest"].notna() & (sorted_frame["open_interest"] < 0)
    gap_samples = _gap_samples(sorted_frame, interval)
    abnormal_price_count = int(abnormal_price_mask.sum())
    abnormal_volume_count = int(abnormal_volume_mask.sum())
    abnormal_open_interest_count = int(abnormal_open_interest_mask.sum())
    duplicate_count = int(duplicated_mask.sum())
    failed_count = abnormal_price_count + abnormal_volume_count + abnormal_open_interest_count + duplicate_count
    status = "failed" if failed_count > 0 else "passed"
    return BarQuality(
        status=status,
        missing_bars=0,
        duplicated_bars=duplicate_count,
        abnormal_price_count=abnormal_price_count,
        abnormal_volume_count=abnormal_volume_count,
        abnormal_open_interest_count=abnormal_open_interest_count,
        details={
            "check_rule_version": "rqdata_jm_v2_direct_bars_v1",
            "check_mode": "dominant_raw_to_standard_without_session_calendar",
            "empty": bool(sorted_frame.empty),
            "missing_bars": 0,
            "missing_bar_note": "Trading-session calendar is not applied; natural lunch, night, holiday and weekend gaps are reported as gap_samples only.",
            "gap_count": len(gap_samples),
            "gap_samples": gap_samples[:20],
            "duplicate_samples": _datetime_samples(sorted_frame.loc[duplicated_mask, "datetime"]),
            "abnormal_price_samples": _datetime_samples(sorted_frame.loc[abnormal_price_mask, "datetime"]),
            "abnormal_volume_samples": _datetime_samples(sorted_frame.loc[abnormal_volume_mask, "datetime"]),
            "abnormal_open_interest_count": abnormal_open_interest_count,
            "abnormal_open_interest_samples": _datetime_samples(sorted_frame.loc[abnormal_open_interest_mask, "datetime"]),
            "datetime_timezone": "naive_local_exchange_time",
            "trading_day_source": "rqdata_trading_date_or_exchange_day_roll",
            "source_contracts": sorted(sorted_frame["source_symbol"].dropna().unique().tolist()),
        },
    )


def _filter_by_datetime(frame: pd.DataFrame, *, start_date: date, end_date: date) -> pd.DataFrame:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    return data[(data["datetime"] >= start) & (data["datetime"] <= end)].reset_index(drop=True)


def _data_version(period: str, start_date: date, end_date: date) -> str:
    return f"rqdata_jm_standard_{period}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_v2"


def _raw_path(output_root: Path, *, period: str, start_date: date, end_date: date) -> Path:
    return (
        output_root
        / "raw"
        / "rqdata"
        / "dominant_contract_bars"
        / "product=jm"
        / f"frequency={period}"
        / "version=v2"
        / f"jm_{period}_dominant_raw_{start_date:%Y%m%d}_{end_date:%Y%m%d}_v2.parquet"
    )


def _standard_path(output_root: Path, *, period: str, start_date: date, end_date: date) -> Path:
    return (
        output_root
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / f"period={period}"
        / "exchange=DCE"
        / "symbol=jm"
        / "contract=jm.MAIN"
        / f"jm_MAIN_{period}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_v2.parquet"
    )


def _file_summary(path: Path, frame: pd.DataFrame) -> dict[str, Any]:
    datetimes = pd.to_datetime(frame["datetime"], errors="coerce")
    return {
        "path": str(path),
        "row_count": len(frame),
        "min_datetime": datetimes.min().to_pydatetime().isoformat(),
        "max_datetime": datetimes.max().to_pydatetime().isoformat(),
        "checksum": sha256_file(path),
    }


def _dominant_contract_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
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


def _contract_segments(records: list[dict[str, Any]], *, start_date: date, end_date: date) -> list[dict[str, Any]]:
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
    for value in record.values():
        if value is not None and not pd.isna(value) and str(value).strip().upper().startswith("JM"):
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


def _trading_day_series(raw: pd.DataFrame, datetimes: pd.Series) -> pd.Series:
    if "trading_date" in raw.columns:
        values = pd.to_datetime(raw["trading_date"], errors="coerce")
        if values.notna().any():
            return values.dt.date
    return pd.to_datetime(datetimes, errors="coerce").map(lambda value: (value + pd.Timedelta(days=1)).date() if value.hour >= 21 else value.date())


def _numeric_series(frame: pd.DataFrame, *columns: str, default: float | None = None) -> pd.Series:
    for column in columns:
        if column in frame.columns:
            return pd.to_numeric(frame[column], errors="coerce").astype("float64")
    if default is not None:
        return pd.Series([default] * len(frame), index=frame.index, dtype="float64")
    raise ValueError(f"JM raw frame missing required numeric column; tried {list(columns)}")


def _gap_samples(frame: pd.DataFrame, interval: str) -> list[dict[str, Any]]:
    expected_delta = _frequency_delta(interval)
    unique_times = list(pd.to_datetime(frame["datetime"]).drop_duplicates().sort_values())
    samples: list[dict[str, Any]] = []
    for previous, current in zip(unique_times, unique_times[1:], strict=False):
        diff = current.to_pydatetime() - previous.to_pydatetime()
        if diff <= expected_delta:
            continue
        if len(samples) < 50:
            samples.append(
                {
                    "from": previous.isoformat(),
                    "to": current.isoformat(),
                    "gap_seconds": int(diff.total_seconds()),
                    "expected_seconds": int(expected_delta.total_seconds()),
                }
            )
    return samples


def _frequency_delta(interval: str) -> pd.Timedelta:
    normalized = interval.strip().lower()
    if normalized == "1m":
        return pd.Timedelta(minutes=1)
    if normalized == "5m":
        return pd.Timedelta(minutes=5)
    if normalized == "15m":
        return pd.Timedelta(minutes=15)
    if normalized == "30m":
        return pd.Timedelta(minutes=30)
    if normalized == "60m":
        return pd.Timedelta(minutes=60)
    if normalized == "1d":
        return pd.Timedelta(days=1)
    if normalized == "1w":
        return pd.Timedelta(weeks=1)
    raise ValueError(f"unsupported interval: {interval}")


def _datetime_samples(values: pd.Series) -> list[str]:
    return [value.isoformat() for value in values.head(10)]
