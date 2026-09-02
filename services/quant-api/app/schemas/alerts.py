"""Pydantic contracts for the HTDY-only Alert API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ProductAlertRuleStateOut(BaseModel):
    rule_code: str
    display_name: str
    kind: str
    input_frequencies: list[str]
    enabled_frequencies: list[str]
    enabled_for_product: bool


class ProductAlertStateResponse(BaseModel):
    symbol: str
    rules: list[ProductAlertRuleStateOut]


class AlertScopeUpdate(BaseModel):
    enabled: bool


class HtdyAlertEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    rule_code: Literal["htdy_original_15m"]
    symbol: str
    contract: str
    trading_day: date | None
    frequency: str
    bar_end: datetime
    result_codes: list[Literal["buy", "sell"]]
    detected_at: datetime
    notification_attempted_at: datetime | None


AlertEventOut = HtdyAlertEventOut


class AlertEventListResponse(BaseModel):
    items: list[HtdyAlertEventOut]


class CurrentAlertEventsResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    trading_day: date | None
    items: list[HtdyAlertEventOut]


class CurrentHtdyEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "unavailable"]
    trading_day: date | None
    items: list[HtdyAlertEventOut]
