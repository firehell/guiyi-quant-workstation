"""The 31 October incident is a separate, exact scope, never a generic exemption."""

import pytest
from datetime import timedelta
from sqlalchemy import select

from app.reference_trading.htdy_conflict_recovery import HtdyConflictRecovery
from app.reference_trading.htdy_conflict_incidents import OCT31_VERSION
from app.reference_trading import htdy_conflict_recovery as domain
from app.reference_trading.models import (
    ReferenceBatch,
    ReferenceStream,
    ReferenceTradeRow,
    ReferenceActionRow,
)
from app.reference_trading.repository import RepositoryConflict
from app.reference_trading.htdy_activation import htdy_identity
from tests.reference_trading.test_htdy_conflict_recovery import (
    NOW,
    conflict_setup,
    add_open_trade,
)


def three_setup(monkeypatch, engine=None):
    factory, recovery, ids = conflict_setup(engine, products=["hc", "ss", "zn", "rb"])
    return configure_three(factory, recovery, monkeypatch)


def configure_three(factory, recovery, monkeypatch):
    add_open_trade(factory, "ss")
    ids = [htdy_identity(p).stream_id for p in ("hc", "ss", "zn")]
    with factory() as db:
        bindings = {
            row.stream_id: (row.revision_id, row.batch_id)
            for row in db.scalars(select(ReferenceBatch))
            if row.kind == "capture" and row.stream_id in ids
        }
    # Fixture-generated immutable IDs; production constants are never modified.
    monkeypatch.setattr(domain, "OCT31_BINDINGS", bindings)
    recovery.incident = OCT31_VERSION
    return factory, recovery, ids


def frozen(recovery, ids):
    return recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )


def test_three_atomic_preserves_originals_and_unselected_stream(monkeypatch):
    factory, recovery, ids = three_setup(monkeypatch)
    with factory() as db:
        original = {
            b.batch_id: domain._row(b) for b in db.scalars(select(ReferenceBatch))
        }
        rb = domain._row(db.get(ReferenceStream, htdy_identity("rb").stream_id))
    plan = frozen(recovery, ids)
    assert plan["version"] == OCT31_VERSION
    result = recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert set(result) == set(ids) and recovery.readback(plan) == result
    with factory() as db:
        assert all(
            domain._row(db.get(ReferenceBatch, k)) == v for k, v in original.items()
        )
        assert domain._row(db.get(ReferenceStream, htdy_identity("rb").stream_id)) == rb
        rows = db.scalars(
            select(ReferenceTradeRow).order_by(ReferenceTradeRow.valid_from_seq)
        ).all()
        assert [r.status for r in rows] == ["OPEN", "DATA_INTERRUPTED"]
        assert rows[1].exit_reference_price is None and rows[1].reference_return is None
        assert len(db.scalars(select(ReferenceActionRow)).all()) == 1
        assert domain.retired_delivery_ids(db, stream_ids=ids) == ()
    # Subsequent events cannot use this fixed old-revision/capture incident again.
    with pytest.raises(RepositoryConflict):
        frozen(recovery, ids)


def test_three_readback_rejects_rehashed_outside_scope(monkeypatch):
    _, recovery, ids = three_setup(monkeypatch)
    plan = frozen(recovery, ids)
    plan["items"][0]["binding"]["stream_id"] = "outside"
    plan["plan_hash"] = domain._hash(
        {k: v for k, v in plan.items() if k != "plan_hash"}
    )
    with pytest.raises(RepositoryConflict, match="SCOPE_INVALID"):
        recovery.readback(plan)


@pytest.mark.parametrize("change", ["source", "fence"])
def test_three_apply_rolls_back_every_stream_on_source_or_final_fence_loss(
    monkeypatch, change
):
    factory, recovery, ids = three_setup(monkeypatch)
    plan = frozen(recovery, ids)
    if change == "source":
        original = recovery.verify_source
        recovery.verify_source = lambda *args: {**original(*args), "changed": True}
    else:
        calls = []

        def lost():
            calls.append(True)
            if len(calls) == 2:
                raise RepositoryConflict("FENCE_LOST")

        recovery.assert_fenced = lost
    with pytest.raises(RepositoryConflict):
        recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert recovery.readback(plan) is None
    with factory() as db:
        assert all(
            db.get(ReferenceStream, sid).activation_generation == 1 for sid in ids
        )


@pytest.mark.parametrize(
    "change", ["scope", "revision", "capture", "generation", "open"]
)
def test_three_scope_and_preimage_drift_fail_closed(monkeypatch, change):
    factory, recovery, ids = three_setup(monkeypatch)
    if change == "scope":
        ids[-1] = htdy_identity("rb").stream_id
    elif change in ("revision", "capture"):
        sid = ids[0]
        rev, cap = domain.OCT31_BINDINGS[sid]
        monkeypatch.setattr(
            domain,
            "OCT31_BINDINGS",
            {
                **domain.OCT31_BINDINGS,
                sid: (
                    "foreign" if change == "revision" else rev,
                    "foreign" if change == "capture" else cap,
                ),
            },
        )
    elif change == "generation":
        with factory() as db, db.begin():
            db.get(ReferenceStream, ids[0]).activation_generation += 1
    else:
        monkeypatch.setattr(domain, "OCT31_OPEN_STREAM", ids[0])
    with pytest.raises(RepositoryConflict):
        frozen(recovery, ids)
    with factory() as db:
        assert not any(
            "htdy_conflict_boundary_v1" in b.source_evidence
            for b in db.scalars(select(ReferenceBatch))
        )


def test_unknown_incident_fails_before_loading_business_state():
    with pytest.raises(ValueError, match="INCIDENT_INVALID"):
        HtdyConflictRecovery(
            None,
            verify_source=lambda *_: None,
            assert_fenced=lambda: None,
            incident="arbitrary-recovery",
        )
