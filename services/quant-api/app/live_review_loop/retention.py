from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, inspect as sa_inspect, select, text
from sqlalchemy.orm import Session

from app.live_review_loop.contracts import canonical_digest
from app.models.live_review_loop import (
    LiveObservationBar,
    RetentionRun,
    SignalDecision,
    SignalDecisionReconciliation,
)
from app.models.signal import SignalEvent, SignalNotification


class RetentionDriftError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    cutoff_at: datetime
    ids: dict[str, tuple[int, ...]]
    counts: dict[str, int]
    manifest_digest: str


class RetentionService:
    RETENTION_DAYS = 30

    def __init__(self, session: Session) -> None:
        self.session = session

    def plan(self, *, as_of: datetime) -> RetentionPlan:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("RETENTION_AS_OF_TIMEZONE_REQUIRED")
        cutoff = as_of.astimezone(UTC) - timedelta(days=self.RETENTION_DAYS)
        decision_ids = tuple(
            self.session.scalars(
                select(SignalDecision.id)
                .where(SignalDecision.created_at < cutoff)
                .order_by(SignalDecision.id)
            )
        )
        event_ids = tuple(
            self.session.scalars(
                select(SignalEvent.id)
                .where(SignalEvent.decision_id.in_(decision_ids) if decision_ids else False)
                .order_by(SignalEvent.id)
            )
        )
        ids = {
            "signal_notifications": tuple(
                self.session.scalars(
                    select(SignalNotification.id)
                    .where(SignalNotification.event_id.in_(event_ids) if event_ids else False)
                    .order_by(SignalNotification.id)
                )
            ),
            "signal_events": event_ids,
            "signal_decision_reconciliations": tuple(
                self.session.scalars(
                    select(SignalDecisionReconciliation.id)
                    .where(
                        SignalDecisionReconciliation.decision_id.in_(decision_ids)
                        if decision_ids
                        else False
                    )
                    .order_by(SignalDecisionReconciliation.id)
                )
            ),
            "signal_decisions": decision_ids,
            "live_observation_bars": tuple(
                self.session.scalars(
                    select(LiveObservationBar.id)
                    .where(LiveObservationBar.created_at < cutoff)
                    .order_by(LiveObservationBar.id)
                )
            ),
        }
        counts = {name: len(values) for name, values in ids.items()}
        manifest = self._manifest(cutoff, ids)
        return RetentionPlan(
            cutoff_at=cutoff,
            ids=ids,
            counts=counts,
            manifest_digest=canonical_digest(manifest),
        )

    def apply(self, plan: RetentionPlan) -> dict[str, int]:
        if not self.session.in_transaction():
            raise RuntimeError("RETENTION_TRANSACTION_REQUIRED")
        self._validate_plan(plan)
        self._lock_tables()
        self._lock_targets(plan)
        fresh = self.plan(as_of=plan.cutoff_at + timedelta(days=self.RETENTION_DAYS))
        if fresh.manifest_digest != plan.manifest_digest or fresh.ids != plan.ids:
            raise RetentionDriftError("RETENTION_PLAN_DRIFT")
        models = {
            "signal_notifications": SignalNotification,
            "signal_events": SignalEvent,
            "signal_decision_reconciliations": SignalDecisionReconciliation,
            "signal_decisions": SignalDecision,
            "live_observation_bars": LiveObservationBar,
        }
        result: dict[str, int] = {}
        for name in (
            "signal_notifications",
            "signal_events",
            "signal_decision_reconciliations",
            "signal_decisions",
            "live_observation_bars",
        ):
            target_ids = plan.ids[name]
            if not target_ids:
                result[name] = 0
                continue
            statement = delete(models[name]).where(models[name].id.in_(target_ids))
            outcome = self.session.execute(statement)
            result[name] = int(outcome.rowcount or 0)
            if result[name] != len(target_ids):
                raise RetentionDriftError("RETENTION_DELETE_COUNT_DRIFT")
        self.session.add(
            RetentionRun(
                cutoff_at=plan.cutoff_at,
                manifest_digest=plan.manifest_digest,
                target_counts=plan.counts,
                result=result,
            )
        )
        self.session.flush()
        return result

    def _validate_plan(self, plan: RetentionPlan) -> None:
        if not isinstance(plan, RetentionPlan):
            raise TypeError("RETENTION_PLAN_TYPE_REQUIRED")
        if plan.cutoff_at.tzinfo is None or plan.cutoff_at.utcoffset() is None:
            raise ValueError("RETENTION_PLAN_CUTOFF_TIMEZONE_REQUIRED")
        if len(plan.manifest_digest) != 64:
            raise ValueError("RETENTION_PLAN_DIGEST_INVALID")
        if plan.counts != {name: len(values) for name, values in plan.ids.items()}:
            raise ValueError("RETENTION_PLAN_COUNTS_INVALID")

    def _lock_tables(self) -> None:
        bind = self.session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        self.session.execute(
            text(
                "LOCK TABLE signal_notifications, signal_events, "
                "signal_decision_reconciliations, signal_decisions, "
                "live_observation_bars IN SHARE ROW EXCLUSIVE MODE"
            )
        )

    def _lock_targets(self, plan: RetentionPlan) -> None:
        models = {
            "signal_notifications": SignalNotification,
            "signal_events": SignalEvent,
            "signal_decision_reconciliations": SignalDecisionReconciliation,
            "signal_decisions": SignalDecision,
            "live_observation_bars": LiveObservationBar,
        }
        for name, model in models.items():
            target_ids = plan.ids[name]
            if target_ids:
                self.session.execute(
                    select(model.id)
                    .where(model.id.in_(target_ids))
                    .order_by(model.id)
                    .with_for_update()
                ).all()

    def _manifest(self, cutoff: datetime, ids: dict[str, tuple[int, ...]]) -> dict[str, Any]:
        models = {
            "signal_notifications": SignalNotification,
            "signal_events": SignalEvent,
            "signal_decision_reconciliations": SignalDecisionReconciliation,
            "signal_decisions": SignalDecision,
            "live_observation_bars": LiveObservationBar,
        }
        rows: dict[str, list[dict[str, Any]]] = {}
        for name, model in models.items():
            target_ids = ids[name]
            values = [] if not target_ids else list(
                self.session.scalars(select(model).where(model.id.in_(target_ids)).order_by(model.id))
            )
            rows[name] = [_row_payload(value) for value in values]
        return {"schema_version": "retention_plan_v1", "cutoff_at": cutoff, "rows": rows}


def _row_payload(row: Any) -> dict[str, Any]:
    mapper = sa_inspect(type(row))
    payload: dict[str, Any] = {}
    for column in mapper.columns:
        value = getattr(row, column.key)
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        payload[column.key] = value
    return payload
