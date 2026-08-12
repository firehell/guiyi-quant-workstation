"""Market API 响应模型（Pydantic）。

与 Canonical K 线、主力映射及 Catalog 覆盖查询的 HTTP 契约对齐；字段类型与
MarketDataService 输出一致（价格/量使用 Decimal）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class MarketBarOut(BaseModel):
    """单根 Canonical K 线。"""

    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None


class CoverageOut(BaseModel):
    """本次查询结果在时间轴上的实际覆盖区间。"""

    start: datetime
    end: datetime


class ContractSegmentOut(BaseModel):
    """actual_dominant 查询时解析出的合约分段（按交易日切换主力）。"""

    contract: str
    start_trading_day: date
    end_trading_day: date


class MarketPageMetaOut(BaseModel):
    """历史游标分页边界。"""

    has_more_before: bool
    next_before: datetime | None


class MarketBarsPageResponse(BaseModel):
    """``/bars/page`` 历史游标分页响应。"""

    request: dict[str, object]
    bars: list[MarketBarOut]
    canonical_coverage: CoverageOut | None
    page: MarketPageMetaOut
    resolved_contract_segments: list[ContractSegmentOut]


class MarketReadStateResponse(BaseModel):
    """Market Web 的统一历史/Live 展示状态。"""

    symbol: str
    series_kind: str
    frequency: str
    operational: bool
    phase: str
    trading_day: date | None
    live_eligible: bool
    live_available: bool
    live_contract: str | None
    canonical_end: datetime | None
    after_market: dict[str, object]


class DominantContractOut(BaseModel):
    """单品种最新主力合约摘要。"""

    product: str
    product_name: str
    sector: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date


class DominantContractListResponse(BaseModel):
    """``/dominants`` 列表响应。"""

    items: list[DominantContractOut]
