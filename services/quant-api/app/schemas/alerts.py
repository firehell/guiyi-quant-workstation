"""Pydantic contracts for the minimal Alert V1 HTTP surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProductAlertRuleStateOut(BaseModel):
    rule_code: str
    display_name: str
    indicator_code: str
    series_kind: str
    frequency: str
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
    frequency: str
    bar_end: datetime
    observation_types: list[str]
    detected_at: datetime
    notified_at: datetime


class AlertEventListResponse(BaseModel):
    items: list[AlertEventOut]
