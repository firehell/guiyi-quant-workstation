"""Pydantic contracts for the two-Rule Alert API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


AlertRuleCode = Literal["htdy_original_15m", "subing_ths_alert_15m_v1"]


class ProductAlertRuleStateOut(BaseModel):
    rule_code: AlertRuleCode
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


class AlertEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    rule_code: AlertRuleCode
    symbol: str
    contract: str
    trading_day: date | None
    frequency: str
    bar_end: datetime
    result_codes: list[Literal["buy", "sell"]]
    detected_at: datetime
    notification_attempted_at: datetime | None

class AlertEventListResponse(BaseModel):
    items: list[AlertEventOut]


class CurrentAlertEventsResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    trading_day: date | None
    items: list[AlertEventOut]
