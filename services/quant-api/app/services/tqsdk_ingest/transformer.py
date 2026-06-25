from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from app.services.tqsdk_ingest.products import ProductSpec

PROVIDER = "tqsdk"
PERIOD = "1m"
RAW_DATA_TYPE = "main_continuous_kline_raw"
CANONICAL_DATA_TYPE = "main_continuous_kline"


@dataclass(frozen=True)
class MonthChunk:
    start: date
    end: date

    @property
    def year(self) -> int:
        return self.start.year

    @property
    def month(self) -> int:
        return self.start.month

    @property
    def key_suffix(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def build_month_chunks(start: date, end: date) -> list[MonthChunk]:
    if end < start:
        raise ValueError("end date must be greater than or equal to start date")
    chunks: list[MonthChunk] = []
    cursor = start
    while cursor <= end:
        next_month = _first_day_next_month(cursor)
        chunk_end = min(end, next_month - timedelta(days=1))
        chunks.append(MonthChunk(start=cursor, end=chunk_end))
        cursor = next_month
    return chunks


def transform_downloader_csv(csv_path: Path, *, spec: ProductSpec, year: int, month: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(csv_path)
    if raw.empty:
        raise ValueError(f"empty TqSdk downloader csv: {csv_path}")
    prefix = spec.download_symbol
    required = [
        "datetime",
        "datetime_nano",
        f"{prefix}.open",
        f"{prefix}.high",
        f"{prefix}.low",
        f"{prefix}.close",
        f"{prefix}.volume",
        f"{prefix}.close_oi",
    ]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise ValueError(f"missing TqSdk downloader columns: {missing}")

    raw_frame = raw.copy()
    raw_frame["product"] = spec.product
    raw_frame["exchange"] = spec.exchange
    raw_frame["download_symbol"] = spec.download_symbol
    raw_frame["period"] = PERIOD
    raw_frame["provider"] = PROVIDER
    raw_frame["data_version"] = _raw_data_version(spec, year, month)
    raw_frame["created_at"] = _utc_now()

    datetimes = pd.to_datetime(raw[f"{prefix}.datetime"] if f"{prefix}.datetime" in raw.columns else raw["datetime"], errors="coerce")
    canonical = pd.DataFrame(
        {
            "symbol": spec.product,
            "contract": spec.contract_code,
            "exchange": spec.exchange,
            "datetime": datetimes,
            "open": pd.to_numeric(raw[f"{prefix}.open"], errors="coerce").astype("float64"),
            "high": pd.to_numeric(raw[f"{prefix}.high"], errors="coerce").astype("float64"),
            "low": pd.to_numeric(raw[f"{prefix}.low"], errors="coerce").astype("float64"),
            "close": pd.to_numeric(raw[f"{prefix}.close"], errors="coerce").astype("float64"),
            "volume": pd.to_numeric(raw[f"{prefix}.volume"], errors="coerce").fillna(0).astype("int64"),
            "open_interest": pd.to_numeric(raw[f"{prefix}.close_oi"], errors="coerce").astype("float64"),
            "turnover": pd.Series([pd.NA] * len(raw), dtype="Float64"),
        }
    )
    canonical = canonical.dropna(subset=["datetime", "open", "high", "low", "close"]).sort_values("datetime")
    canonical["trading_day"] = canonical["datetime"].map(_trading_day)
    canonical["period"] = PERIOD
    canonical["provider"] = PROVIDER
    canonical["source_contract"] = spec.download_symbol
    canonical["is_main_continuous"] = True
    canonical["data_version"] = _canonical_data_version(spec, year, month)
    canonical["created_at"] = _utc_now()
    canonical = canonical[
        [
            "symbol",
            "contract",
            "exchange",
            "datetime",
            "trading_day",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "open_interest",
            "turnover",
            "period",
            "provider",
            "source_contract",
            "is_main_continuous",
            "data_version",
            "created_at",
        ]
    ]
    return raw_frame, canonical


def raw_path(root: Path, spec: ProductSpec, year: int, month: int) -> Path:
    return (
        root
        / "raw"
        / PROVIDER
        / "main_continuous_1m"
        / f"product={spec.product}"
        / f"year={year:04d}"
        / f"month={month:02d}"
        / "part-000.parquet"
    )


def canonical_path(root: Path, spec: ProductSpec, year: int, month: int) -> Path:
    return (
        root
        / "parquet"
        / "canonical"
        / "bars"
        / f"provider={PROVIDER}"
        / f"period={PERIOD}"
        / f"exchange={spec.exchange}"
        / f"symbol={spec.product}"
        / f"contract={spec.contract_code}"
        / f"year={year:04d}"
        / f"month={month:02d}"
        / "part-000.parquet"
    )


def month_key(spec: ProductSpec, chunk: MonthChunk) -> str:
    return f"{spec.product}:{PERIOD}:{chunk.key_suffix}"


def as_datetime(value: date, *, end_of_day: bool = False) -> datetime:
    return datetime.combine(value, time.max if end_of_day else time.min, tzinfo=UTC)


def _first_day_next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _trading_day(value: pd.Timestamp) -> date:
    if value.hour >= 21:
        return (value + pd.Timedelta(days=1)).date()
    return value.date()


def _raw_data_version(spec: ProductSpec, year: int, month: int) -> str:
    return f"tqsdk_main_1m_{spec.product}_{year:04d}_{month:02d}_raw_v1"


def _canonical_data_version(spec: ProductSpec, year: int, month: int) -> str:
    return f"tqsdk_main_1m_{spec.product}_{year:04d}_{month:02d}_canonical_v1"


def _utc_now() -> datetime:
    return datetime.now(UTC)

