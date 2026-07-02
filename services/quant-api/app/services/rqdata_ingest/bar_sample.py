from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import os
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import duckdb
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.data_center import Contract, DataDownloadTask, DataQualityReport, DataSource, Exchange, Instrument, MarketDataFile, utc_now
from app.services.rqdata_ingest.parquet import sha256_file, write_parquet_atomic
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


PROVIDER = "rqdata"
RAW_DATA_TYPE = "contract_bars_raw"
CANONICAL_DATA_TYPE = "bars"
DATA_VERSION_PREFIX = "rqdata_sample_bars"
SUPPORTED_FREQUENCIES = {"1m", "60m", "1d"}
CREDENTIAL_MESSAGE = (
    "RQData credentials not configured. Set RQDATAC2_CONF, RQDATAC_CONF, "
    "RQDATA_LICENSE_KEY, or RQDATA_USERNAME/RQDATA_PASSWORD in environment variables."
)


class MissingRqDataCredentials(RuntimeError):
    """Raised when no RQData credential environment variables are present."""


class RqDataBarsClient(Protocol):
    def contract_bars(self, contract: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame: ...


@dataclass(frozen=True)
class BarQuality:
    status: str
    missing_bars: int
    duplicated_bars: int
    abnormal_price_count: int
    abnormal_volume_count: int
    abnormal_open_interest_count: int
    details: dict[str, Any]


@dataclass(frozen=True)
class RqDataBarSampleResult:
    raw_path: Path
    canonical_path: Path
    raw_rows: int
    canonical_rows: int
    data_version: str
    quality: BarQuality
    market_file_id: int
    task_no: str
    duckdb_summary: dict[str, Any]


def check_rqdata_credential_environment() -> dict[str, Any]:
    has_uri = bool(os.getenv("RQDATAC2_CONF") or os.getenv("RQDATAC_CONF"))
    has_license = bool(os.getenv("RQDATA_LICENSE_KEY"))
    has_username_password = bool(os.getenv("RQDATA_USERNAME") and os.getenv("RQDATA_PASSWORD"))
    configured = has_uri or has_license or has_username_password
    if not configured:
        raise MissingRqDataCredentials(CREDENTIAL_MESSAGE)
    return {
        "configured": True,
        "credential_sources": {
            "uri": has_uri,
            "license_key": has_license,
            "username_password": has_username_password,
        },
    }


def run_rqdata_bar_sample(
    *,
    session: Session,
    client: RqDataBarsClient,
    output_root: Path,
    symbol: str,
    contract: str,
    exchange: str,
    frequency: str,
    start_date: date,
    end_date: date,
) -> RqDataBarSampleResult:
    _validate_request(symbol=symbol, contract=contract, exchange=exchange, frequency=frequency, start_date=start_date, end_date=end_date)
    output_root.mkdir(parents=True, exist_ok=True)
    normalized_symbol = symbol.strip().lower()
    canonical_contract = _canonical_contract(contract)
    exchange_code = exchange.strip().upper()
    normalized_frequency = frequency.strip().lower()
    data_version = f"{DATA_VERSION_PREFIX}_{canonical_contract}_{normalized_frequency}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_v1"

    task = _start_task(
        session=session,
        symbol=normalized_symbol,
        contract=canonical_contract,
        frequency=normalized_frequency,
        start_date=start_date,
        end_date=end_date,
    )
    try:
        raw_frame = client.contract_bars(contract, start_date, end_date, normalized_frequency)
        if raw_frame.empty:
            raise ValueError(f"RQData returned no rows for {contract} {normalized_frequency} {start_date}..{end_date}")

        raw_path = _raw_path(output_root, contract=contract, frequency=normalized_frequency, start_date=start_date, end_date=end_date)
        write_parquet_atomic(raw_frame, raw_path)

        canonical_frame = normalize_bar_frame(
            raw_frame,
            symbol=normalized_symbol,
            contract=canonical_contract,
            source_contract=contract.strip().upper(),
            exchange=exchange_code,
            frequency=normalized_frequency,
            data_version=data_version,
        )
        quality = evaluate_bar_quality(canonical_frame, normalized_frequency)
        canonical_frame["quality_status"] = quality.status
        canonical_path = _canonical_path(
            output_root,
            symbol=normalized_symbol,
            contract=canonical_contract,
            exchange=exchange_code,
            frequency=normalized_frequency,
            start_date=start_date,
            end_date=end_date,
        )
        write_parquet_atomic(canonical_frame, canonical_path)

        _ensure_reference_rows(session, symbol=normalized_symbol, contract=canonical_contract, exchange=exchange_code)
        _record_raw_file(
            session=session,
            task=task,
            path=raw_path,
            symbol=normalized_symbol,
            contract=canonical_contract,
            frequency=normalized_frequency,
            start_time=as_datetime(start_date),
            end_time=as_datetime(end_date, end_of_day=True),
            row_count=len(raw_frame),
            data_version=data_version,
        )
        canonical_file = _record_canonical_file_and_quality(
            session=session,
            task=task,
            path=canonical_path,
            frame=canonical_frame,
            quality=quality,
            symbol=normalized_symbol,
            contract=canonical_contract,
            frequency=normalized_frequency,
            data_version=data_version,
        )
        task.status = "success"
        task.progress = 100
        task.finished_at = utc_now()
        task.result = {
            "raw_file": str(raw_path),
            "canonical_file": str(canonical_path),
            "row_count": len(canonical_frame),
            "quality_status": quality.status,
        }
        session.flush()
        return RqDataBarSampleResult(
            raw_path=raw_path,
            canonical_path=canonical_path,
            raw_rows=len(raw_frame),
            canonical_rows=len(canonical_frame),
            data_version=data_version,
            quality=quality,
            market_file_id=canonical_file.id,
            task_no=task.task_no,
            duckdb_summary=duckdb_bar_summary(canonical_path),
        )
    except Exception as exc:
        task.status = "failed"
        task.progress = 0
        task.error_message = str(exc)
        task.finished_at = utc_now()
        task.result = {"error": str(exc)}
        session.flush()
        raise


def normalize_bar_frame(
    raw_frame: pd.DataFrame,
    *,
    symbol: str,
    contract: str,
    source_contract: str,
    exchange: str,
    frequency: str,
    data_version: str,
) -> pd.DataFrame:
    raw = raw_frame.copy()
    datetimes = _datetime_series(raw)
    open_interest = _numeric(raw, "open_interest", "open_oi", "close_oi", default=0.0)
    turnover = _numeric(raw, "turnover", "total_turnover", "amount", default=0.0)
    frame = pd.DataFrame(
        {
            "symbol": symbol,
            "contract": contract,
            "exchange": exchange,
            "vt_symbol": f"{contract}.{exchange}",
            "datetime": datetimes,
            "open": _numeric(raw, "open"),
            "high": _numeric(raw, "high"),
            "low": _numeric(raw, "low"),
            "close": _numeric(raw, "close"),
            "volume": _numeric(raw, "volume", default=0.0),
            "turnover": turnover,
            "open_interest": open_interest,
        }
    )
    frame = frame.dropna(subset=["datetime", "open", "high", "low", "close"]).sort_values("datetime").reset_index(drop=True)
    frame["trading_day"] = frame["datetime"].map(_trading_day)
    frame["interval"] = frequency
    frame["period"] = frequency
    frame["source"] = PROVIDER
    frame["provider"] = PROVIDER
    frame["data_role"] = "primary"
    frame["quality_status"] = "unchecked"
    frame["data_version"] = data_version
    frame["source_contract"] = source_contract
    frame["created_at"] = utc_now()
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
            "data_role",
            "quality_status",
            "data_version",
            "source_contract",
            "created_at",
        ]
    ]


def evaluate_bar_quality(frame: pd.DataFrame, frequency: str) -> BarQuality:
    if frame.empty:
        return BarQuality(
            status="failed",
            missing_bars=0,
            duplicated_bars=0,
            abnormal_price_count=0,
            abnormal_volume_count=0,
            abnormal_open_interest_count=0,
            details={
                "check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION,
                "empty": True,
                "gap_count": 0,
                "gap_samples": [],
                "duplicate_samples": [],
                "abnormal_price_samples": [],
                "abnormal_volume_samples": [],
                "abnormal_open_interest_samples": [],
            },
        )
    sorted_frame = frame.sort_values("datetime")
    duplicated_mask = sorted_frame["datetime"].duplicated()
    abnormal_price_mask = (sorted_frame["high"] < sorted_frame[["open", "close", "low"]].max(axis=1)) | (
        sorted_frame["low"] > sorted_frame[["open", "close", "high"]].min(axis=1)
    )
    abnormal_volume_mask = sorted_frame["volume"] < 0
    abnormal_open_interest_mask = sorted_frame["open_interest"].notna() & (sorted_frame["open_interest"] < 0)
    missing_bars, gap_samples = _missing_bars(sorted_frame, frequency)
    abnormal_price_count = int(abnormal_price_mask.sum())
    abnormal_volume_count = int(abnormal_volume_mask.sum())
    abnormal_open_interest_count = int(abnormal_open_interest_mask.sum())
    failed_count = abnormal_price_count + abnormal_volume_count + abnormal_open_interest_count
    warning_count = int(duplicated_mask.sum()) + missing_bars
    status = "failed" if failed_count > 0 else "warning" if warning_count > 0 else "passed"
    return BarQuality(
        status=status,
        missing_bars=missing_bars,
        duplicated_bars=int(duplicated_mask.sum()),
        abnormal_price_count=abnormal_price_count,
        abnormal_volume_count=abnormal_volume_count,
        abnormal_open_interest_count=abnormal_open_interest_count,
        details={
            "check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION,
            "empty": False,
            "gap_count": len(gap_samples),
            "gap_samples": gap_samples,
            "duplicate_samples": _datetime_samples(sorted_frame.loc[duplicated_mask, "datetime"]),
            "abnormal_price_samples": _datetime_samples(sorted_frame.loc[abnormal_price_mask, "datetime"]),
            "abnormal_volume_samples": _datetime_samples(sorted_frame.loc[abnormal_volume_mask, "datetime"]),
            "abnormal_open_interest_count": abnormal_open_interest_count,
            "abnormal_open_interest_samples": _datetime_samples(sorted_frame.loc[abnormal_open_interest_mask, "datetime"]),
        },
    )


def duckdb_bar_summary(path: Path) -> dict[str, Any]:
    with duckdb.connect(database=":memory:") as connection:
        row = connection.execute(
            """
            select
                count(*) as row_count,
                min(datetime) as start_time,
                max(datetime) as end_time,
                min(close) as min_close,
                max(close) as max_close
            from read_parquet(?)
            """,
            [str(path)],
        ).fetchone()
    return {
        "row_count": int(row[0]),
        "start_time": row[1].isoformat() if row[1] else None,
        "end_time": row[2].isoformat() if row[2] else None,
        "min_close": None if row[3] is None else float(row[3]),
        "max_close": None if row[4] is None else float(row[4]),
    }


def as_datetime(value: date, *, end_of_day: bool = False) -> datetime:
    return datetime.combine(value, time.max if end_of_day else time.min, tzinfo=UTC)


def _validate_request(*, symbol: str, contract: str, exchange: str, frequency: str, start_date: date, end_date: date) -> None:
    if not symbol.strip() or not contract.strip() or not exchange.strip():
        raise ValueError("symbol, contract, and exchange are required")
    normalized_frequency = frequency.strip().lower()
    if normalized_frequency not in SUPPORTED_FREQUENCIES:
        raise ValueError(f"unsupported sample frequency: {frequency}; expected one of {sorted(SUPPORTED_FREQUENCIES)}")
    if end_date < start_date:
        raise ValueError("end date must be greater than or equal to start date")
    if (end_date - start_date).days > 93:
        raise ValueError("RQData sample range is limited to 93 days")


def _start_task(
    *,
    session: Session,
    symbol: str,
    contract: str,
    frequency: str,
    start_date: date,
    end_date: date,
) -> DataDownloadTask:
    task = DataDownloadTask(
        task_no=f"rqdata-sample-{uuid4().hex[:12]}",
        provider=PROVIDER,
        data_type=CANONICAL_DATA_TYPE,
        instrument_symbol=symbol,
        contract_code=contract,
        period=frequency,
        start_time=as_datetime(start_date),
        end_time=as_datetime(end_date, end_of_day=True),
        status="running",
        progress=0,
        result={"sample_acceptance": True},
        started_at=utc_now(),
    )
    session.add(task)
    session.flush()
    return task


def _record_raw_file(
    *,
    session: Session,
    task: DataDownloadTask,
    path: Path,
    symbol: str,
    contract: str,
    frequency: str,
    start_time: datetime,
    end_time: datetime,
    row_count: int,
    data_version: str,
) -> MarketDataFile:
    market_file = _upsert_market_file(
        session=session,
        provider=PROVIDER,
        data_type=RAW_DATA_TYPE,
        symbol=symbol,
        contract=contract,
        frequency=frequency,
        start_time=start_time,
        end_time=end_time,
        data_version=data_version,
    )
    _fill_market_file(task=task, market_file=market_file, path=path, row_count=row_count, quality_status="passed", data_role="candidate")
    return market_file


def _record_canonical_file_and_quality(
    *,
    session: Session,
    task: DataDownloadTask,
    path: Path,
    frame: pd.DataFrame,
    quality: BarQuality,
    symbol: str,
    contract: str,
    frequency: str,
    data_version: str,
) -> MarketDataFile:
    start_time = _timestamp_to_utc(frame["datetime"].min())
    end_time = _timestamp_to_utc(frame["datetime"].max())
    market_file = _upsert_market_file(
        session=session,
        provider=PROVIDER,
        data_type=CANONICAL_DATA_TYPE,
        symbol=symbol,
        contract=contract,
        frequency=frequency,
        start_time=start_time,
        end_time=end_time,
        data_version=data_version,
    )
    _fill_market_file(task=task, market_file=market_file, path=path, row_count=len(frame), quality_status=quality.status, data_role="primary")
    session.flush()
    session.execute(delete(DataQualityReport).where(DataQualityReport.file_id == market_file.id))
    session.add(
        DataQualityReport(
            file_id=market_file.id,
            task_id=task.id,
            provider=PROVIDER,
            data_type=CANONICAL_DATA_TYPE,
            instrument_symbol=symbol,
            contract_code=contract,
            period=frequency,
            start_time=start_time,
            end_time=end_time,
            status=quality.status,
            missing_bars=quality.missing_bars,
            duplicated_bars=quality.duplicated_bars,
            abnormal_price_count=quality.abnormal_price_count,
            abnormal_volume_count=quality.abnormal_volume_count,
            details={
                **quality.details,
                "data_layer": "canonical",
                "source": PROVIDER,
                "rows": len(frame),
                "columns": list(frame.columns),
            },
        )
    )
    session.flush()
    return market_file


def _upsert_market_file(
    *,
    session: Session,
    provider: str,
    data_type: str,
    symbol: str,
    contract: str,
    frequency: str,
    start_time: datetime,
    end_time: datetime,
    data_version: str,
) -> MarketDataFile:
    market_file = session.scalar(
        select(MarketDataFile).where(
            MarketDataFile.provider == provider,
            MarketDataFile.data_type == data_type,
            MarketDataFile.instrument_symbol == symbol,
            MarketDataFile.contract_code == contract,
            MarketDataFile.period == frequency,
            MarketDataFile.start_time == start_time,
            MarketDataFile.end_time == end_time,
            MarketDataFile.data_version == data_version,
        )
    )
    if market_file is None:
        market_file = MarketDataFile(
            provider=provider,
            data_type=data_type,
            instrument_symbol=symbol,
            contract_code=contract,
            period=frequency,
            start_time=start_time,
            end_time=end_time,
            data_version=data_version,
        )
        session.add(market_file)
    return market_file


def _fill_market_file(
    *,
    task: DataDownloadTask,
    market_file: MarketDataFile,
    path: Path,
    row_count: int,
    quality_status: str,
    data_role: str,
) -> None:
    market_file.task_id = task.id
    market_file.file_path = str(path)
    market_file.row_count = row_count
    market_file.file_size_bytes = path.stat().st_size if path.exists() else None
    market_file.checksum = sha256_file(path) if path.exists() else None
    market_file.quality_status = quality_status
    market_file.data_role = data_role


def _ensure_reference_rows(session: Session, *, symbol: str, contract: str, exchange: str) -> None:
    source = session.scalar(select(DataSource).where(DataSource.provider == PROVIDER))
    if source is None:
        session.add(
            DataSource(
                name="RQData",
                provider=PROVIDER,
                status="enabled",
                priority=5,
                config={"credential_env": ["RQDATAC2_CONF", "RQDATAC_CONF", "RQDATA_LICENSE_KEY", "RQDATA_USERNAME", "RQDATA_PASSWORD"]},
                remark="V1 primary historical data source; credentials are read from environment variables only.",
            )
        )
    else:
        source.status = "enabled"
        source.priority = min(source.priority, 5)
        source.config = {**(source.config or {}), "storage": "parquet", "sample_acceptance": True}
    if session.scalar(select(Exchange).where(Exchange.code == exchange)) is None:
        session.add(Exchange(code=exchange, name=exchange, country="CN"))
    if session.scalar(select(Instrument).where(Instrument.symbol == symbol)) is None:
        session.add(Instrument(symbol=symbol, name=symbol, exchange_code=exchange, category="future", is_active=True))
    if session.scalar(select(Contract).where(Contract.contract_code == contract)) is None:
        session.add(Contract(contract_code=contract, instrument_symbol=symbol, exchange_code=exchange, name=contract, status="sample", raw_symbol=contract.upper(), provider=PROVIDER))


def _raw_path(output_root: Path, *, contract: str, frequency: str, start_date: date, end_date: date) -> Path:
    return (
        output_root
        / "raw"
        / PROVIDER
        / "contract_bars"
        / f"contract={contract.strip().upper()}"
        / f"frequency={frequency}"
        / f"{contract.strip().upper()}_{frequency}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet"
    )


def _canonical_path(output_root: Path, *, symbol: str, contract: str, exchange: str, frequency: str, start_date: date, end_date: date) -> Path:
    return (
        output_root
        / "parquet"
        / "canonical"
        / "bars"
        / f"provider={PROVIDER}"
        / f"period={frequency}"
        / f"exchange={exchange}"
        / f"symbol={symbol}"
        / f"contract={contract}"
        / f"{contract}_{frequency}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet"
    )


def _datetime_series(frame: pd.DataFrame) -> pd.Series:
    for column in ("datetime", "date", "trading_date", "index"):
        if column in frame.columns:
            values = pd.to_datetime(frame[column], errors="coerce")
            if values.notna().any():
                return values
    index_values = pd.to_datetime(frame.index, errors="coerce")
    if index_values.notna().any():
        return pd.Series(index_values, index=frame.index)
    raise ValueError("RQData bar frame does not contain a datetime-like column or index")


def _numeric(frame: pd.DataFrame, *columns: str, default: float | None = None) -> pd.Series:
    for column in columns:
        if column in frame.columns:
            return pd.to_numeric(frame[column], errors="coerce").astype("float64")
    if default is not None:
        return pd.Series([default] * len(frame), index=frame.index, dtype="float64")
    raise ValueError(f"RQData bar frame missing required numeric column; tried {list(columns)}")


def _missing_bars(frame: pd.DataFrame, frequency: str) -> tuple[int, list[dict[str, Any]]]:
    expected_delta = _frequency_delta(frequency)
    unique_times = list(frame["datetime"].drop_duplicates().sort_values())
    missing = 0
    samples: list[dict[str, Any]] = []
    for previous, current in zip(unique_times, unique_times[1:], strict=False):
        diff = current.to_pydatetime() - previous.to_pydatetime()
        if diff <= expected_delta:
            continue
        missing_for_gap = int(diff / expected_delta) - 1
        missing += missing_for_gap
        if len(samples) < 10:
            samples.append({"from": previous.isoformat(), "to": current.isoformat(), "missing_bars": missing_for_gap})
    return missing, samples


def _frequency_delta(frequency: str) -> timedelta:
    normalized = frequency.strip().lower()
    if normalized == "1m":
        return timedelta(minutes=1)
    if normalized == "60m":
        return timedelta(minutes=60)
    if normalized == "1d":
        return timedelta(days=1)
    raise ValueError(f"unsupported sample frequency: {frequency}")


def _datetime_samples(values: pd.Series) -> list[str]:
    return [value.isoformat() for value in values.head(10)]


def _trading_day(value: pd.Timestamp) -> date:
    if value.hour >= 21:
        return (value + pd.Timedelta(days=1)).date()
    return value.date()


def _timestamp_to_utc(value: Any) -> datetime:
    timestamp = pd.to_datetime(value).to_pydatetime()
    return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)


def _canonical_contract(contract: str) -> str:
    return contract.strip().lower()
