"""Market/Data/Runtime dependency composition（数据核心 V2 依赖注入）。

本模块将 Catalog、Parquet Store、RQData 适配器与维护管道拼成可运行对象：
- ``build_market_data_service``：只读查询路径（API/CLI 使用）；
- ``build_historical_data_manager``：历史回填与分区发布路径（含元数据同步与 coverage 校验）。

canonical 根目录由环境变量 ``GUIYI_CANONICAL_DATA_ROOT`` 或仓库默认路径解析，
与八表 Catalog 中的相对 URI 保持一致。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.market_data.catalog import MarketCatalog
from app.market_data.live_market import (
    RQDataLiveProvider,
    LiveMarketService,
    RedisClient,
    RedisLiveStore,
)
from app.market_data.historical_data_manager import HistoricalDataManager
from app.market_data.market_read_service import MarketReadService
from app.market_data.market_phase import MarketPhaseResolver
from app.market_data.operational_universe import (
    ActiveUniverseError,
    OperationalUniverseError,
    load_active_products,
    load_operational_products,
)
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_radar import MarketRadarService
from app.market_data.market_research_service import MarketResearchService
from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentLoader,
    ActualDominantStitchedResearchLoader,
)
from app.market_data.subing_calibration import load_accepted_subing_calibration
from app.market_data.subing_lifecycle_policy import (
    SubingLifecyclePolicyError,
    load_subing_lifecycle_policy,
)
from app.market_data.subing_read_service import SubingReadService
from app.market_data.subing_historical_signal_service import (
    SubingHistoricalSignalService,
)
from app.market_data.subing_daily_watch import (
    SubingDailyWatchBuilder,
    SubingDailyWatchCurrentService,
    SubingDailyWatchError,
    SubingDailyWatchGenerator,
    SubingDailyWatchProduct,
)
from app.market_data.subing_daily_watch_calendar import (
    resolve_expected_daily_watch_day,
    resolve_next_common_trading_day,
)
from app.market_data.subing_daily_watch_store import (
    PathMountInspector,
    SubingDailyWatchStore,
    resolve_subing_observation_root,
)
from app.market_data.product_taxonomy import load_product_taxonomy
from app.market_data.storage import CanonicalMonthlyStore
from app.redis_connections import get_redis_connection


_PRODUCT_STARTS = PROJECT_ROOT / "data/universe/product_window_starts.csv"
_HISTORY_FLOOR = PROJECT_ROOT / "data/universe/active_history_floor.txt"
_SUBING_CALIBRATION = (
    PROJECT_ROOT / "data/research_policies/subing_calibration_intraday_v1.json"
)
_SUBING_LIFECYCLE_POLICY = (
    PROJECT_ROOT / "data/research_policies/subing_lifecycle_v2_research_v1.json"
)


def canonical_root() -> Path:
    """解析 canonical Parquet 根目录（环境变量优先，否则仓库内默认路径）。"""
    configured = os.getenv("GUIYI_CANONICAL_DATA_ROOT")
    root = Path(configured) if configured else PROJECT_ROOT / "data/parquet/canonical"
    return root.resolve()


def build_historical_data_manager(session: Session) -> HistoricalDataManager:
    """构造历史数据维护管理器：含 RQData provider、元数据同步与 session 边界校验 store。"""
    from app.market_data.coverage_source import DatabaseCoverageSource
    from app.market_data.rqdata_adapter import RQDataMarketAdapter

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
        metadata=build_metadata_synchronizer(session, adapter=adapter, catalog=catalog),
        provider=adapter,
    )


def build_metadata_synchronizer(
    session: Session,
    *,
    adapter=None,
    catalog: MarketCatalog | None = None,
):
    """构造唯一 metadata 同步边界，供受限单日同步与历史维护共用。

    不会在构造时初始化 RQData；实际 provider 连接只在同步方法被显式调用时发生。
    可选依赖仅供已有 composition 重用，避免建立第二个 metadata engine。
    """
    from app.market_data.rqdata_adapter import RQDataMarketAdapter
    from app.market_data.metadata import MetadataSynchronizer

    active_catalog = catalog or MarketCatalog(session, canonical_root())
    active_adapter = adapter or RQDataMarketAdapter(session=session)
    return MetadataSynchronizer(active_adapter, active_catalog)


def build_market_data_service(session: Session) -> MarketDataService:
    """构造只读 ``MarketDataService``（查询路径不注入 RQData 与维护依赖）。"""
    root = canonical_root()
    return MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root))


def build_market_research_service(session: Session) -> MarketResearchService:
    """构造 Product Workspace 的只读研究服务。"""
    return MarketResearchService(build_market_data_service(session))


def build_subing_historical_signal_service(
    session: Session,
) -> SubingHistoricalSignalService:
    """Compose confirmed Canonical SuBing replay without Runtime or writes."""
    market_data = build_market_data_service(session)
    return SubingHistoricalSignalService(
        ActualDominantResearchSegmentLoader(market_data),
        products=load_active_products(),
        calibration=load_accepted_subing_calibration(_SUBING_CALIBRATION),
    )


def _subing_daily_watch_v2_root() -> Path:
    return (
        resolve_subing_observation_root(
            environ=os.environ,
            inspector=PathMountInspector(),
        )
        / "v2"
    )


def build_subing_daily_watch_generator(
    session: Session,
) -> SubingDailyWatchGenerator:
    """Compose the active60 Daily Watch writer without starting a run."""
    active = load_active_products()
    operational = load_operational_products()
    if (
        len(active) != 60
        or len(operational) != 60
        or len(set(active)) != 60
        or len(set(operational)) != 60
        or set(active) != set(operational)
    ):
        raise SubingDailyWatchError("ACTIVE_OPERATIONAL_SCOPE_MISMATCH")

    root = _subing_daily_watch_v2_root()
    market_data = build_market_data_service(session)
    dominants = market_data.list_latest_dominants()
    metadata = {
        item.symbol: SubingDailyWatchProduct(
            symbol=item.symbol,
            product_name=item.product_name,
            sector=item.sector,
        )
        for item in dominants
        if item.symbol in set(active)
    }
    store = SubingDailyWatchStore(
        root,
        root_validator=_subing_daily_watch_v2_root,
    )
    return SubingDailyWatchGenerator(
        builder=SubingDailyWatchBuilder(
            stitched_loader=ActualDominantStitchedResearchLoader(market_data),
            products=active,
            product_metadata=metadata,
        ),
        store=store,
        target_day=lambda source: resolve_next_common_trading_day(
            session,
            products=active,
            source_trading_day=source,
        ),
        clock=lambda: datetime.now(UTC),
    )


def build_subing_daily_watch_current_service(
    session: Session,
) -> SubingDailyWatchCurrentService:
    """Compose the current projection from Calendar and extension store only."""
    try:
        products = load_active_products()
        operational_products = load_operational_products()
    except (ActiveUniverseError, OperationalUniverseError):
        products = ()
        operational_products = ()
    return SubingDailyWatchCurrentService(
        products=products,
        operational_products=operational_products,
        expected_day=lambda now: resolve_expected_daily_watch_day(
            session,
            products=products,
            now=now,
        ),
        store_factory=lambda: SubingDailyWatchStore(
            _subing_daily_watch_v2_root(),
            root_validator=_subing_daily_watch_v2_root,
        ),
    )


def build_market_radar_service(session: Session) -> MarketRadarService:
    """构造完整 active 60 的只读 Radar，不注入 provider、Redis 或写入能力。"""
    from app.market_data.coverage_source import DatabaseCoverageSource

    coverage = DatabaseCoverageSource(
        session,
        _PRODUCT_STARTS,
        history_floor_path=_HISTORY_FLOOR,
    )
    return MarketRadarService(
        build_market_data_service(session),
        products=load_active_products(),
        taxonomy=load_product_taxonomy(),
        latest_complete_day=coverage.latest_complete_day,
    )


def build_market_read_service(session: Session) -> MarketReadService:
    """构造 Market Web 只读模型；Redis 仅作为可降级的 transient Live 边界。"""
    return MarketReadService(
        market_data=build_market_data_service(session),
        phase_resolver=MarketPhaseResolver(session),
        operational_products=load_operational_products(),
        live_store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
    )


def build_subing_read_service(session: Session) -> SubingReadService:
    """构造注入 accepted Calibration 与 exact research Policy 的只读模型。"""
    from app.market_data.coverage_source import DatabaseCoverageSource

    calibration = load_accepted_subing_calibration(_SUBING_CALIBRATION)
    try:
        lifecycle_policy = load_subing_lifecycle_policy(_SUBING_LIFECYCLE_POLICY)
    except SubingLifecyclePolicyError:
        lifecycle_policy = None
    return SubingReadService(
        market_data=build_market_data_service(session),
        market_read=build_market_read_service(session),
        calibration=calibration,
        lifecycle_policy=lifecycle_policy,
        lifecycle_coverage=DatabaseCoverageSource(
            session,
            _PRODUCT_STARTS,
            history_floor_path=_HISTORY_FLOOR,
        ),
    )


def build_live_market_service(session: Session) -> LiveMarketService:
    """构造前台 Live 观察服务，不启动循环也不写入 historical Canonical。"""
    from app.market_data.rqdata_adapter import RQDataClient

    rqdata = RQDataClient()
    return LiveMarketService(
        provider_factory=lambda: RQDataLiveProvider(rqdata.live_market_client()),
        dominant_source=rqdata,
        phase_resolver=MarketPhaseResolver(session),
        store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
        operational_products=load_operational_products(),
    )
