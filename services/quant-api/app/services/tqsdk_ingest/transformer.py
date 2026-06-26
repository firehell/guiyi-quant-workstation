from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from app.services.tqsdk_ingest.products import ProductSpec

PROVIDER = "tqsdk"
PERIOD = "1m"
RAW_DATA_TYPE = "main_continuous_kline_raw"
CANONICAL_DATA_TYPE = "main_continuous_kline"
DATA_VERSION = "tq_1m_v1"


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


def transform_downloader_csv(
    csv_path: Path,
    *,
    spec: ProductSpec,
    year: int,
    month: int,
    data_type: str = "main_continuous",
    source_symbol: str | None = None,
    contract_code: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(csv_path)
    if raw.empty:
        raise ValueError(f"empty TqSdk downloader csv: {csv_path}")
    prefix = source_symbol or spec.download_symbol
    contract = contract_code or spec.contract_code
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
    raw_frame["download_symbol"] = prefix
    raw_frame["source_symbol"] = prefix
    raw_frame["period"] = PERIOD
    raw_frame["provider"] = PROVIDER
    raw_frame["data_type"] = data_type
    raw_frame["data_version"] = DATA_VERSION
    raw_frame["created_at"] = _utc_now()

    datetimes = pd.to_datetime(raw[f"{prefix}.datetime"] if f"{prefix}.datetime" in raw.columns else raw["datetime"], errors="coerce")
    canonical = pd.DataFrame(
        {
            "symbol": spec.product,
            "contract": contract,
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
    canonical["data_type"] = data_type
    canonical["source_symbol"] = prefix
    canonical["source_contract"] = prefix
    canonical["is_main_continuous"] = data_type == "main_continuous"
    canonical["data_version"] = DATA_VERSION
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
            "data_type",
            "source_symbol",
            "source_contract",
            "is_main_continuous",
            "data_version",
            "created_at",
        ]
    ]
    return raw_frame, canonical


def raw_path(root: Path, spec: ProductSpec, year: int, month: int, *, data_type: str = "main_continuous", contract_code: str | None = None) -> Path:
    source_symbol = spec.download_symbol if data_type == "main_continuous" else contract_code or spec.contract_code
    layer = "main_continuous_1m" if data_type == "main_continuous" else "contract_1m"
    path = root / "raw" / PROVIDER / layer / f"exchange={spec.exchange}" / f"product={spec.product}"
    if data_type == "contract":
        path = path / f"contract={source_symbol}"
    return (
        path
        / f"year={year:04d}"
        / f"month={month:02d}"
        / f"{source_symbol}_{year:04d}_{month:02d}.parquet"
    )


def canonical_path(root: Path, spec: ProductSpec, year: int, month: int, *, data_type: str = "main_continuous", contract_code: str | None = None) -> Path:
    contract = contract_code or spec.contract_code
    return (
        root
        / "parquet"
        / "canonical"
        / "bars"
        / f"provider={PROVIDER}"
        / f"data_type={data_type}"
        / f"period={PERIOD}"
        / f"exchange={spec.exchange}"
        / f"symbol={spec.product}"
        / f"contract={contract}"
        / f"year={year:04d}"
        / f"month={month:02d}"
        / "part-000.parquet"
    )


def month_key(spec: ProductSpec, chunk: MonthChunk, *, data_type: str = "main_continuous", contract_code: str | None = None) -> str:
    subject = contract_code or spec.product
    return f"{subject}:{data_type}:{PERIOD}:{chunk.key_suffix}"


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


def _utc_now() -> datetime:
    return datetime.now(UTC)
