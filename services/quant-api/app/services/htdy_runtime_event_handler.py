"""Authorized Runtime adapter for the exact HTDY first-seen path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import logging
from typing import Any

from sqlalchemy.orm import Session


LOGGER = logging.getLogger(__name__)


@dataclass
class ClosedBarEvaluationCheckpoint:
    last_bucket_end: datetime | None = None


class HtDyRuntimeEventHandler:
    """Compose Step 2 snapshot/evaluator with the Step 3 immutable writer."""

    def __init__(
        self,
        session: Session | None = None,
        *,
        resolver: Any | None = None,
        evaluator: Any | None = None,
        writer: Any | None = None,
    ) -> None:
        if resolver is None or evaluator is None or writer is None:
            if session is None:
                raise ValueError("HTDY_RUNTIME_SESSION_REQUIRED")
            from app.core.env import PROJECT_ROOT
            from app.services.htdy_first_seen_events import (
                HtDyFirstSeenEventService,
            )
            from app.services.htdy_realtime_evaluator import (
                HtDyRealtimeCandidateEvaluator,
            )
            from app.services.htdy_realtime_snapshot import (
                HtDyRealtimeSnapshotResolver,
            )

            resolver = resolver or HtDyRealtimeSnapshotResolver(
                session,
                project_root=PROJECT_ROOT,
            )
            evaluator = evaluator or HtDyRealtimeCandidateEvaluator()
            writer = writer or HtDyFirstSeenEventService(session)
        self.resolver = resolver
        self.evaluator = evaluator
        self.writer = writer

    def evaluate_and_persist(
        self,
        *,
        trading_day: date,
        actual_contract: str,
        detected_at: datetime,
    ) -> Any:
        snapshot = self.resolver.resolve(
            trading_day=trading_day,
            detected_at=detected_at,
            requested_contract=actual_contract,
        )
        evaluation = self.evaluator.evaluate(
            snapshot,
            detected_at=detected_at,
        )
        result = self.writer.persist(evaluation)
        buckets = tuple(getattr(snapshot, "buckets", ()))
        if not all(
            hasattr(snapshot, name)
            for name in (
                "trading_day",
                "actual_contract",
                "snapshot_sha256",
            )
        ) or not all(
            hasattr(evaluation, name)
            for name in ("candidates", "blocked")
        ) or not all(
            hasattr(result, name)
            for name in ("created", "unchanged", "event_ids")
        ):
            return result
        latest_bucket = buckets[-1] if buckets else None
        identity = (
            latest_bucket.identity if latest_bucket is not None else None
        )
        event_ids = tuple(result.event_ids)
        payload = {
            "trading_day": snapshot.trading_day.isoformat(),
            "actual_contract": snapshot.actual_contract,
            "bucket_start": (
                identity.bucket_start.isoformat()
                if identity is not None
                else None
            ),
            "bucket_end": (
                identity.bucket_end.isoformat()
                if identity is not None
                else None
            ),
            "bucket_status": (
                latest_bucket.status
                if latest_bucket is not None
                else None
            ),
            "snapshot_sha256": snapshot.snapshot_sha256,
            "candidate_count": len(evaluation.candidates),
            "blocked_count": len(evaluation.blocked),
            "created": result.created,
            "unchanged": result.unchanged,
            "changed": 0,
            "latest_event_id": max(event_ids) if event_ids else None,
        }
        LOGGER.info(
            "htdy_observation_summary %s",
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        return result


class HtDyClosedBarRuntimeEventHandler(HtDyRuntimeEventHandler):
    """Run v1.1 once for each newly confirmed 15m bucket end."""

    def __init__(
        self,
        session: Session | None = None,
        *,
        resolver: Any | None = None,
        evaluator: Any | None = None,
        writer: Any | None = None,
        checkpoint: ClosedBarEvaluationCheckpoint | None = None,
        allowed_bucket_ends: set[datetime] | None = None,
    ) -> None:
        if evaluator is None and session is not None:
            from app.services.htdy_realtime_evaluator import (
                HtDyClosedBarCandidateEvaluator,
            )

            evaluator = HtDyClosedBarCandidateEvaluator()
        super().__init__(
            session,
            resolver=resolver,
            evaluator=evaluator,
            writer=writer,
        )
        self._checkpoint = checkpoint or ClosedBarEvaluationCheckpoint()
        self._allowed_bucket_ends = (
            frozenset(allowed_bucket_ends)
            if allowed_bucket_ends is not None
            else None
        )

    @property
    def last_decision_bucket_end(self) -> datetime | None:
        return self._checkpoint.last_bucket_end

    def evaluate_and_persist(
        self,
        *,
        trading_day: date,
        actual_contract: str,
        detected_at: datetime,
    ) -> Any:
        snapshot = self.resolver.resolve(
            trading_day=trading_day,
            detected_at=detected_at,
            requested_contract=actual_contract,
            confirmed_only=True,
        )
        buckets = tuple(getattr(snapshot, "buckets", ()))
        latest = buckets[-1] if buckets else None
        bucket_end = (
            latest.identity.bucket_end
            if latest is not None and latest.status == "confirmed"
            else None
        )
        if (
            bucket_end is None
            or (
                self._allowed_bucket_ends is not None
                and bucket_end not in self._allowed_bucket_ends
            )
            or (
                self._checkpoint.last_bucket_end is not None
                and bucket_end <= self._checkpoint.last_bucket_end
            )
        ):
            return _empty_write_result()
        evaluation = self.evaluator.evaluate(snapshot, detected_at=detected_at)
        result = self.writer.persist(evaluation)
        self._checkpoint.last_bucket_end = bucket_end
        event_ids = tuple(result.event_ids)
        LOGGER.info(
            "htdy_close_evaluation_summary %s",
            json.dumps(
                {
                    "trading_day": trading_day.isoformat(),
                    "actual_contract": actual_contract,
                    "bucket_end": bucket_end.isoformat(),
                    "bucket_status": "confirmed",
                    "partial_allowed": False,
                    "created": result.created,
                    "unchanged": result.unchanged,
                    "blocked": result.blocked,
                    "event_ids": list(event_ids),
                    "signal_changed": 0,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        return result


def _empty_write_result() -> Any:
    from app.services.htdy_first_seen_events import HtDyFirstSeenWriteResult

    return HtDyFirstSeenWriteResult(
        created=0,
        unchanged=0,
        blocked=0,
        event_ids=(),
        blocked_reasons=(),
    )
