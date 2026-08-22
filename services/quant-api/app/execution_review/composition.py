"""Execution Review dependency wiring shared by HTTP and CLI boundaries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.execution_review.contracts import load_product_trade_multipliers
from app.execution_review.reconciler import (
    ExecutionReviewRollReconciler,
)
from app.execution_review.queries import ExecutionReviewQueryService
from app.execution_review.reconstruction import EventReconstructionService
from app.execution_review.service import (
    DefensiveReconcileResult,
    ExecutionReviewService,
)
from app.market_data.composition import build_market_data_service


_MULTIPLIER_PATH = (
    Path(__file__).resolve().parents[4] / "data/reference/product_trade_multipliers.csv"
)


def build_execution_review_roll_reconciler(
    session: Session,
) -> ExecutionReviewRollReconciler:
    return ExecutionReviewRollReconciler(
        session,
        market_data=build_market_data_service(session),
    )


def build_execution_review_service(
    session: Session,
    *,
    clock: Callable[[], datetime] | None = None,
    reconcile_session_factory: Callable[[], Session] | None = None,
) -> ExecutionReviewService:
    active_reconcile_session_factory = reconcile_session_factory or sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        autocommit=False,
    )

    def reconcile_symbol(symbol: str) -> DefensiveReconcileResult:
        with active_reconcile_session_factory() as reconcile_session:
            return build_execution_review_roll_reconciler(
                reconcile_session
            ).reconcile_symbol(symbol)

    return ExecutionReviewService(
        session,
        multipliers=_multipliers(),
        clock=clock or (lambda: datetime.now(UTC)),
        reconcile_symbol=reconcile_symbol,
    )


def build_execution_review_query_service(
    session: Session,
) -> ExecutionReviewQueryService:
    return ExecutionReviewQueryService(session, multipliers=_multipliers())


def build_execution_review_reconstruction_service(
    session: Session,
) -> EventReconstructionService:
    return EventReconstructionService(
        session,
        market_data=build_market_data_service(session),
    )


def _multipliers() -> dict[str, Decimal]:
    return load_product_trade_multipliers(_MULTIPLIER_PATH)
