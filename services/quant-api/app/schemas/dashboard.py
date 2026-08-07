from __future__ import annotations

from pydantic import BaseModel, Field


class DashboardScanTaskSummary(BaseModel):
    task_no: str
    status: str
    progress: float
    watchlist_code: str
    created_at: str | None = None


class DashboardLatestReviewSummary(BaseModel):
    review_id: int
    source_type: str
    source_id: int | None = None
    symbol: str | None = None
    contract: str | None = None
    period: str | None = None
    review_score: int | None = None
    updated_at: str | None = None


class DashboardSummaryOut(BaseModel):
    data_status: str
    risk_status: str
    strategies: int
    v1b_strategies: int = 0
    signals_today: int
    signals_week: int = 0
    data_contracts: int = 0
    jm_primary_passed_assets: int = 0
    latest_scan_task: DashboardScanTaskSummary | None = None
    latest_data_time: str | None = None
    latest_review: DashboardLatestReviewSummary | None = None
    unfinished_review_count: int = 0
    generated_at: str | None = None


class StrategyRegistryItemOut(BaseModel):
    strategy_code: str
    name: str
    description: str
    symbol: str | None = None
    product: str | None = None
    periods: list[str] = Field(default_factory=list)
    is_v1b: bool = False
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
