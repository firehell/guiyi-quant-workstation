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


class MarketBarsResponse(BaseModel):
    """``/bars/canonical`` 完整响应。"""

    request: dict[str, object]
    bars: list[MarketBarOut]
    coverage: CoverageOut | None
    resolved_contract_segments: list[ContractSegmentOut]


class DominantContractOut(BaseModel):
    """单品种最新主力合约摘要。"""

    product: str
    product_name: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date


class DominantContractListResponse(BaseModel):
    """``/dominants`` 列表响应。"""

    items: list[DominantContractOut]


class DatasetCoverageOut(BaseModel):
    """Catalog 中单条数据集（kind + symbol + series + frequency）的覆盖摘要。"""

    kind: str
    symbol: str
    series_or_contract: str
    frequency: str
    start: datetime
    end: datetime
    row_count: int
    partition_count: int


class MarketCoverageResponse(BaseModel):
    """``/coverage/canonical`` 列表响应。"""

    items: list[DatasetCoverageOut]
