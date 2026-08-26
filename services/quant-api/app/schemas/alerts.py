"""Pydantic contracts for Alert V2 read-only HTTP views."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


ConfirmationSourceOut = Literal[
    "formal_v1", "momentum_hold", "pivot_break_hold", "pivot_retest_rebreak"
]
LongExitReasonOut = Literal[
    "EMA21_BREACH_LONG",
    "PREVIOUS_BAR_LOW_BREACH",
    "BOUND_LOW_PIVOT_BREACH",
    "MACD_HIGH_DEAD_CROSS",
    "CONTRACT_SEGMENT_END",
]
ShortExitReasonOut = Literal[
    "EMA21_BREACH_SHORT",
    "PREVIOUS_BAR_HIGH_BREACH",
    "BOUND_HIGH_PIVOT_BREACH",
    "MACD_LOW_GOLDEN_CROSS",
    "CONTRACT_SEGMENT_END",
]
_LONG_EXIT_REASON_ORDER: tuple[LongExitReasonOut, ...] = (
    "EMA21_BREACH_LONG",
    "PREVIOUS_BAR_LOW_BREACH",
    "BOUND_LOW_PIVOT_BREACH",
    "MACD_HIGH_DEAD_CROSS",
    "CONTRACT_SEGMENT_END",
)
_SHORT_EXIT_REASON_ORDER: tuple[ShortExitReasonOut, ...] = (
    "EMA21_BREACH_SHORT",
    "PREVIOUS_BAR_HIGH_BREACH",
    "BOUND_HIGH_PIVOT_BREACH",
    "MACD_LOW_GOLDEN_CROSS",
    "CONTRACT_SEGMENT_END",
)


class _StrictOut(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _SubingStrategyEntryOut(_StrictOut):
    action_id: str
    effective_bar_end: datetime
    reference_price: str
    confirmation_source: ConfirmationSourceOut


class SubingStrategyOpenLongEntryOut(_SubingStrategyEntryOut):
    kind: Literal["open_long"]


class SubingStrategyOpenShortEntryOut(_SubingStrategyEntryOut):
    kind: Literal["open_short"]


class _SubingStrategyBoundPivotOut(_StrictOut):
    pivot_id: str
    source_timeframe: Literal["5m"]
    pivot_time: datetime
    confirmed_at: datetime
    price: str
    contract: str
    segment_start_trading_day: date


class SubingStrategyBoundLowPivotOut(_SubingStrategyBoundPivotOut):
    kind: Literal["low"]


class SubingStrategyBoundHighPivotOut(_SubingStrategyBoundPivotOut):
    kind: Literal["high"]


class _SubingStrategyActionCommonOut(_StrictOut):
    schema_version: Literal[1]
    strategy_id: Literal["subing_strategy_v1"]
    formula_version: Literal["subing_strategy_15m_v1"]
    action_id: str
    episode_id: str
    symbol: str
    contract: str
    trading_day: date
    segment_start_trading_day: date
    opportunity_id: str
    decision_at: datetime
    effective_bar_end: datetime
    reference_price: str


class _SubingStrategyOpenActionOut(_SubingStrategyActionCommonOut):
    effective_open_at: datetime
    fill_basis: Literal["next_bar_open"]
    confirmation_source: ConfirmationSourceOut
    reason_codes: tuple[()]
    direction_context_source_day: date
    direction_context_target_day: date
    entry: Literal[None]
    holding_bar_count: Literal[None]
    reference_change_percent: Literal[None]


class SubingStrategyOpenLongActionOut(_SubingStrategyOpenActionOut):
    kind: Literal["open_long"]
    bound_reference_pivot: SubingStrategyBoundLowPivotOut | None


class SubingStrategyOpenShortActionOut(_SubingStrategyOpenActionOut):
    kind: Literal["open_short"]
    bound_reference_pivot: SubingStrategyBoundHighPivotOut | None


class _SubingStrategyCloseActionOut(_SubingStrategyActionCommonOut):
    effective_open_at: datetime | None
    fill_basis: Literal["next_bar_open", "segment_terminal_close"]
    confirmation_source: Literal[None]
    direction_context_source_day: Literal[None]
    direction_context_target_day: Literal[None]
    holding_bar_count: Annotated[int, Field(ge=1)]
    reference_change_percent: str

    @model_validator(mode="after")
    def validate_fill_timing(self) -> _SubingStrategyCloseActionOut:
        if (self.fill_basis == "next_bar_open") != (self.effective_open_at is not None):
            raise ValueError("invalid close fill timing")
        return self


class SubingStrategyCloseLongActionOut(_SubingStrategyCloseActionOut):
    kind: Literal["close_long"]
    reason_codes: Annotated[list[LongExitReasonOut], Field(min_length=1)]
    bound_reference_pivot: SubingStrategyBoundLowPivotOut | None
    entry: SubingStrategyOpenLongEntryOut

    @model_validator(mode="after")
    def validate_reason_order(self) -> SubingStrategyCloseLongActionOut:
        canonical = [
            reason for reason in _LONG_EXIT_REASON_ORDER if reason in self.reason_codes
        ]
        if self.reason_codes != canonical:
            raise ValueError("invalid close_long reason order")
        return self


class SubingStrategyCloseShortActionOut(_SubingStrategyCloseActionOut):
    kind: Literal["close_short"]
    reason_codes: Annotated[list[ShortExitReasonOut], Field(min_length=1)]
    bound_reference_pivot: SubingStrategyBoundHighPivotOut | None
    entry: SubingStrategyOpenShortEntryOut

    @model_validator(mode="after")
    def validate_reason_order(self) -> SubingStrategyCloseShortActionOut:
        canonical = [
            reason for reason in _SHORT_EXIT_REASON_ORDER if reason in self.reason_codes
        ]
        if self.reason_codes != canonical:
            raise ValueError("invalid close_short reason order")
        return self


SubingStrategyActionOut = Annotated[
    SubingStrategyOpenLongActionOut
    | SubingStrategyOpenShortActionOut
    | SubingStrategyCloseLongActionOut
    | SubingStrategyCloseShortActionOut,
    Field(discriminator="kind"),
]


class _AlertEventCommonOut(_StrictOut):
    id: int
    symbol: str
    contract: str
    trading_day: date | None
    frequency: str
    bar_end: datetime
    detected_at: datetime
    notification_attempted_at: datetime | None


class HtdyAlertEventOut(_AlertEventCommonOut):
    rule_code: Literal["htdy_original_15m"]
    result_codes: list[Literal["buy", "sell"]]
    action_id: Literal[None]
    strategy_action: Literal[None]


class StrategyAlertEventOut(_AlertEventCommonOut):
    rule_code: Literal["subing_strategy_v1"]
    trading_day: date
    frequency: Literal["15m"]
    result_codes: list[Literal["open_long", "open_short", "close_long", "close_short"]]
    action_id: str
    strategy_action: SubingStrategyActionOut

    @model_validator(mode="after")
    def validate_action_binding(self) -> StrategyAlertEventOut:
        action = self.strategy_action
        if (
            self.result_codes != [action.kind]
            or self.action_id != action.action_id
            or self.symbol != action.symbol
            or self.contract != action.contract
            or self.trading_day != action.trading_day
            or self.bar_end != action.decision_at
        ):
            raise ValueError("invalid Strategy Event binding")
        return self


AlertEventOut = Annotated[
    HtdyAlertEventOut | StrategyAlertEventOut,
    Field(discriminator="rule_code"),
]


class StrategyActionAlertEventOut(StrategyAlertEventOut):
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
