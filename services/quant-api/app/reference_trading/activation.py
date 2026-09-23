"""Explicit, fail-closed forward activation. Importing this module has no side effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from uuid import uuid4

from sqlalchemy import select

from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json

from app.reference_trading.models import (
    ReferenceActivationReceipt, ReferenceBatch, ReferenceRevision, ReferenceStream,
)
from app.reference_trading.repository import RepositoryConflict, _identity_from_row


def _instant(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class ActivationPlan:
    stream_id: str
    revision_id: str
    row_version: int
    checkpoint_hash: str
    dependency_digest: str
    host: str
    environment: str
    recording_start: datetime
    expires_at: datetime
    budget: dict[str, int]
    model_acceptance_id: str | None
    recovery_policy: str
    plan_hash: str


class ForwardActivation:
    def __init__(
        self, session_factory, *,
        accepted_models: frozenset[tuple[str, str, str, str, str]] = frozenset(),
    ):
        self._factory = session_factory
        self._accepted_models = accepted_models

    def plan(
        self, stream_id: str, revision_id: str, *, host: str, environment: str,
        recording_start: datetime, expires_at: datetime, budget: dict[str, int],
        model_acceptance_id: str | None = None,
        recovery_policy: str = "block",
    ) -> ActivationPlan:
        _instant(recording_start, "recording_start")
        _instant(expires_at, "expires_at")
        if recovery_policy not in {"block", "interrupt_and_restart"}:
            raise ValueError("RECOVERY_POLICY_INVALID")
        if not host or not environment or not budget or any(
            type(value) is not int or value <= 0 for value in budget.values()
        ):
            raise ValueError("ACTIVATION_PLAN_INVALID")
        with self._factory() as session:
            stream = session.get(ReferenceStream, stream_id)
            revision = session.get(ReferenceRevision, (stream_id, revision_id))
            if stream is None or revision is None:
                raise RepositoryConflict("STREAM_OR_REVISION_NOT_FOUND")
            if stream.recording_mode != RecordingMode.FORWARD_OBSERVATION.value:
                raise RepositoryConflict("MODE_CONFLICT")
            if stream.enabled or stream.activation_generation != 0 or stream.active_revision_id is not None:
                raise RepositoryConflict("ACTIVATION_ALREADY_USED")
            if revision.status != "candidate" or revision.checkpoint_batch_id is None or revision.last_seq != 1:
                raise RepositoryConflict("REVISION_NOT_PUBLISHABLE")
            batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            if batch is None or batch.kind != "seed_seal" or not batch.checkpoint_text or not batch.strategy_schema:
                raise RepositoryConflict("SEED_NOT_SEALED")
            checkpoint = adapter_checkpoint_from_json(
                batch.checkpoint_text, expected_stream=_identity_from_row(stream),
                expected_strategy_schema=batch.strategy_schema,
            )
            if checkpoint.reference_state != ReferenceState.flat(
                checkpoint.stream, recording_start=recording_start,
            ):
                raise RepositoryConflict("FORWARD_SEED_NOT_FLAT")
            acceptance = (
                model_acceptance_id, stream.reference_model_version,
                stream.observation_policy_version, stream.product, stream.frequency,
            )
            if stream.strategy_code.startswith("htdy") and acceptance not in self._accepted_models:
                raise RepositoryConflict("MODEL_NOT_APPROVED")
            payload = {
                "stream_id": stream_id, "revision_id": revision_id,
                "row_version": stream.row_version, "checkpoint_hash": batch.post_state_hash,
                "dependency_digest": revision.dependency_digest, "host": host,
                "environment": environment, "recording_start": recording_start.isoformat(),
                "expires_at": expires_at.isoformat(), "budget": budget,
                "model_acceptance_id": model_acceptance_id,
                "recovery_policy": recovery_policy,
            }
            digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            return ActivationPlan(
                stream_id, revision_id, stream.row_version, batch.post_state_hash,
                revision.dependency_digest, host, environment, recording_start,
                expires_at, dict(budget), model_acceptance_id, recovery_policy, digest,
            )

    def apply(self, plan: ActivationPlan, *, expected_plan_hash: str, now: datetime) -> str:
        _instant(now, "now")
        if expected_plan_hash != plan.plan_hash:
            raise RepositoryConflict("PLAN_HASH_CONFLICT")
        with self._factory() as session:
            stream = session.get(ReferenceStream, plan.stream_id)
            if stream is not None and stream.enabled and stream.activation_plan_hash == plan.plan_hash:
                receipt = session.scalar(select(ReferenceActivationReceipt).where(
                    ReferenceActivationReceipt.stream_id == plan.stream_id,
                    ReferenceActivationReceipt.plan_hash == plan.plan_hash,
                    ReferenceActivationReceipt.disabled_at.is_(None),
                ))
                if receipt is not None:
                    return receipt.receipt_id
        if now > plan.expires_at or plan.recording_start < now:
            raise RepositoryConflict("PLAN_EXPIRED_OR_START_IN_PAST")
        # Replanning verifies every mutable input, including checkpoint and acceptance.
        fresh = self.plan(
            plan.stream_id, plan.revision_id, host=plan.host, environment=plan.environment,
            recording_start=plan.recording_start, expires_at=plan.expires_at,
            budget=plan.budget, model_acceptance_id=plan.model_acceptance_id,
            recovery_policy=plan.recovery_policy,
        )
        if fresh != plan:
            raise RepositoryConflict("ACTIVATION_DEPENDENCY_DRIFT")
        with self._factory() as session, session.begin():
            stream = session.execute(select(ReferenceStream).where(
                ReferenceStream.stream_id == plan.stream_id,
            ).with_for_update()).scalar_one()
            revision = session.execute(select(ReferenceRevision).where(
                ReferenceRevision.stream_id == plan.stream_id,
                ReferenceRevision.revision_id == plan.revision_id,
            ).with_for_update()).scalar_one()
            if (
                stream.enabled or stream.activation_generation != 0 or stream.row_version != plan.row_version
                or stream.active_revision_id is not None or revision.status != "candidate"
                or revision.dependency_digest != plan.dependency_digest
            ):
                raise RepositoryConflict("ACTIVATION_DEPENDENCY_DRIFT")
            batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            if batch is None or batch.post_state_hash != plan.checkpoint_hash:
                raise RepositoryConflict("ACTIVATION_DEPENDENCY_DRIFT")
            stream.active_revision_id = revision.revision_id
            stream.latest_seq = revision.last_seq
            stream.enabled = True
            stream.activation_generation = 1
            stream.row_version += 1
            stream.recording_start = plan.recording_start
            stream.activation_plan_hash = plan.plan_hash
            stream.health = "READY"
            revision.status = "active"
            receipt_id = uuid4().hex
            session.add(ReferenceActivationReceipt(
                receipt_id=receipt_id, stream_id=plan.stream_id,
                revision_id=plan.revision_id, generation=1, plan_hash=plan.plan_hash,
                recording_start=plan.recording_start, activated_at=now,
                environment=plan.environment, host=plan.host, budget=plan.budget,
                recovery_policy=plan.recovery_policy,
            ))
            return receipt_id

    def disable(self, stream_id: str, *, expected_generation: int, now: datetime) -> None:
        _instant(now, "now")
        with self._factory() as session, session.begin():
            stream = session.execute(select(ReferenceStream).where(
                ReferenceStream.stream_id == stream_id,
            ).with_for_update()).scalar_one_or_none()
            if stream is None or not stream.enabled or stream.activation_generation != expected_generation:
                raise RepositoryConflict("ACTIVATION_GENERATION_CONFLICT")
            receipt = session.scalar(select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.stream_id == stream_id,
                ReferenceActivationReceipt.generation == expected_generation,
            ))
            if receipt is None:
                raise RepositoryConflict("ACTIVATION_RECEIPT_MISSING")
            receipt.disabled_at = now
            stream.enabled = False
            stream.activation_generation += 1
            stream.row_version += 1
            stream.health = "DISABLED"
