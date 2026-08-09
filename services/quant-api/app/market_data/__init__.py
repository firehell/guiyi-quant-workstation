"""市场数据包公共导出（数据核心 V2 领域契约面）。

对外稳定暴露查询与身份相关的值类型（``DatasetKey``、``SeriesQuery``、``CanonicalBar`` 等），
供 API schema、CLI 与测试构造请求。完整读写能力通过 ``composition`` 模块工厂注入
``MarketDataService`` / ``HistoricalDataManager``，不在此包顶层重导出。
"""

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    ContractError,
    DatasetKey,
    DatasetKind,
    SeriesKind,
    SeriesPageQuery,
    SeriesQuery,
)

__all__ = [
    "BarFrequency",
    "CanonicalBar",
    "ContractError",
    "DatasetKey",
    "DatasetKind",
    "SeriesKind",
    "SeriesPageQuery",
    "SeriesQuery",
]
