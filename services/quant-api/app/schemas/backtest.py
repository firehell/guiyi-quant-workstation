from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BacktestEngineType(StrEnum):
    CUSTOM_V0 = "custom_v0"
    VNPY = "vnpy"


class BacktestDataRole(StrEnum):
    PRIMARY = "primary"
    VALIDATION = "validation"
    LEGACY_REFERENCE = "legacy_reference"
    CANDIDATE = "candidate"


class BacktestTaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine_type: BacktestEngineType = BacktestEngineType.VNPY
    task_type: str = "single"
    symbol: str
    exchange: str
    interval: str
    start: datetime
    end: datetime
    strategy_class_path: str
    strategy_code: str | None = None
    strategy_version: str | None = None
    strategy_parameters: dict[str, Any] = Field(default_factory=dict)
    rate: float = Field(default=0.0001, ge=0)
    slippage: float = Field(default=1.0, ge=0)
    size: int = Field(default=10, gt=0)
    pricetick: float = Field(default=1.0, gt=0)
    capital: float = Field(default=100000.0, gt=0)
    execution_timing: str = "next_bar_open"
    data_source: str = "local_parquet"
    data_role: BacktestDataRole = BacktestDataRole.PRIMARY
    data_version: str | None = None
    profile_id: str | None = None
    market_data_file_id: int | None = None
    research_only: bool = False
    quality_status: str = "passed"
    bar_data_path: str | None = None
    auxiliary_bar_data_paths: dict[str, str] = Field(default_factory=dict)
    request_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbol", "exchange", "interval", "strategy_class_path", "data_source", "quality_status")
    @classmethod
    def validate_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("task_type")
    @classmethod
    def validate_task_type(cls, value: str) -> str:
        normalized = value.strip()
        forbidden = {"live", "real", "trading", "auto_order"}
        if normalized.lower() in forbidden:
            raise ValueError(f"{normalized} is not allowed for backtest tasks")
        return normalized

    @field_validator("strategy_class_path")
    @classmethod
    def validate_strategy_class_path(cls, value: str) -> str:
        if ":" in value:
            module_name, class_name = value.rsplit(":", 1)
        elif "." in value:
            module_name, class_name = value.rsplit(".", 1)
        else:
            module_name, class_name = "", ""
        if not module_name.strip() or not class_name.strip():
            raise ValueError("strategy_class_path must be a module path plus class name")
        return value

    @model_validator(mode="after")
    def validate_backtest_config(self) -> BacktestTaskConfig:
        if self.engine_type is not BacktestEngineType.VNPY:
            raise ValueError("engine_type must be vnpy for BacktestTaskConfig")
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        if self.data_role is not BacktestDataRole.PRIMARY:
            raise ValueError("only primary RQData/local parquet data is active for backtest tasks")
        normalized_quality = self.quality_status.strip().lower()
        if normalized_quality == "failed":
            raise ValueError("failed quality_status data cannot enter backtest tasks")
        if normalized_quality == "warning" and not self.request_payload.get("allow_warning_quality", False):
            raise ValueError("warning quality_status requires allow_warning_quality=true in request_payload")
        return self


class VnpyBacktestTaskCreate(BaseModel):
    engine_type: BacktestEngineType = BacktestEngineType.VNPY
    task_type: str = "single"
    vnpy_strategy_class: str
    vnpy_setting_json: dict[str, Any] = Field(default_factory=dict)
    data_source: str = "local_parquet"
    data_role: BacktestDataRole = BacktestDataRole.PRIMARY
    data_version: str | None = None
    research_only: bool = False
    request_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_research_only_role(self) -> VnpyBacktestTaskCreate:
        if self.data_role is not BacktestDataRole.PRIMARY:
            raise ValueError("only primary RQData/local parquet data is active for backtest tasks")
        return self


class BacktestTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_no: str
    task_type: str
    engine_type: str
    status: str
    data_source: str | None = None
    data_role: str | None = None
    data_version: str | None = None
    profile_id: str | None = None
    market_data_file_id: int | None = None
    research_only: bool = False
    error_type: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class BacktestReportMetrics(BaseModel):
    initial_capital: float = 0.0
    final_equity: float = 0.0
    total_return: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_amount: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    trade_count: int = 0
    max_consecutive_losses: int = 0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    max_margin_required: float | None = None
    max_margin_usage_pct: float | None = None
    rollover_exit_count: int = 0
    delivery_risk_exit_count: int = 0
    average_hold_bars: float | None = None
    metric_units: dict[str, str] | None = None


class BacktestReportOut(BacktestReportMetrics):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    task_no: str
    report_no: str
    engine_type: str
    engine_version: str | None = None
    strategy_code: str | None = None
    strategy_version: str | None = None
    symbol: str
    contract: str
    period: str
    data_source: str | None = None
    data_role: str | None = None
    data_version: str | None = None
    profile_id: str | None = None
    market_data_file_id: int | None = None
    research_only: bool = False
    status: str
    suitability_label: str
    suitability_score: float
    consistency_hash: str | None = None
    summary: dict[str, Any]
    warnings: list[str]
    error_type: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
