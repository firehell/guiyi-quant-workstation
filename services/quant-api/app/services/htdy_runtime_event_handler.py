"""Authorized Runtime adapter for the exact HTDY first-seen path."""

from __future__ import annotations

from datetime import date, datetime
import json
import logging
from typing import Any

from sqlalchemy.orm import Session


LOGGER = logging.getLogger(__name__)


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
