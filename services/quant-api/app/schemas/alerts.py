"""Pydantic contracts for Alert V2 read-only HTTP views."""

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


class SubingStrategyEntryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    kind: Literal["open_long", "open_short"]
    effective_bar_end: datetime
    reference_price: str
    confirmation_source: Literal[
        "formal_v1", "momentum_hold", "pivot_break_hold", "pivot_retest_rebreak"
    ]


class SubingStrategyBoundPivotOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pivot_id: str
    kind: Literal["high", "low"]
    source_timeframe: Literal["5m"]
    pivot_time: datetime
    confirmed_at: datetime
    price: str
    contract: str
    segment_start_trading_day: date


class SubingStrategyActionOut(BaseModel):
    """Exact validated Strategy Action payload exposed to HTTP clients."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    strategy_id: Literal["subing_strategy_v1"]
    formula_version: Literal["subing_strategy_15m_v1"]
    action_id: str
    episode_id: str
    kind: Literal["open_long", "open_short", "close_long", "close_short"]
    symbol: str
    contract: str
    trading_day: date
    segment_start_trading_day: date
    opportunity_id: str
    decision_at: datetime
    effective_open_at: datetime | None
    effective_bar_end: datetime
    reference_price: str
    fill_basis: Literal["next_bar_open", "segment_terminal_close"]
    confirmation_source: (
        Literal[
            "formal_v1", "momentum_hold", "pivot_break_hold", "pivot_retest_rebreak"
        ]
        | None
    )
    reason_codes: list[str]
    direction_context_source_day: date | None
    direction_context_target_day: date | None
    bound_reference_pivot: SubingStrategyBoundPivotOut | None
    entry: SubingStrategyEntryOut | None
    holding_bar_count: int | None
    reference_change_percent: str | None


class AlertEventOut(BaseModel):
    id: int
    rule_code: str
    symbol: str
    contract: str
    trading_day: date | None
    frequency: str
    bar_end: datetime
    result_codes: list[str]
    action_id: str | None
    strategy_action: SubingStrategyActionOut | None
    detected_at: datetime
    notification_attempted_at: datetime | None


class StrategyActionAlertEventOut(AlertEventOut):
    display_name: str
    product_name: str


class AlertEventListResponse(BaseModel):
    items: list[AlertEventOut]


class CurrentAlertEventsResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    trading_day: date | None
    items: list[AlertEventOut]


class CurrentStrategyActionEventsResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    trading_day: date | None
    items: list[StrategyActionAlertEventOut]
