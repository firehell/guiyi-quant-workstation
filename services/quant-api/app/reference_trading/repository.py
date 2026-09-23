"""Transactional repository for durable reference-trading projections."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from uuid import uuid4

from dataclasses import fields, is_dataclass, replace

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from guiyi_quant.reference_trading import (
    ActionKind,
    RecordingMode,
    ReferenceAction,
    ReferenceMark,
    ReferenceState,
    ReferenceTrade,
    Side,
    StreamIdentity,
    TradeStatus,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_from_json,
    adapter_checkpoint_to_json,
)

from app.reference_trading.contracts import (
    CheckpointToken,
    CommitResult,
    manifest_sha256,
    PreparedBatch,
    SeedChunk,
    SnapshotIdentity,
    StoredPage,
    StoredRevisionState,
    StoredStream,
    validate_dependency_advance,
)
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.models import (
    ReferenceActionRow,
    ReferenceActivationReceipt,
    ReferenceBatch,
    ReferenceMarkRow,
    ReferenceRevision,
    ReferenceStream,
    ReferenceTradeRow,
)


SessionFactory = Callable[[], Session]


class RepositoryConflict(RuntimeError):
    """Stable fail-closed repository error without SQL or connection details."""


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("manifest must be finite canonical JSON") from error


def _digest(value: object) -> str:
    return sha256(_canonical(value).encode()).hexdigest()


def _wire(value: object) -> object:
    """Return a complete deterministic representation for idempotency hashing."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _wire(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _wire(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire(item) for item in value]
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _checkpoint_hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _required_aware(value: datetime | None, field: str) -> datetime:
    aware = _aware(value)
    if aware is None:
        raise RepositoryConflict(f"{field}_CORRUPT")
    return aware


def _identity_from_row(row: ReferenceStream) -> StreamIdentity:
    return StreamIdentity(
        strategy_code=row.strategy_code,
        formula_versions=tuple(row.formula_versions),
        profile_id=row.profile_id,
        reference_model_version=row.reference_model_version,
        futures_adaptation_version=row.futures_adaptation_version,
        product=row.product,
        frequency=row.frequency,
        series_kind=row.series_kind,
        recording_mode=RecordingMode(row.recording_mode),
        observation_policy_version=row.observation_policy_version,
    )


def _stored(row: ReferenceStream) -> StoredStream:
    return StoredStream(
        row.stream_id, row.enabled, row.active_revision_id, row.latest_seq,
        row.row_version, row.health,
    )


class ReferenceRepository:
    def __init__(self, session_factory: SessionFactory, *, fault_injector=None) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory
        self._fault_injector = fault_injector or (lambda _stage: None)

    def ensure_stream(self, identity: StreamIdentity) -> StoredStream:
        if not isinstance(identity, StreamIdentity):
            raise TypeError("identity must be StreamIdentity")
        identity_hash = identity.stream_id.removeprefix("reference-stream:")
        with self._session_factory() as session, session.begin():
            row = session.get(ReferenceStream, identity.stream_id)
            if row is None:
                row = ReferenceStream(
                    stream_id=identity.stream_id,
                    identity_hash=identity_hash,
                    strategy_code=identity.strategy_code,
                    formula_versions=list(identity.formula_versions),
                    profile_id=identity.profile_id,
                    reference_model_version=identity.reference_model_version,
                    futures_adaptation_version=identity.futures_adaptation_version,
                    product=identity.product,
                    frequency=identity.frequency,
                    series_kind=identity.series_kind,
                    recording_mode=identity.recording_mode.value,
                    observation_policy_version=identity.observation_policy_version,
                )
                session.add(row)
                session.flush()
            elif _identity_from_row(row) != identity or row.identity_hash != identity_hash:
                raise RepositoryConflict("STREAM_IDENTITY_CONFLICT")
            result = _stored(row)
        return result

    def capture_forward(self, capture: ForwardCapture) -> str:
        """Persist one immutable observation without advancing reference state."""
        if not isinstance(capture, ForwardCapture):
            raise TypeError("capture must be ForwardCapture")
        with self._session_factory() as session, session.begin():
            stream = session.execute(select(ReferenceStream).where(
                ReferenceStream.stream_id == capture.stream_id,
            ).with_for_update()).scalar_one_or_none()
            if stream is None or stream.recording_mode != RecordingMode.FORWARD_OBSERVATION.value:
                raise RepositoryConflict("STREAM_NOT_FORWARD")
            revision = session.execute(select(ReferenceRevision).where(
                ReferenceRevision.stream_id == capture.stream_id,
                ReferenceRevision.revision_id == capture.revision_id,
            ).with_for_update()).scalar_one_or_none()
            if (
                revision is None or revision.status != "active"
                or stream.active_revision_id != capture.revision_id
                or not stream.enabled or stream.activation_generation != capture.generation
            ):
                raise RepositoryConflict("ACTIVATION_GENERATION_CONFLICT")
            if stream.recording_start is None or capture.observed_at < _required_aware(
                stream.recording_start, "recording_start",
            ):
                raise RepositoryConflict("BEFORE_RECORDING_START")
            if capture.eligibility == "gap_recovery":
                receipt = session.scalar(select(ReferenceActivationReceipt).where(
                    ReferenceActivationReceipt.stream_id == capture.stream_id,
                    ReferenceActivationReceipt.generation == capture.generation,
                    ReferenceActivationReceipt.disabled_at.is_(None),
                ))
                if receipt is None or receipt.recovery_policy != "interrupt_and_restart":
                    raise RepositoryConflict("RECOVERY_POLICY_NOT_APPROVED")
            existing = session.scalar(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == capture.stream_id,
                ReferenceBatch.revision_id == capture.revision_id,
                ReferenceBatch.batch_key == capture.batch_key,
            ))
            if existing is not None:
                if existing.kind != "capture" or existing.payload_hash != capture.capture_hash:
                    raise RepositoryConflict("CAPTURE_CONTENT_CONFLICT")
                return existing.batch_id
            pending = session.scalar(select(ReferenceBatch.batch_id).where(
                ReferenceBatch.stream_id == capture.stream_id,
                ReferenceBatch.revision_id == capture.revision_id,
                ReferenceBatch.kind == "capture",
                ReferenceBatch.consumed_by_batch_id.is_(None),
            ).limit(1))
            if pending is not None:
                raise RepositoryConflict("PENDING_CAPTURE_FIRST")
            batch_id = uuid4().hex
            session.add(ReferenceBatch(
                batch_id=batch_id, stream_id=capture.stream_id,
                revision_id=capture.revision_id, batch_key=capture.batch_key,
                payload_hash=capture.capture_hash, kind="capture", outcome="pending",
                seq=None, expected_seq=revision.last_seq,
                dependency_manifest={}, source_evidence=capture.evidence(),
                projected_action_pks=[], diagnostics=[], observed_at=capture.observed_at,
                processed_at=datetime.now(UTC),
            ))
            return batch_id

    def read_pending_capture(self, stream_id: str) -> tuple[str, dict[str, object]] | None:
        with self._session_factory() as session:
            stream = session.get(ReferenceStream, stream_id)
            if stream is None or not stream.enabled or stream.active_revision_id is None:
                return None
            row = session.scalar(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == stream_id,
                ReferenceBatch.revision_id == stream.active_revision_id,
                ReferenceBatch.kind == "capture",
                ReferenceBatch.consumed_by_batch_id.is_(None),
            ).order_by(ReferenceBatch.processed_at, ReferenceBatch.batch_id).limit(1))
            return None if row is None else (row.batch_id, dict(row.source_evidence))

    def enabled_forward_stream_ids(
        self, *, limit: int = 512, after: str | None = None,
    ) -> tuple[str, ...]:
        if type(limit) is not int or not 1 <= limit <= 512:
            raise ValueError("limit must be between 1 and 512")
        with self._session_factory() as session:
            query = select(ReferenceStream.stream_id).where(
                ReferenceStream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value,
                ReferenceStream.enabled.is_(True),
            )
            if after is not None:
                query = query.where(ReferenceStream.stream_id > after)
            return tuple(session.scalars(
                query.order_by(ReferenceStream.stream_id).limit(limit),
            ).all())

    def forward_source_context(
        self, stream_id: str,
    ) -> tuple[StreamIdentity, str, int, datetime, datetime | None, str] | None:
        """Freeze the persisted activation and watermark before a source read."""
        with self._session_factory() as session:
            stream = session.get(ReferenceStream, stream_id)
            if (
                stream is None or not stream.enabled
                or stream.recording_mode != RecordingMode.FORWARD_OBSERVATION.value
                or stream.active_revision_id is None or stream.recording_start is None
            ):
                return None
            revision = session.get(ReferenceRevision, (stream_id, stream.active_revision_id))
            if revision is None or revision.status != "active" or revision.checkpoint_batch_id is None:
                raise RepositoryConflict("FORWARD_ACTIVATION_INVALID")
            batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            if batch is None or batch.checkpoint_text is None or batch.strategy_schema is None:
                raise RepositoryConflict("CHECKPOINT_CORRUPT")
            identity = _identity_from_row(stream)
            checkpoint = adapter_checkpoint_from_json(
                batch.checkpoint_text, expected_stream=identity,
                expected_strategy_schema=batch.strategy_schema,
            )
            receipt = session.scalar(select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.stream_id == stream_id,
                ReferenceActivationReceipt.generation == stream.activation_generation,
                ReferenceActivationReceipt.disabled_at.is_(None),
            ))
            if receipt is None:
                raise RepositoryConflict("ACTIVATION_RECEIPT_MISSING")
            return (
                identity, revision.revision_id, stream.activation_generation,
                _required_aware(stream.recording_start, "RECORDING_START"),
                checkpoint.computed_through,
                receipt.recovery_policy,
            )

    def create_revision(
        self, stream_id: str, expected_row_version: int, dependency_digest: str,
    ) -> str:
        if len(dependency_digest) != 64:
            raise ValueError("dependency_digest must be sha256")
        revision_id = uuid4().hex
        with self._session_factory() as session, session.begin():
            stream = session.execute(
                select(ReferenceStream).where(ReferenceStream.stream_id == stream_id).with_for_update()
            ).scalar_one_or_none()
            if stream is None:
                raise RepositoryConflict("STREAM_NOT_FOUND")
            if stream.row_version != expected_row_version:
                raise RepositoryConflict("STALE_CHECKPOINT")
            session.add(ReferenceRevision(
                stream_id=stream_id,
                revision_id=revision_id,
                status="candidate",
                dependency_digest=dependency_digest,
                parent_revision_id=stream.active_revision_id,
            ))
        return revision_id

    def stage_seed_chunk(self, revision_id: str, chunk: SeedChunk) -> None:
        if not isinstance(chunk, SeedChunk):
            raise TypeError("chunk must be SeedChunk")
        payload_hash = sha256(chunk.content.encode()).hexdigest()
        with self._session_factory() as session, session.begin():
            _stream, revision = self._lock_stream_revision_by_revision_id(
                session, revision_id,
            )
            if revision.status != "candidate" or revision.checkpoint_batch_id is not None:
                raise RepositoryConflict("REVISION_NOT_SEEDABLE")
            existing = session.execute(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == revision.stream_id,
                ReferenceBatch.revision_id == revision_id,
                ReferenceBatch.batch_key == chunk.batch_key,
            )).scalar_one_or_none()
            if existing is not None:
                if (
                    existing.payload_hash == payload_hash
                    and existing.seed_chunk_index == chunk.index
                    and existing.seed_chunk_count == chunk.count
                    and existing.seed_root_hash == chunk.root_hash
                ):
                    return
                raise RepositoryConflict("BATCH_CONTENT_CONFLICT")
            session.add(ReferenceBatch(
                batch_id=uuid4().hex,
                stream_id=revision.stream_id,
                revision_id=revision_id,
                batch_key=chunk.batch_key,
                payload_hash=payload_hash,
                kind="seed_chunk",
                outcome="staged",
                seq=None,
                expected_seq=0,
                dependency_manifest={},
                source_evidence={},
                projected_action_pks=[],
                diagnostics=[],
                processed_at=datetime.now(UTC),
                seed_chunk_index=chunk.index,
                seed_chunk_count=chunk.count,
                seed_root_hash=chunk.root_hash,
                seed_chunk_text=chunk.content,
            ))

    def seal_seed(
        self,
        revision_id: str,
        manifest: dict[str, object],
        checkpoint: AdapterCheckpoint[object],
        strategy_schema: str,
    ) -> CheckpointToken:
        manifest_digest = _digest(manifest)
        if checkpoint.stream is None:
            raise ValueError("checkpoint stream is required")
        checkpoint_text = adapter_checkpoint_to_json(checkpoint, strategy_schema=strategy_schema)
        # Verify the exact persisted text through the strict P2 decoder before opening a transaction.
        adapter_checkpoint_from_json(
            checkpoint_text,
            expected_stream=checkpoint.stream,
            expected_strategy_schema=strategy_schema,
        )
        state_hash = _checkpoint_hash(checkpoint_text)
        with self._session_factory() as session, session.begin():
            stream, revision = self._lock_stream_revision_by_revision_id(
                session, revision_id,
            )
            if revision.checkpoint_batch_id is not None:
                sealed = session.get(ReferenceBatch, revision.checkpoint_batch_id)
                if (
                    revision.status == "candidate"
                    and sealed is not None
                    and sealed.kind == "seed_seal"
                    and sealed.checkpoint_text == checkpoint_text
                    and sealed.strategy_schema == strategy_schema
                    and sealed.dependency_manifest == manifest
                    and sealed.post_state_hash == state_hash
                ):
                    return CheckpointToken(
                        stream.stream_id, revision_id, revision.last_seq,
                        stream.row_version, state_hash,
                    )
                raise RepositoryConflict("BATCH_CONTENT_CONFLICT")
            if revision.status != "candidate":
                raise RepositoryConflict("REVISION_NOT_SEEDABLE")
            if checkpoint.stream.stream_id != stream.stream_id:
                raise RepositoryConflict("CHECKPOINT_STREAM_CONFLICT")
            if revision.dependency_digest != manifest_digest:
                raise RepositoryConflict("DEPENDENCY_CONFLICT")
            chunks = session.execute(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == stream.stream_id,
                ReferenceBatch.revision_id == revision_id,
                ReferenceBatch.kind == "seed_chunk",
            )).scalars().all()
            self._validate_chunks(chunks)
            batch_id = uuid4().hex
            session.add(ReferenceBatch(
                batch_id=batch_id,
                stream_id=stream.stream_id,
                revision_id=revision_id,
                batch_key="seed-seal:" + state_hash,
                payload_hash=sha256((manifest_digest + state_hash).encode()).hexdigest(),
                kind="seed_seal",
                outcome="committed",
                seq=1,
                expected_seq=0,
                pre_state_hash=None,
                post_state_hash=state_hash,
                checkpoint_text=checkpoint_text,
                strategy_schema=strategy_schema,
                computed_through=checkpoint.computed_through,
                dependency_manifest=manifest,
                source_evidence={"seed_root_hash": chunks[0].seed_root_hash},
                projected_action_pks=[],
                diagnostics=[],
                processed_at=datetime.now(UTC),
            ))
            revision.last_seq = 1
            revision.checkpoint_batch_id = batch_id
            token = CheckpointToken(stream.stream_id, revision_id, 1, stream.row_version, state_hash)
        return token

    def load_checkpoint(
        self, stream_id: str, revision_id: str | None = None,
    ) -> tuple[CheckpointToken, AdapterCheckpoint[object]]:
        with self._session_factory() as session:
            stream = session.get(ReferenceStream, stream_id)
            if stream is None:
                raise RepositoryConflict("STREAM_NOT_FOUND")
            chosen = revision_id or stream.active_revision_id
            if chosen is None:
                raise RepositoryConflict("NO_ACTIVE_REVISION")
            revision = session.get(ReferenceRevision, (stream_id, chosen))
            if revision is None:
                raise RepositoryConflict("REVISION_NOT_FOUND")
            if revision.status == "invalid":
                raise RepositoryConflict("SNAPSHOT_INVALIDATED")
            if revision.checkpoint_batch_id is None:
                raise RepositoryConflict("SEED_NOT_SEALED")
            batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            if batch is None or batch.checkpoint_text is None or batch.strategy_schema is None:
                raise RepositoryConflict("CHECKPOINT_CORRUPT")
            identity = _identity_from_row(stream)
            checkpoint = adapter_checkpoint_from_json(
                batch.checkpoint_text,
                expected_stream=identity,
                expected_strategy_schema=batch.strategy_schema,
            )
            token = CheckpointToken(
                stream_id, chosen, revision.last_seq, stream.row_version,
                _checkpoint_hash(batch.checkpoint_text),
            )
            return token, checkpoint

    def read_state(
        self, stream_id: str, revision_id: str | None = None,
    ) -> StoredRevisionState:
        """Read the exact revision/checkpoint/manifest without creating a stream."""
        with self._session_factory() as session:
            stream = session.get(ReferenceStream, stream_id)
            if stream is None:
                raise RepositoryConflict("STREAM_NOT_FOUND")
            chosen = revision_id or stream.active_revision_id
            if chosen is None:
                raise RepositoryConflict("NO_ACTIVE_REVISION")
            revision = session.get(ReferenceRevision, (stream_id, chosen))
            if revision is None:
                raise RepositoryConflict("REVISION_NOT_FOUND")
            if revision.checkpoint_batch_id is None:
                raise RepositoryConflict("SEED_NOT_SEALED")
            batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            if (
                batch is None
                or batch.checkpoint_text is None
                or batch.strategy_schema is None
            ):
                raise RepositoryConflict("CHECKPOINT_CORRUPT")
            token = CheckpointToken(
                stream_id, chosen, revision.last_seq, stream.row_version,
                _checkpoint_hash(batch.checkpoint_text),
            )
            return StoredRevisionState(
                _stored(stream), chosen, revision.status, batch.dependency_manifest,
                revision.dependency_digest, token, batch.batch_key,
                dict(batch.source_evidence),
            )

    def publish_revision(
        self,
        stream_id: str,
        revision_id: str,
        expected_row_version: int,
        expected_dependency_digest: str,
    ) -> SnapshotIdentity:
        with self._session_factory() as session, session.begin():
            stream = session.execute(
                select(ReferenceStream).where(ReferenceStream.stream_id == stream_id).with_for_update()
            ).scalar_one_or_none()
            if stream is None:
                raise RepositoryConflict("STREAM_NOT_FOUND")
            if stream.row_version != expected_row_version:
                raise RepositoryConflict("STALE_CHECKPOINT")
            revision = session.execute(select(ReferenceRevision).where(
                ReferenceRevision.stream_id == stream_id,
                ReferenceRevision.revision_id == revision_id,
            ).with_for_update()).scalar_one_or_none()
            if revision is None:
                raise RepositoryConflict("REVISION_NOT_FOUND")
            if (
                revision.status != "candidate"
                or revision.checkpoint_batch_id is None
                or revision.dependency_digest != expected_dependency_digest
                or revision.last_seq <= 0
            ):
                raise RepositoryConflict("REVISION_NOT_PUBLISHABLE")
            if stream.active_revision_id is not None:
                old = session.get(ReferenceRevision, (stream_id, stream.active_revision_id))
                if old is not None and old.status == "active":
                    old.status = "superseded"
            revision.status = "active"
            stream.active_revision_id = revision_id
            stream.latest_seq = revision.last_seq
            stream.row_version += 1
            stream.health = "READY"
            return SnapshotIdentity(stream_id, revision_id, revision.last_seq)

    def commit_batch(
        self, expected: CheckpointToken, prepared: PreparedBatch,
    ) -> CommitResult:
        if not isinstance(expected, CheckpointToken) or not isinstance(prepared, PreparedBatch):
            raise TypeError("expected and prepared have invalid types")
        if expected != prepared.expected:
            raise ValueError("expected token must equal prepared.expected")
        self._validate_prepared(prepared)
        checkpoint_text = adapter_checkpoint_to_json(
            prepared.checkpoint, strategy_schema=prepared.strategy_schema,
        )
        checkpoint_stream = prepared.checkpoint.stream
        if checkpoint_stream is None:
            raise RepositoryConflict("CHECKPOINT_STREAM_CONFLICT")
        adapter_checkpoint_from_json(
            checkpoint_text,
            expected_stream=checkpoint_stream,
            expected_strategy_schema=prepared.strategy_schema,
        )
        post_hash = _checkpoint_hash(checkpoint_text)
        payload_hash = self._prepared_hash(prepared, checkpoint_text)
        with self._session_factory() as session, session.begin():
            stream = session.execute(select(ReferenceStream).where(
                ReferenceStream.stream_id == prepared.stream_id,
            ).with_for_update()).scalar_one_or_none()
            if stream is None:
                raise RepositoryConflict("STREAM_NOT_FOUND")
            revision = session.execute(select(ReferenceRevision).where(
                ReferenceRevision.stream_id == prepared.stream_id,
                ReferenceRevision.revision_id == prepared.revision_id,
            ).with_for_update()).scalar_one_or_none()
            if revision is None:
                raise RepositoryConflict("REVISION_NOT_FOUND")
            existing = session.execute(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == prepared.stream_id,
                ReferenceBatch.revision_id == prepared.revision_id,
                ReferenceBatch.batch_key == prepared.batch_key,
            )).scalar_one_or_none()
            if existing is not None:
                if existing.payload_hash != payload_hash:
                    raise RepositoryConflict("BATCH_CONTENT_CONFLICT")
                if existing.seq is None or existing.post_state_hash is None:
                    raise RepositoryConflict("BATCH_NOT_COMMITTED")
                return CommitResult(
                    "noop", prepared.revision_id, existing.seq, existing.post_state_hash,
                )
            capture_row = None
            if stream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value:
                proof = prepared.source_evidence.get("forward_capture_v1")
                if not isinstance(proof, dict) or not isinstance(proof.get("capture_id"), str):
                    raise RepositoryConflict("FORWARD_CAPTURE_REQUIRED")
                capture_row = session.get(ReferenceBatch, proof["capture_id"])
                if (
                    not stream.enabled or stream.active_revision_id != revision.revision_id
                    or type(proof.get("generation")) is not int
                    or proof["generation"] != stream.activation_generation
                    or capture_row is None or capture_row.kind != "capture"
                    or capture_row.stream_id != stream.stream_id
                    or capture_row.revision_id != revision.revision_id
                    or capture_row.consumed_by_batch_id is not None
                    or capture_row.payload_hash != proof.get("hash")
                    or _aware(capture_row.observed_at) != prepared.input_observed_at
                    or capture_row.expected_seq != revision.last_seq
                ):
                    raise RepositoryConflict("FORWARD_CAPTURE_CONFLICT")
            if revision.status not in {"candidate", "active"}:
                raise RepositoryConflict("REVISION_NOT_WRITABLE")
            if (
                expected.stream_id != stream.stream_id
                or expected.revision_id != revision.revision_id
                or expected.seq != revision.last_seq
                or expected.row_version != stream.row_version
            ):
                raise RepositoryConflict("STALE_CHECKPOINT")
            checkpoint_batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            if (
                checkpoint_batch is None
                or checkpoint_batch.checkpoint_text is None
                or checkpoint_batch.strategy_schema is None
                or _checkpoint_hash(checkpoint_batch.checkpoint_text) != expected.state_hash
            ):
                raise RepositoryConflict("STALE_CHECKPOINT")
            persisted_checkpoint = adapter_checkpoint_from_json(
                checkpoint_batch.checkpoint_text,
                expected_stream=_identity_from_row(stream),
                expected_strategy_schema=checkpoint_batch.strategy_schema,
            )
            prior_state = persisted_checkpoint.reference_state
            final_state = prepared.checkpoint.reference_state
            if prior_state is None or final_state is None:
                raise RepositoryConflict("CHECKPOINT_STATE_CONFLICT")
            self._validate_state_progress(prior_state, final_state)
            self._validate_action_progress(prior_state, final_state, prepared)
            self._validate_open_projection(
                session, prepared.stream_id, prepared.revision_id, prior_state.open_trade,
            )
            if prepared.dependency_advance is None:
                if revision.dependency_digest != _digest(prepared.dependency_manifest):
                    raise RepositoryConflict("DEPENDENCY_CONFLICT")
            else:
                advance = prepared.dependency_advance
                try:
                    validate_dependency_advance(
                        checkpoint_batch.dependency_manifest, advance,
                    )
                except ValueError as error:
                    raise RepositoryConflict("DEPENDENCY_CONFLICT") from error
                if (
                    revision.dependency_digest != advance.expected_prior_digest
                    or manifest_sha256(prepared.dependency_manifest) != advance.new_digest
                ):
                    raise RepositoryConflict("DEPENDENCY_CONFLICT")
            if prepared.transitions[-1].state != prepared.checkpoint.reference_state:
                raise RepositoryConflict("CHECKPOINT_TRANSITION_CONFLICT")
            seq = revision.last_seq + 1
            batch_id = uuid4().hex
            batch = ReferenceBatch(
                batch_id=batch_id,
                stream_id=stream.stream_id,
                revision_id=revision.revision_id,
                batch_key=prepared.batch_key,
                payload_hash=payload_hash,
                kind="calculation",
                outcome="committed",
                seq=seq,
                expected_seq=expected.seq,
                pre_state_hash=expected.state_hash,
                post_state_hash=post_hash,
                checkpoint_text=checkpoint_text,
                strategy_schema=prepared.strategy_schema,
                computed_through=prepared.checkpoint.reference_state.computed_through,
                last_event_bar_end=(
                    None if prepared.checkpoint.reference_state.last_event_key is None
                    else prepared.checkpoint.reference_state.last_event_key[0]
                ),
                last_event_kind=(
                    None if prepared.checkpoint.reference_state.last_event_key is None
                    else prepared.checkpoint.reference_state.last_event_key[1]
                ),
                last_event_sequence=(
                    None if prepared.checkpoint.reference_state.last_event_key is None
                    else prepared.checkpoint.reference_state.last_event_key[2]
                ),
                dependency_manifest=prepared.dependency_manifest,
                source_evidence=prepared.source_evidence,
                projected_action_pks=[],
                diagnostics=[
                    diagnostic
                    for transition in prepared.transitions
                    for diagnostic in transition.diagnostics
                ],
                observed_at=prepared.input_observed_at,
                processed_at=datetime.now(UTC),
            )
            session.add(batch)
            session.flush()
            if capture_row is not None:
                capture_row.consumed_by_batch_id = batch_id
                capture_row.outcome = "consumed"
            action_pks = self._insert_actions(
                session, prepared, batch_id=batch_id, batch_seq=seq,
            )
            batch.projected_action_pks = list(dict.fromkeys(action_pks.values()))
            self._fault_injector("after_actions")
            births = self._apply_trade_changes(
                session, prepared, action_pks=action_pks, seq=seq,
            )
            self._fault_injector("after_trades")
            self._insert_marks(
                session, prepared, action_pks=action_pks, births=births, seq=seq,
            )
            session.flush()
            self._validate_open_projection(
                session, prepared.stream_id, prepared.revision_id, final_state.open_trade,
            )
            self._fault_injector("before_checkpoint")
            revision.last_seq = seq
            revision.checkpoint_batch_id = batch_id
            if prepared.dependency_advance is not None:
                revision.dependency_digest = prepared.dependency_advance.new_digest
            stream.row_version += 1
            if stream.active_revision_id == revision.revision_id:
                stream.latest_seq = seq
            self._fault_injector("before_commit")
        return CommitResult("committed", prepared.revision_id, seq, post_hash)

    def read_batch(
        self, stream_id: str, revision_id: str, batch_key: str,
        *, expected_payload_hash: str | None = None,
    ) -> CommitResult | None:
        with self._session_factory() as session:
            row = session.execute(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == stream_id,
                ReferenceBatch.revision_id == revision_id,
                ReferenceBatch.batch_key == batch_key,
            )).scalar_one_or_none()
            if row is None:
                return None
            if expected_payload_hash is not None and row.payload_hash != expected_payload_hash:
                raise RepositoryConflict("BATCH_CONTENT_CONFLICT")
            if row.seq is None or row.post_state_hash is None:
                raise RepositoryConflict("BATCH_NOT_COMMITTED")
            return CommitResult("committed", revision_id, row.seq, row.post_state_hash)

    def read_prepared_batch(self, prepared: PreparedBatch) -> CommitResult | None:
        checkpoint_text = adapter_checkpoint_to_json(
            prepared.checkpoint, strategy_schema=prepared.strategy_schema,
        )
        return self.read_batch(
            prepared.stream_id, prepared.revision_id, prepared.batch_key,
            expected_payload_hash=self._prepared_hash(prepared, checkpoint_text),
        )

    def read_batch_evidence(
        self, stream_id: str, revision_id: str, batch_key: str,
    ) -> dict[str, object] | None:
        """Read immutable source progress for explicit resume validation."""
        with self._session_factory() as session:
            row = session.execute(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == stream_id,
                ReferenceBatch.revision_id == revision_id,
                ReferenceBatch.batch_key == batch_key,
            )).scalar_one_or_none()
            if row is None or row.seq is None:
                return None
            return dict(row.source_evidence)

    def read_actions(
        self,
        snapshot: SnapshotIdentity,
        *,
        cutoff: datetime | None,
        limit: int,
        after_key: tuple[object, ...] | None = None,
    ) -> StoredPage[ReferenceAction]:
        self._validate_page(limit, cutoff)
        with self._session_factory() as session:
            stream, _revision = self._validate_snapshot(session, snapshot)
            batches = session.execute(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == snapshot.stream_id,
                ReferenceBatch.revision_id == snapshot.revision_id,
                ReferenceBatch.seq.is_not(None),
                ReferenceBatch.seq <= snapshot.seq,
            )).scalars().all()
            projected = {
                action_pk for batch in batches for action_pk in batch.projected_action_pks
            }
            if not projected:
                return StoredPage((), None, snapshot)
            statement = select(ReferenceActionRow).where(
                ReferenceActionRow.stream_id == snapshot.stream_id,
                ReferenceActionRow.action_pk.in_(projected),
            )
            if cutoff is not None:
                statement = statement.where(ReferenceActionRow.bar_end <= cutoff)
                if stream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value:
                    statement = statement.where(ReferenceActionRow.observed_at <= cutoff)
            rows = session.execute(statement.order_by(
                ReferenceActionRow.bar_end,
                ReferenceActionRow.sequence,
                ReferenceActionRow.action_pk,
            )).scalars().all()
            keyed = [
                ((row.bar_end, row.sequence, row.action_pk), row)
                for row in rows
            ]
            if after_key is not None:
                keyed = [item for item in keyed if item[0] > after_key]
            selected = keyed[: limit + 1]
            more = len(selected) > limit
            selected = selected[:limit]
            identity = _identity_from_row(stream)
            items = tuple(self._action_domain(identity, row) for _key, row in selected)
            next_key = selected[-1][0] if more and selected else None
            return StoredPage(items, next_key, snapshot)

    def read_trades(
        self,
        snapshot: SnapshotIdentity,
        *,
        cutoff: datetime | None,
        limit: int,
        after_key: tuple[object, ...] | None = None,
        since: date | None = None,
        through: date | None = None,
    ) -> StoredPage[ReferenceTrade]:
        self._validate_page(limit, cutoff)
        with self._session_factory() as session:
            stream, _revision = self._validate_snapshot(session, snapshot)
            versions = session.execute(select(ReferenceTradeRow).where(
                ReferenceTradeRow.stream_id == snapshot.stream_id,
                ReferenceTradeRow.revision_id == snapshot.revision_id,
                ReferenceTradeRow.valid_from_seq <= snapshot.seq,
            )).scalars().all()
            by_trade: dict[str, list[ReferenceTradeRow]] = {}
            for row in versions:
                if cutoff is not None and _required_aware(
                    row.entry_bar_end, "TRADE_ENTRY_BAR_END",
                ) > cutoff:
                    continue
                by_trade.setdefault(row.trade_id, []).append(row)
            identity = _identity_from_row(stream)
            selected_trades: list[ReferenceTrade] = []
            for trade_versions in by_trade.values():
                trade_versions.sort(key=lambda row: row.valid_from_seq)
                if (
                    cutoff is not None
                    and stream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value
                ):
                    entry_action = session.get(
                        ReferenceActionRow, trade_versions[0].entry_action_pk,
                    )
                    if (
                        entry_action is None
                        or entry_action.observed_at is None
                        or _required_aware(
                            entry_action.observed_at, "ACTION_OBSERVED_AT",
                        ) > cutoff
                    ):
                        continue
                eligible = [
                    row for row in trade_versions
                    if self._trade_version_visible_at_cutoff(session, row, cutoff)
                ]
                if eligible:
                    chosen = eligible[-1]
                else:
                    opens = [row for row in trade_versions if row.status == TradeStatus.OPEN.value]
                    if not opens:
                        continue
                    chosen = opens[0]
                trade = self._trade_domain(session, identity, chosen)
                if since is not None and trade.entry_trading_day < since:
                    if not (
                        stream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value
                        and (
                            trade.status is TradeStatus.OPEN
                            or trade.exit_trading_day is not None
                            and trade.exit_trading_day >= since
                        )
                    ):
                        continue
                if through is not None and trade.entry_trading_day > through:
                    continue
                if trade.status is TradeStatus.OPEN:
                    mark_statement = select(ReferenceMarkRow).where(
                        ReferenceMarkRow.stream_id == snapshot.stream_id,
                        ReferenceMarkRow.revision_id == snapshot.revision_id,
                        ReferenceMarkRow.trade_id == trade.reference_trade_id,
                        ReferenceMarkRow.batch_seq <= snapshot.seq,
                        *(() if cutoff is None else (ReferenceMarkRow.bar_end <= cutoff,)),
                    )
                    if (
                        cutoff is not None
                        and stream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value
                    ):
                        mark_statement = mark_statement.where(
                            ReferenceMarkRow.observed_at <= cutoff,
                        )
                    mark = session.execute(mark_statement.order_by(
                        ReferenceMarkRow.bar_end.desc(), ReferenceMarkRow.batch_seq.desc(),
                    )).scalars().first()
                    if mark is not None:
                        trade = replace(
                            trade,
                            holding_bars=mark.holding_bars,
                            mark_bar_end=_aware(mark.bar_end),
                            mark_trading_day=mark.trading_day,
                            mark_reference_price=mark.reference_price,
                            mark_return=mark.reference_return,
                        )
                selected_trades.append(trade)
            selected_trades.sort(
                key=lambda trade: (trade.entry_bar_end, trade.reference_trade_id), reverse=True,
            )
            keyed = [
                ((trade.entry_bar_end, trade.reference_trade_id), trade)
                for trade in selected_trades
            ]
            if after_key is not None:
                keyed = [item for item in keyed if item[0] < after_key]
            chosen_items = keyed[: limit + 1]
            more = len(chosen_items) > limit
            chosen_items = chosen_items[:limit]
            return StoredPage(
                tuple(item for _key, item in chosen_items),
                chosen_items[-1][0] if more and chosen_items else None,
                snapshot,
            )

    def query_historical_trades(
        self, session: Session, snapshot: SnapshotIdentity, *,
        since: date, through: date, cutoff: datetime | None,
        limit: int, after_key: tuple[datetime, str] | None = None,
        initial_interruptions: frozenset[tuple[str, str, str]] = frozenset(),
        forward: bool = False,
    ) -> StoredPage[ReferenceTrade]:
        """Select one eligible version per trade in SQL, then hydrate one page.

        The caller owns a single read-only repeatable-read transaction.  No
        batch, trade-version, action, or mark history is loaded into Python.
        """
        self._validate_page(limit, cutoff)
        if type(since) is not date or type(through) is not date or since > through:
            raise ValueError("TRADING_DAY_WINDOW_INVALID")
        stream, _revision = self._validate_snapshot(session, snapshot)
        expected_mode = (
            RecordingMode.FORWARD_OBSERVATION.value if forward
            else RecordingMode.HISTORICAL_REPLAY.value
        )
        if stream.recording_mode != expected_mode:
            raise RepositoryConflict("MODE_NOT_AVAILABLE")
        row = ReferenceTradeRow
        eligible = [
            row.stream_id == snapshot.stream_id,
            row.revision_id == snapshot.revision_id,
            row.valid_from_seq <= snapshot.seq,
        ]
        if cutoff is not None:
            eligible.extend((
                row.entry_bar_end <= cutoff,
                row.effective_bar_end <= cutoff,
                or_(row.exit_bar_end.is_(None), row.exit_bar_end <= cutoff),
            ))
            if forward:
                eligible.extend((
                    select(ReferenceActionRow.action_pk).where(
                        ReferenceActionRow.action_pk == row.entry_action_pk,
                        ReferenceActionRow.observed_at <= cutoff,
                    ).exists(),
                    select(ReferenceBatch.batch_id).where(
                        ReferenceBatch.stream_id == row.stream_id,
                        ReferenceBatch.revision_id == row.revision_id,
                        ReferenceBatch.seq == row.valid_from_seq,
                        ReferenceBatch.observed_at <= cutoff,
                    ).exists(),
                ))
        ranked = select(
            row.trade_id.label("trade_id"),
            row.valid_from_seq.label("valid_from_seq"),
            func.row_number().over(
                partition_by=row.trade_id,
                order_by=row.valid_from_seq.desc(),
            ).label("rank"),
        ).where(*eligible).subquery()
        statement = select(row).join(
            ranked,
            and_(
                ranked.c.trade_id == row.trade_id,
                ranked.c.valid_from_seq == row.valid_from_seq,
                ranked.c.rank == 1,
            ),
        ).where(
            row.stream_id == snapshot.stream_id,
            row.revision_id == snapshot.revision_id,
            row.entry_trading_day <= through,
        )
        if forward:
            statement = statement.where(or_(
                row.entry_trading_day >= since,
                row.exit_trading_day >= since,
                row.status == "OPEN",
            ))
        elif stream.strategy_code.replace("-", "_") == "subing_reference":
            statement = statement.where(or_(
                row.entry_trading_day >= since,
                row.exit_trading_day >= since,
                row.status == "OPEN",
                and_(
                    row.status.in_(("DATA_INTERRUPTED", "ROLLOVER_INTERRUPTED")),
                    tuple_(row.physical_contract, row.owner_segment_id,
                           row.calculation_segment_id).in_(initial_interruptions),
                ),
            ))
        if after_key is not None:
            if (
                len(after_key) != 2 or not isinstance(after_key[0], datetime)
                or not isinstance(after_key[1], str)
            ):
                raise ValueError("CURSOR_INVALID")
            statement = statement.where(tuple_(row.entry_bar_end, row.trade_id) < after_key)
        rows = session.execute(statement.order_by(
            row.entry_bar_end.desc(), row.trade_id.desc(),
        ).limit(limit + 1)).scalars().all()
        more = len(rows) > limit
        rows = rows[:limit]
        if not rows:
            return StoredPage((), None, snapshot)
        action_pks = {
            pk for item in rows
            for pk in (item.entry_action_pk, item.exit_action_pk) if pk is not None
        }
        actions = {
            action.action_pk: action
            for action in session.execute(select(ReferenceActionRow).where(
                ReferenceActionRow.stream_id == snapshot.stream_id,
                ReferenceActionRow.action_pk.in_(action_pks),
            )).scalars()
        }
        identity = _identity_from_row(stream)
        trades = [self._trade_domain(session, identity, item, actions) for item in rows]
        open_ids = [item.reference_trade_id for item in trades if item.status is TradeStatus.OPEN]
        if open_ids:
            mark = ReferenceMarkRow
            mark_eligible = [
                mark.stream_id == snapshot.stream_id,
                mark.revision_id == snapshot.revision_id,
                mark.trade_id.in_(open_ids),
                mark.batch_seq <= snapshot.seq,
            ]
            if cutoff is not None:
                mark_eligible.append(mark.bar_end <= cutoff)
                if forward:
                    mark_eligible.append(mark.observed_at <= cutoff)
            latest = select(
                mark.trade_id.label("trade_id"), mark.batch_seq.label("batch_seq"),
                mark.bar_end.label("bar_end"),
                func.row_number().over(
                    partition_by=mark.trade_id,
                    order_by=(mark.bar_end.desc(), mark.batch_seq.desc()),
                ).label("rank"),
            ).where(*mark_eligible).subquery()
            marks = {
                item.trade_id: item for item in session.execute(select(mark).join(
                    latest,
                    and_(
                        latest.c.trade_id == mark.trade_id,
                        latest.c.batch_seq == mark.batch_seq,
                        latest.c.bar_end == mark.bar_end,
                        latest.c.rank == 1,
                    ),
                ).where(
                    mark.stream_id == snapshot.stream_id,
                    mark.revision_id == snapshot.revision_id,
                )).scalars()
            }
            trades = [
                replace(
                    item, holding_bars=marks[item.reference_trade_id].holding_bars,
                    mark_bar_end=_aware(marks[item.reference_trade_id].bar_end),
                    mark_trading_day=marks[item.reference_trade_id].trading_day,
                    mark_reference_price=marks[item.reference_trade_id].reference_price,
                    mark_return=marks[item.reference_trade_id].reference_return,
                ) if item.reference_trade_id in marks else item
                for item in trades
            ]
        last = rows[-1]
        return StoredPage(
            tuple(trades),
            (_required_aware(last.entry_bar_end, "TRADE_ENTRY_BAR_END"), last.trade_id)
            if more else None,
            snapshot,
        )

    def read_marks(
        self,
        snapshot: SnapshotIdentity,
        *,
        cutoff: datetime | None,
        limit: int,
        after_key: tuple[object, ...] | None = None,
    ) -> StoredPage[ReferenceMark]:
        self._validate_page(limit, cutoff)
        with self._session_factory() as session:
            stream, _revision = self._validate_snapshot(session, snapshot)
            statement = select(ReferenceMarkRow).where(
                ReferenceMarkRow.stream_id == snapshot.stream_id,
                ReferenceMarkRow.revision_id == snapshot.revision_id,
                ReferenceMarkRow.batch_seq <= snapshot.seq,
            )
            if cutoff is not None:
                statement = statement.where(ReferenceMarkRow.bar_end <= cutoff)
                if stream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value:
                    statement = statement.where(ReferenceMarkRow.observed_at <= cutoff)
            rows = session.execute(statement.order_by(
                ReferenceMarkRow.bar_end,
                ReferenceMarkRow.trade_id,
                ReferenceMarkRow.batch_seq,
            )).scalars().all()
            keyed = [((row.bar_end, row.trade_id, row.batch_seq), row) for row in rows]
            if after_key is not None:
                keyed = [item for item in keyed if item[0] > after_key]
            selected = keyed[: limit + 1]
            more = len(selected) > limit
            selected = selected[:limit]
            return StoredPage(
                tuple(ReferenceMark(
                    row.trade_id, _required_aware(row.bar_end, "MARK_BAR_END"),
                    row.trading_day, row.reference_price,
                    row.holding_bars, row.reference_return,
                ) for _key, row in selected),
                selected[-1][0] if more and selected else None,
                snapshot,
            )

    def invalidate_revision(
        self, stream_id: str, revision_id: str, expected_row_version: int, reason: str,
    ) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be non-empty text")
        with self._session_factory() as session, session.begin():
            stream = session.execute(select(ReferenceStream).where(
                ReferenceStream.stream_id == stream_id,
            ).with_for_update()).scalar_one_or_none()
            if stream is None or stream.row_version != expected_row_version:
                raise RepositoryConflict("STALE_CHECKPOINT")
            revision = session.get(ReferenceRevision, (stream_id, revision_id))
            if revision is None:
                raise RepositoryConflict("REVISION_NOT_FOUND")
            revision.status = "invalid"
            revision.invalid_reason = reason[:256]
            stream.row_version += 1
            if stream.active_revision_id == revision_id:
                stream.health = "STALE_INVALID"

    def record_diagnostic(
        self,
        stream_id: str,
        revision_id: str,
        batch_key: str,
        evidence: dict[str, object],
        code: str,
    ) -> None:
        payload_hash = _digest({"evidence": evidence, "code": code})
        with self._session_factory() as session, session.begin():
            revision = session.get(ReferenceRevision, (stream_id, revision_id))
            if revision is None:
                raise RepositoryConflict("REVISION_NOT_FOUND")
            existing = session.execute(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == stream_id,
                ReferenceBatch.revision_id == revision_id,
                ReferenceBatch.batch_key == batch_key,
            )).scalar_one_or_none()
            if existing is not None:
                if existing.payload_hash == payload_hash:
                    return
                raise RepositoryConflict("BATCH_CONTENT_CONFLICT")
            session.add(ReferenceBatch(
                batch_id=uuid4().hex,
                stream_id=stream_id,
                revision_id=revision_id,
                batch_key=batch_key,
                payload_hash=payload_hash,
                kind="diagnostic",
                outcome="diagnostic",
                seq=None,
                expected_seq=revision.last_seq,
                dependency_manifest={},
                source_evidence=evidence,
                projected_action_pks=[],
                diagnostics=[code],
                processed_at=datetime.now(UTC),
            ))

    @staticmethod
    def _validate_page(limit: int, cutoff: datetime | None) -> None:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        if cutoff is not None and (
            not isinstance(cutoff, datetime)
            or cutoff.tzinfo is None
            or cutoff.utcoffset() is None
        ):
            raise ValueError("cutoff must be timezone-aware")

    @staticmethod
    def _validate_snapshot(
        session: Session, snapshot: SnapshotIdentity,
    ) -> tuple[ReferenceStream, ReferenceRevision]:
        if not isinstance(snapshot, SnapshotIdentity):
            raise TypeError("snapshot must be SnapshotIdentity")
        stream = session.get(ReferenceStream, snapshot.stream_id)
        revision = session.get(
            ReferenceRevision, (snapshot.stream_id, snapshot.revision_id),
        )
        if stream is None or revision is None:
            raise RepositoryConflict("SNAPSHOT_NOT_FOUND")
        if revision.status == "candidate":
            raise RepositoryConflict("SNAPSHOT_NOT_PUBLISHED")
        if revision.status == "invalid":
            raise RepositoryConflict("SNAPSHOT_INVALIDATED")
        if snapshot.seq <= 0 or snapshot.seq > revision.last_seq:
            raise RepositoryConflict("SNAPSHOT_SEQ_INVALID")
        return stream, revision

    @staticmethod
    def _action_domain(identity: StreamIdentity, row: ReferenceActionRow) -> ReferenceAction:
        return ReferenceAction(
            stream=identity,
            source_action_id=row.source_action_id,
            physical_contract=row.physical_contract,
            owner_segment_id=row.owner_segment_id,
            calculation_segment_id=row.calculation_segment_id,
            bar_end=_required_aware(row.bar_end, "ACTION_BAR_END"),
            trading_day=row.trading_day,
            sequence=row.sequence,
            kind=ActionKind(row.kind),
            reference_price=row.reference_price,
            entry_action_id=row.entry_source_action_id,
            reference_price_type=row.reference_price_type,
        )

    @staticmethod
    def _trade_domain(
        session: Session, identity: StreamIdentity, row: ReferenceTradeRow,
        actions: dict[str, ReferenceActionRow] | None = None,
    ) -> ReferenceTrade:
        entry_action = (
            session.get(ReferenceActionRow, row.entry_action_pk)
            if actions is None else actions.get(row.entry_action_pk)
        )
        exit_action = (
            None if row.exit_action_pk is None
            else (
                session.get(ReferenceActionRow, row.exit_action_pk)
                if actions is None else actions.get(row.exit_action_pk)
            )
        )
        if entry_action is None or (row.exit_action_pk is not None and exit_action is None):
            raise RepositoryConflict("TRADE_ACTION_CORRUPT")
        return ReferenceTrade(
            reference_trade_id=row.trade_id,
            stream=identity,
            side=Side(row.side),
            physical_contract=row.physical_contract,
            owner_segment_id=row.owner_segment_id,
            calculation_segment_id=row.calculation_segment_id,
            entry_action_id=entry_action.source_action_id,
            entry_bar_end=_required_aware(row.entry_bar_end, "TRADE_ENTRY_BAR_END"),
            entry_trading_day=row.entry_trading_day,
            entry_reference_price=row.entry_reference_price,
            status=TradeStatus(row.status),
            exit_action_id=(
                None if exit_action is None else exit_action.source_action_id
            ),
            exit_bar_end=_aware(row.exit_bar_end),
            exit_trading_day=row.exit_trading_day,
            exit_reference_price=row.exit_reference_price,
            reference_return=row.reference_return,
            holding_bars=row.holding_bars,
        )

    @staticmethod
    def _trade_version_visible_at_cutoff(
        session: Session, row: ReferenceTradeRow, cutoff: datetime | None,
    ) -> bool:
        if cutoff is None:
            return True
        if _required_aware(row.effective_bar_end, "TRADE_EFFECTIVE_BAR_END") > cutoff:
            return False
        if (
            row.observed_at is not None
            and _required_aware(row.observed_at, "TRADE_OBSERVED_AT") > cutoff
        ):
            return False
        if row.status == TradeStatus.CLOSED.value:
            if row.exit_bar_end is None or _required_aware(
                row.exit_bar_end, "TRADE_EXIT_BAR_END",
            ) > cutoff:
                return False
            action = (
                None if row.exit_action_pk is None
                else session.get(ReferenceActionRow, row.exit_action_pk)
            )
            return (
                action is None
                or action.recording_mode != RecordingMode.FORWARD_OBSERVATION.value
                or (
                    action.observed_at is not None
                    and _required_aware(
                        action.observed_at, "ACTION_OBSERVED_AT",
                    ) <= cutoff
                )
            )
        if row.status == TradeStatus.OPEN.value:
            return True
        return True

    @staticmethod
    def _prepared_hash(prepared: PreparedBatch, checkpoint_text: str) -> str:
        return _digest({
            "stream_id": prepared.stream_id,
            "revision_id": prepared.revision_id,
            "batch_key": prepared.batch_key,
            "dependency_manifest": _wire(prepared.dependency_manifest),
            "source_actions": _wire(prepared.source_actions),
            "transitions": _wire(prepared.transitions),
            "checkpoint": checkpoint_text,
            "strategy_schema": prepared.strategy_schema,
            "source_evidence": _wire(prepared.source_evidence),
            "input_observed_at": _wire(prepared.input_observed_at),
            "dependency_advance": _wire(prepared.dependency_advance),
        })

    @staticmethod
    def _validate_prepared(prepared: PreparedBatch) -> None:
        source_ids = [item.action.source_action_id for item in prepared.source_actions]
        if len(source_ids) != len(set(source_ids)):
            raise RepositoryConflict("DUPLICATE_SOURCE_ACTION")
        event_keys = [
            (item.action.bar_end, item.action.sequence)
            for item in prepared.source_actions
        ]
        if event_keys != sorted(event_keys) or len(event_keys) != len(set(event_keys)):
            raise RepositoryConflict("ACTION_ORDER_CONFLICT")
        mark_keys = [
            (mark.reference_trade_id, mark.bar_end)
            for transition in prepared.transitions
            for mark in transition.marks
        ]
        if len(mark_keys) != len(set(mark_keys)):
            raise RepositoryConflict("DUPLICATE_MARK")

    @staticmethod
    def _validate_state_progress(prior: ReferenceState, final: ReferenceState) -> None:
        if prior.stream != final.stream or prior.recording_start != final.recording_start:
            raise RepositoryConflict("CHECKPOINT_STATE_CONFLICT")
        if prior.computed_through is not None and (
            final.computed_through is None
            or final.computed_through < prior.computed_through
        ):
            raise RepositoryConflict("CHECKPOINT_WATERMARK_REGRESSION")
        if prior.last_event_key is not None and (
            final.last_event_key is None
            or final.last_event_key < prior.last_event_key
        ):
            raise RepositoryConflict("CHECKPOINT_EVENT_REGRESSION")

    @staticmethod
    def _validate_action_progress(
        prior: ReferenceState, final: ReferenceState, prepared: PreparedBatch,
    ) -> None:
        keys = [
            (item.action.bar_end, 0, item.action.sequence)
            for item in prepared.source_actions
        ]
        if prior.last_event_key is not None and any(
            key <= prior.last_event_key for key in keys
        ):
            raise RepositoryConflict("ACTION_WATERMARK_CONFLICT")
        if keys and (
            final.last_event_key is None
            or final.last_event_key < max(keys)
        ):
            raise RepositoryConflict("CHECKPOINT_EVENT_CONFLICT")

    @staticmethod
    def _validate_open_projection(
        session: Session,
        stream_id: str,
        revision_id: str,
        expected: ReferenceTrade | None,
    ) -> None:
        rows = session.execute(select(ReferenceTradeRow).where(
            ReferenceTradeRow.stream_id == stream_id,
            ReferenceTradeRow.revision_id == revision_id,
            ReferenceTradeRow.status == TradeStatus.OPEN.value,
            ReferenceTradeRow.valid_to_seq.is_(None),
        )).scalars().all()
        if expected is None:
            if rows:
                raise RepositoryConflict("CHECKPOINT_OPEN_DIVERGENCE")
            return
        if len(rows) != 1:
            raise RepositoryConflict("CHECKPOINT_OPEN_DIVERGENCE")
        row = rows[0]
        if (
            row.trade_id,
            row.side,
            row.physical_contract,
            row.owner_segment_id,
            row.calculation_segment_id,
            _aware(row.entry_bar_end),
            row.entry_trading_day,
            row.entry_reference_price,
        ) != (
            expected.reference_trade_id,
            expected.side.value,
            expected.physical_contract,
            expected.owner_segment_id,
            expected.calculation_segment_id,
            expected.entry_bar_end,
            expected.entry_trading_day,
            expected.entry_reference_price,
        ):
            raise RepositoryConflict("CHECKPOINT_OPEN_DIVERGENCE")

    def _insert_actions(
        self, session: Session, prepared: PreparedBatch, *, batch_id: str, batch_seq: int,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in prepared.source_actions:
            action = item.action
            if action.stream.stream_id != prepared.stream_id:
                raise RepositoryConflict("ACTION_STREAM_CONFLICT")
            origin = item.origin_revision_id or prepared.revision_id
            if item.origin_revision_id is not None:
                origin_row = session.get(ReferenceRevision, (prepared.stream_id, origin))
                if (
                    origin_row is None
                    or origin == prepared.revision_id
                    or origin_row.status not in {"active", "superseded"}
                    or action.stream.recording_mode is not RecordingMode.FORWARD_OBSERVATION
                ):
                    raise RepositoryConflict("ACTION_ORIGIN_CONFLICT")
                existing = session.execute(select(ReferenceActionRow).where(
                    ReferenceActionRow.stream_id == prepared.stream_id,
                    ReferenceActionRow.origin_revision_id == origin,
                    ReferenceActionRow.source_action_id == action.source_action_id,
                )).scalar_one_or_none()
                if existing is None:
                    raise RepositoryConflict("ACTION_ORIGIN_NOT_FOUND")
                if not self._same_action_fact(existing, item):
                    raise RepositoryConflict("ACTION_IMMUTABILITY_CONFLICT")
                result[action.source_action_id] = existing.action_pk
                continue
            key_scope = "" if action.stream.recording_mode is RecordingMode.FORWARD_OBSERVATION else origin
            action_pk = sha256(
                f"{prepared.stream_id}|{key_scope}|{action.source_action_id}".encode()
            ).hexdigest()
            session.add(ReferenceActionRow(
                action_pk=action_pk,
                stream_id=prepared.stream_id,
                origin_revision_id=origin,
                batch_revision_id=prepared.revision_id,
                source_action_id=action.source_action_id,
                recording_mode=action.stream.recording_mode.value,
                kind=action.kind.value,
                sequence=action.sequence,
                physical_contract=action.physical_contract,
                owner_segment_id=action.owner_segment_id,
                calculation_segment_id=action.calculation_segment_id,
                bar_end=action.bar_end,
                trading_day=action.trading_day,
                observed_at=item.observed_at,
                reference_price=action.reference_price,
                reference_price_type=action.reference_price_type,
                entry_source_action_id=action.entry_action_id,
                batch_id=batch_id,
                batch_seq=batch_seq,
            ))
            result[action.source_action_id] = action_pk
        session.flush()
        return result

    @staticmethod
    def _same_action_fact(existing: ReferenceActionRow, item) -> bool:
        action = item.action
        return (
            existing.kind == action.kind.value
            and existing.sequence == action.sequence
            and existing.physical_contract == action.physical_contract
            and existing.owner_segment_id == action.owner_segment_id
            and existing.calculation_segment_id == action.calculation_segment_id
            and _aware(existing.bar_end) == action.bar_end
            and existing.trading_day == action.trading_day
            and _aware(existing.observed_at) == item.observed_at
            and existing.reference_price == action.reference_price
            and existing.reference_price_type == action.reference_price_type
            and existing.entry_source_action_id == action.entry_action_id
        )

    def _action_pk(
        self, session: Session, prepared: PreparedBatch, action_pks: dict[str, str], source_id: str,
    ) -> str:
        if source_id in action_pks:
            return action_pks[source_id]
        query = select(ReferenceActionRow).where(
            ReferenceActionRow.stream_id == prepared.stream_id,
            ReferenceActionRow.source_action_id == source_id,
        )
        checkpoint_stream = prepared.checkpoint.stream
        if checkpoint_stream is None:
            raise RepositoryConflict("CHECKPOINT_STREAM_CONFLICT")
        if checkpoint_stream.recording_mode is RecordingMode.HISTORICAL_REPLAY:
            query = query.where(ReferenceActionRow.origin_revision_id == prepared.revision_id)
        rows = session.execute(query).scalars().all()
        if len(rows) != 1:
            raise RepositoryConflict("ACTION_LINK_NOT_FOUND")
        return rows[0].action_pk

    def _apply_trade_changes(
        self, session: Session, prepared: PreparedBatch, *, action_pks: dict[str, str], seq: int,
    ) -> dict[str, int]:
        final: dict[str, tuple[ReferenceTrade, datetime | None]] = {}
        for transition in prepared.transitions:
            for trade in transition.changed_trades:
                if trade.stream.stream_id != prepared.stream_id:
                    raise RepositoryConflict("TRADE_STREAM_CONFLICT")
                effective_event = (
                    None
                    if transition.state.last_event_key is None
                    else transition.state.last_event_key[0]
                )
                final[trade.reference_trade_id] = (trade, effective_event)
        births: dict[str, int] = {}
        for trade_id, (trade, transition_event) in final.items():
            current = session.execute(select(ReferenceTradeRow).where(
                ReferenceTradeRow.stream_id == prepared.stream_id,
                ReferenceTradeRow.revision_id == prepared.revision_id,
                ReferenceTradeRow.trade_id == trade_id,
                ReferenceTradeRow.valid_to_seq.is_(None),
            ).with_for_update()).scalar_one_or_none()
            structural = (
                trade.status.value, trade.exit_action_id, trade.exit_bar_end,
                trade.exit_reference_price, trade.reference_return,
            )
            if current is not None:
                if (
                    current.side,
                    current.physical_contract,
                    current.owner_segment_id,
                    current.calculation_segment_id,
                    _aware(current.entry_bar_end),
                    current.entry_trading_day,
                    current.entry_reference_price,
                ) != (
                    trade.side.value,
                    trade.physical_contract,
                    trade.owner_segment_id,
                    trade.calculation_segment_id,
                    trade.entry_bar_end,
                    trade.entry_trading_day,
                    trade.entry_reference_price,
                ):
                    raise RepositoryConflict("TRADE_LIFECYCLE_CONFLICT")
                existing = (
                    current.status,
                    None if current.exit_action_pk is None else trade.exit_action_id,
                    current.exit_bar_end, current.exit_reference_price, current.reference_return,
                )
                births[trade_id] = current.valid_from_seq
                if structural == existing:
                    continue
                if current.status != "OPEN" or trade.status.value == "OPEN":
                    raise RepositoryConflict("TRADE_LIFECYCLE_CONFLICT")
                current.valid_to_seq = seq
                session.flush()
            elif trade.status is TradeStatus.OPEN:
                other_open = session.execute(select(ReferenceTradeRow).where(
                    ReferenceTradeRow.stream_id == prepared.stream_id,
                    ReferenceTradeRow.revision_id == prepared.revision_id,
                    ReferenceTradeRow.status == TradeStatus.OPEN.value,
                    ReferenceTradeRow.valid_to_seq.is_(None),
                )).scalars().first()
                if other_open is not None:
                    raise RepositoryConflict("TRADE_LIFECYCLE_CONFLICT")
            entry_pk = self._action_pk(
                session, prepared, action_pks, trade.entry_action_id,
            )
            entry_action = session.get(ReferenceActionRow, entry_pk)
            if entry_action is None or (
                entry_action.physical_contract,
                entry_action.owner_segment_id,
                entry_action.calculation_segment_id,
                _aware(entry_action.bar_end),
                entry_action.trading_day,
                entry_action.reference_price,
            ) != (
                trade.physical_contract,
                trade.owner_segment_id,
                trade.calculation_segment_id,
                trade.entry_bar_end,
                trade.entry_trading_day,
                trade.entry_reference_price,
            ):
                raise RepositoryConflict("TRADE_ENTRY_CONFLICT")
            exit_pk = None
            if trade.exit_action_id is not None:
                exit_pk = self._action_pk(
                    session, prepared, action_pks, trade.exit_action_id,
                )
                exit_action = session.get(ReferenceActionRow, exit_pk)
                if exit_action is None or (
                    exit_action.physical_contract,
                    exit_action.owner_segment_id,
                    exit_action.calculation_segment_id,
                    _aware(exit_action.bar_end),
                    exit_action.trading_day,
                    exit_action.reference_price,
                ) != (
                    trade.physical_contract,
                    trade.owner_segment_id,
                    trade.calculation_segment_id,
                    trade.exit_bar_end,
                    trade.exit_trading_day,
                    trade.exit_reference_price,
                ):
                    raise RepositoryConflict("TRADE_EXIT_CONFLICT")
            if trade.status is TradeStatus.OPEN:
                effective_bar_end = trade.entry_bar_end
                observation_time = entry_action.observed_at
            elif trade.status is TradeStatus.CLOSED:
                if trade.exit_bar_end is None or exit_action is None:
                    raise RepositoryConflict("TRADE_EXIT_CONFLICT")
                effective_bar_end = trade.exit_bar_end
                observation_time = exit_action.observed_at
            else:
                if transition_event is None:
                    raise RepositoryConflict("TRADE_EVENT_TIME_MISSING")
                effective_bar_end = transition_event
                observation_time = prepared.input_observed_at
            row = ReferenceTradeRow(
                stream_id=prepared.stream_id,
                revision_id=prepared.revision_id,
                trade_id=trade_id,
                valid_from_seq=seq,
                valid_to_seq=None,
                entry_action_pk=entry_pk,
                exit_action_pk=exit_pk,
                side=trade.side.value,
                status=trade.status.value,
                physical_contract=trade.physical_contract,
                owner_segment_id=trade.owner_segment_id,
                calculation_segment_id=trade.calculation_segment_id,
                entry_bar_end=trade.entry_bar_end,
                entry_trading_day=trade.entry_trading_day,
                entry_reference_price=trade.entry_reference_price,
                exit_bar_end=trade.exit_bar_end,
                exit_trading_day=trade.exit_trading_day,
                exit_reference_price=trade.exit_reference_price,
                reference_return=trade.reference_return,
                holding_bars=trade.holding_bars,
                effective_bar_end=effective_bar_end,
                observed_at=observation_time,
            )
            session.add(row)
            births[trade_id] = seq
        session.flush()
        return births

    def _insert_marks(
        self, session: Session, prepared: PreparedBatch, *, action_pks: dict[str, str],
        births: dict[str, int], seq: int,
    ) -> None:
        for transition in prepared.transitions:
            for mark in transition.marks:
                birth = births.get(mark.reference_trade_id)
                if birth is None:
                    trade = session.execute(select(ReferenceTradeRow).where(
                        ReferenceTradeRow.stream_id == prepared.stream_id,
                        ReferenceTradeRow.revision_id == prepared.revision_id,
                        ReferenceTradeRow.trade_id == mark.reference_trade_id,
                        ReferenceTradeRow.valid_from_seq <= seq,
                        or_(
                            ReferenceTradeRow.valid_to_seq.is_(None),
                            ReferenceTradeRow.valid_to_seq > seq,
                        ),
                    ).order_by(ReferenceTradeRow.valid_from_seq.desc())).scalars().first()
                    if trade is None:
                        raise RepositoryConflict("ORPHAN_MARK")
                    birth = trade.valid_from_seq
                trade = session.get(
                    ReferenceTradeRow,
                    (prepared.stream_id, prepared.revision_id, mark.reference_trade_id, birth),
                )
                if trade is None or (
                    trade.status != "OPEN"
                    and not (
                        trade.status in {
                            "CLOSED", "ROLLOVER_INTERRUPTED",
                            "DATA_INTERRUPTED", "OBSERVATION_INTERRUPTED",
                        }
                        and mark.bar_end < _required_aware(
                            trade.effective_bar_end, "TRADE_EFFECTIVE_BAR_END",
                        )
                    )
                ):
                    raise RepositoryConflict("ORPHAN_MARK")
                session.add(ReferenceMarkRow(
                    stream_id=prepared.stream_id,
                    revision_id=prepared.revision_id,
                    trade_id=mark.reference_trade_id,
                    trade_valid_from_seq=birth,
                    batch_seq=seq,
                    bar_end=mark.bar_end,
                    entry_action_pk=trade.entry_action_pk,
                    trading_day=mark.trading_day,
                    reference_price=mark.reference_price,
                    holding_bars=mark.holding_bars,
                    reference_return=mark.reference_return,
                    observed_at=prepared.input_observed_at,
                ))

    def _revision_by_id(self, session: Session, revision_id: str, *, lock: bool) -> ReferenceRevision:
        statement = select(ReferenceRevision).where(ReferenceRevision.revision_id == revision_id)
        if lock:
            statement = statement.with_for_update()
        rows = session.execute(statement).scalars().all()
        if len(rows) != 1:
            raise RepositoryConflict("REVISION_NOT_FOUND")
        return rows[0]

    def _lock_stream_revision_by_revision_id(
        self, session: Session, revision_id: str,
    ) -> tuple[ReferenceStream, ReferenceRevision]:
        located = self._revision_by_id(session, revision_id, lock=False)
        stream = session.execute(select(ReferenceStream).where(
            ReferenceStream.stream_id == located.stream_id,
        ).with_for_update()).scalar_one_or_none()
        if stream is None:
            raise RepositoryConflict("STREAM_NOT_FOUND")
        self._fault_injector("after_stream_lock")
        revision = session.execute(select(ReferenceRevision).where(
            ReferenceRevision.stream_id == located.stream_id,
            ReferenceRevision.revision_id == revision_id,
        ).with_for_update()).scalar_one_or_none()
        if revision is None:
            raise RepositoryConflict("REVISION_NOT_FOUND")
        return stream, revision

    @staticmethod
    def _validate_chunks(chunks: Sequence[ReferenceBatch]) -> None:
        if not chunks:
            raise RepositoryConflict("SEED_INCOMPLETE")
        count = chunks[0].seed_chunk_count
        root = chunks[0].seed_root_hash
        if count is None or root is None or len(chunks) != count:
            raise RepositoryConflict("SEED_INCOMPLETE")
        ordered = sorted(chunks, key=lambda row: row.seed_chunk_index if row.seed_chunk_index is not None else -1)
        if [row.seed_chunk_index for row in ordered] != list(range(count)):
            raise RepositoryConflict("SEED_INCOMPLETE")
        if any(row.seed_chunk_count != count or row.seed_root_hash != root for row in ordered):
            raise RepositoryConflict("SEED_CONTENT_CONFLICT")
        actual = sha256("".join(row.seed_chunk_text or "" for row in ordered).encode()).hexdigest()
        if actual != root:
            raise RepositoryConflict("SEED_ROOT_HASH_CONFLICT")
