from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.live_review_loop.contracts import canonical_digest
from app.models.live_review_loop import ResearchSample, SignalDecision, SignalDecisionReconciliation
from app.models.review import ReviewNote


class ResearchSampleError(RuntimeError):
    pass


def create_or_get_decision_review(session: Session, decision_id: int) -> ReviewNote:
    existing = session.scalar(
        select(ReviewNote).where(
            ReviewNote.source_type == "signal_decision",
            ReviewNote.source_id == decision_id,
        )
    )
    if existing is not None:
        return existing
    decision = session.get(SignalDecision, decision_id)
    if decision is None:
        raise ResearchSampleError("SIGNAL_DECISION_NOT_FOUND")
    note = ReviewNote(
        source_type="signal_decision",
        source_id=decision.id,
        symbol="jm",
        contract=decision.actual_contract,
        period="15m",
        direction=decision.direction,
        strategy_name=decision.strategy_code,
        strategy_version=decision.strategy_version,
        open_time=decision.bar_end,
        close_time=decision.bar_end,
        open_price=None,
        close_price=None,
        volume=0,
        net_pnl=None,
        mistake_tags=[],
        rule_tags=[],
        emotion_tags=[],
        screenshot_paths=[],
        kline_focus_time=decision.bar_end,
        kline_window_start=decision.input_window_start,
        kline_window_end=decision.input_window_end,
        ai_status="reserved",
        extra={
            "lineage_status": "ready",
            "formal_lineage": {
                "schema_version": "signal_decision_review_lineage_v1",
                "decision_key": decision.decision_key,
                "dataset_key": decision.dataset_key,
                "manifest_digest": decision.manifest_digest,
                "input_digest": decision.input_digest,
                "fingerprint": decision.fingerprint,
            },
        },
    )
    session.add(note)
    session.flush()
    return note


def extract_research_sample(session: Session, review_id: int) -> ResearchSample:
    review = session.get(ReviewNote, review_id)
    if review is None or review.source_type != "signal_decision" or review.source_id is None:
        raise ResearchSampleError("RESEARCH_SAMPLE_REVIEW_INVALID")
    if (
        not isinstance(review.market_phase, str)
        or not review.market_phase.strip()
        or review.is_system_compliant is None
        or not review.rule_tags
        or not isinstance(review.lesson, str)
        or not review.lesson.strip()
    ):
        raise ResearchSampleError("RESEARCH_SAMPLE_LABELS_INCOMPLETE")
    decision = session.get(SignalDecision, review.source_id)
    if decision is None:
        raise ResearchSampleError("RESEARCH_SAMPLE_DECISION_NOT_FOUND")
    reconciliation = session.scalar(
        select(SignalDecisionReconciliation)
        .where(
            SignalDecisionReconciliation.decision_id == decision.id,
            SignalDecisionReconciliation.status == "completed",
        )
        .order_by(SignalDecisionReconciliation.id.desc())
    )
    if reconciliation is None or reconciliation.recomputed_result_digest is None:
        raise ResearchSampleError("RESEARCH_SAMPLE_EOD_INCOMPLETE")
    reconciliation_digest = canonical_digest(
        {
            "provider_final_digest": reconciliation.provider_final_digest,
            "provider_data_version": reconciliation.provider_data_version,
            "provider_request_digest": reconciliation.provider_request_digest,
            "result_digest": reconciliation.recomputed_result_digest,
            "outcome": reconciliation.outcome,
        }
    )
    sample_key = canonical_digest(
        {
            "schema_version": "research_sample_v1",
            "decision_key": decision.decision_key,
            "review_id": review.id,
            "reconciliation_digest": reconciliation_digest,
        }
    )
    existing = session.scalar(select(ResearchSample).where(ResearchSample.sample_key == sample_key))
    if existing is not None:
        return existing
    sample = ResearchSample(
        sample_key=sample_key,
        schema_version="research_sample_v1",
        decision_key=decision.decision_key,
        review_id=review.id,
        reconciliation_digest=reconciliation_digest,
        features={
            "strategy_code": decision.strategy_code,
            "strategy_version": decision.strategy_version,
            "policy_id": decision.policy_id,
            "actual_contract": decision.actual_contract,
            "trading_day": decision.trading_day.isoformat(),
            "bar_end": decision.bar_end.isoformat(),
            "result_kind": decision.result_kind,
            "direction": decision.direction,
        },
        outcome={
            "reconciliation_outcome": reconciliation.outcome,
            "data_changed": reconciliation.data_changed,
            "result_changed": reconciliation.result_changed,
        },
        labels={
            "market_phase": review.market_phase,
            "is_system_compliant": review.is_system_compliant,
            "rule_tags": list(review.rule_tags),
            "mistake_tags": list(review.mistake_tags or []),
            "emotion_tags": list(review.emotion_tags or []),
            "lesson": review.lesson,
        },
        lineage={
            "dataset_key": decision.dataset_key,
            "manifest_digest": decision.manifest_digest,
            "input_digest": decision.input_digest,
            "fingerprint": decision.fingerprint,
            "result_digest": decision.result_digest,
        },
    )
    session.add(sample)
    session.flush()
    return sample
