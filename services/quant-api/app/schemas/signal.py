from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SignalDataRole(StrEnum):
    PRIMARY = "primary"
    VALIDATION = "validation"
    LEGACY_REFERENCE = "legacy_reference"


class SignalStatus(StrEnum):
    NEW = "new"
    VIEWED = "viewed"
    IGNORED = "ignored"
    WATCHING = "watching"
    EXPIRED = "expired"


class SignalScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchlist_code: str = "black"
    periods: list[str] = Field(default_factory=list)
    symbols: list[str] | None = None
    provider: str | None = None
    data_role: SignalDataRole = SignalDataRole.PRIMARY
    research_only: bool = False
    account_equity: float = Field(default=100000.0, gt=0)
    risk_per_trade_pct: float = Field(default=0.01, gt=0, le=1)
    max_margin_usage_pct: float = Field(default=0.35, gt=0, le=1)
    min_score_bucket: int = Field(default=51, ge=0, le=80)
    allow_warning_quality: bool = False
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    run_inline: bool = False

    @field_validator("watchlist_code")
    @classmethod
    def validate_watchlist_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("watchlist_code cannot be blank")
        return normalized

    @field_validator("periods")
    @classmethod
    def validate_periods(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def validate_data_role(self) -> SignalScanRequest:
        if self.data_role in {SignalDataRole.VALIDATION, SignalDataRole.LEGACY_REFERENCE} and not self.research_only:
            raise ValueError("validation and legacy_reference signal scans must set research_only=true")
        return self


class SignalStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SignalStatus


class SignalScanTaskOut(BaseModel):
    id: int
    task_no: str
    status: str
    progress: float
    watchlist_code: str
    periods: list[str]
    data_role: str = SignalDataRole.PRIMARY.value
    research_only: bool = False
    total_items: int
    completed_items: int
    failed_items: int
    skipped_items: int
    error_message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    result_payload: dict[str, Any]


class StrategySignalOut(BaseModel):
    id: int
    task_no: str | None = None
    strategy_id: str
    strategy_version_id: str
    strategy_code: str
    strategy_name: str
    strategy_version: str
    watchlist_code: str | None = None
    symbol: str
    contract: str
    exchange: str | None = None
    interval: str
    period: str
    signal_time: str
    direction: str
    signal_type: str
    price: float
    signal_price: float
    entry_interval: str
    daily_direction: str | None = None
    entry_reason: str | None = None
    no_signal_reason: str | None = None
    max_hold_bars: int | None = None
    current_price: float
    strength_score: int
    signal_level: int
    score_bucket: int
    bucket_label: str
    reason: str
    reasons: list[str]
    status: SignalStatus
    strategy_status: str
    target_price: float | None = None
    stop_loss_price: float | None = None
    risk_reward_ratio: float | None = None
    open_volume: int
    margin_required: float
    risk_amount: float
    account_equity: float
    data_role: str = SignalDataRole.PRIMARY.value
    research_only: bool = False
    features: dict[str, Any]
    quality_status: dict[str, Any]
    research_contract: bool
    spec_source: str | None = None
    alert_status: str
    created_at: str | None = None
    updated_at: str | None = None
