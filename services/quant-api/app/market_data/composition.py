"""市场数据子系统组装入口（数据核心 V2 依赖注入）。

本模块将 Catalog、Parquet Store、RQData 适配器与维护管道拼成可运行对象：
- ``build_market_data_service``：只读查询路径（API/CLI 使用）；
- ``build_historical_data_manager``：历史回填与分区发布路径（含元数据同步与 coverage 校验）。

canonical 根目录由环境变量 ``GUIYI_CANONICAL_DATA_ROOT`` 或仓库默认路径解析，
与八表 Catalog 中的相对 URI 保持一致。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.market_data.catalog import MarketCatalog
from app.market_data.live_market import RQDataLiveProvider, LiveMarketService, RedisClient, RedisLiveStore
from app.market_data.maintenance import HistoricalDataManager
from app.market_data.market_read import MarketReadService
from app.market_data.market_phase import MarketPhaseResolver
from app.market_data.operational_universe import load_operational_products
from app.market_data.service import MarketDataService
from app.market_data.storage import CanonicalMonthlyStore
from app.queue import get_redis_connection


_PRODUCT_STARTS = PROJECT_ROOT / "data/universe/product_window_starts.csv"
_HISTORY_FLOOR = PROJECT_ROOT / "data/universe/active_history_floor.txt"


def canonical_root() -> Path:
    """解析 canonical Parquet 根目录（环境变量优先，否则仓库内默认路径）。"""
    configured = os.getenv("GUIYI_CANONICAL_DATA_ROOT")
    root = Path(configured) if configured else PROJECT_ROOT / "data/parquet/canonical"
    return root.resolve()


def build_historical_data_manager(session: Session) -> HistoricalDataManager:
    """构造历史数据维护管理器：含 RQData provider、元数据同步与 session 边界校验 store。"""
    from app.market_data.infrastructure import DatabaseCoverageSource, RQDataMarketAdapter
    from app.market_data.metadata import MetadataSynchronizer

    root = canonical_root()
    catalog = MarketCatalog(session, root)
    adapter = RQDataMarketAdapter(session=session)
    coverage = DatabaseCoverageSource(
        session,
        _PRODUCT_STARTS,
        history_floor_path=_HISTORY_FLOOR,
    )
    return HistoricalDataManager(
        catalog=catalog,
        store=CanonicalMonthlyStore(root, boundary_validator=coverage.valid_boundary),
        coverage=coverage,
        metadata=MetadataSynchronizer(adapter, catalog),
        provider=adapter,
    )


def build_market_data_service(session: Session) -> MarketDataService:
    """构造只读 ``MarketDataService``（查询路径不注入 RQData 与维护依赖）。"""
    root = canonical_root()
    return MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root))


def build_market_read_service(session: Session) -> MarketReadService:
    """构造 Market Web 只读模型；Redis 仅作为可降级的 transient Live 边界。"""
    return MarketReadService(
        market_data=build_market_data_service(session),
        phase_resolver=MarketPhaseResolver(session),
        operational_products=load_operational_products(),
        live_store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
    )


def build_live_market_service(session: Session) -> LiveMarketService:
    """构造前台 Live 观察服务，不启动循环也不写入 historical Canonical。"""
    from app.market_data.infrastructure import RQDataClient

    rqdata = RQDataClient()
    return LiveMarketService(
        provider_factory=lambda: RQDataLiveProvider(rqdata.live_market_client()),
        dominant_source=rqdata,
        phase_resolver=MarketPhaseResolver(session),
        store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
        operational_products=load_operational_products(),
    )
