"""Pydantic contracts for Alert V2 read-only HTTP views."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


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


class AlertEventOut(BaseModel):
    id: int
    rule_code: str
    symbol: str
    contract: str
    trading_day: date | None
    frequency: str
    bar_end: datetime
    result_codes: list[str]
    lower_tf_confirmation: bool
    detected_at: datetime
    notification_attempted_at: datetime | None


class FormalSignalAlertEventOut(AlertEventOut):
    display_name: str
    product_name: str


class AlertEventListResponse(BaseModel):
    items: list[AlertEventOut]


class CurrentAlertEventsResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    trading_day: date | None
    items: list[AlertEventOut]


class CurrentFormalSignalEventsResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    trading_day: date | None
    items: list[FormalSignalAlertEventOut]
