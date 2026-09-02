"""Typed responses for the read-only Market API."""

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
