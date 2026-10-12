"""Exact, append-only activation renewal for one proven observation interruption.

Caller freezes the retained journal and authoritative missing Session endpoints.
This entry point never reads provider history, changes a cursor or sends a notice.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.reference_trading.capture import ForwardCapture
from app.reference_trading.models import (
    ReferenceActivationReceipt, ReferenceBatch, ReferenceRevision, ReferenceStream,
)
from app.reference_trading.recovery import capture_observation_gap
from app.reference_trading.repository import RepositoryConflict, _identity_from_row
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _receipt_hash(receipt):
    return _hash({column.name: getattr(receipt, column.name)
                  for column in receipt.__table__.columns})


@dataclass(frozen=True)
class BoundedRecoveryPlan:
    capture: ForwardCapture
    row_version: int
    checkpoint_batch_id: str
    checkpoint_hash: str
    receipt_id: str
    receipt_hash: str
    dependency_digest: str
    expires_at: datetime
    journal_proof: dict
    plan_hash: str


class BoundedForwardRecovery:
    def __init__(self, session_factory, *, verify_gap):
        """verify_gap rechecks retained envelope/hash and authoritative endpoints.

        It must raise on drift; it returns the exact missing endpoint tuple. No
        provider or Canonical Bar can stand in for an original forward observation.
        """
        self._factory = session_factory
        self._verify_gap = verify_gap

    def plan(self, stream_id, *, endpoints, trading_day, observed_at, expires_at,
             journal_proof):
        if (not endpoints or tuple(sorted(set(endpoints))) != tuple(endpoints)
                or observed_at.tzinfo is None or expires_at.tzinfo is None
                or expires_at <= observed_at or not journal_proof):
            raise ValueError("RECOVERY_PLAN_INVALID")
        with self._factory() as session:
            return self._plan(session, stream_id, endpoints=tuple(endpoints),
                              trading_day=trading_day, observed_at=observed_at,
                              expires_at=expires_at, journal_proof=journal_proof)

    def _plan(self, session, stream_id, *, endpoints, trading_day, observed_at,
              expires_at, journal_proof):
        stream = session.get(ReferenceStream, stream_id)
        if (stream is None or not stream.enabled or stream.active_revision_id is None
                or stream.recording_mode != "forward_observation" or stream.recording_start is None):
            raise RepositoryConflict("FORWARD_ACTIVATION_INVALID")
        revision = session.get(ReferenceRevision, (stream_id, stream.active_revision_id))
        receipt = session.scalar(select(ReferenceActivationReceipt).where(
            ReferenceActivationReceipt.stream_id == stream_id,
            ReferenceActivationReceipt.generation == stream.activation_generation,
        ))
        batch = session.get(ReferenceBatch, revision.checkpoint_batch_id) if revision else None
        if (receipt is None or receipt.disabled_at is not None or receipt.recovery_policy != "block"
                or receipt.revision_id != revision.revision_id
                or observed_at.timestamp() < stream.recording_start.timestamp()
                or batch is None or not batch.checkpoint_text or revision.status != "active"
                or revision.last_seq != stream.latest_seq or batch.seq != revision.last_seq):
            raise RepositoryConflict("RECOVERY_PREIMAGE_INVALID")
        identity = _identity_from_row(stream)
        if not identity.strategy_code.replace("-", "_").startswith("newow_") or identity.frequency != "60m":
            raise RepositoryConflict("RECOVERY_SCOPE_INVALID")
        pending = session.scalar(select(ReferenceBatch.batch_id).where(
            ReferenceBatch.stream_id == stream_id,
            ReferenceBatch.revision_id == revision.revision_id,
            ReferenceBatch.kind == "capture", ReferenceBatch.consumed_by_batch_id.is_(None),
        ).limit(1))
        if pending is not None:
            raise RepositoryConflict("PENDING_CAPTURE_FIRST")
        checkpoint = adapter_checkpoint_from_json(batch.checkpoint_text,
            expected_stream=identity, expected_strategy_schema=batch.strategy_schema)
        verified = self._verify_gap(identity, checkpoint.computed_through, journal_proof)
        if tuple(verified) != endpoints:
            raise RepositoryConflict("RECOVERY_SOURCE_DRIFT")
        capture = capture_observation_gap(identity, revision_id=revision.revision_id,
            generation=stream.activation_generation + 1,
            previous_watermark=checkpoint.computed_through, observed_at=observed_at,
            reason="OBSERVATION_GAP", trading_day=trading_day, endpoints=endpoints,
            interruption_end=endpoints[-1])
        values = (capture.capture_hash, stream.row_version, batch.batch_id,
                  batch.post_state_hash, receipt.receipt_id, _receipt_hash(receipt),
                  revision.dependency_digest, expires_at.isoformat(), journal_proof)
        return BoundedRecoveryPlan(capture, stream.row_version, batch.batch_id,
            batch.post_state_hash, receipt.receipt_id, _receipt_hash(receipt),
            revision.dependency_digest, expires_at, dict(journal_proof), _hash(values))

    def readback(self, plan):
        """Independent exact readback; None never grants an unknown attempt retry."""
        with self._factory() as session:
            receipt = session.scalar(select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.stream_id == plan.capture.stream_id,
                ReferenceActivationReceipt.plan_hash == plan.plan_hash))
            capture = session.scalar(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == plan.capture.stream_id,
                ReferenceBatch.revision_id == plan.capture.revision_id,
                ReferenceBatch.batch_key == plan.capture.batch_key))
            if receipt is None and capture is None:
                return None
            old = session.get(ReferenceActivationReceipt, plan.receipt_id)
            if (receipt is None or capture is None or old is None
                    or _receipt_hash(old) != plan.receipt_hash
                    or receipt.generation != plan.capture.generation
                    or receipt.budget.get("bounded_recovery_capture_sha256") != plan.capture.capture_hash
                    or capture.payload_hash != plan.capture.capture_hash):
                raise RepositoryConflict("RECOVERY_READBACK_CONFLICT")
            return receipt.receipt_id, capture.batch_id

    def apply(self, plan, *, expected_plan_hash, now):
        try:
            return self._apply(plan, expected_plan_hash=expected_plan_hash, now=now)
        except SQLAlchemyError as error:
            # Never repeat a mutation after an uncertain connection/commit.
            try:
                result = self.readback(plan)
            except SQLAlchemyError:
                result = None
            if result is not None:
                return result
            raise RepositoryConflict("RECOVERY_COMMIT_OUTCOME_UNKNOWN") from error

    def _apply(self, plan, *, expected_plan_hash, now):
        if expected_plan_hash != plan.plan_hash or now.tzinfo is None:
            raise RepositoryConflict("PLAN_HASH_CONFLICT")
        with self._factory() as session, session.begin():
            stream = session.execute(select(ReferenceStream).where(
                ReferenceStream.stream_id == plan.capture.stream_id).with_for_update()).scalar_one()
            revision = session.execute(select(ReferenceRevision).where(
                ReferenceRevision.stream_id == plan.capture.stream_id,
                ReferenceRevision.revision_id == plan.capture.revision_id).with_for_update()).scalar_one()
            existing = session.scalar(select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.stream_id == plan.capture.stream_id,
                ReferenceActivationReceipt.plan_hash == plan.plan_hash))
            if existing is not None:
                capture = session.scalar(select(ReferenceBatch).where(
                    ReferenceBatch.stream_id == plan.capture.stream_id,
                    ReferenceBatch.revision_id == plan.capture.revision_id,
                    ReferenceBatch.batch_key == plan.capture.batch_key))
                old = session.get(ReferenceActivationReceipt, plan.receipt_id)
                if (capture is None or capture.payload_hash != plan.capture.capture_hash
                        or old is None or _receipt_hash(old) != plan.receipt_hash
                        or existing.generation != plan.capture.generation
                        or existing.budget.get("bounded_recovery_capture_sha256") != plan.capture.capture_hash):
                    raise RepositoryConflict("RECOVERY_READBACK_CONFLICT")
                return existing.receipt_id, capture.batch_id
            if now > plan.expires_at or now < plan.capture.observed_at:
                raise RepositoryConflict("PLAN_EXPIRED")
            fresh = self._plan(session, plan.capture.stream_id,
                endpoints=tuple(datetime.fromisoformat(item) for item in plan.capture.source_proof["gap_endpoints"]),
                trading_day=date.fromisoformat(plan.capture.input_payload["trading_day"]),
                observed_at=plan.capture.observed_at, expires_at=plan.expires_at,
                journal_proof=plan.journal_proof)
            if fresh != plan:
                raise RepositoryConflict("RECOVERY_PREIMAGE_DRIFT")
            old_receipt = session.get(ReferenceActivationReceipt, plan.receipt_id)
            budget = dict(old_receipt.budget)
            budget.update(bounded_recovery_capture_sha256=plan.capture.capture_hash,
                          previous_receipt_sha256=plan.receipt_hash,
                          journal_proof_sha256=_hash(plan.journal_proof))
            receipt_id, capture_id = uuid4().hex, uuid4().hex
            session.add(ReferenceActivationReceipt(receipt_id=receipt_id,
                stream_id=stream.stream_id, revision_id=revision.revision_id,
                generation=plan.capture.generation, plan_hash=plan.plan_hash,
                recording_start=stream.recording_start, activated_at=now,
                environment=old_receipt.environment, host=old_receipt.host,
                budget=budget, recovery_policy="interrupt_and_restart"))
            # The new receipt and exact pending interruption commit together.
            # Existing receipt/checkpoint/batches stay byte-for-byte unchanged.
            session.add(ReferenceBatch(batch_id=capture_id, stream_id=stream.stream_id,
                revision_id=revision.revision_id, batch_key=plan.capture.batch_key,
                payload_hash=plan.capture.capture_hash, kind="capture", outcome="pending",
                seq=None, expected_seq=revision.last_seq, dependency_manifest={},
                source_evidence=plan.capture.evidence(), projected_action_pks=[], diagnostics=[],
                observed_at=plan.capture.observed_at, processed_at=now))
            stream.activation_generation = plan.capture.generation
            stream.activation_plan_hash = plan.plan_hash
            stream.row_version += 1
            stream.health = "RECOVERY_PENDING"
            return receipt_id, capture_id
