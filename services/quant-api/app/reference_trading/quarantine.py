"""Terminal transfer of known-conflict originals into existing append-only batches.

This is not a successful calculation, replay permission, or conflict recovery.
Global journal progress is allowed only after the exact original has durable
receipts on every affected route. Active revision mismatch evidence is retained.
"""
from datetime import UTC, datetime
from hashlib import sha256
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.market_data.observation_stream import ObservationEnvelope
from app.reference_trading.models import ReferenceBatch, ReferenceCaptureReconciliation, ReferenceRevision, ReferenceStream
from app.reference_trading.repository import RepositoryConflict


CODE = 'REFERENCE_CANONICAL_MISMATCH'


def mismatch_evidence(session, routes):
    rows = session.execute(select(ReferenceCaptureReconciliation, ReferenceBatch).join(
        ReferenceBatch, ReferenceBatch.batch_id == ReferenceCaptureReconciliation.capture_batch_id
    ).join(ReferenceStream, ReferenceStream.stream_id == ReferenceBatch.stream_id).where(
        ReferenceBatch.stream_id.in_(routes),
        ReferenceBatch.revision_id == ReferenceStream.active_revision_id,
        ReferenceCaptureReconciliation.status == 'mismatch',
    ).order_by(ReferenceCaptureReconciliation.reconciliation_id)).all()
    return [{'reconciliation_id': r.reconciliation_id, 'capture_id': b.batch_id,
        'stream_id': b.stream_id, 'revision_id': b.revision_id,
        'captured_sha256': r.captured_sha256, 'canonical_sha256': r.canonical_sha256,
        'source_revision': r.source_revision, 'checked_at': r.checked_at.isoformat()}
        for r, b in rows]


def quarantine_observation(factory, routes, observation, *, assert_owned, now=lambda: datetime.now(UTC)):
    processed_at = now()
    if processed_at.tzinfo is None or processed_at.utcoffset() is None:
        raise RepositoryConflict('QUARANTINE_TIME_INVALID')
    if (not isinstance(observation, ObservationEnvelope) or not observation.stream_id
            or not observation.notification_eligible or observation.confirmed_at is None
            or not routes or len(routes) > 4 or len(set(routes)) != len(routes)):
        raise RepositoryConflict('QUARANTINE_INPUT_INVALID')
    if processed_at < observation.confirmed_at:
        raise RepositoryConflict('QUARANTINE_TIME_INVALID')
    raw = observation.to_json()
    key = 'quarantine:' + sha256((observation.trading_day.isoformat() + ':' + observation.stream_id).encode()).hexdigest()
    try:
        with factory() as session, session.begin():
            streams = session.scalars(select(ReferenceStream).where(
                ReferenceStream.stream_id.in_(routes)).order_by(ReferenceStream.stream_id).with_for_update()).all()
            if (len(streams) != len(routes) or any(not s.enabled or not s.active_revision_id
                    or s.recording_mode != 'forward_observation' for s in streams)
                    or len({(s.product.lower(), s.frequency) for s in streams}) != 1
                    or observation.channel != f'live:bar:{streams[0].product.lower()}:{streams[0].frequency}'):
                raise RepositoryConflict('QUARANTINE_SCOPE_CONFLICT')
            # Freeze the exact complete routing group; a partial receipt cannot ack a fusion dependency.
            current = tuple(session.scalars(select(ReferenceStream.stream_id).where(
                ReferenceStream.enabled.is_(True), ReferenceStream.recording_mode == 'forward_observation',
                ReferenceStream.product == streams[0].product,
                ReferenceStream.frequency == streams[0].frequency)).all())
            if set(current) != set(routes):
                raise RepositoryConflict('QUARANTINE_SCOPE_CONFLICT')
            conflicts = mismatch_evidence(session, routes)
            if not conflicts:
                return False
            evidence = {'quarantine_v1': {'stream_id': observation.stream_id,
                'envelope': json.loads(raw), 'routes': sorted(routes), 'reason': CODE,
                'bindings': [{'stream_id': stream.stream_id, 'revision_id': stream.active_revision_id,
                              'generation': stream.activation_generation} for stream in streams]}}
            # Conflict records already immutable in their owning capture; links do not
            # change as later reconciliation rows are appended.
            existing_rows = session.scalars(select(ReferenceBatch).where(
                ReferenceBatch.stream_id.in_(routes), ReferenceBatch.batch_key == key,
                ReferenceBatch.kind == 'diagnostic')).all()
            existing = {b.stream_id: b for b in existing_rows}
            for stream in streams:
                row = existing.get(stream.stream_id)
                if row is not None:
                    old = row.source_evidence.get('quarantine_v1', {})
                    if (row.revision_id != stream.active_revision_id
                            or any(old.get(k) != v for k, v in evidence['quarantine_v1'].items())):
                        raise RepositoryConflict('QUARANTINE_RECEIPT_CONFLICT')
                    continue
                revision = session.get(ReferenceRevision,
                    (stream.stream_id, stream.active_revision_id))
                if revision is None or revision.status != 'active':
                    raise RepositoryConflict('QUARANTINE_SCOPE_CONFLICT')
                stored = {'quarantine_v1': {**evidence['quarantine_v1'], 'conflicts': conflicts}}
                payload_hash = sha256(json.dumps(stored, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                session.add(ReferenceBatch(batch_id=uuid4().hex, stream_id=stream.stream_id,
                    revision_id=stream.active_revision_id, batch_key=key, payload_hash=payload_hash,
                    kind='diagnostic', outcome='diagnostic', seq=None, expected_seq=revision.last_seq,
                    dependency_manifest={}, source_evidence=stored, projected_action_pks=[], diagnostics=[CODE],
                    observed_at=observation.confirmed_at, processed_at=processed_at))
            session.flush()
            assert_owned()
            return True
    except SQLAlchemyError as error:
        # No blind retry/readback on an unknown quarantine commit. Restart may only
        # encounter exact persisted terminal receipts under the usual ownership fence.
        raise RepositoryConflict('QUARANTINE_COMMIT_OUTCOME_UNKNOWN') from error
