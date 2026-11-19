import pytest
from sqlalchemy import create_engine, select

from app.reference_trading import htdy_conflict_recovery, inbox_recovery, interval_retirement
from app.reference_trading.models import ReferenceBatch
from app.reference_trading.repository import RepositoryConflict
from tests.reference_trading.test_formula_transition import fixture


def test_terminal_kind_probe_only_dispatches_scoped_proof_readers(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        factory, pairs = fixture(engine, current=True)
        conflict, interval, wrong_kind = [pair[0] for pair in pairs[:3]]
        with factory.begin() as db:
            for sid, key, kind in (
                (conflict, "htdy-conflict:probe", "calculation"),
                (interval, interval_retirement.PREFIX + "probe", "seed_seal"),
                (wrong_kind, "htdy-conflict:ignored", "seed_seal"),
            ):
                batch = db.scalar(select(ReferenceBatch).where(
                    ReferenceBatch.stream_id == sid, ReferenceBatch.seq.is_not(None),
                ).order_by(ReferenceBatch.seq))
                batch.batch_key, batch.kind = key, kind
            db.flush()
            # An interval-looking key on an ordinary batch must reach the
            # actual verifier and fail, even if the batch kind differs.
            with pytest.raises(RepositoryConflict):
                inbox_recovery.verified_resolution_groups(db, stream_ids=(interval,))

            calls = []
            def verifier(name):
                def verify(session, *, stream_ids, check_cancelled):
                    assert session is db
                    calls.append((name, stream_ids))
                    return (name + "-proved",)
                return verify

            monkeypatch.setattr(htdy_conflict_recovery, "retired_delivery_ids", verifier("conflict"))
            monkeypatch.setattr(interval_retirement, "retired_interval_delivery_ids", verifier("interval"))
            for scope, expected in (
                (None, ("conflict", "interval")),
                ((conflict, interval), ("conflict", "interval")),
                ((conflict,), ("conflict",)),
                ((interval,), ("interval",)),
                ((wrong_kind,), ()),
                ((), ()),
            ):
                calls.clear()
                groups = inbox_recovery.verified_resolution_groups(db, stream_ids=scope)
                assert calls == [(name, scope) for name in expected]
                for name in ("conflict", "interval"):
                    assert groups[name + "_retired"] == ((name + "-proved",) if name in expected else ())
    finally:
        engine.dispose()
