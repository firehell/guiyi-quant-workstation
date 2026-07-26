"""Authorized Runtime adapter for the exact HTDY first-seen path."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session


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
            from app.services.htdy_first_seen_events import (
                HtDyFirstSeenEventService,
            )
            from app.services.htdy_realtime_evaluator import (
                HtDyRealtimeCandidateEvaluator,
            )
            from app.services.htdy_realtime_snapshot import (
                HtDyRealtimeSnapshotResolver,
            )

            resolver = resolver or HtDyRealtimeSnapshotResolver(session)
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
        return self.writer.persist(evaluation)
