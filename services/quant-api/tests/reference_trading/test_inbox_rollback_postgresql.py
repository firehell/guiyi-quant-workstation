"""Real PostgreSQL row-lock and atomic closure checks; no provider access."""

from contextlib import contextmanager
from dataclasses import replace
import pytest
from sqlalchemy import event, select
from app.reference_trading.htdy_recovery_source import HtdyRecoverySource
from app.reference_trading.models import ReferenceStream
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401
from tests.reference_trading.test_inbox_rollback import prepared
from tests.reference_trading.test_htdy_60m_forward import Read

pytestmark = pytest.mark.isolated_postgresql


def test_source_callback_and_atomic_commit_return_under_real_stream_row_lock(
    reference_postgresql,  # noqa: F811
    tmp_path,
):
    factory, repo, inbox, r, parent, cid, evaluate = prepared(
        tmp_path, engine=reference_postgresql
    )

    class Market(Read):
        def bars_until(self, query, *, trading_day, end, limit):
            window = super().bars_until(
                query, trading_day=trading_day, end=end, limit=limit
            )
            return replace(
                window, symbol="al", contract="AL2610", bar_contracts=("AL2610",) * 32
            )

    from time import monotonic

    market = Market()

    @contextmanager
    def facts():
        yield market, lambda *_: ("owner", "calc")

    source = HtdyRecoverySource(factory, facts)
    queries = []

    def capture_sql(conn, cursor, statement, *_):
        queries.append(statement.lower())

    event.listen(reference_postgresql, "before_cursor_execute", capture_sql)
    try:
        with factory() as lock_db, lock_db.begin():
            lock_db.scalar(
                select(ReferenceStream)
                .where(ReferenceStream.stream_id == parent.capture.stream_id)
                .with_for_update()
            )
            start = len(queries)
            started = monotonic()
            source(parent)
            assert monotonic() - started < 3
            assert not any("reference_streams" in q for q in queries[start:])
        r.verify_source = source
        p = r.plan_rollback_continuation(
            parent, capture_id=cid, expires_at=parent.expires_at
        )
        result = r.apply_rollback_continuation(
            p, expected_plan_hash=p.plan_hash, evaluator=evaluate
        )
        assert r.readback(p) == result and inbox.health()["blocked_count"] == 0
        assert market.checks >= 4
    finally:
        event.remove(reference_postgresql, "before_cursor_execute", capture_sql)


def test_concurrent_continuations_commit_only_once(reference_postgresql, tmp_path):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import func
    from app.reference_trading.models import (
        ReferenceInboxRecoveryResult,
        ReferenceBatch,
    )

    factory, repo, inbox, r, parent, cid, evaluate = prepared(
        tmp_path, engine=reference_postgresql
    )
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    barrier = Barrier(2)

    def apply():
        barrier.wait(timeout=5)
        try:
            return r.apply_rollback_continuation(
                p, expected_plan_hash=p.plan_hash, evaluator=evaluate
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply(), range(2)))
    committed = r.readback(p)
    assert committed is not None and any(x == committed for x in results)
    with factory() as db:
        assert (
            db.scalar(select(func.count()).select_from(ReferenceInboxRecoveryResult))
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ReferenceBatch)
                .where(ReferenceBatch.kind == "capture")
            )
            == 1
        )
    assert inbox.health()["unfinished_deliveries"] == 0


def test_pg_failure_rolls_back_and_restart_cannot_reuse_continuation(
    reference_postgresql,  # noqa: F811
    tmp_path,
):
    from app.reference_trading.inbox_recovery import InboxRecovery

    factory, repo, inbox, r, parent, cid, evaluate = prepared(
        tmp_path, engine=reference_postgresql
    )
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    before = repo.load_checkpoint(parent.capture.stream_id)[0]

    def fail(stage):
        if stage == "after_actions":
            raise RuntimeError("injected")

    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        r.apply_rollback_continuation(
            p, expected_plan_hash=p.plan_hash, evaluator=evaluate, fault_injector=fail
        )
    restarted = InboxRecovery(
        factory,
        attempt_dir=r.attempt_dir,
        verify_fence=r.verify_fence,
        verify_source=r.verify_source,
        verify_rollback=r.verify_rollback,
        now=r.now,
    )
    with pytest.raises(ValueError, match="ATTEMPT_CONSUMED"):
        restarted.apply_rollback_continuation(
            p, expected_plan_hash=p.plan_hash, evaluator=evaluate
        )
    assert repo.load_checkpoint(parent.capture.stream_id)[0] == before
    assert restarted.readback(p) is None
    assert repo.read_pending_capture(parent.capture.stream_id)[0] == cid
