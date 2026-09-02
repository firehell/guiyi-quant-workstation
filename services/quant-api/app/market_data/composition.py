"""Market/Data/Runtime dependency composition."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.market_data.catalog import MarketCatalog
from app.market_data.historical_data_manager import HistoricalDataManager
from app.market_data.live_market import (
    LiveMarketService,
    RedisClient,
    RedisLiveStore,
    RQDataLiveProvider,
)
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_phase import MarketPhaseResolver
from app.market_data.market_read_service import MarketReadService
from app.market_data.market_research_service import MarketResearchService
from app.market_data.operational_universe import load_operational_products
from app.market_data.storage import CanonicalMonthlyStore
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
