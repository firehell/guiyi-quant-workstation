from __future__ import annotations

from pydantic import BaseModel, Field


class DashboardScanTaskSummary(BaseModel):
    task_no: str
    status: str
    progress: float
    watchlist_code: str
    created_at: str | None = None


class DashboardLatestReportSummary(BaseModel):
    report_id: int
    report_no: str
    strategy_code: str | None = None
    status: str
    created_at: str | None = None


class DashboardSummaryOut(BaseModel):
    data_status: str
    risk_status: str
    strategies: int
    v1b_strategies: int = 0
    signals_today: int
    signals_week: int = 0
    backtests: int
    backtest_reports: int = 0
    backtest_reports_success: int = 0
    data_contracts: int = 0
    jm_primary_passed_assets: int = 0
    live_target_readiness: str | None = None
    live_targets_preview_only: bool = True
    latest_scan_task: DashboardScanTaskSummary | None = None
    latest_jm_report: DashboardLatestReportSummary | None = None
    generated_at: str | None = None


class StrategyBacktestEndpointOut(BaseModel):
    label: str
    path: str
    method: str = "POST"


class StrategyRegistryItemOut(BaseModel):
    strategy_code: str
    name: str
    description: str
    symbol: str | None = None
    product: str | None = None
    periods: list[str] = Field(default_factory=list)
    is_v1b: bool = False
    backtest_endpoints: list[StrategyBacktestEndpointOut] = Field(default_factory=list)
    scan_endpoint: str | None = None
    strategy_version: str | None = None
    spec_doc_path: str | None = None
    spec_doc_exists: bool = False
    capability_classes: list[str] = Field(default_factory=list)
    capability_class: str | None = None
    validation_outcome: str | None = None
    live_observation: bool = False


class StrategyRegistryOut(BaseModel):
    items: list[StrategyRegistryItemOut]
    total: int
    v1b_count: int
