"""Only MDS, coverage and the pure warm-up planner are composed for this audit."""

from dataclasses import asdict
import time

from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.market_data.composition import build_market_data_service
from app.market_data.coverage_source import DatabaseCoverageSource
from app.market_data.historical_data_manager import (
    ContractWarmupPlanner,
    ContractWarmupRequest,
)
from app.market_data.operational_universe import load_active_products

from .product_reader import NewowProductReader
from .product_service import NewowProductService
from .readiness import AuditBudget, NewowReadinessAudit, ReadinessRequest


def build_newow_readiness(session: Session, *, request: ReadinessRequest) -> dict:
    budget = AuditBudget(request, time.monotonic)
    market = build_market_data_service(session)
    products = load_active_products()
    if not set(request.products) <= set(products):
        raise ValueError("NEWOW_INVALID_PRODUCT")
    coverage = DatabaseCoverageSource(
        session,
        PROJECT_ROOT / "data/universe/product_window_starts.csv",
        now=lambda: request.as_of,
    )

    def reader_factory(context, cancelled):
        return NewowProductReader(
            market,
            coverage=coverage,
            active_products=products,
            context_frequencies=context,
            now=lambda: request.as_of,
            cancelled=lambda: (
                budget.expired() or (cancelled is not None and cancelled())
            ),
        )

    planner = ContractWarmupPlanner(
        catalog=market.catalog,
        store=market.store,
        coverage=coverage,
        check_budget=budget.checkpoint,
    )

    def plan(intent: ContractWarmupRequest) -> dict:
        return asdict(planner.plan(intent))

    return NewowReadinessAudit(
        reader=reader_factory((), None),
        plan=plan,
        budget=budget,
        service=NewowProductService(
            reader_factory, now=lambda: request.as_of, cancelled=budget.expired
        ),
    ).run(request)
