from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BacktestEngineType(StrEnum):
    CUSTOM_V0 = "custom_v0"
    VNPY = "vnpy"


class BacktestDataRole(StrEnum):
    PRIMARY = "primary"
    VALIDATION = "validation"
    LEGACY_REFERENCE = "legacy_reference"
    CANDIDATE = "candidate"


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
        if self.data_role in {BacktestDataRole.VALIDATION, BacktestDataRole.LEGACY_REFERENCE} and not self.research_only:
            raise ValueError("validation and legacy_reference backtests must set research_only=true")
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
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    trade_count: int = 0
    max_consecutive_losses: int = 0
    total_commission: float = 0.0
    total_slippage: float = 0.0


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
    research_only: bool = False
    status: str
    suitability_label: str
    suitability_score: float
    summary: dict[str, Any]
    warnings: list[str]
    error_type: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
