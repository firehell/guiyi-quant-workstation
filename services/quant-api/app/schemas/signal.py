from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.data_core.contracts import BarFrequency, BarQuery, DatasetKind


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


class SignalScanMode(StrEnum):
    SCAN = "scan"
    REPLAY = "replay"
    REPAIR = "repair"
    RECOMPUTE = "recompute"


class SignalScanRequest(BaseModel):
    """Formal historical scan contract over canonical actual-dominant data."""

    model_config = ConfigDict(extra="forbid")

    dataset_kind: DatasetKind
    instrument_symbol: str
    contract_or_series: str
    periods: list[str] = Field(default_factory=lambda: ["15m"])
    start: datetime
    end: datetime
    mode: SignalScanMode = SignalScanMode.SCAN
    watchlist_code: str = "black"
    account_equity: float = Field(default=100000.0, gt=0)
    risk_per_trade_pct: float = Field(default=0.01, gt=0, le=1)
    max_margin_usage_pct: float = Field(default=0.35, gt=0, le=1)
    min_score_bucket: int = Field(default=51, ge=0, le=80)
    strategy_code: str = "su_bing_ema21"
    strategy_version: str = "v0"
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    run_inline: bool = False

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_identity(cls, value: Any) -> Any:
        if isinstance(value, dict):
            forbidden = {
                "profile_id",
                "market_data_file_id",
                "symbols",
                "provider",
                "data_role",
                "allow_warning_quality",
                "research_only",
            } & set(value)
            if forbidden:
                raise ValueError("signal_formal_data_selection_forbidden")
        return value

    @field_validator("instrument_symbol")
    @classmethod
    def validate_instrument_symbol(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("watchlist_code", "strategy_code", "strategy_version")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("contract_or_series")
    @classmethod
    def validate_contract(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("contract_or_series cannot be blank")
        return normalized

    @field_validator("periods")
    @classmethod
    def validate_formal_periods(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if not normalized or any(not item for item in normalized):
            raise ValueError("periods cannot be empty or contain blank values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("periods cannot contain duplicates")
        return normalized

    @field_validator("start", "end")
    @classmethod
    def validate_aware_window(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("formal signal window datetimes must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_canonical_identity(self) -> SignalScanRequest:
        if self.dataset_kind is not DatasetKind.ACTUAL_DOMINANT:
            raise ValueError("SIGNAL_FORMAL_ACTUAL_DOMINANT_REQUIRED")
        if self.instrument_symbol.lower() != "jm":
            raise ValueError("SIGNAL_FORMAL_ACTUAL_DOMINANT_PRODUCT_UNSUPPORTED")
        if self.contract_or_series.endswith(".MAIN"):
            raise ValueError("SIGNAL_FORMAL_CONCRETE_CONTRACT_REQUIRED")
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        for period in self.periods:
            BarQuery(
                dataset_kind=self.dataset_kind,
                symbol=self.instrument_symbol,
                contract_or_series=self.contract_or_series,
                frequency=BarFrequency(period),
                start=self.start,
                end=self.end,
            )
        return self


class ResearchSignalScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchlist_code: str = "black"
    profile_id: str = "intraday_research_v1"
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
    def validate_data_role(self) -> ResearchSignalScanRequest:
        if self.data_role is not SignalDataRole.PRIMARY:
            raise ValueError("only primary RQData/local parquet data is active for signal scans")
        return self


class LiveSignalEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = "jm"
    profile_id: str = "live_observation_v1"
    contract: str | None = None
    entry_intervals: list[str] = Field(default_factory=lambda: ["15m", "5m"])
    provider: str | None = "rqdata"
    source_mode: str | None = None
    limit: int = Field(default=500, ge=1, le=10000)
    allow_warning_quality: bool = False
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    pricetick: float = Field(default=0.5, gt=0)

    @field_validator("symbol")
    @classmethod
    def validate_live_symbol(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "jm":
            raise ValueError("live evaluator v1 only supports symbol=jm")
        return normalized

    @field_validator("profile_id")
    @classmethod
    def validate_live_profile(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != "live_observation_v1":
            raise ValueError("live evaluator requires profile_id=live_observation_v1")
        return normalized

    @field_validator("contract")
    @classmethod
    def validate_live_contract(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("contract cannot be blank")
        return normalized

    @field_validator("entry_intervals")
    @classmethod
    def validate_live_entry_intervals(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if not normalized:
            raise ValueError("entry_intervals cannot be empty")
        unsupported = sorted(set(normalized) - {"15m", "5m"})
        if unsupported:
            raise ValueError(f"unsupported live evaluator entry intervals: {', '.join(unsupported)}")
        return normalized


class LiveSignalEvaluationItem(BaseModel):
    strategy_code: str
    strategy_version: str
    symbol: str
    contract: str
    continuous_contract: str | None = None
    actual_contract: str | None = None
    dominant_mapping_date: str | None = None
    entry_interval: str
    evaluated_at: str
    bar_time: str | None = None
    bar_end: str | None = None
    trigger_price: float | None = None
    direction: str
    status: str
    daily_direction: str
    entry_reason: str | None = None
    no_signal_reason: str | None = None
    stop_loss_price: float | None = None
    quality: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    source: dict[str, Any]
    context: "LiveSignalContextOut | None" = None


class LiveSignalContextOut(BaseModel):
    status: str
    blocked_reason: str | None = None
    historical_context_file_id: int | None = None
    historical_context_data_version: str | None = None
    historical_context_hash: str | None = None
    historical_context_file_checksum: str | None = None
    historical_context_bar_count: int = 0
    historical_context_start: str | None = None
    historical_context_end: str | None = None
    historical_context_max_trading_day: str | None = None
    live_bar_id: int | None = None
    live_bar_revision: int | None = None
    confirmed_at: str | None = None
    live_trading_day: str | None = None
    actual_contract: str | None = None
    dominant_mapping_date: str | None = None
    merged_bar_count: int = 0
    exact_duplicate_count: int = 0


class LiveSignalEvaluationResponse(BaseModel):
    strategy_code: str
    strategy_version: str
    symbol: str
    contract: str
    continuous_contract: str | None = None
    actual_contract: str | None = None
    dominant_mapping_date: str | None = None
    evaluated_at: str
    results: list[LiveSignalEvaluationItem]
    quality_summary: dict[str, Any]
    message: str | None = None


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
    mode: SignalScanMode = SignalScanMode.SCAN
    profile_id: str | None = None
    market_data_file_id: int | None = None
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
    product: str | None = None
    continuous_contract: str | None = None
    actual_contract: str | None = None
    dominant_mapping_date: str | None = None
    exchange: str | None = None
    interval: str
    period: str
    signal_time: str
    bar_start: str | None = None
    bar_end: str | None = None
    trigger_price: float | None = None
    provider: str | None = None
    source: str | None = None
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
    profile_id: str | None = None
    market_data_file_id: int | None = None
    input_identity: dict[str, Any] | None = None
    research_contract: bool
    spec_source: str | None = None
    alert_status: str
    created_at: str | None = None
    updated_at: str | None = None


class SignalEventOut(BaseModel):
    id: int
    event_key: str
    event_type: str
    signal_id: int | None = None
    task_no: str | None = None
    source_mode: str
    strategy_name: str
    strategy_version: str
    watchlist_code: str | None = None
    symbol: str
    contract: str
    product: str | None = None
    continuous_contract: str | None = None
    actual_contract: str | None = None
    dominant_mapping_date: str | None = None
    exchange: str | None = None
    period: str
    signal_time: str | None = None
    bar_start: str | None = None
    bar_end: str | None = None
    trigger_price: float | None = None
    provider: str | None = None
    source: str | None = None
    direction: str
    signal_status: str
    lifecycle_status: str
    score_bucket: int
    data_role: str
    quality_status: dict[str, Any]
    profile_id: str | None = None
    market_data_file_id: int | None = None
    input_identity: dict[str, Any] | None = None
    payload: dict[str, Any]
    created_at: str | None = None


class Stage9WechatPreviewOut(BaseModel):
    allowed: bool
    blocked_reasons: list[str]
    would_send: bool = False
    channel: str
    notification_recorded: bool = False
    payload_basis: dict[str, Any]
    wechat_payload: dict[str, Any] | None = None


class Stage9WechatNotificationOut(BaseModel):
    id: int
    event_id: int | None = None
    signal_id: int | None = None
    task_no: str | None = None
    dedupe_key: str
    event_type: str
    channel: str
    status: str
    payload: dict[str, Any]
    error_message: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    last_attempt_at: str | None = None
    next_retry_at: str | None = None
    last_error_type: str | None = None
    response_status_code: int | None = None
    created_at: str | None = None
    sent_at: str | None = None
