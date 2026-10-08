"""Pydantic contracts for the two-Rule Alert API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


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


class SubingAlignmentPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency: Literal["5m", "15m", "30m", "60m", "1d", "1w"]
    contract: str
    bar_end: datetime | None
    close: str | None
    ema21: str | None
    direction: Literal["LONG", "SHORT", "FLAT", "UNKNOWN"]
    reason: str | None
    input_snapshot_hash: str | None = None


class SubingAlignmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_version: Literal["subing_ema21_alignment_v1"]
    as_of: datetime
    observed_at: datetime
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    periods: list[SubingAlignmentPeriod]

    @model_validator(mode="after")
    def validate_snapshot(self):
        from decimal import Decimal, InvalidOperation
        from app.alerts.registry import SUBING_SIGNAL_FREQUENCIES

        if (
            tuple(p.frequency for p in self.periods) != SUBING_SIGNAL_FREQUENCIES
            or self.as_of.tzinfo is None
            or self.observed_at.tzinfo is None
            or self.observed_at < self.as_of
        ):
            raise ValueError("SUBING_ALIGNMENT_INVALID")
        for period in self.periods:
            if period.bar_end is not None and (
                period.bar_end.tzinfo is None or period.bar_end > self.as_of
            ):
                raise ValueError("SUBING_ALIGNMENT_INVALID")
            if period.direction != "UNKNOWN":
                if (
                    period.bar_end is None
                    or period.close is None
                    or period.ema21 is None
                ):
                    raise ValueError("SUBING_ALIGNMENT_INVALID")
                try:
                    close, ema = Decimal(period.close), Decimal(period.ema21)
                except InvalidOperation:
                    raise ValueError("SUBING_ALIGNMENT_INVALID") from None
                if (
                    not close.is_finite()
                    or not ema.is_finite()
                    or close <= 0
                    or ema <= 0
                ):
                    raise ValueError("SUBING_ALIGNMENT_INVALID")
                expected = (
                    "LONG"
                    if round(float(close), 6) > float(ema)
                    else "SHORT"
                    if round(float(close), 6) < float(ema)
                    else "FLAT"
                )
                if period.direction != expected or period.reason is not None:
                    raise ValueError("SUBING_ALIGNMENT_INVALID")
            elif period.reason is None:
                raise ValueError("SUBING_ALIGNMENT_INVALID")
        if any(p.direction == "UNKNOWN" for p in self.periods) != (
            self.status == "UNKNOWN"
        ):
            raise ValueError("SUBING_ALIGNMENT_INVALID")
        return self


class AlertEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    formula_version: str | None = None
    subing_alignment: SubingAlignmentOut | None = None
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


class AlertEventHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"]
    start_day: date
    end_day: date
    symbol: str | None
    rule_code: AlertRuleCode | None
    items: list[AlertEventOut]
    next_before: str | None
