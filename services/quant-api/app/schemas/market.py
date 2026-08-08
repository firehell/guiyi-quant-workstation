from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class MarketBarOut(BaseModel):
    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None


class CoverageOut(BaseModel):
    start: datetime
    end: datetime


class PartitionDigestOut(BaseModel):
    dataset: dict[str, str]
    year: int
    month: int
    checksum: str
    manifest_digest: str


class ContractSegmentOut(BaseModel):
    contract: str
    start_trading_day: date
    end_trading_day: date


class MarketBarsResponse(BaseModel):
    request: dict[str, object]
    bars: list[MarketBarOut]
    coverage: CoverageOut | None
    partition_digests: list[PartitionDigestOut]
    resolved_contract_segments: list[ContractSegmentOut]
    main_map_digest: str | None


class DominantContractOut(BaseModel):
    product: str
    product_name: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date


class DominantContractListResponse(BaseModel):
    items: list[DominantContractOut]


class DatasetCoverageOut(BaseModel):
    kind: str
    symbol: str
    series_or_contract: str
    frequency: str
    start: datetime
    end: datetime
    row_count: int
    partition_count: int


class MarketCoverageResponse(BaseModel):
    items: list[DatasetCoverageOut]
