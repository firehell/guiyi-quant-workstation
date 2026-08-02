from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from sqlalchemy.orm import Session

from app.live_review_loop.contracts import StrategyInputSchema
from app.live_review_loop.decisions import SignalDecisionStore
from app.live_review_loop.eod import EodReconciliationService
from app.live_review_loop.evaluator import ApprovedEma21DirectionEvaluator
from app.live_review_loop.gates import LiveReviewExecutionGate
from app.live_review_loop.live import LiveObservationInput, LiveObservationStore
from app.live_review_loop.provider_final import ProviderFinalSnapshot
from app.live_review_loop.retention import RetentionPlan, RetentionService
from app.models.live_review_loop import (
    LiveObservationBar,
    SignalDecision,
    SignalDecisionReconciliation,
)


class LiveReviewRuntime:
    """The only enabled execution facade; domain services remain pure/testable."""

    __slots__ = ("session", "gate")

    def __init__(
        self,
        session: Session,
        *,
        environ: Mapping[str, str],
    ) -> None:
        self.session = session
        self.gate = LiveReviewExecutionGate(environ)

    def record_live(self, item: LiveObservationInput) -> LiveObservationBar:
        self.gate.require_live()
        return LiveObservationStore(self.session).put(item)

    def create_decision(
        self,
        strategy_input: StrategyInputSchema,
        *,
        decision_at: datetime,
    ) -> SignalDecision:
        self.gate.require_live()
        result = ApprovedEma21DirectionEvaluator().evaluate_schema(strategy_input)
        return SignalDecisionStore(self.session).create(
            strategy_input,
            result_kind=str(result["result_kind"]),
            direction=result.get("direction"),
            result_payload=result["payload"],
            decision_at=decision_at,
        )

    def reconcile_eod(
        self,
        decision: SignalDecision,
        *,
        recipe_version: str,
        provider_final_loader: Callable[[SignalDecision], ProviderFinalSnapshot],
        gap_recorder: Callable[[SignalDecision, datetime, datetime], None],
    ) -> SignalDecisionReconciliation:
        self.gate.require_eod()
        return EodReconciliationService(self.session).run(
            decision,
            recipe_version=recipe_version,
            provider_final_loader=provider_final_loader,
            gap_recorder=gap_recorder,
        )

    def apply_retention(self, plan: RetentionPlan) -> dict[str, int]:
        self.gate.require_retention()
        return RetentionService(self.session).apply(plan)
