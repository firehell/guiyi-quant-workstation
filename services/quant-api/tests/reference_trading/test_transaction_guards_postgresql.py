"""Real PostgreSQL locking and atomic bounded-recovery guard validation."""

from concurrent.futures import ThreadPoolExecutor
import threading
from time import monotonic, sleep

import pytest
from sqlalchemy import select, text

from app.db.base import Base
from sqlalchemy.orm import sessionmaker

from app.reference_trading.models import ReferenceStream
from app.reference_trading.transaction_guards import assert_source_allowed
from tests.reference_trading.test_repository_postgresql import (
    isolated_postgres_engine,  # noqa: F401
    reference_postgresql,  # noqa: F401
    _seed,  # noqa: F401
)
from tests.reference_trading import test_bounded_recovery_health as health_cases

pytestmark = pytest.mark.isolated_postgresql


@pytest.mark.parametrize(
    "case",
    [
        health_cases.test_exact_consumed_gap_restores_health_atomically,
        health_cases.test_failed_commit_rolls_back_health_capture_and_checkpoint,
    ],
    ids=lambda case: case.__name__,
)
def test_recovery_guard_transaction(case, reference_postgresql):  # noqa: F811
    case(reference_postgresql)


def test_source_guard_retains_stream_row_lock_until_transaction_end(
    reference_postgresql,  # noqa: F811
):
    Base.metadata.create_all(reference_postgresql)
    _, stream, *_ = _seed(reference_postgresql)
    factory = sessionmaker(reference_postgresql)
    started, completed = threading.Event(), threading.Event()
    contender_pid = []

    def contender():
        with factory.begin() as session:
            contender_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            assert_source_allowed(session, stream.stream_id)
        completed.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with factory.begin() as session:
            session.scalar(
                select(ReferenceStream)
                .where(
                    ReferenceStream.stream_id == stream.stream_id,
                )
                .with_for_update()
            )
            future = executor.submit(contender)
            assert started.wait(5)
            deadline = monotonic() + 5
            while monotonic() < deadline:
                with factory() as observer:
                    wait_type = observer.scalar(
                        text(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": contender_pid[0]},
                    )
                if wait_type == "Lock":
                    break
                sleep(0.01)
            assert wait_type == "Lock"
            assert not completed.is_set()
        future.result(timeout=5)
    assert completed.is_set()


def test_reconciliation_mismatch_rolls_back_recovery_health_and_calculation(
    reference_postgresql,  # noqa: F811
):
    from app.reference_trading.models import (
        ReferenceBatch,
        ReferenceCaptureReconciliation,
    )
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    from app.reference_trading.forward_service import ForwardReferenceService
    from app.reference_trading.scheduled_reconciliation import (
        ScheduledCanonicalReconciliation,
    )

    factory, repository, identity, recovery, plan, _, capture, evaluator = (
        health_cases.prepared_case(reference_postgresql)
    )
    original = repository.load_checkpoint(identity.stream_id)[0]
    with factory.begin() as session:
        session.add(
            ReferenceCaptureReconciliation(
                reconciliation_id="isolated-mismatch",
                capture_batch_id=capture,
                source_revision="isolated-canonical",
                status="mismatch",
                captured_sha256="a" * 64,
                canonical_sha256="b" * 64,
                checked_at=plan.expires_at,
            )
        )
    scheduler = ScheduledCanonicalReconciliation(factory, None, read_guard=None)
    # Both scheduler entry points retain the shared guard's public error adaptation.
    with pytest.raises(ForwardInputUnavailable, match="REFERENCE_CANONICAL_MISMATCH"):
        scheduler.assert_source_allowed(identity.stream_id)
    from app.reference_trading.repository import RepositoryConflict

    with pytest.raises(RepositoryConflict, match="REFERENCE_CANONICAL_MISMATCH"):
        with factory.begin() as session:
            scheduler.commit_guard(session, identity.stream_id)
    # The repository calls the same guard after projected writes, before commit.
    with pytest.raises(
        RepositoryConflict, match="FORWARD_COMMIT_OUTCOME_UNKNOWN"
    ) as failure:
        ForwardReferenceService(repository, evaluator).process_pending(
            identity.stream_id
        )
    assert isinstance(failure.value.__cause__, ForwardInputUnavailable)
    assert str(failure.value.__cause__) == "REFERENCE_CANONICAL_MISMATCH"
    assert health_cases.health(factory, identity.stream_id) == "RECOVERY_PENDING"
    assert repository.load_checkpoint(identity.stream_id)[0] == original
    assert recovery.consumed_calculation(plan) is None
    with factory() as session:
        assert session.get(ReferenceBatch, capture).consumed_by_batch_id is None
        assert (
            session.scalars(
                select(ReferenceBatch).where(ReferenceBatch.kind == "calculation")
            ).all()
            == []
        )
