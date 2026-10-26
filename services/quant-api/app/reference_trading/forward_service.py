"""Project immutable pending observations through the existing batch repository."""

from __future__ import annotations

from collections.abc import Callable

from app.reference_trading.contracts import CheckpointToken, CommitResult, PreparedBatch
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict


ForwardEvaluator = Callable[[CheckpointToken, object, dict[str, object]], PreparedBatch]


class ForwardReferenceService:
    def __init__(self, repository: ReferenceRepository, evaluator: ForwardEvaluator, *, commit_guard=None):
        self._repository = repository
        self._evaluator = evaluator
        self._commit_guard = commit_guard

    def process_pending(self, stream_id: str) -> CommitResult | None:
        pending = self._repository.read_pending_capture(stream_id)
        if pending is None:
            return None
        capture_id, stored_evidence = pending
        token, checkpoint = self._repository.load_checkpoint(stream_id)
        capture = stored_evidence.get("forward_capture_v1")
        if not isinstance(capture, dict):
            raise RepositoryConflict("CAPTURE_CORRUPT")
        prepared = self._evaluator(token, checkpoint, {
            **stored_evidence, "capture_id": capture_id,
        })
        if not isinstance(prepared, PreparedBatch):
            raise TypeError("forward evaluator must return PreparedBatch")
        proof = prepared.source_evidence.get("forward_capture_v1")
        if (
            not isinstance(proof, dict)
            or proof.get("capture_id") != capture_id
            or proof.get("hash") != capture.get("hash")
            or proof.get("generation") != capture.get("generation")
            or prepared.expected != token
        ):
            raise RepositoryConflict("FORWARD_CAPTURE_CONFLICT")
        original_proof = capture.get("source_proof", {})
        if original_proof.get("inbox_delivery_id"):
            from dataclasses import replace
            from datetime import UTC, datetime
            confirmed = datetime.fromisoformat(capture["observed_at"])
            calculated = datetime.now(UTC)
            lag = max(0.0, (calculated - confirmed).total_seconds())
            timing = {"protocol": "reference_receiving_v2",
                "raw_received_at": original_proof.get("raw_received_at"),
                "confirmed_at": confirmed.isoformat(),
                "ingested_at": original_proof.get("ingested_at"),
                "calculated_at": calculated.isoformat(), "calculation_delay_seconds": lag,
                "processing_mode": "delayed_original" if lag > 30 else "original"}
            evidence = {**prepared.source_evidence, "delivery_timing_v2": timing}
            display = evidence.get("presentation_v1")
            if isinstance(display, dict):
                evidence["presentation_v1"] = {**display, "points": [
                    {**point, "value": {**point["value"], "delivery": timing}}
                    if isinstance(point.get("value"), dict) else point
                    for point in display.get("points", [])]}
            prepared = replace(prepared, source_evidence=evidence)
        try:
            if self._commit_guard is None:
                return self._repository.commit_batch(token, prepared)
            return self._repository.commit_batch(token, prepared, commit_guard=self._commit_guard)
        except Exception as error:
            # The transaction result is uncertain only for connection/commit failures.
            # Read back the exact batch once; never replay an unknown calculation.
            if isinstance(error, (RepositoryConflict, TypeError, ValueError)):
                raise
            result = self._repository.read_prepared_batch(prepared)
            if result is not None:
                return result
            raise RepositoryConflict("FORWARD_COMMIT_OUTCOME_UNKNOWN") from error
