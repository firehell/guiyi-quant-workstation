"""Strict request and status contracts for local research backtests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Frequency = Literal["1d", "1m"]
MatchingType = Literal["current_bar", "next_bar"]
SlippageModel = Literal["PriceRatioSlippage", "TickSizeSlippage"]

MATCHING_TYPES_BY_FREQUENCY: dict[str, frozenset[str]] = {
    "1d": frozenset({"current_bar"}),
    "1m": frozenset({"current_bar", "next_bar"}),
}


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"


def normalize_decimal(value: Decimal) -> str:
    """Return a finite Decimal as a plain canonical JSON string."""

    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


class BacktestRunRequest(BaseModel):
    """The user-controlled request and optional registered-default overrides."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    start_date: date
    end_date: date
    frequency: Frequency
    future_cash: Decimal | None = Field(
        default=None, gt=Decimal("0"), allow_inf_nan=False
    )
    matching_type: MatchingType | None = None
    margin_multiplier: Decimal | None = Field(
        default=None, gt=Decimal("0"), allow_inf_nan=False
    )
    futures_commission_multiplier: Decimal | None = Field(
        default=None, ge=Decimal("0"), allow_inf_nan=False
    )
    slippage_model: SlippageModel | None = None
    slippage: Decimal | None = Field(default=None, ge=Decimal("0"), allow_inf_nan=False)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "future_cash",
        "margin_multiplier",
        "futures_commission_multiplier",
        "slippage",
        mode="before",
    )
    @classmethod
    def decimals_are_json_strings(cls, value: object) -> object:
        if value is None:
            return value
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("decimal value must be a string")
        return value

    @model_validator(mode="after")
    def validate_dates_and_matching(self) -> BacktestRunRequest:
        if self.start_date > self.end_date:
            raise ValueError("start date must not exceed end date")
        if (
            self.matching_type is not None
            and self.matching_type not in MATCHING_TYPES_BY_FREQUENCY[self.frequency]
        ):
            raise ValueError("matching type is incompatible with frequency")
        return self
