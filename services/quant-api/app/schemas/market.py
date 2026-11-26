"""Typed responses for the read-only Market API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


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
    source_bar_sha256: str | None = Field(None, exclude_if=lambda value: value is None)


class CoverageOut(BaseModel):
    start: datetime
    end: datetime


class ContractSegmentOut(BaseModel):
    contract: str
    start_trading_day: date
    end_trading_day: date


class MarketPageMetaOut(BaseModel):
    has_more_before: bool
    next_before: datetime | None


class MarketBarsPageResponse(BaseModel):
    request: dict[str, object]
    bars: list[MarketBarOut]
    canonical_coverage: CoverageOut | None
    page: MarketPageMetaOut
    resolved_contract_segments: list[ContractSegmentOut]


MarketChartStudyId = Literal["ema10", "ema21", "ema60", "boll"]
MarketChartStudyPointStatus = Literal["READY", "WARMING", "UNKNOWN", "INVALID", "ERROR"]


class MarketChartStudyPointOut(BaseModel):
    status: MarketChartStudyPointStatus
    values: dict[str, FiniteFloat] | None
    diagnostic: str | None


class MarketChartStudyFeatureOut(BaseModel):
    study: MarketChartStudyId
    formula_version: str
    backend_version: str
    parameters_hash: str = Field(pattern=r"^[a-f0-9]{16}$")
    points: list[MarketChartStudyPointOut]


class MarketChartStudyBarOut(BaseModel):
    bar_end: datetime
    close: Decimal
    source_bar_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class MarketChartStudySegmentOut(BaseModel):
    physical_contract: str
    segment_id: str
    bars: list[MarketChartStudyBarOut]
    features: list[MarketChartStudyFeatureOut]


class MarketChartStudyDisplayOut(BaseModel):
    schema_version: Literal["guiyi_market_chart_studies_v1"] = "guiyi_market_chart_studies_v1"
    result_schema_version: Literal["guiyi_feature_result_v1"] = "guiyi_feature_result_v1"
    symbol: str
    series_kind: Literal["contract", "actual_dominant", "continuous"]
    contract: str | None
    frequency: str
    as_of: datetime
    source_revision: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    unavailable_reason: Literal["PHYSICAL_OWNER_REQUIRED"] | None
    segments: list[MarketChartStudySegmentOut]


class MarketProgressResponse(BaseModel):
    phase: str
    trading_day: date | None
    contract: str | None = None
    status: Literal["historical", "waiting", "unknown", "source", "confirmation", "confirmed"]
    expected_end: datetime | None = None
    source_end: datetime | None = None
    source_received_at: datetime | None = None
    completed_end: datetime | None = None


class MarketReadStateResponse(BaseModel):
    symbol: str
    series_kind: str
    frequency: str
    operational: bool
    phase: str
    trading_day: date | None
    live_eligible: bool
    live_available: bool
    live_contract: str | None
    canonical_end: datetime | None
    after_market: dict[str, object]
    display_preview: bool = False
    canonical_revision: str | None = None


class DominantContractOut(BaseModel):
    product: str
    product_name: str
    sector: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date


class DominantContractListResponse(BaseModel):
    items: list[DominantContractOut]


class MarketProductDirectoryItem(BaseModel):
    product: str
    product_name: str
    exchange: str
    sector: str


class MarketProductDirectoryResponse(BaseModel):
    items: list[MarketProductDirectoryItem]


class ProductResearchResponse(BaseModel):
    symbol: str
    product_name: str
    sector: str
    exchange: str
    series_kind: str
    contract: str | None
    as_of: date
    current_dominant: str
    metric_contract: str | None
    dominant_mapping_date: date
    daily_trend: str
    weekly_trend: str
    position20: Decimal | None
    distance_to_20d_high: Decimal | None
    distance_to_20d_low: Decimal | None
    volume_ratio20: Decimal | None
    oi_change_1d: Decimal | None
    turnover_change_5d: Decimal | None
    atr14_percentile252: Decimal | None
    recent_daily: list[MarketBarOut]


class MarketHomeSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_up_count: int
    price_down_count: int
    price_flat_count: int
    price_unavailable_count: int = Field(ge=0)
    daily_up_count: int
    daily_down_count: int
    daily_neutral_count: int
    daily_unavailable_count: int
    aligned_up_count: int
    aligned_down_count: int


class MarketHomeItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    product_name: str
    sector: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date
    data_as_of: date
    close: Decimal
    price_change_1d: Decimal | None
    price_change_5d: Decimal | None
    volume_ratio20: Decimal | None
    oi_change_1d: Decimal | None
    atr14_percentile252: Decimal | None
    daily_trend: Literal["up", "down", "neutral", "unavailable"]
    weekly_trend: Literal["up", "down", "neutral", "unavailable"]
    reason_codes: list[str]


class MarketHomeSectorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sector: str
    active_count: int
    participant_count: int
    median_price_change_1d: Decimal | None


class MarketHomeOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_status: Literal["ready", "updating", "stale", "failed", "missing"] = "ready"

    status: Literal["ready", "degraded"]
    target_as_of: date
    data_as_of: date
    freshness: Literal["fresh", "stale", "unavailable"]
    active_count: int
    participant_count: int
    stale_count: int
    unavailable_count: int
    summary: MarketHomeSummaryOut
    items: list[MarketHomeItemOut]
    sectors: list[MarketHomeSectorOut]

    @model_validator(mode="after")
    def validate_price_summary_partition(self) -> "MarketHomeOverviewResponse":
        expected_counts = (
            sum(
                item.price_change_1d is not None and item.price_change_1d > 0
                for item in self.items
            ),
            sum(
                item.price_change_1d is not None and item.price_change_1d < 0
                for item in self.items
            ),
            sum(item.price_change_1d == 0 for item in self.items),
            sum(item.price_change_1d is None for item in self.items),
        )
        actual_counts = (
            self.summary.price_up_count,
            self.summary.price_down_count,
            self.summary.price_flat_count,
            self.summary.price_unavailable_count,
        )
        if self.participant_count != len(self.items) or actual_counts != expected_counts:
            raise ValueError("price summary does not match participants")
        return self
