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
    sector: str | None = None
    category: str | None = None
    is_active: bool = True
    continuous_contract: str
    actual_contract: str
    dominant_mapping_date: date
    bars_coverage: dict[str, DominantBarsCoveragePeriod] = {}
    quote_ready: bool = False
    default_period: str = "15m"


class DominantContractListResponse(BaseModel):
    items: list[DominantContractItem]
    default_quote_period: str = "15m"


class LiveTargetCoveragePeriod(BaseModel):
    available: bool = False
    provider: str | None = None
    data_type: str | None = None
    source_mode: str | None = None
    data_role: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    latest_bar_time: datetime | None = None
    row_count: int = 0
    quality_status: str = "missing"
    data_version: str | None = None
    file_path: str | None = None
    failed_count: int = 0
    rejected_count: int = 0


class LiveTargetContractItem(BaseModel):
    product: str
    continuous_contract: str
    actual_contract: str | None = None
    dominant_mapping_date: date | None = None
    provider: str
    data_role: str
    required_historical_periods: list[str]
    readiness_status: str
    blocked_reasons: list[str]
    trading_parameter_status: dict[str, Any]
    historical_coverage: dict[str, LiveTargetCoveragePeriod] = {}
    live_coverage: dict[str, LiveTargetCoveragePeriod] = {}
    preview_only: bool = True
    writes_strategy_signal: bool = False
    writes_signal_event: bool = False
    sends_notification: bool = False
    auto_order: bool = False


class LiveTargetContractsResponse(BaseModel):
    provider: str
    target_products: list[str]
    trade_date: date | None = None
    readiness_status: str
    preview_only: bool = True
    writes_strategy_signal: bool = False
    writes_signal_event: bool = False
    sends_notification: bool = False
    auto_order: bool = False
    items: list[LiveTargetContractItem]


class MarketCoveragePeriod(BaseModel):
    period: str
    provider: str
    data_type: str
    source_mode: str | None = None
    view_role: str = "unknown"
    continuous_contract: str | None = None
    actual_contract: str | None = None
    start_time: datetime
    end_time: datetime
    latest_bar_time: datetime | None = None
    row_count: int
    quality_status: str
    data_version: str | None = None
    data_role: str | None = None
    file_path: str | None = None


class MarketCoverageContract(BaseModel):
    contract: str
    name: str | None = None
    exchange: str | None = None
    provider: str | None = None
    status: str | None = None
    view_role: str = "unknown"
    continuous_contract: str | None = None
    actual_contract: str | None = None
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
    view_role: str = "unknown"
    continuous_contract: str | None = None
    actual_contract: str | None = None
    exchange: str | None = None
    name: str | None = None
    start_time: datetime
    end_time: datetime
    latest_bar_time: datetime | None = None
    row_count: int
    quality_status: str
    data_version: str | None = None
    data_role: str | None = None
    file_path: str | None = None


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
    view_role: str = "unknown"
    continuous_contract: str | None = None
    actual_contract: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    latest_bar_time: datetime | None = None
    row_count: int = 0
    quality_status: str = "unchecked"
    data_version: str | None = None
    data_role: str | None = None
    file_path: str | None = None


class MarketBarsRequest(BaseModel):
    symbol: str
    contract: str
    period: str
    start: datetime | None = None
    end: datetime | None = None
    provider: str | None = None
    data_role: str | None = None
    limit: int
    tail: bool = True


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
