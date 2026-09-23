"""Explicit P4 composition; importing this module creates no engine or client."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager

from app.reference_trading.inputs import HistoricalInputReader
from app.reference_trading.planning import HistoricalReferencePlanner


def build_historical_reference_planner(
    *, input_reader: HistoricalInputReader, repository: object | None = None,
    now: Callable | None = None,
) -> HistoricalReferencePlanner:
    return HistoricalReferencePlanner(input_reader, repository=repository, now=now)


@contextmanager
def open_historical_reference_components(*, session_factory=None):
    """Compose P4 from read-only MDS consumers and the P3 repository on demand."""
    from app.db.session import SessionLocal
    from app.market_data.catalog import MarketCatalog
    from app.market_data.composition import (
        build_database_coverage_source,
        build_market_data_service,
        canonical_root,
    )
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.operational_universe import load_active_products
    from app.market_data.subing_reference import SubingReferenceService
    from app.reference_trading.inputs import MarketDataHistoricalInputReader
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.service import HistoricalReferenceService

    factory = session_factory or SessionLocal
    with factory() as session:
        market_data = build_market_data_service(session)
        coverage = build_database_coverage_source(session)
        products = load_active_products()
        catalog = MarketCatalog(session, canonical_root())

        @contextmanager
        def guard():
            lease = catalog.acquire_maintenance_lock()
            if lease is None:
                raise ValueError("SOURCE_BUSY")
            try:
                yield
            finally:
                lease.release()

        reader = MarketDataHistoricalInputReader(
            newow_reader=NewowProductReader(
                market_data,
                coverage=coverage,
                active_products=products,
            ),
            subing_service=SubingReferenceService(
                market_data,
                coverage=coverage,
                active_products=products,
            ),
            read_guard=guard,
        )
        repository = ReferenceRepository(factory)
        planner = HistoricalReferencePlanner(reader, repository=repository)
        service = HistoricalReferenceService(repository, reader)
        yield planner, service
