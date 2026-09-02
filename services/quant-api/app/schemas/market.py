"""Typed responses for the read-only Market API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


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


class DominantContractOut(BaseModel):
    product: str
    product_name: str
    sector: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date


class DominantContractListResponse(BaseModel):
    items: list[DominantContractOut]


class ProductResearchResponse(BaseModel):
    symbol: str
    product_name: str
    sector: str
    exchange: str
    series_kind: str
    contract: str | None
    as_of: date
    current_dominant: str
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
