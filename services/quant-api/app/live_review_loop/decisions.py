from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.live_review_loop.contracts import (
    FINGERPRINT_RECIPE_VERSION,
    STRATEGY_INPUT_SCHEMA_VERSION,
    StrategyInputSchema,
    canonical_digest,
)
from app.live_review_loop.evaluator import ApprovedEma21DirectionEvaluator
from app.models.live_review_loop import SignalDecision


class DecisionConflictError(RuntimeError):
    pass


class SignalDecisionStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        strategy_input: StrategyInputSchema,
        *,
        result_kind: str,
        direction: str | None,
        result_payload: Mapping[str, Any],
        decision_at: datetime,
    ) -> SignalDecision:
        ApprovedEma21DirectionEvaluator().evaluate_schema(strategy_input)
        if result_kind not in {"signal", "no_signal"}:
            raise ValueError("SIGNAL_DECISION_RESULT_KIND_INVALID")
        if (result_kind == "signal" and direction not in {"long", "short"}) or (
            result_kind == "no_signal" and direction is not None
        ):
            raise ValueError("SIGNAL_DECISION_DIRECTION_INVALID")
        decision_bar = strategy_input.snapshot["decision_bar"]
        bar_end = _parse_datetime(decision_bar["bar_end"])
        decision_key = canonical_digest(
            {
                "strategy_code": strategy_input.strategy_code,
                "strategy_version": strategy_input.strategy_version,
                "policy_id": strategy_input.policy_id,
                "actual_contract": strategy_input.actual_contract,
                "trading_day": strategy_input.trading_day,
                "bar_end": bar_end,
                "trigger": "confirmed_15m_close",
            }
        )
        result = dict(result_payload)
        result_digest = canonical_digest(
            {"result_kind": result_kind, "direction": direction, "payload": result}
        )
        existing = self.session.scalar(
            select(SignalDecision).where(SignalDecision.decision_key == decision_key)
        )
        if existing is not None:
            if (
                existing.input_digest != strategy_input.input_digest
                or existing.fingerprint != strategy_input.fingerprint
                or existing.result_digest != result_digest
            ):
                raise DecisionConflictError("SIGNAL_DECISION_CONFLICT")
            return existing
        historical = strategy_input.snapshot["historical_input"]
        row = SignalDecision(
            decision_key=decision_key,
            decision_at=decision_at,
            trading_day=strategy_input.trading_day,
            bar_end=bar_end,
            provider="rqdata",
            source_mode="session_aggregate_15m_v2",
            actual_contract=strategy_input.actual_contract,
            strategy_code=strategy_input.strategy_code,
            strategy_version=strategy_input.strategy_version,
            policy_id=strategy_input.policy_id,
            parameter_digest=strategy_input.parameter_digest,
            input_schema_version=STRATEGY_INPUT_SCHEMA_VERSION,
            input_window_start=_parse_datetime(strategy_input.snapshot["live_inputs"][0]["source_start"]),
            input_window_end=bar_end,
            dataset_key=dict(historical["dataset_key"]),
            manifest_digest=str(historical["manifest_digest"]),
            input_snapshot=strategy_input.snapshot,
            input_digest=strategy_input.input_digest,
            fingerprint_recipe_version=FINGERPRINT_RECIPE_VERSION,
            fingerprint=strategy_input.fingerprint,
            result_kind=result_kind,
            direction=direction,
            result_payload=result,
            result_digest=result_digest,
        )
        self.session.add(row)
        self.session.flush()
        return row


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("SIGNAL_DECISION_DATETIME_INVALID")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("SIGNAL_DECISION_DATETIME_TIMEZONE_REQUIRED")
    return parsed
