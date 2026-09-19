"""Only MDS, coverage and the pure warm-up planner are composed for this audit."""

from dataclasses import asdict, replace
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
from guiyi_quant.newow.product_identity import InputQualityPolicy

from .product_reader import NewowProductReader
from .product_service import NewowProductService
from .readiness import AuditBudget, NewowReadinessAudit, ReadinessRequest
from .product_release import REMAINING_WEEKLY_V2_PRODUCTS


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
    remaining = set(request.products) & set(REMAINING_WEEKLY_V2_PRODUCTS)
    if request.candidate_weekly and remaining and remaining != set(request.products):
        raise ValueError("NEWOW_READINESS_QUALITY_POLICY_MIXED")
    quality_policy = (
        InputQualityPolicy.WEEKLY_V2
        if request.candidate_weekly and remaining
        else InputQualityPolicy.V1
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
            input_quality_policy=quality_policy,
        )

    planner = ContractWarmupPlanner(
        catalog=market.catalog,
        store=market.store,
        coverage=coverage,
        check_budget=budget.checkpoint,
    )

    def plan(intent: ContractWarmupRequest) -> dict:
        return asdict(planner.plan(intent))

    audit = NewowReadinessAudit(
        reader=reader_factory((), None),
        plan=plan,
        budget=budget,
        service=NewowProductService(
            reader_factory,
            now=lambda: request.as_of,
            cancelled=budget.expired,
            reuse_read_inputs=True,
            quality_policy=quality_policy,
        ),
    )
    report = audit.run(request)
    if not request.consumer_only or budget.expired():
        return report

    legal = {"READY", "WARMING", "NOT_APPLICABLE", "UNAVAILABLE", "DATA_INTERRUPTED"}
    failed_products = tuple(dict.fromkeys(
        str(case["symbol"])
        for case in report["cases"]
        if any(
            state.get("status") not in legal
            for state in case["sections"].values()
        )
    ))
    if not failed_products:
        return report
    repair_report = audit.run(replace(
        request,
        products=failed_products,
        matrix=False,
        consumer_only=False,
    ))
    report["repair_targets"] = repair_report["repair_targets"]
    report["metadata_proposals"] = repair_report["metadata_proposals"]
    report["budget_exhausted"] = budget.exhausted
    return report
