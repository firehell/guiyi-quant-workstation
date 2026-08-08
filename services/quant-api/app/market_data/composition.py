from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.market_data.catalog import MarketCatalog
from app.market_data.maintenance import HistoricalDataManager
from app.market_data.service import MarketDataService
from app.market_data.storage import CanonicalMonthlyStore


_PRODUCT_STARTS = PROJECT_ROOT / "data/universe/product_window_starts.csv"
_HISTORY_FLOOR = PROJECT_ROOT / "data/universe/active_history_floor.txt"


def canonical_root() -> Path:
    configured = os.getenv("GUIYI_CANONICAL_DATA_ROOT")
    root = Path(configured) if configured else PROJECT_ROOT / "data/parquet/canonical"
    return root.resolve()


def build_historical_data_manager(session: Session) -> HistoricalDataManager:
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
    root = canonical_root()
    return MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root))
