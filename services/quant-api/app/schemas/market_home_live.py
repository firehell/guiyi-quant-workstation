"""WebSocket contracts for the operational homepage market overlay."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class MarketHomeLiveItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    physical_contract: str | None
    trading_day: str | None
    bar_end: str | None
    price: str | None
    previous_close: str | None
    price_change: str | None
    source: Literal["completed_1m", "completed_1d", "none"]
    availability: Literal["live", "historical", "unavailable"]
    phase: Literal["TRADING", "BREAK", "CLOSED", "UNKNOWN"]
    reason: str | None


class MarketHomeLiveSnapshotFrame(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    schema_version: Literal[1] = 1
    observed_at: str
    scope: Literal["operational"] = "operational"
    items: list[MarketHomeLiveItemResponse]


class MarketHomeLiveQuoteFrame(BaseModel):
    type: Literal["quote"] = "quote"
    schema_version: Literal[1] = 1
    observed_at: str
    item: MarketHomeLiveItemResponse


class MarketHomeLiveResetFrame(BaseModel):
    type: Literal["reset"] = "reset"
    schema_version: Literal[1] = 1
    observed_at: str
    reason: Literal["AUTHORITY_CHANGED"] = "AUTHORITY_CHANGED"
    items: list[MarketHomeLiveItemResponse]


class MarketHomeLiveUnavailableFrame(BaseModel):
    type: Literal["unavailable"] = "unavailable"
    schema_version: Literal[1] = 1
    observed_at: str
    code: Literal["MARKET_HOME_LIVE_UNAVAILABLE"] = "MARKET_HOME_LIVE_UNAVAILABLE"
