"""Market/Data/Runtime dependency composition."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.market_data.catalog import MarketCatalog
from app.market_data.errors import InfrastructureError
from app.market_data.historical_data_manager import HistoricalDataManager
from app.market_data.live_market import (
    LiveMarketService,
    RedisClient,
    RedisLiveStore,
    RQDataLiveProvider,
)
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_home_overview import (
    MarketHomeOverviewError,
    MarketHomeOverviewService,
)
from app.market_data.market_home_projection import (
    MarketHomeProjection,
    MarketHomeProjectionStore,
    market_home_projection_path,
)
from app.market_data.market_phase import MarketPhaseResolver
from app.market_data.market_read_service import MarketReadService
from app.market_data.market_research_service import MarketResearchService
from app.market_data.operational_universe import (
    ActiveUniverseError,
    load_active_products,
    load_operational_products,
)
from app.market_data.product_taxonomy import ProductTaxonomyError, load_product_taxonomy
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.session_anchor_repair import (
    SessionAnchorRepairError,
    SessionAnchorRepairService,
    local_runtime_stopped,
    run_session_anchor_migration,
)
from app.redis_connections import get_redis_connection


_PRODUCT_STARTS = PROJECT_ROOT / "data/universe/product_window_starts.csv"
_HISTORY_FLOOR = PROJECT_ROOT / "data/universe/active_history_floor.txt"


def canonical_root() -> Path:
    """Resolve the single Canonical Parquet root."""

    configured = os.getenv("GUIYI_CANONICAL_DATA_ROOT")
    root = Path(configured) if configured else PROJECT_ROOT / "data/parquet/canonical"
    return root.resolve()


def build_historical_data_manager(session: Session) -> HistoricalDataManager:
    """Compose the Historical maintenance boundary without starting a run."""

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
    """Compose the shared metadata synchronization boundary."""

    from app.market_data.metadata import MetadataSynchronizer
    from app.market_data.rqdata_adapter import RQDataMarketAdapter

    active_catalog = catalog or MarketCatalog(session, canonical_root())
    active_adapter = adapter or RQDataMarketAdapter(session=session)
    return MetadataSynchronizer(active_adapter, active_catalog)


def build_market_data_service(session: Session) -> MarketDataService:
    """Compose the read-only Historical market service."""

    root = canonical_root()
    return MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root))


def build_market_research_service(session: Session) -> MarketResearchService:
    return MarketResearchService(build_market_data_service(session))


def build_market_home_overview_service(session: Session) -> MarketHomeOverviewService:
    """Compose the completed-D1/W1 home overview without Live dependencies."""

    from app.market_data.coverage_source import DatabaseCoverageSource

    try:
        coverage = DatabaseCoverageSource(
            session,
            _PRODUCT_STARTS,
            history_floor_path=_HISTORY_FLOOR,
        )
        products = load_active_products()
        taxonomy = load_product_taxonomy()
    except (ActiveUniverseError, InfrastructureError, ProductTaxonomyError) as exc:
        raise MarketHomeOverviewError("MARKET_HOME_AUTHORITY_UNAVAILABLE") from exc
    return MarketHomeOverviewService(
        market_data=build_market_data_service(session),
        products=products,
        taxonomy=taxonomy,
        latest_complete_day=coverage.latest_complete_day,
    )


def build_market_home_projection(session: Session) -> MarketHomeProjection:
    """Compose the shared-root derived overview projection."""

    root = canonical_root()
    return MarketHomeProjection(
        service=build_market_home_overview_service(session),
        store=MarketHomeProjectionStore(market_home_projection_path(root)),
    )


def build_market_read_service(session: Session) -> MarketReadService:
    """Compose Market reads with an optional transient Redis Live overlay."""

    return MarketReadService(
        market_data=build_market_data_service(session),
        phase_resolver=MarketPhaseResolver(session),
        operational_products=load_operational_products(),
        live_store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
    )


def build_live_market_service(session: Session) -> LiveMarketService:
    """Compose the foreground Live observation service without starting it."""

    from app.market_data.rqdata_adapter import RQDataClient

    rqdata = RQDataClient()
    return LiveMarketService(
        provider_factory=lambda: RQDataLiveProvider(rqdata.live_market_client()),
        dominant_source=rqdata,
        phase_resolver=MarketPhaseResolver(session),
        store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
        operational_products=load_operational_products(),
    )


def build_session_anchor_repair_service(session: Session) -> SessionAnchorRepairService:
    """Compose the gated one-off session-anchor repair boundary."""
    from app.alerts.current_trading_day import (
        CurrentTradingDayStatus,
        resolve_current_trading_day,
    )
    from app.market_data.rqdata_adapter import RQDataMarketAdapter

    root = canonical_root()
    live_store = RedisLiveStore(cast(RedisClient, get_redis_connection()))

    def current_trading_day() -> date:
        result = resolve_current_trading_day(
            MarketPhaseResolver(session),
            products=load_operational_products(),
            now=datetime.now(UTC),
        )
        if (
            result.status is not CurrentTradingDayStatus.READY
            or result.trading_day is None
        ):
            raise SessionAnchorRepairError("SESSION_ANCHOR_CURRENT_DAY_UNAVAILABLE")
        return result.trading_day

    return SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=RQDataMarketAdapter(session=session),
        runtime_stopped=local_runtime_stopped,
        migration_runner=run_session_anchor_migration,
        current_trading_day=current_trading_day,
        live_cleanup=live_store.cleanup_bars_for_trading_day,
    )
