from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    DatasetKind,
    UnsupportedFrequencyError,
    parse_bar_frequency,
)


FORMAL_SIGNAL_STRATEGY_CODE = "su_bing_ema21"
FORMAL_SIGNAL_STRATEGY_VERSION = "v0"
FORMAL_SIGNAL_EXECUTION_CONTRACT = "formal_historical_scan_v1"
FORMAL_SIGNAL_AUXILIARY_PERIOD = {
    "5m": "15m",
    "15m": "30m",
    "30m": "60m",
    "60m": "1d",
}
FORMAL_SIGNAL_PERIODS = frozenset({*FORMAL_SIGNAL_AUXILIARY_PERIOD, "1d"})
FORMAL_SIGNAL_INTERNAL_TASK_FIELDS = frozenset(
    {
        "data_role",
        "research_only",
        "observation_only",
        "not_trading_instruction",
        "auto_order",
        "execution_contract",
        "request_payload_sha256",
    }
)


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
    periods: list[BarFrequency] = Field(default_factory=lambda: [BarFrequency.M15])
    start: datetime
    end: datetime
    mode: SignalScanMode = SignalScanMode.SCAN
    watchlist_code: str = "black"
    account_equity: Decimal = Field(default=Decimal("100000"), gt=0)
    risk_per_trade_pct: Decimal = Field(default=Decimal("0.01"), gt=0, le=Decimal("0.01"))
    max_margin_usage_pct: Decimal = Field(default=Decimal("0.35"), gt=0, le=Decimal("0.35"))
    min_score_bucket: int = Field(default=51, ge=0, le=80)
    strategy_code: str = FORMAL_SIGNAL_STRATEGY_CODE
    strategy_version: str = FORMAL_SIGNAL_STRATEGY_VERSION
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

    @field_validator("periods", mode="before")
    @classmethod
    def validate_formal_periods(cls, value: Any) -> list[BarFrequency]:
        if not isinstance(value, list) or not value:
            raise ValueError("periods cannot be empty")
        try:
            normalized = [
                parse_bar_frequency(item, field="periods") for item in value
            ]
        except UnsupportedFrequencyError as exc:
            raise ValueError(exc.code) from exc
        if len(set(normalized)) != len(normalized):
            raise ValueError("periods cannot contain duplicates")
        if any(period not in FORMAL_SIGNAL_PERIODS for period in normalized):
            raise ValueError("SIGNAL_FORMAL_PERIOD_UNSUPPORTED")
        return normalized

    @field_validator("start", "end")
    @classmethod
    def validate_aware_window(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("formal signal window datetimes must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_canonical_identity(self) -> SignalScanRequest:
        if (
            self.strategy_code != FORMAL_SIGNAL_STRATEGY_CODE
            or self.strategy_version != FORMAL_SIGNAL_STRATEGY_VERSION
        ):
            raise ValueError("SIGNAL_FORMAL_STRATEGY_UNSUPPORTED")
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
                frequency=period,
                start=self.start,
                end=self.end,
            )
        return self


def build_formal_signal_task_payload(request: SignalScanRequest) -> dict[str, Any]:
    payload = {
        **request.model_dump(mode="json"),
        "data_role": SignalDataRole.PRIMARY.value,
        "research_only": False,
        "observation_only": True,
        "not_trading_instruction": True,
        "auto_order": False,
        "execution_contract": FORMAL_SIGNAL_EXECUTION_CONTRACT,
    }
    payload["request_payload_sha256"] = _formal_signal_payload_sha256(payload)
    return payload


def validate_formal_signal_task_payload(payload: Any) -> SignalScanRequest:
    if not isinstance(payload, dict):
        raise ValueError("SIGNAL_FORMAL_TASK_IDENTITY_INVALID")
    provided_hash = payload.get("request_payload_sha256")
    payload_without_hash = {
        key: value for key, value in payload.items() if key != "request_payload_sha256"
    }
    if (
        payload.get("data_role") != SignalDataRole.PRIMARY.value
        or payload.get("research_only") is not False
        or payload.get("observation_only") is not True
        or payload.get("not_trading_instruction") is not True
        or payload.get("auto_order") is not False
        or payload.get("execution_contract") != FORMAL_SIGNAL_EXECUTION_CONTRACT
        or provided_hash != _formal_signal_payload_sha256(payload_without_hash)
    ):
        raise ValueError("SIGNAL_FORMAL_TASK_IDENTITY_INVALID")
    formal_payload = {
        key: value
        for key, value in payload.items()
        if key not in FORMAL_SIGNAL_INTERNAL_TASK_FIELDS
    }
    try:
        request = SignalScanRequest.model_validate(formal_payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("SIGNAL_FORMAL_TASK_IDENTITY_INVALID") from exc
    if request.mode is not SignalScanMode.SCAN:
        raise ValueError("SIGNAL_FORMAL_TASK_IDENTITY_INVALID")
    if payload != build_formal_signal_task_payload(request):
        raise ValueError("SIGNAL_FORMAL_TASK_IDENTITY_INVALID")
    return request


def _formal_signal_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
