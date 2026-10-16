"""Transaction-local Reference guards; callers own sessions and commit boundaries.

Source checks retain row locking and exact reconciliation queries. These helpers
never open a transaction, schedule reads, or commit persisted changes.
"""

from hashlib import sha256
import json

from sqlalchemy import select

from app.reference_trading.forward_inputs import ForwardInputUnavailable
from app.reference_trading.models import (
    ReferenceActivationReceipt,
    ReferenceBatch,
    ReferenceCaptureReconciliation,
    ReferenceStream,
)


def _hash(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def receipt_hash(receipt):
    return _hash(
        {
            column.name: getattr(receipt, column.name)
            for column in receipt.__table__.columns
        }
    )


def consumed_bound_receipt(session, receipt, revision):
    """A previous one-shot interruption grants no automatic future recovery.

    It may be renewed only after its exact generation/hash capture was consumed
    by a committed calculation in this active revision. Uncertain/pending work
    can never grant the next explicit task-local plan.
    """
    bound = receipt.budget.get("bounded_recovery_capture_sha256")
    if (
        receipt.recovery_policy != "interrupt_and_restart"
        or not isinstance(bound, str)
        or len(bound) != 64
    ):
        return False
    previous = session.scalar(
        select(ReferenceActivationReceipt).where(
            ReferenceActivationReceipt.stream_id == receipt.stream_id,
            ReferenceActivationReceipt.generation == receipt.generation - 1,
        )
    )
    if previous is None or receipt.budget.get(
        "previous_receipt_sha256"
    ) != receipt_hash(previous):
        return False
    additions = {
        "bounded_recovery_capture_sha256",
        "previous_receipt_sha256",
        "journal_proof_sha256",
    }
    if (
        {k: v for k, v in receipt.budget.items() if k not in additions}
        != {k: v for k, v in previous.budget.items() if k not in additions}
        or not isinstance(receipt.budget.get("journal_proof_sha256"), str)
        or len(receipt.budget["journal_proof_sha256"]) != 64
    ):
        return False
    captures = session.scalars(
        select(ReferenceBatch).where(
            ReferenceBatch.stream_id == receipt.stream_id,
            ReferenceBatch.revision_id == receipt.revision_id,
            ReferenceBatch.kind == "capture",
            ReferenceBatch.payload_hash == bound,
        )
    ).all()
    if len(captures) != 1:
        return False
    capture = captures[0]
    source = capture.source_evidence.get("forward_capture_v1", {})
    calculation = (
        session.get(ReferenceBatch, capture.consumed_by_batch_id)
        if capture.consumed_by_batch_id
        else None
    )
    proof = (
        calculation.source_evidence.get("forward_capture_v1", {}) if calculation else {}
    )
    return (
        source.get("generation") == receipt.generation
        and source.get("hash") == bound
        and source.get("source_kind") == "observation_interruption"
        and calculation is not None
        and calculation.kind == "calculation"
        and calculation.outcome == "committed"
        and calculation.stream_id == capture.stream_id
        and calculation.revision_id == capture.revision_id
        and proof.get("capture_id") == capture.batch_id
        and proof.get("hash") == bound
        and proof.get("generation") == receipt.generation
        and capture.expected_seq is not None
        and calculation.seq == capture.expected_seq + 1
        and calculation.seq <= revision.last_seq
    )


def assert_source_allowed(session, stream_id):
    stream = session.execute(
        select(ReferenceStream)
        .where(
            ReferenceStream.stream_id == stream_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    mismatch = session.scalar(
        select(ReferenceCaptureReconciliation.reconciliation_id)
        .join(
            ReferenceBatch,
            ReferenceBatch.batch_id == ReferenceCaptureReconciliation.capture_batch_id,
        )
        .join(
            ReferenceStream,
            ReferenceStream.stream_id == ReferenceBatch.stream_id,
        )
        .where(
            ReferenceBatch.stream_id == stream_id,
            ReferenceBatch.revision_id == ReferenceStream.active_revision_id,
            ReferenceCaptureReconciliation.status == "mismatch",
        )
        .limit(1)
    )
    if stream is not None:
        from app.reference_trading.original_conflict import original_conflict_evidence

        routes = session.scalars(
            select(ReferenceStream.stream_id).where(
                ReferenceStream.product == stream.product,
                ReferenceStream.frequency == stream.frequency,
                ReferenceStream.recording_mode == "forward_observation",
                ReferenceStream.enabled.is_(True),
            )
        ).all()
        if original_conflict_evidence(session, routes):
            raise ForwardInputUnavailable("ORIGINAL_OBSERVATION_CANONICAL_CONFLICT")
    if mismatch is not None:
        raise ForwardInputUnavailable("REFERENCE_CANONICAL_MISMATCH")
    if stream is not None and stream.strategy_code == "newow_dual_fusion":
        for code in ("newow_trend", "newow_oscillation"):
            ids = session.scalars(
                select(ReferenceStream.stream_id).where(
                    ReferenceStream.strategy_code == code,
                    ReferenceStream.product == stream.product,
                    ReferenceStream.frequency == stream.frequency,
                    ReferenceStream.recording_mode == "forward_observation",
                    ReferenceStream.enabled.is_(True),
                )
            ).all()
            for base_id in sorted(ids):
                assert_source_allowed(session, base_id)
