"""Health changes only with the exact consumed bounded interruption transaction."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.reference_trading.bounded_recovery import BoundedForwardRecovery
from app.reference_trading.forward_service import ForwardReferenceService
from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch, ReferenceStream
from app.reference_trading.recovery import evaluate_observation_gap
from app.reference_trading.repository import ReferenceRepository
from tests.reference_trading.test_newow_worker_recovery import _setup, _worker


def prepared_case(engine=None):
    factory, repo, identity, _, start, observed, _ = _setup(frequency='60m', engine=engine)
    endpoints = (start + timedelta(seconds=1), start + timedelta(seconds=2))
    service = BoundedForwardRecovery(factory, verify_gap=lambda *_: endpoints)
    plan = service.plan(identity.stream_id, endpoints=endpoints, trading_day=start.date(),
        observed_at=observed, expires_at=observed + timedelta(minutes=5), journal_proof={'isolated': True})
    receipt, capture = service.apply(plan, expected_plan_hash=plan.plan_hash, now=observed)
    manifest = repo.read_state(identity.stream_id).dependency_manifest
    def evaluator(token, checkpoint, evidence):
        return evaluate_observation_gap(token, checkpoint, evidence, dependency_manifest=manifest)
    return factory, repo, identity, service, plan, receipt, capture, evaluator


def health(factory, stream_id):
    with factory() as session:
        return session.get(ReferenceStream, stream_id).health


def test_exact_consumed_gap_restores_health_atomically(engine=None):
    factory, repo, identity, service, plan, _, capture, evaluator = prepared_case(engine)
    assert health(factory, identity.stream_id) == 'RECOVERY_PENDING'
    result = ForwardReferenceService(repo, evaluator).process_pending(identity.stream_id)
    assert result.outcome == 'committed'
    assert service.consumed_calculation(plan) is not None
    assert health(factory, identity.stream_id) == 'READY'
    with factory() as session:
        assert session.get(ReferenceBatch, capture).outcome == 'consumed'
    assert ForwardReferenceService(repo, evaluator).process_pending(identity.stream_id) is None


def test_remaining_pending_capture_keeps_recovery_pending():
    factory, repo, identity, _, plan, _, _, evaluator = prepared_case()
    # Inject a second persisted pending row to exercise the defensive transaction
    # boundary. Public bounded admission correctly forbids creating this state.
    with factory.begin() as session:
        first = session.scalar(select(ReferenceBatch).where(ReferenceBatch.kind == 'capture'))
        values = {c.name: getattr(first, c.name) for c in first.__table__.columns}
        other_id = 'isolated-other-pending'
        session.add(ReferenceBatch(**{**values, 'batch_id': other_id, 'batch_key': other_id}))
    ForwardReferenceService(repo, evaluator).process_pending(identity.stream_id)
    assert health(factory, identity.stream_id) == 'RECOVERY_PENDING'
    with factory() as session:
        assert session.get(ReferenceBatch, other_id).consumed_by_batch_id is None


def test_wrong_bound_receipt_cannot_grant_health():
    factory, repo, identity, _, _, receipt, _, evaluator = prepared_case()
    with factory.begin() as session:
        row = session.get(ReferenceActivationReceipt, receipt)
        row.budget = {**row.budget, 'bounded_recovery_capture_sha256': '0' * 64}
    ForwardReferenceService(repo, evaluator).process_pending(identity.stream_id)
    assert health(factory, identity.stream_id) == 'RECOVERY_PENDING'


@pytest.mark.parametrize('status', ['PENDING_WARMUP', 'DATA_CONFLICT', 'STALE_INVALID'])
def test_successful_gap_does_not_promote_other_health(status):
    factory, repo, identity, _, _, _, _, evaluator = prepared_case()
    with factory.begin() as session:
        session.get(ReferenceStream, identity.stream_id).health = status
    ForwardReferenceService(repo, evaluator).process_pending(identity.stream_id)
    assert health(factory, identity.stream_id) == status


def test_failed_commit_rolls_back_health_capture_and_checkpoint(engine=None):
    factory, repo, identity, service, plan, _, capture, evaluator = prepared_case(engine)
    original = repo.load_checkpoint(identity.stream_id)[0]
    def fail(stage):
        if stage == 'before_commit':
            raise RuntimeError('INJECTED_COMMIT_FAILURE')
    failing = ReferenceRepository(factory, fault_injector=fail)
    with pytest.raises(RuntimeError, match='FORWARD_COMMIT_OUTCOME_UNKNOWN'):
        ForwardReferenceService(failing, evaluator).process_pending(identity.stream_id)
    assert health(factory, identity.stream_id) == 'RECOVERY_PENDING'
    assert repo.load_checkpoint(identity.stream_id)[0] == original
    assert service.consumed_calculation(plan) is None
    with factory() as session:
        assert session.get(ReferenceBatch, capture).consumed_by_batch_id is None
        assert session.scalars(select(ReferenceBatch).where(ReferenceBatch.kind == 'calculation')).all() == []


def test_ordinary_capture_cannot_clear_recovery_pending():
    factory, repo, identity, _, _, observed, reader = _setup()
    with factory.begin() as session:
        session.get(ReferenceStream, identity.stream_id).health = 'RECOVERY_PENDING'
    worker = _worker(repo, reader, observed)
    worker.wake(identity.stream_id)
    worker.run_round()
    assert not worker.health().blocked, worker.health().blocked
    assert repo.read_pending_capture(identity.stream_id) is None
    assert health(factory, identity.stream_id) == 'RECOVERY_PENDING'


def test_known_commit_readback_preserves_atomic_ready_after_response_loss(engine=None):
    factory, repo, identity, service, plan, _, _, evaluator = prepared_case(engine)
    class LostResponse(ReferenceRepository):
        def commit_batch(self, *args, **kwargs):
            super().commit_batch(*args, **kwargs)
            raise OSError('isolated-response-loss')
    result = ForwardReferenceService(LostResponse(factory), evaluator).process_pending(identity.stream_id)
    assert result.outcome == 'committed'
    assert service.consumed_calculation(plan) is not None
    assert health(factory, identity.stream_id) == 'READY'


def test_current_typed_conflict_blocks_health_and_rolls_back_consumption():
    from tests.reference_trading.test_original_conflict import setup_group, proof
    from tests.reference_trading.test_newow_bootstrap import START
    from app.reference_trading.original_conflict import OriginalObservationTransfer
    factory, repo, _, routes, original = setup_group()
    transfer = OriginalObservationTransfer(factory, verify_observation=proof, assert_fenced=lambda: None)
    transfer_plan = transfer.plan(routes, (original,))
    now = START + timedelta(minutes=3)
    transfer.apply(transfer_plan, expected_plan_hash=transfer_plan['plan_hash'], now=now)
    route = routes[0]
    endpoints = (START + timedelta(minutes=2),)
    service = BoundedForwardRecovery(factory, verify_gap=lambda *_: endpoints)
    plan = service.plan(route, endpoints=endpoints, trading_day=START.date(), observed_at=now,
        expires_at=now+timedelta(minutes=1), journal_proof={'isolated':True})
    service.apply(plan, expected_plan_hash=plan.plan_hash, now=now)
    manifest = repo.read_state(route).dependency_manifest
    processor = ForwardReferenceService(repo, lambda token, checkpoint, evidence:
        evaluate_observation_gap(token, checkpoint, evidence, dependency_manifest=manifest))
    with pytest.raises(RuntimeError):
        processor.process_pending(route)
    assert service.consumed_calculation(plan) is None
    assert health(factory, route) == 'RECOVERY_PENDING'


from tests.alembic.conftest import isolated_postgres_engine  # noqa: E402,F401
from tests.reference_trading.test_newow_worker_recovery import forward_postgresql  # noqa: E402,F401


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize('case', [test_exact_consumed_gap_restores_health_atomically,
    test_failed_commit_rolls_back_health_capture_and_checkpoint,
    test_known_commit_readback_preserves_atomic_ready_after_response_loss], ids=lambda c: c.__name__)
def test_bounded_gap_health_postgresql(case, forward_postgresql):  # noqa: F811
    case(forward_postgresql)
