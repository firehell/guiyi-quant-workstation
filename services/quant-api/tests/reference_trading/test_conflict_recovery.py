from datetime import timedelta
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import select, func

from app.reference_trading.conflict_recovery import ConflictRevisionRecovery
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.models import ReferenceBatch, ReferenceCaptureReconciliation, ReferenceRevision, ReferenceActivationReceipt
from app.reference_trading.newow_bootstrap import NewowForwardBootstrap
from app.reference_trading.reconciliation import ForwardReconciler, CanonicalEvidence
from app.reference_trading.repository import RepositoryConflict
from tests.reference_trading.test_newow_bootstrap import setup_source, plan_for, NOW, START


def setup_recovery(*, historical_open=False, engine=None):
    factory, repo, source, source_revision, checkpoint = setup_source(engine, frequency='60m')
    if historical_open:
        from guiyi_quant.reference_trading import ReferenceTrade, ReferenceState
        from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json
        trade = ReferenceTrade('history-open', source, 'LONG', 'RB2610', 'owner', 'calc',
            'history-build', checkpoint.computed_through, checkpoint.computed_through.date(), Decimal('3500'))
        with factory.begin() as session:
            revision = session.get(ReferenceRevision, (source.stream_id, source_revision))
            batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            batch.checkpoint_text = adapter_checkpoint_to_json(replace(checkpoint,
                reference_state=ReferenceState(source, open_trade=trade)), strategy_schema=batch.strategy_schema)
            batch.post_state_hash = sha256(batch.checkpoint_text.encode()).hexdigest()
    bootstrap = NewowForwardBootstrap(factory)
    plan = plan_for(bootstrap, source)
    initial = bootstrap.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    target = initial['target_stream_id']
    _, checkpoint = repo.load_checkpoint(target)
    capture = ForwardCapture(target, initial['revision_id'], 1, 'original', START,
        START + timedelta(seconds=1), 'completed_live', {'close': '1'},
        {'source_sha256': sha256(b'old').hexdigest()}, 'first_seen')
    capture_id = repo.capture_forward(capture)
    ForwardReconciler(factory, lambda _: CanonicalEvidence('new-source', sha256(b'new').hexdigest())).reconcile(capture_id, now=START + timedelta(seconds=2))
    service = ConflictRevisionRecovery(factory, verify_source=lambda *_: {'canonical_epoch': 'verified'}, assert_fenced=lambda: None)
    plan = service.plan((source.stream_id,), recording_start=START + timedelta(minutes=10),
        expires_at=START + timedelta(minutes=9), now=START + timedelta(minutes=1))
    return factory, repo, source, target, initial['revision_id'], capture_id, service, plan


def test_recovery_preserves_old_capture_and_conflict_and_starts_flat_new_revision():
    factory, repo, _, target, old_revision, capture_id, service, plan = setup_recovery()
    with factory() as session:
        original = session.get(ReferenceBatch, capture_id).source_evidence
        count = session.scalar(select(func.count()).select_from(ReferenceCaptureReconciliation))
    current = START + timedelta(minutes=2)
    result = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=current)
    assert result[target] != old_revision
    _, checkpoint = repo.load_checkpoint(target)
    assert checkpoint.reference_state.open_trade is None
    assert checkpoint.reference_state.recording_start == START + timedelta(minutes=10)
    with factory() as session:
        assert session.get(ReferenceBatch, capture_id).source_evidence == original
        assert session.get(ReferenceBatch, capture_id).consumed_by_batch_id is None
        assert session.scalar(select(func.count()).select_from(ReferenceCaptureReconciliation)) == count
        assert session.get(ReferenceRevision, (target, old_revision)).invalid_reason == 'DATA_CONFLICT'
        boundary = session.scalar(select(ReferenceBatch).where(ReferenceBatch.kind == 'diagnostic'))
        assert boundary.source_evidence['conflict_boundary_v1']['reason'] == 'DATA_CONFLICT'
        assert boundary.observed_at is None
    assert service.apply(plan, expected_plan_hash=plan['plan_hash'], now=current + timedelta(days=1)) == result


def test_recovery_source_drift_and_fence_loss_roll_back():
    factory, _, _, target, old, _, service, plan = setup_recovery()
    service.verify_source = lambda *_: {'canonical_epoch': 'changed'}
    with pytest.raises(RepositoryConflict, match='CONFLICT_RECOVERY_PREIMAGE_DRIFT'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=2))
    service.verify_source = lambda *_: {'canonical_epoch': 'verified'}
    calls = []
    def fence():
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError('FENCE_LOST')
    service.assert_fenced = fence
    with pytest.raises(RuntimeError, match='FENCE_LOST'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=2))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceActivationReceipt)) == 1
        assert session.get(ReferenceRevision, (target, old)).status == 'active'


def test_historical_open_source_is_preserved_but_never_carried_to_new_revision():
    factory, repo, source, target, _, _, service, plan = setup_recovery(historical_open=True)
    _, before = repo.load_checkpoint(source.stream_id)
    assert before.reference_state.open_trade.reference_trade_id == 'history-open'
    service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=2))
    _, after = repo.load_checkpoint(target)
    assert after.reference_state.open_trade is None
    assert after.strategy_state == before.strategy_state
    assert repo.load_checkpoint(source.stream_id)[1] == before


def test_input_diagnostic_is_bounded_and_preserves_domain_code():
    from app.reference_trading.diagnostics import diagnose_inputs
    calls = []
    def pure(route, kind, end):
        calls.append((route, kind, end))
        raise RepositoryConflict('OWNER_IDENTITY_CONFLICT')
    result = diagnose_inputs(('one', 'two'), pure)
    assert result['checked'] == 2
    assert calls == [('one', 'scan', None), ('two', 'scan', None)]
    assert result['items'][0]['reason'] == 'OWNER_IDENTITY_CONFLICT'
