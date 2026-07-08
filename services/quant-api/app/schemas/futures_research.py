from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class CoverageSummary(BaseModel):
    local_min_date: date | None = None
    local_max_date: date | None = None
    requested_start: date
    requested_end: date
    requested_filled: bool = False


class ChartSeriesSpec(BaseModel):
    name: str
    data: list[float | str | None]
    y_axis_index: int = Field(default=0, alias="yAxisIndex")

    model_config = {"populate_by_name": True}


class ChartSpec(BaseModel):
    chart_type: Literal["line", "step", "bar"] = "line"
    x_axis: list[str] = Field(default_factory=list, alias="xAxis")
    y_axis_categories: list[str] | None = Field(default=None, alias="yAxisCategories")
    series: list[ChartSeriesSpec] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class ColumnSpec(BaseModel):
    key: str
    title: str
    width: int | None = None


class FuturesResearchPanelMeta(BaseModel):
    panel_id: str
    label: str
    description: str
    enabled: bool = True
    reason: str | None = None
    requires_contract: bool = False
    sync_script: str | None = None
    local_coverage_start: date | None = None
    local_coverage_end: date | None = None


class FuturesResearchPanelCatalogResponse(BaseModel):
    symbol: str
    contract: str | None = None
    panels: list[FuturesResearchPanelMeta]


class FuturesResearchPanelResponse(BaseModel):
    panel_id: str
    symbol: str
    contract: str | None = None
    start: date
    end: date
    source: Literal["local_postgresql"] = "local_postgresql"
    provider: str = "rqdata"
    data_version: str | None = None
    row_count: int = 0
    coverage: CoverageSummary
    chart: ChartSpec
    columns: list[ColumnSpec]
    rows: list[dict[str, Any]]
    empty_reason: str | None = None
