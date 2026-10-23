"""Actual PostgreSQL JSONB, rollback and concurrent source-classification checks."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import threading

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.reference_trading.activation import ForwardActivation
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.models import ReferenceBatch, ReferenceCaptureReconciliation
from app.reference_trading.reconciliation import CanonicalEvidence, ForwardReconciler
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.scheduled_reconciliation import ScheduledCanonicalReconciliation
from app.reference_trading.source_revisions import append_source_revision, build_revision_proof
from app.reference_trading.transaction_guards import assert_source_allowed
from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from tests.reference_trading.test_repository import _stream
from tests.reference_trading.test_repository_postgresql import isolated_postgres_engine, reference_postgresql  # noqa: F401
from test_activation import NOW
from test_source_revisions import inputs

pytestmark = pytest.mark.isolated_postgresql


def prepared(engine):
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    identity = replace(_stream(), strategy_code='newow_trend', product='b', frequency='60m',
                       recording_mode=RecordingMode.FORWARD_OBSERVATION,
                       observation_policy_version='completed_observation_v1')
    stored = repo.ensure_stream(identity)
    manifest = {'fixture':'isolated-source-revision'}
    revision = repo.create_revision(identity.stream_id, stored.row_version, manifest_sha256(manifest))
    checkpoint = AdapterCheckpoint(seed_replay_state(), stream=identity,
                                   reference_state=ReferenceState.flat(identity, recording_start=NOW))
    repo.stage_seed_chunk(revision, SeedChunk('seed', 0, 1, sha256(b'seed').hexdigest(), 'seed'))
    repo.seal_seed(revision, manifest, checkpoint, 'newow_product_replay_v1')
    from datetime import timedelta
    activation = ForwardActivation(factory)
    plan = activation.plan(identity.stream_id, revision, host='isolated', environment='isolated',
                           recording_start=NOW, expires_at=NOW+timedelta(minutes=1), budget={'max_pending':32})
    activation.apply(plan, expected_plan_hash=plan.plan_hash, now=NOW)
    evidence, canonical, source = inputs()
    capture = ForwardCapture(identity.stream_id, revision, 1, 'B2611:20261023:H1',
                             datetime.fromisoformat(evidence['bar_end']),
                             datetime.fromisoformat(evidence['observed_at']), 'completed_live',
                             evidence['input_payload'], evidence['source_proof'], 'completed_observation')
    cid = repo.capture_forward(capture)
    proof = build_revision_proof(capture.evidence()['forward_capture_v1'], canonical, source, provider='rqdata')
    return factory, repo, identity, cid, proof, capture.observed_at


def test_postgresql_classification_rollback_keeps_the_original_blocker(reference_postgresql):  # noqa: F811
    factory, repo, identity, cid, proof, now = prepared(reference_postgresql)
    strict = ForwardReconciler(factory, lambda _: CanonicalEvidence(proof['source_revision'], proof['canonical_sha256']))
    assert strict.reconcile(cid, now=now) == 'mismatch'
    token = repo.load_checkpoint(identity.stream_id)[0]
    with pytest.raises(RuntimeError, match='rollback'):
        with factory() as session, session.begin():
            comparison = session.query(ReferenceCaptureReconciliation).one()
            append_source_revision(session, session.get(ReferenceBatch, cid), comparison, proof, now=now)
            raise RuntimeError('rollback')
    with factory() as session:
        assert session.query(ReferenceBatch).filter(ReferenceBatch.batch_key.like('source-revision:%')).count() == 0
        assert session.query(ReferenceCaptureReconciliation).one().status == 'mismatch'
    assert repo.load_checkpoint(identity.stream_id)[0] == token


def test_postgresql_concurrent_classification_appends_exactly_once_and_preserves_checkpoint(reference_postgresql):  # noqa: F811
    factory, repo, identity, cid, proof, now = prepared(reference_postgresql)
    token = repo.load_checkpoint(identity.stream_id)[0]
    def reader(_):
        return CanonicalEvidence(proof['source_revision'], proof['canonical_sha256'], proof)
    barrier = threading.Barrier(2)
    def apply():
        barrier.wait()
        return ForwardReconciler(factory, reader, scope_guard=ScheduledCanonicalReconciliation._scope_guard).reconcile(cid, now=now)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(apply), executor.submit(apply)
        assert first.result(timeout=10) == second.result(timeout=10) == 'source_revised'
    with factory() as session:
        assert session.query(ReferenceBatch).filter(ReferenceBatch.batch_key.like('source-revision:%')).count() == 1
        assert session.query(ReferenceCaptureReconciliation).one().status == 'mismatch'
        assert_source_allowed(session, identity.stream_id)
    assert repo.load_checkpoint(identity.stream_id)[0] == token
