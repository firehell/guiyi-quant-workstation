from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

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


def _assert_candidate_root_isolated(candidate_root: Path) -> Path:
    root = candidate_root.resolve()
    previous = canonical_root()
    if root == previous or previous in root.parents or root in previous.parents:
        raise ValueError("CANDIDATE_ROOT_MUST_BE_ISOLATED")
    return root


def build_historical_data_manager(session: Session) -> HistoricalDataManager:
    from app.market_data.infrastructure import (
        DatabaseCoverageSource,
        RQDataMarketAdapter,
    )
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
        legacy=None,
    )


def build_candidate_historical_data_manager(
    session: Session,
    candidate_root: Path,
) -> HistoricalDataManager:
    """Compose an isolated RQData-only Candidate writer.

    Reuses the production HistoricalDataManager algorithm with legacy=None.
    Callers must supply an isolated Catalog session and candidate root.
    """
    from app.market_data.infrastructure import DatabaseCoverageSource, RQDataMarketAdapter
    from app.market_data.metadata import MetadataSynchronizer

    root = _assert_candidate_root_isolated(candidate_root)
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
        legacy=None,
    )


def build_candidate_bootstrap_manager(
    session: Session,
    candidate_root: Path,
    *,
    exact_scope: Mapping[str, Any] | None = None,
) -> HistoricalDataManager:
    """Freeze: migration-only legacy Gate A composition.

    Pending removal after Gate C. New Gate A MUST use
    ``build_candidate_historical_data_manager`` instead.
    """
    from app.market_data.infrastructure import DatabaseCoverageSource, RQDataMarketAdapter
    from app.market_data.legacy_bootstrap import ExactScopeProvider, LegacyBootstrapAdapter
    from app.market_data.metadata import MetadataSynchronizer

    root = _assert_candidate_root_isolated(candidate_root)
    previous = canonical_root()
    contract_root = (PROJECT_ROOT / "data/raw/rqdata/actual_contract_bars").resolve()
    continuous_raw_root = (PROJECT_ROOT / "data/raw/rqdata/dominant_contract_bars").resolve()
    catalog = MarketCatalog(session, root)
    coverage = DatabaseCoverageSource(
        session,
        _PRODUCT_STARTS,
        history_floor_path=_HISTORY_FLOOR,
    )
    adapter = RQDataMarketAdapter(session=session)
    provider = ExactScopeProvider(adapter, exact_scope) if exact_scope is not None else adapter
    return HistoricalDataManager(
        catalog=catalog,
        store=CanonicalMonthlyStore(root, boundary_validator=coverage.valid_boundary),
        coverage=coverage,
        metadata=MetadataSynchronizer(adapter, catalog),
        provider=provider,
        legacy=LegacyBootstrapAdapter(
            contract_root=contract_root,
            continuous_raw_root=continuous_raw_root,
            previous_canonical_root=previous,
            allowed_roots=(contract_root, continuous_raw_root, previous),
            exact_scope=exact_scope,
        ),
    )


def build_market_data_service(session: Session) -> MarketDataService:
    root = canonical_root()
    return MarketDataService(
        MarketCatalog(session, root),
        CanonicalMonthlyStore(root),
    )
