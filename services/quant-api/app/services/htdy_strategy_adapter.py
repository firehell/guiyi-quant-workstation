"""Read-only adapter over the frozen JM HTDY realtime evaluator."""

from __future__ import annotations

from app.services.htdy_realtime_evaluator import HtDyRealtimeCandidateEvaluator
from app.services.htdy_realtime_models import HtDyRealtimeSnapshot
from app.services.observation_plans import require_supported_observation_plan
from app.services.strategy_adapter import (
    SignalCandidate,
    StrategyContext,
    StrategyEvaluation,
)
from guiyi_quant.indicators import (
    RealtimeRepaintingObservationPolicy,
    require_realtime_repainting_observation_policy,
)


class HtDyStrategyAdapter:
    """Delegate to the existing evaluator without adding any writer capability."""

    def evaluate(self, context: StrategyContext) -> StrategyEvaluation:
        if not isinstance(context, StrategyContext):
            raise ValueError("STRATEGY_ADAPTER_CONTEXT_TYPE")
        try:
            require_supported_observation_plan(context.plan)
        except ValueError as exc:
            if str(exc) == "STRATEGY_ADAPTER_PLAN_DISABLED":
                raise
            raise ValueError("STRATEGY_ADAPTER_PLAN_CONTRACT_MISMATCH") from exc
        if not isinstance(context.market_snapshot, HtDyRealtimeSnapshot):
            raise ValueError("STRATEGY_ADAPTER_SNAPSHOT_TYPE")
        if context.market_snapshot.partial_allowed is not True:
            raise ValueError("STRATEGY_ADAPTER_PARTIAL_POLICY_MISMATCH")

        result = HtDyRealtimeCandidateEvaluator().evaluate(
            context.market_snapshot,
            detected_at=context.detected_at,
        )
        if any(
            getattr(result, field, None) is not False
            for field in (
                "writes_enabled",
                "signal_event_enabled",
                "notification_enabled",
            )
        ):
            raise ValueError("STRATEGY_ADAPTER_WRITE_CAPABILITY_FORBIDDEN")

        policy = require_realtime_repainting_observation_policy(
            RealtimeRepaintingObservationPolicy()
        )
        candidates = tuple(
            _adapt_candidate(candidate, context=context, policy=policy)
            for candidate in result.candidates
        )
        return StrategyEvaluation(
            candidates=candidates,
            blocked=tuple(result.blocked),
            snapshot_sha256=result.snapshot_sha256,
            evaluated_at=result.evaluated_at,
        )


def _adapt_candidate(candidate, *, context: StrategyContext, policy) -> SignalCandidate:
    expected = {
        "period": context.plan.period,
        "strategy_code": context.plan.strategy_code,
        "strategy_version": context.plan.strategy_version,
        "policy_id": policy.policy_id,
    }
    if any(getattr(candidate, field, None) != value for field, value in expected.items()):
        raise ValueError("STRATEGY_ADAPTER_CANDIDATE_CONTRACT_MISMATCH")
    return SignalCandidate(
        observation_key=candidate.observation_key,
        direction=candidate.direction,
        detected_at=candidate.detected_at,
        actual_contract=candidate.actual_contract,
        period=candidate.period,
        strategy_code=candidate.strategy_code,
        strategy_version=candidate.strategy_version,
        policy_id=candidate.policy_id,
        native_candidate=candidate,
    )
