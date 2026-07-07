from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class DominantBarsCoveragePeriod(BaseModel):
    available: bool = False
    start_time: datetime | None = None
    end_time: datetime | None = None
    row_count: int = 0
    quality_status: str = "unchecked"


class DominantContractItem(BaseModel):
    product: str
    product_name: str
    exchange: str | None = None
    exchange_name: str | None = None
    continuous_contract: str
    actual_contract: str
    dominant_mapping_date: date
    bars_coverage: dict[str, DominantBarsCoveragePeriod] = {}
    quote_ready: bool = False
    default_period: str = "15m"


class DominantContractListResponse(BaseModel):
    items: list[DominantContractItem]
    default_quote_period: str = "15m"


class MarketCoveragePeriod(BaseModel):
    period: str
    provider: str
    data_type: str
    source_mode: str | None = None
    start_time: datetime
    end_time: datetime
    row_count: int
    quality_status: str


class MarketCoverageContract(BaseModel):
    contract: str
    name: str | None = None
    exchange: str | None = None
    provider: str | None = None
    status: str | None = None
    periods: list[MarketCoveragePeriod]


class MarketCoverageInstrument(BaseModel):
    symbol: str
    name: str | None = None
    exchange: str | None = None
    sector: str | None = None
    contracts: list[MarketCoverageContract]


class MarketCoverageItem(BaseModel):
    symbol: str
    contract: str
    period: str
    provider: str
    data_type: str
    source_mode: str | None = None
    exchange: str | None = None
    name: str | None = None
    start_time: datetime
    end_time: datetime
    row_count: int
    quality_status: str


class MarketWorkbenchSelection(BaseModel):
    symbol: str
    contract: str
    period: str
    provider: str | None = None
    start: datetime
    end: datetime


class MarketWorkbenchCoverage(BaseModel):
    instruments: list[MarketCoverageInstrument]
    items: list[MarketCoverageItem]
    default_selection: MarketWorkbenchSelection | None = None


class MarketBarsQuality(BaseModel):
    status: str
    missing_bars: int = 0
    duplicated_bars: int = 0
    abnormal_price_count: int = 0
    abnormal_volume_count: int = 0
    report_count: int = 0


class LiveMarketBarsQuality(BaseModel):
    status: str
    row_count: int = 0
    chart_row_count: int = 0
    passed_count: int = 0
    warning_count: int = 0
    failed_count: int = 0
    rejected_count: int = 0
    partial_count: int = 0


class MarketBarsCoverage(BaseModel):
    symbol: str
    contract: str
    period: str
    provider: str | None = None
    data_type: str | None = None
    source_mode: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    row_count: int = 0
    quality_status: str = "unchecked"


class MarketBarsRequest(BaseModel):
    symbol: str
    contract: str
    period: str
    start: datetime | None = None
    end: datetime | None = None
    provider: str | None = None
    data_role: str | None = None
    limit: int


class LiveMarketBarsRequest(BaseModel):
    symbol: str
    contract: str
    period: str
    start: datetime | None = None
    end: datetime | None = None
    provider: str | None = None
    source_mode: str | None = None
    limit: int


class MarketBarsResponse(BaseModel):
    bars: list[dict[str, Any]]
    quality: MarketBarsQuality
    coverage: MarketBarsCoverage | None = None
    request: MarketBarsRequest
    message: str | None = None


class LiveMarketBarsResponse(BaseModel):
    bars: list[dict[str, Any]]
    quality: LiveMarketBarsQuality
    coverage: MarketBarsCoverage | None = None
    request: LiveMarketBarsRequest
    message: str | None = None
