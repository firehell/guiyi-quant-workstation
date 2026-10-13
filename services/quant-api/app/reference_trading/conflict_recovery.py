"""Explicit bounded revision renewal after a proven Canonical conflict.

No provider, journal cursor, observation replay or notifications. The caller must
hold a stopped-writer fence and revalidate the historical manifest against MDS.
"""
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch, ReferenceRevision, ReferenceStream
from app.reference_trading.newow_bootstrap import NewowForwardBootstrap, POLICY, _BorrowedSession, _aware, _hash
from app.reference_trading.quarantine import mismatch_evidence
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict
from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json


class ConflictRevisionRecovery:
    plan_version = "reference_conflict_recovery_v1"
    boundary_key = "conflict_boundary_v1"
    manifest_key = "conflict_recovery_v1"
    new_health = "READY"
    retirement_reason = "DATA_CONFLICT"

    def _source(self, session, source_id, *, lock):
        return NewowForwardBootstrap(self.factory)._source(session, source_id, lock=lock)

    def _conflicts(self, session, targets):
        return mismatch_evidence(session, targets)

    def __init__(self, factory, *, verify_source, assert_fenced):
        self.factory, self.verify_source, self.assert_fenced = factory, verify_source, assert_fenced

    def _freeze(self, session, source_ids, *, start, expiry, lock=False):
        if not source_ids or len(source_ids) > 4 or len(set(source_ids)) != len(source_ids):
            raise RepositoryConflict('CONFLICT_RECOVERY_SCOPE_INVALID')
        items, data = [], []
        for source_id in sorted(source_ids):
            identity, checkpoint, schema, manifest, binding = self._source(session, source_id, lock=lock)
            if checkpoint.computed_through >= start:
                raise RepositoryConflict('CONFLICT_RECOVERY_WARMUP_AFTER_START')
            proof = self.verify_source(identity, binding, manifest)
            if not isinstance(proof, dict) or not proof:
                raise RepositoryConflict('CONFLICT_RECOVERY_SOURCE_UNVERIFIED')
            target = replace(identity, recording_mode=RecordingMode.FORWARD_OBSERVATION, observation_policy_version=POLICY)
            query = select(ReferenceStream).where(ReferenceStream.stream_id == target.stream_id)
            stream = session.scalar(query.with_for_update() if lock else query)
            if stream is None or not stream.enabled or not stream.active_revision_id:
                raise RepositoryConflict('CONFLICT_RECOVERY_TARGET_INVALID')
            revision = session.get(ReferenceRevision, (stream.stream_id, stream.active_revision_id))
            receipt = session.scalar(select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.stream_id == stream.stream_id,
                ReferenceActivationReceipt.generation == stream.activation_generation,
                ReferenceActivationReceipt.disabled_at.is_(None)))
            if revision is None or revision.status != 'active' or receipt is None:
                raise RepositoryConflict('CONFLICT_RECOVERY_TARGET_INVALID')
            old = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            if old is None or old.seq != stream.latest_seq or old.seq != revision.last_seq:
                raise RepositoryConflict('CONFLICT_RECOVERY_TARGET_INVALID')
            # Freeze every existing batch: unknown or newly arrived work changes the plan.
            batches = session.execute(select(ReferenceBatch.batch_id, ReferenceBatch.payload_hash,
                ReferenceBatch.consumed_by_batch_id).where(ReferenceBatch.stream_id == stream.stream_id,
                ReferenceBatch.revision_id == revision.revision_id).order_by(ReferenceBatch.batch_id)).all()
            preimage = {'stream_id': stream.stream_id, 'revision_id': revision.revision_id,
                'row_version': stream.row_version, 'generation': stream.activation_generation,
                'checkpoint_id': old.batch_id, 'checkpoint_hash': old.post_state_hash,
                'batches_hash': _hash([list(row) for row in batches]),
                'receipt_hash': _hash({c.name: str(getattr(receipt, c.name)) for c in receipt.__table__.columns})}
            items.append({'source': binding, 'source_proof': proof, 'target': preimage})
            data.append((target, checkpoint, schema, manifest, stream, revision, receipt))
        groups = {(item[0].product, item[0].frequency) for item in data}
        if len(groups) != 1:
            raise RepositoryConflict('CONFLICT_RECOVERY_SCOPE_INVALID')
        product, frequency = next(iter(groups))
        current = set(session.scalars(select(ReferenceStream.stream_id).where(
            ReferenceStream.enabled.is_(True), ReferenceStream.recording_mode == 'forward_observation',
            ReferenceStream.product == product, ReferenceStream.frequency == frequency)))
        targets = {item[0].stream_id for item in data}
        conflicts = self._conflicts(session, targets)
        if current != targets or not conflicts:
            raise RepositoryConflict('CONFLICT_RECOVERY_SCOPE_INVALID')
        payload = {'version': self.plan_version, 'items': items,
            'conflicts': conflicts, 'recording_start': start.isoformat(), 'expires_at': expiry.isoformat()}
        return {**payload, 'plan_hash': _hash(payload)}, data

    def plan(self, source_ids, *, recording_start, expires_at, now):
        start, expiry, current = map(_aware, (recording_start, expires_at, now))
        if not current < expiry <= start:
            raise RepositoryConflict('CONFLICT_RECOVERY_WINDOW_INVALID')
        self.assert_fenced()
        with self.factory() as session:
            plan, _ = self._freeze(session, source_ids, start=start, expiry=expiry)
            return plan

    def apply(self, plan, *, expected_plan_hash, now):
        payload = {k: v for k, v in plan.items() if k != 'plan_hash'}
        if (plan.get('version') != self.plan_version or expected_plan_hash != plan.get('plan_hash')
                or _hash(payload) != expected_plan_hash):
            raise RepositoryConflict('PLAN_HASH_CONFLICT')
        current = _aware(now)
        start, expiry = map(lambda v: _aware(datetime.fromisoformat(v)), (plan['recording_start'], plan['expires_at']))
        self.assert_fenced()
        try:
            with self.factory() as session, session.begin():
                target_ids = [item['target']['stream_id'] for item in plan['items']]
                prior = session.scalars(select(ReferenceActivationReceipt).where(
                    ReferenceActivationReceipt.stream_id.in_(target_ids),
                    ReferenceActivationReceipt.plan_hash == expected_plan_hash)).all()
                if prior:
                    if {r.stream_id for r in prior} != set(target_ids):
                        raise RepositoryConflict('CONFLICT_RECOVERY_PARTIAL_COMMIT')
                    for receipt in prior:
                        stream = session.get(ReferenceStream, receipt.stream_id)
                        if (stream is None or stream.active_revision_id != receipt.revision_id
                                or stream.activation_generation != receipt.generation or receipt.disabled_at is not None):
                            raise RepositoryConflict('CONFLICT_RECOVERY_RECEIPT_STALE')
                    return {r.stream_id: r.revision_id for r in prior}
                if not current < expiry <= start:
                    raise RepositoryConflict('CONFLICT_RECOVERY_WINDOW_INVALID')
                fresh, data = self._freeze(session, [item['source']['stream_id'] for item in plan['items']], start=start, expiry=expiry, lock=True)
                if fresh != plan:
                    raise RepositoryConflict('CONFLICT_RECOVERY_PREIMAGE_DRIFT')
                repo = ReferenceRepository(lambda: _BorrowedSession(session))
                results = {}
                for identity, source, schema, manifest, stream, old, receipt in data:
                    boundary = {'reason': self.retirement_reason, 'plan_hash': expected_plan_hash,
                        'previous_revision_id': old.revision_id, 'recording_start': start.isoformat(),
                        'source': next(item['source'] for item in plan['items'] if item['target']['stream_id'] == stream.stream_id)}
                    manifest = {**manifest, self.manifest_key: boundary}
                    revision_id = repo.create_revision(stream.stream_id, stream.row_version, manifest_sha256(manifest))
                    checkpoint = replace(source, stream=identity,
                        reference_state=ReferenceState.flat(identity, recording_start=start))
                    content = adapter_checkpoint_to_json(checkpoint, strategy_schema=schema)
                    repo.stage_seed_chunk(revision_id, SeedChunk('conflict:' + expected_plan_hash, 0, 1, sha256(content.encode()).hexdigest(), content))
                    repo.seal_seed(revision_id, manifest, checkpoint, schema)
                    session.add(ReferenceBatch(batch_id=uuid4().hex, stream_id=stream.stream_id,
                        revision_id=old.revision_id, batch_key='conflict-boundary:' + expected_plan_hash,
                        payload_hash=_hash(boundary), kind='diagnostic', outcome='diagnostic', seq=None,
                        expected_seq=old.last_seq, dependency_manifest={}, source_evidence={self.boundary_key: boundary},
                        projected_action_pks=[], diagnostics=[self.retirement_reason], processed_at=current))
                    old.status, old.invalid_reason = 'invalid', self.retirement_reason
                    new = session.get(ReferenceRevision, (stream.stream_id, revision_id))
                    new.status = 'active'
                    receipt.disabled_at = current
                    stream.active_revision_id, stream.latest_seq = revision_id, new.last_seq
                    stream.activation_generation += 1
                    stream.row_version += 1
                    stream.recording_start, stream.activation_plan_hash = start, expected_plan_hash
                    stream.health = self.new_health
                    session.add(ReferenceActivationReceipt(receipt_id=uuid4().hex, stream_id=stream.stream_id,
                        revision_id=revision_id, generation=stream.activation_generation, plan_hash=expected_plan_hash,
                        recording_start=start, activated_at=current, environment=receipt.environment, host=receipt.host,
                        budget={k: v for k, v in receipt.budget.items() if k not in {
                            'bounded_recovery_capture_sha256', 'previous_receipt_sha256', 'journal_proof_sha256'}}, recovery_policy='block'))
                    results[stream.stream_id] = revision_id
                session.flush()
                self.assert_fenced()
                return results
        except SQLAlchemyError as error:
            raise RepositoryConflict('CONFLICT_RECOVERY_COMMIT_OUTCOME_UNKNOWN') from error
